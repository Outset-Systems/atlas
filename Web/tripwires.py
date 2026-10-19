"""TRIPWIRES — honeypots and canary tokens, and the trips that reach the map.

`stones[]` charts the bait (schema.py). This module is everything that happens
when something touches it and a tool says so: the webhook's credential check,
the three payload shapes it understands, attributing a trip to a charted
tripwire, writing it into THE ANNALS, and the read model the scene draws.
The payload shapes were checked against each sender's own source.

**Where a trip goes.** Into the annals (`events.json`) as a `kind: tripwire`
event, so it is acknowledged, counted and listed like every other thing that
befell the realm. The annals are a JSON file on every backend, which is why the
webhook works on the default file install — the relay ingest it sits beside
needs the database, a trip does not. Beside the annals, `tripwires.json` keeps
one small row per sender: when it was last heard and when it last tripped.

**What a trip may carry.** A payload is attacker-influenced: an intruder
chooses what they type into a fake login, and the honeypot faithfully reports
it. So nothing is stored as received. A trip is rebuilt from an allow-list —
source, the name it was matched on, a signal label, an IP address (only if it
parses as one), a port, a time — every string stripped of control and markup
characters and capped. Usernames, passwords, paths, memos, management URLs and
the raw body never touch the disk or a response.

**Who may see it.** Where a honeypot sits is a map for an intruder. Charted
tripwires and their trips are admin-only (redaction.py, api/v2/feeds.py,
api/v2/tripwires.py).
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from urllib.parse import parse_qs

import envnames
import events
import schema
import settings
from ingest import _RateLimiter
from jsonio import iso_utc
from jsonstore import JsonStore

log = logging.getLogger("atlas.live.tripwires")

MAX_BYTES = 64 * 1024        # an alert is a few hundred bytes; a canary's geo blob a few KB
RATE_LIMIT = 60              # trips per credential per minute (a port scan coalesces anyway)
CAP = 200                    # the longest any stored string may be
LIT_HOURS = 24               # "lit" = an unacknowledged trip within this window
COALESCE_SECONDS = 600       # one storm, one event: same tripwire+source+sensor, unacked
RECENT_PER_TRIPWIRE = 10     # trips listed under each tripwire
UNMATCHED_SHOWN = 20         # unmatched trips listed
SECRET_MIN = 16              # a shorter secret is refused as unset
SOURCES = ("opencanary", "canarytokens", "generic")
KEY_PLACEHOLDER = "YOUR-WEBHOOK-KEY"
_KEY_LABEL = b"atlas-tripwires-key/v1"

#: The ingest gate's limiter class, a separate instance: a trip storm must not
#: spend a relay's budget, nor a relay a honeypot's.
limiter = _RateLimiter(limit=RATE_LIMIT, window=60.0)


# ── configuration ────────────────────────────────────────────────────────────
def secret():
    """The webhook secret (ATLAS_TRIPWIRES_SECRET, or the file named by
    ATLAS_TRIPWIRES_SECRET_FILE), or '' when unset or too short to trust."""
    value = (envnames.env("ATLAS_TRIPWIRES_SECRET") or "").strip()
    if not value:
        path = envnames.env("ATLAS_TRIPWIRES_SECRET_FILE")
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    value = fh.read().strip()
            except OSError as e:  # pragma: no cover - defensive
                log.warning("could not read tripwires secret file: %s", e)
    if value and len(value) < SECRET_MIN:
        log.warning("ATLAS_TRIPWIRES_SECRET is shorter than %d characters; ignored", SECRET_MIN)
        return ""
    return value


def webhook_key(secret_value=None):
    """The bearer/query key, DERIVED from the secret so the signing secret
    itself never travels. Rotating the secret rotates the key. '' when unset."""
    s = secret() if secret_value is None else secret_value
    if not s:
        return ""
    return "atlas_tw_" + hmac.new(s.encode("utf-8"), _KEY_LABEL, hashlib.sha256).hexdigest()[:48]


def enabled():
    """Is the webhook live? Off unless ATLAS_TRIPWIRES_WEBHOOK=1, and off when
    no credential could ever be valid (no secret, and no db for site tokens):
    an endpoint that cannot be used should not be reachable."""
    if (envnames.env("ATLAS_TRIPWIRES_WEBHOOK") or "").strip() != "1":
        return False
    return bool(secret()) or settings.DATA_BACKEND == "db"


def state_path():
    return envnames.env("ATLAS_TRIPWIRES_STATE") or os.path.join(
        os.path.dirname(settings.EVENTS_PATH) or ".", "tripwires.json")


def _shape_state(raw):
    sources = raw.get("sources") if isinstance(raw, dict) else None
    return {"sources": {k: v for k, v in (sources or {}).items()
                        if k in SOURCES and isinstance(v, dict)}}


_STATE = JsonStore(state_path, _shape_state)


# ── the credential ───────────────────────────────────────────────────────────
def _refuse(message, status):
    from flask import jsonify
    return jsonify({"error": message}), status


def authenticate(raw):
    """Who sent this? Returns (credential_id, None) or (None, response).

    Three ways to present one credential, because each sender can do exactly
    one: an HMAC signature over the body (scripts), a bearer header
    (OpenCanary), a `key` query parameter (Canarytokens, which takes a bare
    URL). The bearer and query forms accept the derived webhook key, or on
    the db backend a site token carrying the `tripwires` scope."""
    from flask import request

    s = secret()
    signature = request.headers.get("X-Atlas-Signature")
    if signature is not None:
        if not s:
            return None, _refuse("signatures are not configured (no ATLAS_TRIPWIRES_SECRET)", 401)
        want = "sha256=" + hmac.new(s.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(want.encode(), signature.strip().lower().encode()):
            log.warning("tripwires: bad signature from %s", request.remote_addr)
            return None, _refuse("bad signature", 401)
        return "hmac", None

    raw_auth = request.headers.get("Authorization", "")
    given = raw_auth[7:].strip() if raw_auth.lower().startswith("bearer ") else ""
    given = given or (request.args.get("key") or "").strip()
    if not given:
        return None, _refuse("missing credential (bearer key, ?key=, or X-Atlas-Signature)", 401)

    key = webhook_key(s)
    if key and hmac.compare_digest(key.encode(), given.encode()):
        return "key", None

    if settings.DATA_BACKEND == "db":
        from store import session_scope
        from store.tokens import verify_token
        with session_scope() as session:
            site, row, err = verify_token(session, given, scope="tripwires")
            if err == "revoked":
                log.warning("tripwires: revoked token %s from %s", row.id, request.remote_addr)
                return None, _refuse("token revoked", 401)
            if err == "scope":
                return None, _refuse("token lacks the 'tripwires' scope", 403)
            if err is None:
                if site is None or site.slug != settings.SITE_SLUG:
                    # the tenancy invariant: these annals are this site's
                    return None, _refuse("token is not valid for this site", 403)
                return f"token:{row.id}", None
    log.warning("tripwires: unknown credential from %s", request.remote_addr)
    return None, _refuse("unknown credential", 401)


# ── reading a payload ────────────────────────────────────────────────────────
_SPACE = re.compile(r"[\t\n\r]")
#: Control characters, markup and quote characters, the backslash, and the
#: invisible formatting/bidi marks that can disguise what a string says.
_STRIP = re.compile(r"[\x00-\x1f\x7f<>&\"'`\\\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def clean(value, cap=CAP):
    """A stored string: text or a number only, control/markup characters
    removed, whitespace collapsed, capped. None when nothing is left."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = " ".join(_STRIP.sub("", _SPACE.sub(" ", value[:cap * 4])).split())
    return value[:cap] or None


