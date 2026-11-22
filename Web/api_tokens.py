import hashlib
import hmac
import ipaddress
import logging
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque

from flask import g, has_request_context, jsonify, request

import envnames
import settings
import token_log
from filelock import exclusive, lock_for
from jsonio import iso_utc, read_json_dict, write_json_atomic

log = logging.getLogger("atlas.api.tokens")

ACCESS_ENV = "ATLAS_AGENT_API"
OFF_REASON = ("Agent access is turned off on this Atlas. "
              "An admin can turn it on in Settings, Connections.")
_NO = ("0", "off", "false", "no")
_YES = ("1", "on", "true", "yes")
_KEEP = object()

PREFIX = "atl_"
STORE = "api-tokens.json"
MAX_TOKENS = 50
MAX_NAME = 64
LIFETIMES = (30, 90, 365, None)
DEFAULT_DAYS = 90
FULL, CLOUD = "full", "cloud"
PROFILES = (FULL, CLOUD)
CLOUD_LIFETIMES = (7, 30)
CLOUD_DEFAULT_DAYS = 30
CLOUD_ONLY_MCP = ("This token is for a cloud tool, so it reads through the MCP endpoint only. "
                  "A script or a local model needs a full token.")
TOUCH_EVERY_S = 60
RATE_PER_MINUTE = 120
PREAUTH_PER_MINUTE = 30
REFUSAL_LOG_EVERY_S = 60

LAN = "lan"
LAN_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10"))
MAX_NETWORKS = 8
OUTSIDE = ("This token only works from the networks it was bound to, "
           "and this request came from somewhere else.")

MCP_PATH = "/api/v2/mcp"
READ_PATHS = frozenset({
    "/api/v2/lab-data",
    "/api/v2/maps",
    "/api/v2/signals",
    "/api/v2/rites",
    "/api/v2/events",
    "/api/v2/places/roster",
    "/api/v2/overview",
    "/api/v2/openapi.json",
})

_TOKEN = re.compile(r"^atl_([0-9a-f]{8})_[A-Za-z0-9_-]{32,64}$")
_lock = threading.Lock()
_recent = defaultdict(deque)
_touched = {}
_misses = defaultdict(deque)
_refusal_logged = {}


def _path():
    return os.path.join(settings.DATA_DIR, STORE)


def _lock_path():
    return lock_for(_path())


def _hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _store():
    return read_json_dict(_path())


def _load():
    return list(_store().get("tokens") or [])


def _save(tokens, enabled=_KEEP):
    path = _path()
    chosen = _store().get("enabled") if enabled is _KEEP else enabled
    doc = {"tokens": tokens}
    if isinstance(chosen, bool):
        doc["enabled"] = chosen
    write_json_atomic(path, doc, keep_backup=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def access():
    env = (envnames.env(ACCESS_ENV) or "").strip().lower()
    if env in _NO:
        return {"on": False, "locked": True, "by": "deployment"}
    chosen = _store().get("enabled")
    if isinstance(chosen, bool):
        return {"on": chosen, "locked": False, "by": "settings"}
    on = env in _YES
    return {"on": on, "locked": False, "by": "deployment" if on else "default"}


def set_access(on, actor):
    on = bool(on)
    if on and access()["locked"]:
        raise ValueError(f"This deployment sets {ACCESS_ENV}=0, so agent access "
                         "cannot be turned on here. Change it there.")
    with exclusive(_lock_path()):
        _save(_load(), enabled=on)
    log.warning("agent access turned %s by %s", "on" if on else "off", actor)
    return access()


def profile_of(rec):
    if "profile" not in rec:
        return FULL
    return FULL if rec.get("profile") == FULL else CLOUD


def lifetimes(profile):
    return (CLOUD_LIFETIMES, CLOUD_DEFAULT_DAYS) if profile == CLOUD else (LIFETIMES, DEFAULT_DAYS)


def parse_networks(value):
    if value in (None, False, "", [], "any"):
        return None
    if value is True or value == LAN:
        return [LAN]
    if isinstance(value, str):
        value = [v for v in re.split(r"[\s,]+", value) if v]
    if not isinstance(value, (list, tuple)):
        raise ValueError("Name the networks as a list, like 192.168.1.0/24.")
    if len(value) > MAX_NETWORKS:
        raise ValueError(f"Bind a token to at most {MAX_NETWORKS} networks.")
    out = []
    for item in value:
        text = str(item).strip().lower()
        if text == LAN:
            net = LAN
        else:
            try:
                net = str(ipaddress.ip_network(text, strict=True))
            except ValueError:
                raise ValueError(f"{str(item)[:60]!r} is not a network. "
                                 "Write it like 192.168.1.0/24 or 10.0.0.5.") from None
        if net not in out:
            out.append(net)
    return out or None


def networks_of(rec):
    nets = rec.get("networks")
    if nets is None:
        return None
    if isinstance(nets, str):
        return [nets]
    return [str(n) for n in nets] if isinstance(nets, list) else []


def allowed_from(rec, ip):
    nets = networks_of(rec)
    if nets is None:
        return True
    try:
        addr = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return False
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    for net in nets:
        if net == LAN:
            if any(addr in lan for lan in LAN_NETWORKS):
                return True
            continue
        try:
            if addr in ipaddress.ip_network(net):
                return True
        except ValueError:
            continue
    return False


def _public(rec):
    now = time.time()
    return {k: rec.get(k) for k in ("id", "name", "created", "created_by", "expires", "last_used")} | {
        "expired": bool(rec.get("expires_at")) and rec["expires_at"] <= now,
        "profile": profile_of(rec),
        "untyped": "profile" not in rec,
        "networks": networks_of(rec),
    }


def listing():
    return [_public(t) for t in _load()]


def issue(name, days, actor, profile=FULL, networks=None):
    networks = parse_networks(networks)
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name:
        raise ValueError("Give the token a name, so you can tell it from the next one.")
    if len(name) > MAX_NAME:
        raise ValueError(f"Keep the name under {MAX_NAME} characters.")
    if profile not in PROFILES:
        raise ValueError("A token is either full or cloud.")
    if days not in lifetimes(profile)[0]:
        if profile == CLOUD:
            raise ValueError("A cloud token lasts 7 or 30 days.")
        raise ValueError("That is not one of the offered lifetimes.")
    if not access()["on"]:
        raise ValueError("Agent access is off. Turn it on first, then create the token.")
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
               "expires_at": expires_at, "last_used": None, "profile": profile}
        if networks:
            rec["networks"] = networks
        tokens.append(rec)
        _save(tokens)
    log.info("api token %s (%s, %s) issued by %s, expires %s, from %s", tid, name, profile, actor,
             rec["expires"], ",".join(networks) if networks else "any address")
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
    except Exception as e:
        log.debug("api token last-used not recorded: %s", e)


