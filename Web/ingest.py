import logging
import threading
import time
from collections import defaultdict, deque

from flask import g, jsonify, request

import settings

log = logging.getLogger("atlas.live.ingest")

MAX_BYTES = 1024 * 1024
RATE_LIMIT = 60
RATE_WINDOW = 60.0
SNAPSHOT_RING = 10


def enabled():
    if not settings.INGEST_ENABLED:
        return False
    if settings.DATA_BACKEND != "db":
        log.warning("ATLAS_INGEST_ENABLED=1 ignored: ingest needs ATLAS_DATA_BACKEND=db")
        return False
    return True


def announce(url_prefix):
    log.warning(
        "SECURITY: relay ingest is ENABLED at %s/* — these endpoints bypass the Hub "
        "session gate and trust per-site bearer tokens alone. Issue tokens with "
        "`python cli.py token-issue`, revoke with `python cli.py token-revoke`.", url_prefix)


MAX_TRACKED = 4096


class _RateLimiter:

    def __init__(self, limit=RATE_LIMIT, window=RATE_WINDOW):
        self.limit, self.window = limit, window
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key):
        now = time.monotonic()
        with self._lock:
            if len(self._hits) >= MAX_TRACKED:
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


limiter = _RateLimiter()


def _bearer():
    import security
    return security.bearer_token(request) or None


def authenticate():
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
        if site is None:
            return jsonify({"error": "token's site no longer exists"}), 403
        g.site_slug, g.token_id = site.slug, row.id

    if not limiter.hit(g.token_id):
        return jsonify({"error": f"rate limit: {RATE_LIMIT} requests/minute"}), 429
    return None


def body():
    data = request.get_data(cache=True)
    if len(data) > MAX_BYTES:
        return None, (jsonify({"error": f"payload too large (max {MAX_BYTES} bytes)"}), 413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify({"error": "expected a JSON object"}), 422)
    named = payload.get("site")
    if named and named != g.site_slug:
        log.warning("ingest: token %s tried to write site %r (owns %r)",
                    g.token_id, named, g.site_slug)
        return None, (jsonify({"error": "token is not valid for that site"}), 403)
    return payload, None