def clean_ip(value):
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def clean_port(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, int) and 0 < value < 65536:
        return value
    return None


_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S (UTC)")


def parse_time(value):
    """The sender's own claim of when, as the Atlas's UTC spelling, or None.
    OpenCanary writes `2026-10-18 12:00:00.123456` (UTC), Canarytokens
    `2026-10-18 12:00:00 (UTC)`, the generic shape ISO 8601. A time more than a
    day ahead is not believed."""
    if not isinstance(value, str) or not value or len(value) > 40:
        return None
    text = value.strip()
    dt = None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in _TIME_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    epoch = dt.timestamp()
    if epoch > time.time() + 86400 or dt.year < 2000:
        return None
    return iso_utc(epoch)


def parse_body(raw):
    """A JSON object, or a form body (OpenCanary posts `data=` form-encoded
    unless a header value says application/json). None when neither."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError):
        obj = None
        if "=" in text and not text.lstrip().startswith(("{", "[")):
            try:
                form = parse_qs(text, max_num_fields=50, strict_parsing=True)
            except ValueError:
                return None
            obj = {k: v[0] for k, v in form.items() if v}
    return obj if isinstance(obj, dict) else None


#: OpenCanary's logtypes (opencanary/logger.py LoggerBase.LOG_*), by name.
#: 1000-1006 are the daemon talking about itself: contact, never a trip.
OPENCANARY_LOGTYPES = {
    1000: "boot", 1001: "message", 1002: "debug", 1003: "error", 1004: "ping",
    1005: "config saved", 1006: "example",
    2000: "FTP login attempt", 2001: "FTP auth attempt",
    3000: "HTTP GET", 3001: "HTTP login attempt", 3002: "HTTP unimplemented method",
    3003: "HTTP redirect",
    4000: "SSH new connection", 4001: "SSH version sent", 4002: "SSH login attempt",
    5000: "SMB file open", 5001: "port scan (SYN)", 5002: "port scan (nmap OS)",
    5003: "port scan (nmap NULL)", 5004: "port scan (nmap XMAS)", 5005: "port scan (nmap FIN)",
    6001: "telnet login attempt", 6002: "telnet connection",
    7001: "HTTP proxy login attempt", 8001: "MySQL login attempt",
    9001: "MSSQL login (SQL auth)", 9002: "MSSQL login (Windows auth)",
    9003: "MySQL connection", 10001: "TFTP", 11001: "NTP monlist", 12001: "VNC",
    13001: "SNMP command", 14001: "RDP", 15001: "SIP request", 16001: "git clone",
    17001: "Redis command", 18001: "TCP banner connection", 18002: "TCP banner keep-alive",
    18003: "TCP banner secret received", 18004: "TCP banner data (keep-alive)",
    18005: "TCP banner data", 19001: "LLMNR query response", 20001: "MongoDB login attempt",
}
OPENCANARY_CONTACT = range(1000, 1007)
#: What Canarytokens sends when a webhook is saved (webhook_formatting.py,
#: generate_webhook_test_payload): proof of contact, not a trip.
CANARYTOKENS_TEST_TOKEN = "a+test+token"


def _reading(source, keys, signal=None, src=None, port=None, sent_at=None,
             contact_only=False, label=None):
    keys = [(field, v) for field, v in keys if v]
    return {"source": source, "keys": keys, "signal": clean(signal, 80),
            "src": src, "port": port, "sent_at": sent_at, "contact_only": contact_only,
            "label": clean(label) or (keys[0][1] if keys else None)}


def _opencanary(p):
    rec = p
    if "logtype" not in p and isinstance(p.get("message"), str):
        try:
            rec = json.loads(p["message"])
        except (ValueError, RecursionError):
            return None
    if not isinstance(rec, dict) or "logtype" not in rec:
        return None
    try:
        logtype = int(rec.get("logtype"))
    except (TypeError, ValueError):
        return None
    node = clean(rec.get("node_id"))
    dst = clean(rec.get("dst_host"), 64)
    port = clean_port(rec.get("dst_port"))
    keys = []
    if port:
        keys += [("sensor", node and f"{node}:{port}"), ("sensor", dst and f"{dst}:{port}")]
    keys += [("sensor", node), ("sensor", dst), ("id", node)]
    return _reading("opencanary", keys,
                    signal=OPENCANARY_LOGTYPES.get(logtype, f"logtype {logtype}"),
                    src=clean_ip(rec.get("src_host")), port=port,
                    sent_at=parse_time(rec.get("utc_time") or rec.get("local_time")),
                    contact_only=logtype in OPENCANARY_CONTACT,
                    label=node or dst)


def _canarytokens(p):
    if not ("manage_url" in p or ("token" in p and "channel" in p)):
        return None
    token, memo = clean(p.get("token")), clean(p.get("memo"))
    signal = " ".join(x for x in (clean(p.get("channel"), 40), clean(p.get("token_type"), 40)) if x)
    return _reading("canarytokens",
                    [("sensor", token), ("id", memo), ("sensor", memo)],
                    signal=signal or "canarytoken", src=clean_ip(p.get("src_ip")),
                    sent_at=parse_time(p.get("time")),
                    contact_only=p.get("token") == CANARYTOKENS_TEST_TOKEN,
                    label=token)


def _generic(p):
    if "tripwire_id" not in p:
        return None
    tid = clean(p.get("tripwire_id"))
    return _reading("generic", [("id", tid), ("sensor", tid)],
                    signal=p.get("kind") or "trip", src=clean_ip(p.get("src")),
                    port=clean_port(p.get("port")), sent_at=parse_time(p.get("at")),
                    contact_only=p.get("kind") == "ping", label=tid)


def interpret(payload):
    """The payload as a reading (which sender, what to match on, the
    allow-listed facts), or None when it is none of the three shapes."""
    if not isinstance(payload, dict):
        return None
    for reader in (_generic, _opencanary, _canarytokens):
        out = reader(payload)
        if out is not None:
            return out
    return None


def match(reading, stones):
    """The charted stone this reading names, or None. First hit wins, in the
    order the reading lists its keys."""
    by = {"id": {}, "sensor": {}}
    for s in stones or []:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        by["id"].setdefault(str(s["id"]).strip().lower(), s)
        if isinstance(s.get("sensor"), str) and s["sensor"].strip():
            by["sensor"].setdefault(s["sensor"].strip().lower(), s)
    for field, value in reading["keys"]:
        hit = by[field].get(str(value).strip().lower())
        if hit is not None:
            return hit
    return None


def gravity_for(stone):
    """The annals' gravity. Anything internal reaches a human; a `wan` stone
    is the only kind whose low-severity trips may be filed quietly. A trip
    nobody can attribute is grave: it is bait we did not know we had."""
    if stone is None or stone.get("zone") != "wan":
        return "grave"
    return {"critical": "grave", "high": "grave", "medium": "warn"}.get(
        stone.get("severity"), "quiet")


# ── writing it down ──────────────────────────────────────────────────────────
def _epoch(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def touch(source, tripped):
    """Stamp the sender's row: heard now, and tripped now if it was a trip."""
    now = iso_utc()
    with _STATE.locked():
        state = _STATE.load()
        row = state["sources"].setdefault(source, {})
        row["last_heard"] = now
        row["heard"] = int(row.get("heard") or 0) + 1
        if tripped:
            row["last_trip"] = now
            row["trips"] = int(row.get("trips") or 0) + 1
        _STATE.save(state)


