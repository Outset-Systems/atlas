"""API TOKENS — how a script, a local model or a coding harness reads this Atlas.

The shape is the one NetBox and Zabbix settled on, narrowed. A token is named,
issued by an admin, shown once and stored only as a hash. It expires unless
someone says otherwise, it records when it was last used, and revoking it is
immediate.

OFF UNTIL SOMEONE TURNS IT ON (2026-11-11). `access()` decides whether any
token is honoured at all, and it starts off: the MCP endpoint answers 404 and a
token on a read route is refused before it is looked up. An admin turns it on in
Settings, Connections; `ATLAS_AGENT_API=0` in the deployment keeps it off and
that screen cannot undo it. The answer is read from the store on every request,
like the tokens, so turning it off is immediate on every worker.

THREE LIMITS, AND WHY THEY ARE NOT OPTIONS:

  * **Read-only.** There is no write scope to choose. The first thing an AI
    harness does with a tool is try it, and a map that can be edited by a model
    on a bad prompt is not a map anyone can trust. Writes stay a person in a
    session.
  * **No more than an ordinary viewer's eyes.** `viewer_groups()` answers an
    empty set for a token request, so `redact_for_groups` and the signals feed
    cut it down as they cut down a signed-in viewer with no clearance: no
    account rosters, no tripwires, no `require_group` places. A token can never
    see more than a person with no groups, whoever issued it, and it sees a
    little less: a URL reaches it without `user:pass@` or its query string
    (`redaction.bare_urls`), and a scheduled job's own words about its run stay
    behind (`heartbeats.without_job_words`).
  * **A short list of doors.** `READ_PATHS` plus the MCP endpoint, GET and HEAD
    only for the former. Everything else ignores the header and answers as if
    there were no credential, so a new route is closed to tokens until a diff
    here says otherwise.

TWO KINDS (2026-11-11). What a tool reads leaves with it, and a cloud harness
sends every tool result to its model's vendor. The Atlas cannot see where a
client sends things, so the admin says which kind a token is when it is made,
and that cannot be changed afterwards:

  * `full` is for a local model or a script on the owner's own network. It reads
    what the limits above describe, on every door.
  * `cloud` is for a cloud AI tool. It reads the reduced view in `cloud_view.py`
    (only places a person has checked, a short list of fields, no address, URL
    or note), through the MCP endpoint only, and it lives 30 days at most.

A token from before the kinds existed is `full`, which is what it was made as,
and the list says so. A kind this code does not recognise gets the reduced view.

WHERE IT MAY COME FROM (2026-11-12). A token can be bound to the local network:
loopback and the private ranges, or a list of networks the admin names. A
request from anywhere else is refused with the token still valid, so a secret
that leaked into a chat log or a backup is no use from the internet. New tokens
are bound unless the admin unticks it; one made before this has no binding and
the list says so. Two limits, stated wherever the choice is offered:

  * The address is the one `atlas_auth.client_ip()` resolves, so it is only as
    true as `ATLAS_TRUSTED_PROXIES`. Behind a proxy Atlas has not been told
    about, every caller looks like the proxy, which is on the local network.
  * It stops a leaked token being used from outside. It does not stop what a
    tool on the local network does with what it reads.

EVERY REQUEST IS WRITTEN DOWN (`token_log.py`): which token, from where, which
route or tool with its arguments, and the size and hash of the answer. The
same file is how the rate limit sees the other worker: `RATE_PER_MINUTE` is one
budget across both workers and the stdio pipe, not one each. Before a token is
even looked up, an address that keeps presenting bad ones to the MCP endpoint
is told to wait (`PREAUTH_PER_MINUTE`).
"""

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

#: The deployment's word on agent access. "0" keeps it off and Settings cannot turn
#: it on; "1" turns it on until an admin turns it off; unset leaves it to the
#: switch in Settings, which starts off.
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
#: Offered lifetimes, in days. None = never, which is allowed and is not the default.
LIFETIMES = (30, 90, 365, None)
DEFAULT_DAYS = 90
#: The two kinds of token. See TWO KINDS in the module docstring.
FULL, CLOUD = "full", "cloud"
PROFILES = (FULL, CLOUD)
#: A cloud token is short-lived on purpose, and there is no "never" for one.
CLOUD_LIFETIMES = (7, 30)
CLOUD_DEFAULT_DAYS = 30
CLOUD_ONLY_MCP = ("This token is for a cloud tool, so it reads through the MCP endpoint only. "
                  "A script or a local model needs a full token.")
#: `last_used` is a convenience, not an audit log: one write a minute at most, so
#: a chatty harness does not turn every read into a file replace.
TOUCH_EVERY_S = 60
RATE_PER_MINUTE = 120
#: Bad or missing tokens one address may present to the MCP endpoint in a minute
#: before it is refused without the store being read. Per process: it only has
#: to make guessing slow and the unauthenticated path cheap.
PREAUTH_PER_MINUTE = 30
#: A refusal is logged once a minute per token and reason, not once per request:
#: the log must not be something a looping client can fill, and its row ceiling
#: must not be spent on refusals at the cost of real reads.
REFUSAL_LOG_EVERY_S = 60

