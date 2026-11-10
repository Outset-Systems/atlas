"""API TOKENS — how a script, a local model or a coding harness reads this Atlas.

The shape is the one NetBox and Zabbix settled on, narrowed. A token is named,
issued by an admin, shown once and stored only as a hash. It expires unless
someone says otherwise, it records when it was last used, and revoking it is
immediate.

THREE LIMITS, AND WHY THEY ARE NOT OPTIONS:

  * **Read-only.** There is no write scope to choose. The first thing an AI
    harness does with a tool is try it, and a map that can be edited by a model
    on a bad prompt is not a map anyone can trust. Writes stay a person in a
    session.
  * **An ordinary viewer's eyes.** `viewer_groups()` answers an empty set for a
    token request, so `redact_for_groups` and the signals feed cut it down
    exactly as they cut down a signed-in viewer with no clearance: no account
    rosters, no tripwires, no `require_group` places. A token can never see more
    than a person with no groups, whoever issued it.
  * **A short list of doors.** `READ_PATHS` plus the MCP endpoint, GET only for
    the former. Everything else ignores the header and answers as if there were
    no credential, so a new route is closed to tokens until a diff here says
    otherwise.

What a tool reads leaves with it. A cloud harness sends tool results to its
model's vendor, which is why the Settings screen says so beside the button.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque

from flask import g, has_request_context, jsonify, request

import settings
from filelock import exclusive
from jsonio import iso_utc, read_json_dict, write_json_atomic

log = logging.getLogger("atlas.api.tokens")

PREFIX = "atl_"
STORE = "api-tokens.json"
MAX_TOKENS = 50
MAX_NAME = 64
#: Offered lifetimes, in days. None = never, which is allowed and is not the default.
LIFETIMES = (30, 90, 365, None)
DEFAULT_DAYS = 90
#: `last_used` is a convenience, not an audit log: one write a minute at most, so
#: a chatty harness does not turn every read into a file replace.
TOUCH_EVERY_S = 60
RATE_PER_MINUTE = 120

MCP_PATH = "/api/v2/mcp"
#: The read routes a token may call. A literal, so widening it shows in a diff.
READ_PATHS = frozenset({
    "/api/v2/lab-data",
    "/api/v2/maps",
    "/api/v2/signals",
    "/api/v2/rites",
    "/api/v2/events",
    # the reference for the five above: static, and the same file as docs/openapi.json
    "/api/v2/openapi.json",
})

_TOKEN = re.compile(r"^atl_([0-9a-f]{8})_[A-Za-z0-9_-]{32,64}$")
_lock = threading.Lock()
_recent = defaultdict(deque)
_touched = {}


def _path():
    return os.path.join(settings.DATA_DIR, STORE)


def _lock_path():
    """A sidecar: the store itself is replaced on save, so it cannot hold a lock."""
    return _path() + ".lock"


def _hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load():
    """Read the file every time, on purpose. It is at most 50 short rows, and a
    cache keyed on its mtime let a revoked token keep working: two writes in one
    clock tick look like no write at all. Revoking has to be immediate."""
    return list(read_json_dict(_path()).get("tokens") or [])


def _save(tokens):
    path = _path()
    write_json_atomic(path, {"tokens": tokens}, keep_backup=False)
    try:
        os.chmod(path, 0o600)
    except OSError:      # a share that will not take modes; the hashes are not the keys
        pass


def _public(rec):
    now = time.time()
    return {k: rec.get(k) for k in ("id", "name", "created", "created_by", "expires", "last_used")} | {
        "expired": bool(rec.get("expires_at")) and rec["expires_at"] <= now,
    }


def listing():
    """Tokens as a form may show them: never the hash."""
    return [_public(t) for t in _load()]


def issue(name, days, actor):
    """Create a token. Returns (public record, the plaintext, shown this once)."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name:
        raise ValueError("Give the token a name, so you can tell it from the next one.")
    if len(name) > MAX_NAME:
        raise ValueError(f"Keep the name under {MAX_NAME} characters.")
    if days not in LIFETIMES:
        raise ValueError("That is not one of the offered lifetimes.")
    with exclusive(_lock_path()):
        tokens = _load()
        if len(tokens) >= MAX_TOKENS:
            raise ValueError("That is the limit. Revoke one you no longer use.")
        if any(t.get("name") == name for t in tokens):
            raise ValueError("A token already has that name.")
        tid = secrets.token_hex(4)
        raw = f"{PREFIX}{tid}_{secrets.token_urlsafe(32)}"
        now = time.time()
        expires_at = now + days * 86400 if days else None
        rec = {"id": tid, "name": name, "hash": _hash(raw), "created": iso_utc(now),
               "created_by": actor, "expires": iso_utc(expires_at) if expires_at else None,
               "expires_at": expires_at, "last_used": None}
        tokens.append(rec)
        _save(tokens)
    log.info("api token %s (%s) issued by %s, expires %s", tid, name, actor, rec["expires"])
    return _public(rec), raw