def record(reading, stone):
    """Write the trip into THE ANNALS. Returns (event, coalesced)."""
    now = iso_utc()
    target = str(stone["id"]) if stone else "unmatched"
    sensor = reading["label"]
    with events._STORE.locked():
        store = events._STORE.load()
        for ev in reversed(store["events"][-200:]):
            trip = ev.get("trip") if ev.get("kind") == "tripwire" else None
            if not isinstance(trip, dict) or ev.get("ack"):
                continue
            if (ev.get("target") == target and trip.get("source") == reading["source"]
                    and trip.get("sensor") == sensor
                    and time.time() - _epoch(trip.get("last_at")) <= COALESCE_SECONDS):
                trip["count"] = min(int(trip.get("count") or 1) + 1, 10 ** 6)
                trip["last_at"] = now
                events._STORE.save(store)
                return ev, True
        store["seq"] += 1
        event = {
            "id": store["seq"], "at": now, "kind": "tripwire", "target": target,
            "name": (str(stone.get("name") or stone["id"])[:CAP] if stone else "unmatched trip"),
            "from": "quiet", "to": "tripped", "gravity": gravity_for(stone), "ack": None,
            "trip": {"source": reading["source"], "sensor": sensor,
                     "signal": reading["signal"], "src": reading["src"],
                     "port": reading["port"], "sent_at": reading["sent_at"],
                     "count": 1, "last_at": now},
        }
        store["events"].append(event)
        if len(store["events"]) > events.KEEP:
            store["events"] = store["events"][-events.KEEP:]
        events._STORE.save(store)
    log.warning("tripwire: %s tripped (%s)", target, reading["source"])
    return event, False