#: "The local network", as a token's binding means it: loopback, the private
#: ranges, link-local, and IPv6's unique-local range. Not carrier-grade NAT
#: (100.64/10): an admin who reaches the lab over an overlay names it.
LAN = "lan"
LAN_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10"))
MAX_NETWORKS = 8
OUTSIDE = ("This token only works from the networks it was bound to, "
           "and this request came from somewhere else.")

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
_misses = defaultdict(deque)
_refusal_logged = {}


def _path():
    return os.path.join(settings.DATA_DIR, STORE)


def _lock_path():
    """A sidecar: the store itself is replaced on save, so it cannot hold a lock."""
    return lock_for(_path())


def _hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _store():
    """Read the file every time, on purpose. It is at most 50 short rows, and a
    cache keyed on its mtime let a revoked token keep working: two writes in one
    clock tick look like no write at all. Revoking has to be immediate, and so
    does turning agent access off."""
    return read_json_dict(_path())


def _load():
    return list(_store().get("tokens") or [])


def _save(tokens, enabled=_KEEP):
    """Write the tokens, and the switch beside them. `enabled` left alone keeps
    whatever the file says, so issuing or revoking never moves the switch."""
    path = _path()
    chosen = _store().get("enabled") if enabled is _KEEP else enabled
    doc = {"tokens": tokens}
    if isinstance(chosen, bool):
        doc["enabled"] = chosen
    write_json_atomic(path, doc, keep_backup=False)
    try:
        os.chmod(path, 0o600)
    except OSError:      # a share that will not take modes; the hashes are not the keys
        pass


def access():
    """Whether a token may read this Atlas at all: `{"on", "locked", "by"}`.

    Three voices, and off wins. The deployment's `ATLAS_AGENT_API=0` is a lock:
    nothing on the Settings screen undoes it, so a stolen admin session cannot
    open what the owner closed in the compose file. Otherwise the switch an admin
    set in Settings decides. With neither, `ATLAS_AGENT_API=1` means on and
    anything else means off, which is how a fresh install starts.
    """
    env = (envnames.env(ACCESS_ENV) or "").strip().lower()
    if env in _NO:
        return {"on": False, "locked": True, "by": "deployment"}
    chosen = _store().get("enabled")
    if isinstance(chosen, bool):
        return {"on": chosen, "locked": False, "by": "settings"}
    on = env in _YES
    return {"on": on, "locked": False, "by": "deployment" if on else "default"}


def set_access(on, actor):
    """Turn agent access on or off from Settings. Off always works. On is refused
    while the deployment holds the lock. Tokens are kept either way: off refuses
    them, it does not revoke them."""
    on = bool(on)
    if on and access()["locked"]:
        raise ValueError(f"This deployment sets {ACCESS_ENV}=0, so agent access "
                         "cannot be turned on here. Change it there.")
    with exclusive(_lock_path()):
        _save(_load(), enabled=on)
    log.warning("agent access turned %s by %s", "on" if on else "off", actor)
    return access()


def profile_of(rec):
    """Which view a token reads. One made before the kinds existed is `full`: that
    is what it was issued as. Anything else that is not exactly `full` reads the
    reduced view, so a kind this code does not know is never the larger one."""
    if "profile" not in rec:
        return FULL
    return FULL if rec.get("profile") == FULL else CLOUD


def lifetimes(profile):
    """(offered lifetimes in days, the default) for a kind of token."""
    return (CLOUD_LIFETIMES, CLOUD_DEFAULT_DAYS) if profile == CLOUD else (LIFETIMES, DEFAULT_DAYS)


def parse_networks(value):
    """What a token is bound to, as it is stored: `None` (anywhere), `["lan"]`,
    or a short list of networks in CIDR form. Raises ValueError with a sentence
    for the form.

    `True` and `"lan"` mean the local network. A list may mix `"lan"` with
    networks. A bare address is taken as that one host. A network must be
    written at its own address (`10.0.0.0/8`, not `10.1.2.3/8`): a typo that
    silently widened a binding would be the wrong way to fail.
    """
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
    """A token's binding as stored, or None when it may be used from anywhere."""
    nets = rec.get("networks")
    if nets is None:
        return None
    # Anything else that is not a list of networks is a store someone edited by
    # hand. It must not read as "anywhere": a bare string is taken as one entry,
    # and what cannot be read at all admits nothing.
    if isinstance(nets, str):
        return [nets]
    return [str(n) for n in nets] if isinstance(nets, list) else []