def authenticate(raw):
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
    try:
        elsewhere = token_log.recent_elsewhere(tid)
    except Exception as e:
        log.debug("api token rate: the shared count was not read: %s", e)
        elsewhere = 0
    now = time.monotonic()
    with _lock:
        q = _recent[tid]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) + elsewhere >= RATE_PER_MINUTE:
            return False
        q.append(now)
        return True


def _client():
    import atlas_auth
    try:
        return atlas_auth.client_ip()
    except Exception:
        return request.remote_addr or "?"


def _missed_too_often(ip):
    now = time.monotonic()
    with _lock:
        q = _misses.get(ip)
        if not q:
            return False
        while q and now - q[0] > 60:
            q.popleft()
        return len(q) >= PREAUTH_PER_MINUTE


def _miss(ip):
    now = time.monotonic()
    with _lock:
        if len(_misses) > 4096:
            _misses.clear()
        _misses[ip].append(now)


def _turned_away(rec, status, reason, why):
    g.api_token_refused = (rec, why)
    return _refuse(status, reason)


def _bearer():
    import security
    return security.bearer_token(request)


def _plain_hub():
    import hub_auth.auth as auth
    return auth.AUTH_MODE == "hub" and not auth.AUTH_SECRET


def _refuse(status, reason):
    error = {401: "Unauthorized", 404: "Not found"}.get(status, "Refused")
    resp = jsonify({"error": error, "reason": reason})
    resp.status_code = status
    if status == 401:
        resp.headers["WWW-Authenticate"] = "Bearer"
    return resp


def gate():
    path = request.path
    if path != MCP_PATH and path not in READ_PATHS:
        return None
    raw = _bearer()
    if path != MCP_PATH and not raw.startswith(PREFIX):
        return None
    if not access()["on"]:
        return _refuse(404 if path == MCP_PATH else 403, OFF_REASON)
    if _plain_hub():
        return _refuse(403, "API tokens need Atlas to do its own sign-in (accounts mode) or the "
                            "Hub to sign each request (ATLAS_HUB_SECRET). This Atlas trusts a "
                            "plain header, so its port must stay closed to everything but the Hub.")
    ip = _client()
    if _missed_too_often(ip):
        resp = _refuse(429, "too many requests without a valid token from this address, wait a minute")
        resp.headers["Retry-After"] = "60"
        return resp
    if not raw:
        _miss(ip)
        return _refuse(401, "an API token is required")
    rec = authenticate(raw)
    if rec is None:
        _miss(ip)
        return _refuse(401, "that token is not valid, or it has expired")
    if not allowed_from(rec, ip):
        log.warning("api token %s (%s) refused from %s: outside its networks", rec["id"], rec.get("name"), ip)
        return _turned_away(rec, 403, OUTSIDE, "outside its networks")
    if path != MCP_PATH and profile_of(rec) == CLOUD:
        return _turned_away(rec, 403, CLOUD_ONLY_MCP, "a cloud token on a read route")
    if path != MCP_PATH and request.method not in ("GET", "HEAD"):
        return _turned_away(rec, 403, "API tokens are read-only", "not a read")
    if not _allow(rec["id"]):
        resp = _turned_away(rec, 429, "too many requests for this token, wait a minute", RATE_LIMITED)
        resp.headers["Retry-After"] = "60"
        return resp
    g.api_token = rec
    g.api_token_ip = ip
    _touch(rec)
    return None


RATE_LIMITED = "over the rate limit"


def log_read(resp):
    if not has_request_context():
        return resp
    rec, why = g.get("api_token"), None
    if rec is None:
        refused = g.get("api_token_refused")
        if not refused:
            return resp
        rec, why = refused
        now = time.monotonic()
        with _lock:
            if len(_refusal_logged) > 4096:
                _refusal_logged.clear()
            key = (rec["id"], why)
            if now - _refusal_logged.get(key, -REFUSAL_LOG_EVERY_S) < REFUSAL_LOG_EVERY_S:
                return resp
            _refusal_logged[key] = now
    token_log.record(rec, profile_of(rec), g.get("api_token_ip") or _client(), resp, refused=why)
    return resp


def current():
    return g.get("api_token") if has_request_context() else None