# ── keeping it from viewers who may not see it ───────────────────────────────
def is_trip(event):
    return isinstance(event, dict) and event.get("kind") == "tripwire"


def listing_without_trips(limit=100, visible=None, unacked_only=False):
    """The annals for a viewer not cleared for tripwires: trip rows removed
    BEFORE the limit, so the page is still `limit` long."""
    out = [e for e in events.listing(limit=events.KEEP, visible=visible,
                                     unacked_only=unacked_only) if not is_trip(e)]
    return out[:limit]


def counts_without_trips(visible=None):
    """`events.counts()` with trip rows left out of every total — a bare
    "1 unacknowledged" would say a tripwire just fired."""
    rows = listing_without_trips(limit=events.KEEP, visible=visible)
    day_ago = iso_utc(time.time() - 86400)
    return {"total": len(rows),
            "unacked": sum(1 for e in rows if not e.get("ack")
                           and e.get("gravity") in ("grave", "warn")),
            "last_24h": sum(1 for e in rows if e.get("at", "") >= day_ago)}


# ── the read model ───────────────────────────────────────────────────────────
_STONE_FIELDS = ("id", "name", "kind", "host", "zone", "severity", "placement",
                 "mimics", "planted", "expires", "sensor", "retired", "note")
_DECOY_STATES = ("silent", "stirred", "speaking")