def revoke(tid, actor):
    with exclusive(_lock_path()):
        tokens = _load()
        kept = [t for t in tokens if t.get("id") != tid]
        if len(kept) == len(tokens):
            return False
        _save(kept)
    log.info("api token %s revoked by %s", tid, actor)
    return True


def _touch(rec):
    now = time.time()
    if now - _touched.get(rec["id"], 0) < TOUCH_EVERY_S:
        return
    _touched[rec["id"]] = now
    try:
        with exclusive(_lock_path(), timeout=0.2):
            tokens = _load()
            for t in tokens:
                if t.get("id") == rec["id"]:
                    t["last_used"] = iso_utc(now)
            _save(tokens)
    except Exception as e:  # noqa: BLE001 — a read must never fail over its own bookkeeping
        log.debug("api token last-used not recorded: %s", e)


def authenticate(raw):
    """The token's record, or None. The id only finds the row; the hash decides."""
    m = _TOKEN.match(raw or "")
    if not m:
        return None
    want = _hash(raw)
    for rec in _load():
        if rec.get("id") == m.group(1) and hmac.compare_digest(str(rec.get("hash") or ""), want):
            if rec.get("expires_at") and rec["expires_at"] <= time.time():
                return None
            return rec
    return None


def _allow(tid):
    now = time.monotonic()
    with _lock:
        q = _recent[tid]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_PER_MINUTE:
            return False
        q.append(now)
        return True


def _bearer():
    import security
    return security.bearer_token(request)


def _refuse(status, reason):
    resp = jsonify({"error": "Unauthorized" if status == 401 else "Refused", "reason": reason})
    resp.status_code = status
    if status == 401:
        resp.headers["WWW-Authenticate"] = "Bearer"
    return resp


def gate():
    """Run before the session gate. Returns a response to send, or None.

    None with `g.api_token` set means a token has vouched for this request and
    the session gate must not run. None without it means this is not a token
    request and the session gate decides, as if this module did not exist.
    """
    path = request.path
    if path != MCP_PATH and path not in READ_PATHS:
        return None
    raw = _bearer()
    if path != MCP_PATH and not raw.startswith(PREFIX):
        # The read routes are also the map's own, for a browser with a session,
        # and another kind of bearer (a relay's site token) is none of our business.
        return None
    if not raw:
        # The MCP endpoint is not the map's: a token is its whole credential, which
        # is also why it needs no same-origin check (a cookie opens nothing here).
        return _refuse(401, "an API token is required")
    rec = authenticate(raw)
    if rec is None:
        return _refuse(401, "that token is not valid, or it has expired")
    if path != MCP_PATH and request.method not in ("GET", "HEAD"):
        return _refuse(403, "API tokens are read-only")
    if not _allow(rec["id"]):
        resp = _refuse(429, "too many requests for this token, wait a minute")
        resp.headers["Retry-After"] = "60"
        return resp
    g.api_token = rec
    _touch(rec)
    return None


def current():
    """The token behind this request, or None."""
    return g.get("api_token") if has_request_context() else None
