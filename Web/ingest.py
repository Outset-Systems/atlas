"""The relay ingest gate — the hosted side of `atlas-relay`.

The routes live in `api/v2/ingest_v2.py` (`POST /api/v2/ingest/{signals,
inventory,observed}`); this module is what stands in front of them: the
bearer-token check, the size cap, the per-token rate limiter, and the body
reader that enforces the tenancy invariant. It was the v1 route module until
the v1 removal (v1.41.0), when the routes went and the gate stayed — one
limiter, one token check, one place to read when the question is "what does a
relay have to present".

The ingest paths are exempt from the Hub session gate — a relay has no
session, the token is the credential. That makes the token checks the entire
boundary, so they are strict on purpose: unknown or revoked token 401, wrong
scope or a payload naming another site 403, oversize 413, malformed 422, too
fast 429. A token may only ever write to its own site.
"""

import logging
import threading
import time
from collections import defaultdict, deque

from flask import g, jsonify, request

import settings

log = logging.getLogger("atlas.live.ingest")

MAX_BYTES = 1024 * 1024          # 1 MB — a site's inventory is kilobytes
RATE_LIMIT = 60                  # requests per token...
RATE_WINDOW = 60.0               # ...per minute
SNAPSHOT_RING = 10               # signal snapshots kept per site


def enabled():
    """Is the ingest surface live on this instance? Off unless
    ATLAS_INGEST_ENABLED=1 AND the db backend is on: without the db there is
    nowhere to put a push, and an endpoint that cannot be used should not be
    reachable — the v2 blueprint 404s per request on this same predicate."""
    if not settings.INGEST_ENABLED:
        return False
    if settings.DATA_BACKEND != "db":
        log.warning("ATLAS_INGEST_ENABLED=1 ignored: ingest needs ATLAS_DATA_BACKEND=db")
        return False
    return True


def announce(url_prefix):
    """Say at boot, loudly, that a gate-exempt write surface is live."""
    log.warning(
        "SECURITY: relay ingest is ENABLED at %s/* — these endpoints bypass the Hub "
        "session gate and trust per-site bearer tokens alone. Issue tokens with "
        "`python cli.py token-issue`, revoke with `python cli.py token-revoke`.", url_prefix)


#: Clients a limiter holds before it sweeps out the ones it has stopped hearing.
MAX_TRACKED = 4096


class _RateLimiter:
    """Fixed-window-ish sliding limiter, per worker process (same trade-off as
    the signals cache: no Redis, and a few extra allowed requests across
    workers is harmless for a write path that is idempotent anyway)."""

    def __init__(self, limit=RATE_LIMIT, window=RATE_WINDOW):
        self.limit, self.window = limit, window
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key):
        now = time.monotonic()
        with self._lock:
            if len(self._hits) >= MAX_TRACKED:      # a public route meets many clients
                self._forget(now)
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def _forget(self, now):
        for key in [k for k, q in self._hits.items() if not q or now - q[-1] > self.window]:
            del self._hits[key]

    def reset(self):
        with self._lock:
            self._hits.clear()


#: ONE limiter for the process — the tests reset it between calls.
limiter = _RateLimiter()


def _bearer():
    import security
    return security.bearer_token(request) or None


def authenticate():
    """Token -> site. Every failure mode answers with the narrowest useful
    code; None means the request may proceed with `g.site_slug` set."""
    from store import session_scope
    from store.tokens import verify_token

    token = _bearer()
    if not token:
        return jsonify({"error": "missing bearer token"}), 401

    length = request.content_length
    if length is not None and length > MAX_BYTES:
        return jsonify({"error": f"payload too large (max {MAX_BYTES} bytes)"}), 413

    with session_scope() as session:
        site, row, err = verify_token(session, token, scope="ingest")
        if err == "unknown":
            log.warning("ingest: unknown token from %s", request.remote_addr)
            return jsonify({"error": "unknown token"}), 401
        if err == "revoked":
            log.warning("ingest: revoked token %s from %s", row.id, request.remote_addr)
            return jsonify({"error": "token revoked"}), 401
        if err == "scope":
            return jsonify({"error": "token lacks the 'ingest' scope"}), 403
        if site is None:  # token outlived its site
            return jsonify({"error": "token's site no longer exists"}), 403
        g.site_slug, g.token_id = site.slug, row.id

    if not limiter.hit(g.token_id):
        return jsonify({"error": f"rate limit: {RATE_LIMIT} requests/minute"}), 429
    return None


def body():
    """Parsed JSON object, or (None, response) on any problem."""
    data = request.get_data(cache=True)
    if len(data) > MAX_BYTES:
        return None, (jsonify({"error": f"payload too large (max {MAX_BYTES} bytes)"}), 413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify({"error": "expected a JSON object"}), 422)
    named = payload.get("site")
    if named and named != g.site_slug:
        # the tenancy invariant: a token writes to its own site or nowhere
        log.warning("ingest: token %s tried to write site %r (owns %r)",
                    g.token_id, named, g.site_slug)
        return None, (jsonify({"error": "token is not valid for that site"}), 403)
    return payload, None