def _trip_view(ev):
    trip = ev.get("trip") or {}
    return {"event": ev.get("id"), "tripwire": None if ev.get("target") == "unmatched"
            else ev.get("target"), "name": ev.get("name"), "source": trip.get("source"),
            "signal": trip.get("signal"), "sensor": trip.get("sensor"),
            "src": trip.get("src"), "port": trip.get("port"), "at": ev.get("at"),
            "last_at": trip.get("last_at") or ev.get("at"), "sent_at": trip.get("sent_at"),
            "count": trip.get("count") or 1, "gravity": ev.get("gravity"),
            "ack": ev.get("ack")}


def _decoy(info):
    if not isinstance(info, dict) or info.get("state") not in _DECOY_STATES:
        return None
    return {"state": info["state"], "last_spoke": clean(info.get("last_spoke"), 40)}


def _expiry(value, today):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return (date.fromisoformat(value.strip()) - today).days
    except ValueError:
        return None


def _latest(*isos):
    vals = [v for v in isos if isinstance(v, str) and v]
    return max(vals, key=_epoch) if vals else None


def _decoy_source(feed, stones_live):
    import integrations
    fs = feed.get("sources") or {}
    configured = ("deception" in integrations.enabled_sources()
                  and bool(integrations.get("ATLAS_DECOYS_URL")))
    out = {"configured": configured, "path": integrations.decoys_path(), "demo": False}
    if "deception" in fs:
        out["contact"] = "ok" if fs["deception"] == "ok" else "lost"
    elif configured:
        out["contact"] = "lost"
    elif fs.get("demo") == "ok" and stones_live:
        out["contact"], out["demo"] = "ok", True
    else:
        out["contact"] = "off"
    metric = (feed.get("metrics") or {}).get("unattributed_trips")
    out["unattributed"] = metric if isinstance(metric, (int, float)) else None
    out["last_trip"] = _latest(*[d["last_spoke"] for d in stones_live.values()
                                 if d and d["state"] != "silent"])
    return out