def allowed_from(rec, ip):
    """Whether a request from `ip` may use this token. Unbound: yes. Bound: only
    from inside one of its networks, and an address that cannot be read as one
    is outside all of them."""
    nets = networks_of(rec)
    if nets is None:
        return True
    try:
        addr = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return False
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:           # ::ffff:192.168.1.5 is 192.168.1.5
        addr = mapped
    for net in nets:
        if net == LAN:
            if any(addr in lan for lan in LAN_NETWORKS):
                return True
            continue
        try:
            if addr in ipaddress.ip_network(net):
                return True
        except ValueError:           # a stored entry nobody can read admits nothing
            continue
    return False


def _public(rec):
    now = time.time()
    return {k: rec.get(k) for k in ("id", "name", "created", "created_by", "expires", "last_used")} | {
        "expired": bool(rec.get("expires_at")) and rec["expires_at"] <= now,
        "profile": profile_of(rec),
        # made before a token had a kind: it reads the full view, and nobody chose that
        "untyped": "profile" not in rec,
        # None = usable from any address; a token made before bindings has none
        "networks": networks_of(rec),
    }


def listing():
    """Tokens as a form may show them: never the hash."""
    return [_public(t) for t in _load()]


def issue(name, days, actor, profile=FULL, networks=None):
    """Create a token. Returns (public record, the plaintext, shown this once).

    `profile` and `networks` are fixed here for the token's life: there is no
    route that changes either, so a cloud token cannot be widened, a binding
    cannot be lifted, and a token that needs more is revoked and made again.
    """
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
        # a token minted while access is off would start working, unannounced,
        # the moment someone turned it on
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
    """One budget for a token across every process that serves it. This process
    counts what it has let through in memory; what the other worker or a stdio
    pipe served is read from the log they all write. If the log cannot be read
    the count falls back to this process alone, which is what it was before."""
    try:
        elsewhere = token_log.recent_elsewhere(tid)
    except Exception as e:  # noqa: BLE001 — the limit must not fail a read
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
    """The caller's address, by the one rule the sign-in throttle uses."""
    import atlas_auth
    try:
        return atlas_auth.client_ip()
    except Exception:  # noqa: BLE001 — an address we cannot resolve is outside every binding
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
    """Count a request that carried no token or a bad one."""
    now = time.monotonic()
    with _lock:
        if len(_misses) > 4096:      # a flood of addresses must not become a flood of memory
            _misses.clear()
        _misses[ip].append(now)


def _turned_away(rec, status, reason, why):
    """Refuse a request whose token is valid, and remember why for the log."""
    g.api_token_refused = (rec, why)
    return _refuse(status, reason)


def _bearer():
    import security
    return security.bearer_token(request)


def _plain_hub():
    """Hub mode with no signing secret: Atlas believes a plain `X-Remote-User`
    header, so it is safe only while nothing but the Hub can reach its port. A
    client with a token has to reach that port itself, which is the one thing
    that mode cannot survive, so tokens are not served there."""
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
    if not access()["on"]:
        # OFF IS OFF. The MCP endpoint is not there, and a token on a read route is
        # refused before it is looked up, so a leaked one cannot even learn whether
        # it is still valid.
        return _refuse(404 if path == MCP_PATH else 403, OFF_REASON)
    if _plain_hub():
        return _refuse(403, "API tokens need Atlas to do its own sign-in (accounts mode) or the "
                            "Hub to sign each request (ATLAS_HUB_SECRET). This Atlas trusts a "
                            "plain header, so its port must stay closed to everything but the Hub.")
    ip = _client()
    if _missed_too_often(ip):
        # before the store is read: an address guessing tokens gets slow answers
        # that cost nothing to give
        resp = _refuse(429, "too many requests without a valid token from this address, wait a minute")
        resp.headers["Retry-After"] = "60"
        return resp
    if not raw:
        # The MCP endpoint is not the map's: a token is its whole credential, which
        # is also why it needs no same-origin check (a cookie opens nothing here).
        _miss(ip)
        return _refuse(401, "an API token is required")
    rec = authenticate(raw)
    if rec is None:
        _miss(ip)
        return _refuse(401, "that token is not valid, or it has expired")
    if not allowed_from(rec, ip):
        # first, so a token used from outside learns nothing else about itself
        log.warning("api token %s (%s) refused from %s: outside its networks", rec["id"], rec.get("name"), ip)
        return _turned_away(rec, 403, OUTSIDE, "outside its networks")
    if path != MCP_PATH and profile_of(rec) == CLOUD:
        # the read routes serve the dataset whole; the reduced view lives in the tools
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
    """Runs after every request. Writes the read log's line for one a token made,
    served or refused, and leaves every other response alone."""
    if not has_request_context():
        return resp
    rec, why = g.get("api_token"), None
    if rec is None:
        refused = g.get("api_token_refused")
        if not refused:
            return resp
        rec, why = refused
        # every refusal, not only the rate limit: a token outside its networks or
        # hammering a write is refused before the limit is counted, and each of
        # those would otherwise be a line
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
    """The token behind this request, or None."""
    return g.get("api_token") if has_request_context() else None