def _webhook_source():
    state = _STATE.load()["sources"]
    by = {name: {"last_heard": row.get("last_heard"), "last_trip": row.get("last_trip"),
                 "heard": int(row.get("heard") or 0), "trips": int(row.get("trips") or 0)}
          for name, row in state.items()}
    on = enabled()
    has_secret = bool(secret())
    return {"configured": on, "contact": "ok" if on else "off",
            "auth": {"signature": on and has_secret, "key": on and has_secret,
                     "token": on and settings.DATA_BACKEND == "db"},
            "last_heard": _latest(*[r["last_heard"] for r in by.values()]),
            "last_trip": _latest(*[r["last_trip"] for r in by.values()]),
            "by": by}


def overview(data, feed, now=None):
    """Everything the scene draws, in one admin-only answer."""
    now = time.time() if now is None else now
    cutoff = now - LIT_HOURS * 3600
    today = datetime.fromtimestamp(now, timezone.utc).date()
    stones = [s for s in (data.get("stones") or []) if isinstance(s, dict) and s.get("id")]
    ids = {str(s["id"]) for s in stones}
    live = {str(k): _decoy(v) for k, v in (feed.get("stones") or {}).items()}

    trips = [e for e in events.listing(limit=events.KEEP) if is_trip(e)]
    by_target, unmatched = {}, []
    for ev in trips:
        if ev.get("target") in ids:
            by_target.setdefault(ev["target"], []).append(ev)
        else:
            unmatched.append(ev)

    out_stones, counts = [], {"charted": len(stones), "lit": 0, "stirred": 0,
                              "unacked": 0, "unmatched": len(unmatched), "expired": 0}
    for s in stones:
        sid = str(s["id"])
        evs = by_target.get(sid, [])
        recent = [e for e in evs if _epoch((e.get("trip") or {}).get("last_at") or e.get("at")) >= cutoff]
        decoy = live.get(sid)
        unacked = sum(1 for e in evs if not e.get("ack"))
        lit = any(not e.get("ack") for e in recent) or bool(decoy and decoy["state"] == "speaking")
        stirred = not lit and (bool(recent) or bool(decoy and decoy["state"] == "stirred"))
        state = "lit" if lit else ("stirred" if stirred else "quiet")
        views = [_trip_view(e) for e in evs[:RECENT_PER_TRIPWIRE]]
        if decoy and decoy["state"] != "silent":
            # the decoy feed's own verdict, as a trip row with no event behind it
            views.insert(0, {"event": None, "tripwire": sid, "name": s.get("name"),
                             "source": "decoys", "signal": decoy["state"], "sensor": None,
                             "src": None, "port": None, "at": decoy["last_spoke"],
                             "last_at": decoy["last_spoke"], "sent_at": None, "count": 1,
                             "gravity": "grave" if decoy["state"] == "speaking" else "warn",
                             "ack": None})
        days = _expiry(s.get("expires"), today)
        row = {k: s.get(k) for k in _STONE_FIELDS}
        row["retired"] = bool(s.get("retired"))
        row.update({
            "family": schema.stone_family(s),
            "state": state, "lit": lit, "unacked": unacked,
            "trips_in_window": len(recent),
            "last_trip": _latest(*([(e.get("trip") or {}).get("last_at") for e in evs[:1]]
                                   + [decoy["last_spoke"] if decoy and decoy["state"] != "silent"
                                      else None])),
            "expires_in_days": days, "expired": days is not None and days < 0,
            "decoy": decoy, "trips": views,
        })
        counts["lit"] += lit
        counts["stirred"] += stirred
        counts["unacked"] += unacked
        counts["expired"] += row["expired"]
        out_stones.append(row)

    return {
        "generated": iso_utc(now), "lit_window_hours": LIT_HOURS,
        "tripwires": out_stones,
        "unmatched": [_trip_view(e) for e in unmatched[:UNMATCHED_SHOWN]],
        "sources": {"decoys": _decoy_source(feed, {k: v for k, v in live.items() if v}),
                    "webhook": _webhook_source()},
        "counts": counts,
    }


# ── setup helpers: what to paste where ───────────────────────────────────────
def setup(base_url):
    """Copy-paste configuration for each sender. Never a secret: the key is
    `YOUR-WEBHOOK-KEY` with the command that prints it."""
    import integrations
    url = base_url.rstrip("/") + "/api/v2/ingest/tripwires"
    key_url = f"{url}?key={KEY_PLACEHOLDER}"
    db = settings.DATA_BACKEND == "db"
    handler = {
        "class": "opencanary.logger.WebhookHandler",
        "url": url,
        "method": "POST",
        "data": {"message": "%(message)s"},
        "status_code": 200,
        "headers": {"Authorization": f"Bearer {KEY_PLACEHOLDER}",
                    "Content-Type": "application/json"},
    }
    example = {"tripwire_id": "finance-doc", "at": "2026-10-18T12:00:00Z", "kind": "opened"}
    return {
        "enabled": enabled(),
        "url": url,
        "backend": settings.DATA_BACKEND,
        "site": settings.SITE_SLUG,
        "secret_set": bool(secret()),
        "enable": ["ATLAS_TRIPWIRES_WEBHOOK=1",
                   "ATLAS_TRIPWIRES_SECRET_FILE=/run/secrets/atlas_tripwires"],
        "key_command": "python cli.py tripwires-key",
        "token_command": (f"python cli.py token-issue --site {settings.SITE_SLUG} "
                          "--scopes tripwires --label opencanary") if db else None,
        "auth": [
            {"scheme": "bearer", "header": "Authorization",
             "value": f"Bearer {KEY_PLACEHOLDER}", "for": "opencanary"},
            {"scheme": "query", "url": key_url, "for": "canarytokens"},
            {"scheme": "signature", "header": "X-Atlas-Signature",
             "value": "sha256=HEX-HMAC-SHA256-OF-THE-RAW-BODY", "for": "generic"},
        ],
        "opencanary": {
            "handler_name": "Webhook",
            "handler": handler,
            "config": json.dumps({"logger": {"class": "PyLogger", "kwargs": {
                "formatters": {"plain": {"format": "%(message)s"}},
                "handlers": {"Webhook": handler}}}}, indent=2),
            "notes": [
                "Add the Webhook handler to logger.kwargs.handlers in opencanary.conf.",
                "Set the tripwire's `Reported as` to the canary's device.node_id, "
                "or node_id:port for one service.",
                "Boot and ping messages count as contact, not trips.",
            ],
        },
        "canarytokens": {
            "webhook_url": key_url,
            "notes": [
                "Paste the URL as the token's webhook. Canarytokens sends a test "
                "on save; it counts as contact, not a trip.",
                "Write the tripwire's id as the token's reminder, or put the "
                "token id in the tripwire's `Reported as`.",
            ],
        },
        "generic": {
            "example": example,
            "curl": (f"curl -X POST {url} -H 'Authorization: Bearer {KEY_PLACEHOLDER}' "
                     f"-H 'Content-Type: application/json' -d '{json.dumps(example)}'"),
        },
        "matching": [
            "generic: tripwire_id = a tripwire's id or its `Reported as`",
            "opencanary: `Reported as` = node_id:port, dst_host:port, node_id or "
            "dst_host; else id = node_id",
            "canarytokens: `Reported as` = the token id; else id or `Reported as` = the reminder",
            "anything else is an unmatched trip: still an event, never dropped",
        ],
        "decoys": {"setting": "ATLAS_DECOYS_PATH", "path": integrations.decoys_path(),
                   "default": integrations.DECOYS_PATH_DEFAULT},
    }
