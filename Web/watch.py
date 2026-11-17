"""THE WATCH (2026-11-15): Atlas's own checks, each on its own schedule.

What it asks, and only that:

* A service link's check, or a place's own. The map says which: a link with
  an http(s) `url` and no `check` is asked as it always was (one GET, below
  500 healthy); `check` names another kind — `tcp`, `dns`, `keyword`, `json`
  — or `off`. A place is asked only when it has a `check` of its own, and
  then that alone decides its marker; without one it takes the worst of its
  services, as before.
* Only what is charted. A host, a port or a name is asked because someone
  charted that check: nothing is discovered, no port is tried on its own, no
  range is walked. A cloud metadata or link-local address is never asked: not
  written as one, not written as a bare number a resolver reads as one, and
  not reached through a name that resolves to one.
* Kuma stands where it watches: a link that names a monitor is not asked,
  and a place a monitor is mapped to gets no check of its own and no state
  from here. With the map's `meta.shadow_kuma` on, both are asked all the
  same, as SHADOW checks: their answers never reach the feed, and shadow.py
  sets each beside Kuma's.
* No credentials are sent and no redirect is followed. The body is read only
  by a keyword or json check, at most 64 KB, compared and dropped, never
  stored or logged. A certificate is not verified for the answer (a
  self-signed service is still up), but an https check reads the one the
  service presents (its own short handshake, at most every six hours) and
  keeps its end date, issuer and names, so SEALS can say what the wire shows.

When: each check has its own interval (`check_every`, default 60 s, 20 s at
the least), retries (`check_retries`, default 1: a failing answer has to be
seen twice before the state changes; meanwhile it is asked again after 20 s)
and timeout (`check_timeout`, default 3 s). A round asks only what is due.
The map-wide rate is capped (`ATLAS_CHECKS_PER_MINUTE`, default 600): past
it every interval is stretched evenly and the log says so, never silently.

Who asks: a thread per gunicorn worker (`start`, from gunicorn.conf.py), every
`ATLAS_CHECKS_POLL` seconds (default 5; 0 = off), while the `checks` source is
on. The workers share one store (`checks.json` beside the dataset) and one
lock, so a check is asked once, not once per worker. With no thread (the dev
server, the test suite, a worker that lost it) the feed's own read asks a
round when the store has not moved for a while (`signals.ChecksAdapter`).
"""

import ipaddress
import json
import logging
import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import settings
import signals

log = logging.getLogger("atlas.live.watch")

#: The kinds of check. `off` (on the map) asks nothing.
TYPES = ("http", "tcp", "dns", "keyword", "json")
#: What a shadow target is: a service Kuma's monitor watches, a place one is
#: tied to. Asked, stored, compared (shadow.py), never in the feed.
SHADOW_KINDS = ("shadow", "shadow-place")
EVERY, EVERY_MIN, EVERY_MAX = 60, 20, 3600
RETRIES, RETRIES_MAX = 1, 5
TIMEOUT, TIMEOUT_MIN, TIMEOUT_MAX = 3.0, 1.0, 10.0
#: How soon a failing check is asked again while it still has retries.
RETRY_EVERY = 20
#: The most of a body a keyword or json check reads.
BODY_MAX = 64 * 1024
#: How often an https check reads the certificate again.
TLS_EVERY = 6 * 3600
WORKERS = 8
PER_MINUTE = 600
POLL = 5
#: A round in the background may take this long; one inside a request less.
TICK_BUDGET = 25.0
FILE = "checks.json"
VERSION = 2

_UA = {"User-Agent": "Atlas-check"}
_METADATA = frozenset(map(ipaddress.ip_address, ("fd00:ec2::254", "100.100.100.200", "192.0.0.192")))


@dataclass(frozen=True)
class Target:
    """One check: what is asked, how, and how often."""
    ckey: str          # its key in the store: `s:<service key>`, `p:<place id>`,
                       # and in shadow `k:<monitor>` or `kp:<place id>`
    key: str           # the feed's key: the service key, or the place id
    kind: str          # "service", "place", or one of SHADOW_KINDS
    place: str         # the place it belongs to
    type: str          # one of TYPES
    url: str = ""      # http, keyword, json
    host: str = ""     # tcp, dns
    port: int = 0      # tcp
    expect: str = ""
    every: int = EVERY
    retries: int = RETRIES
    timeout: float = TIMEOUT
    rolls_up: bool = True   # a service's state counts towards its place's marker


# ── what the map charts ─────────────────────────────────────────────────────

def _bounded(value, default, low, high, cast):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return cast(min(max(value, low), high))


#: A host written only in digits, hex and dots that is not a dotted address:
#: `2852039166`, `0xa9.0xfe.0xa9.0xfe`, `169.254.43518`. A resolver reads each
#: as an address, so it is refused rather than judged.
_NUMERIC = re.compile(r"^[0-9a-fA-FxX.]+$")


def _refused_ip(ip):
    if ip.version == 4 and ip in ipaddress.ip_network("0.0.0.0/8"):
        return True
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip in _METADATA


def refused_host(host):
    """True for an address no check may ask: a cloud metadata address, a
    link-local one, "this network" and the like, or a bare number a resolver
    would read as an address. A name is judged where it is asked
    (`_resolves_refused`), once it has resolved."""
    text = str(host or "").strip().strip("[]")
    try:
        ip = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return bool(_NUMERIC.match(text)) and any(c.isdigit() for c in text)
    return _refused_ip(ip)


def _resolves_refused(host, port):
    """True when a name resolves to an address no check may ask. A name that
    does not resolve is left to the check itself to fail."""
    try:
        infos = socket.getaddrinfo(host, port or None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    for info in infos:
        try:
            if _refused_ip(ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])):
                return True
        except ValueError:
            continue
    return False


def _address(value):
    """A place's `ip` as an address a check may use, or ''."""
    text = str(value or "").strip()
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return ""
    return text


def _parts(url):
    """(host, port) of an http(s) URL, the scheme's port when none is given."""
    try:
        u = urlsplit(url)
        port = u.port or (443 if u.scheme == "https" else 80)
        return u.hostname or "", port
    except ValueError:
        return "", 0


def spec_of(entry):
    """The `check_*` fields of a link or a place, read leniently: anything
    out of range is brought into range, anything else takes the default."""
    kind = entry.get("check")
    kind = kind if (kind in TYPES or kind == "off") else ""
    host = entry.get("check_host")
    port = entry.get("check_port")
    expect = entry.get("check_expect")
    return {
        "type": kind,
        "host": host.strip() if isinstance(host, str) else "",
        "port": port if isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536 else 0,
        "expect": expect.strip()[:200] if isinstance(expect, str) else "",
        "every": _bounded(entry.get("check_every"), EVERY, EVERY_MIN, EVERY_MAX, int),
        "retries": _bounded(entry.get("check_retries"), RETRIES, 0, RETRIES_MAX, int),
        "timeout": _bounded(entry.get("check_timeout"), TIMEOUT, TIMEOUT_MIN, TIMEOUT_MAX, float),
    }


def _resolve(kind, spec, url, fallback_host):
    """(url, host, port) a check of `kind` asks, or None when the map does not
    give it enough to ask."""
    if kind in ("http", "keyword", "json"):
        asked = signals._check_url(spec["host"]) or url
        if not asked:
            return None
        host, _ = _parts(asked)
        return None if refused_host(host) else (asked, "", 0)
    named = spec["host"]
    if named.lower().startswith(("http://", "https://")):
        named = _parts(named)[0]
    url_host, url_port = _parts(url) if url else ("", 0)
    host = named or url_host or (fallback_host if kind == "tcp" else "")
    if not host or refused_host(host):
        return None
    if kind == "dns":
        return ("", host, 0)
    port = spec["port"] or url_port
    return ("", host, port) if port else None


def _make(ckey, key, kind, place, check, spec, url, fallback_host, rolls_up=True):
    where = _resolve(check, spec, url, fallback_host)
    if where is None:
        return None
    asked, host, port = where
    return Target(ckey=ckey, key=key, kind=kind, place=place, type=check, url=asked, host=host,
                  port=port, expect=spec["expect"], every=spec["every"], retries=spec["retries"],
                  timeout=spec["timeout"], rolls_up=rolls_up)


def targets(data):
    """[Target] for everything the map gives a check, in map order."""
    out, seen = [], set()
    if not isinstance(data, dict):
        return out
    watched = {nid for nid in signals.monitor_map(data).values() if nid}
    unmanaged = signals.unmanaged_ids(data)
    quiet = signals.unmanaged_service_keys(data)
    meta = data.get("meta")
    shadow = isinstance(meta, dict) and meta.get("shadow_kuma") is True
    mapped = set(signals.monitor_map(data))
    for node in data.get("nodes") or []:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or node.get("planned"):
            continue
        nid = node["id"]
        if nid in unmanaged:
            continue
        ip = _address(node.get("ip"))
        own = spec_of(node)
        if own["type"] in TYPES and (nid not in watched or shadow):
            ckey, kind = (f"kp:{nid}", "shadow-place") if nid in watched else (f"p:{nid}", "place")
            t = _make(ckey, nid, kind, nid, own["type"], own, "", ip)
            if t:
                out.append(t)
                seen.add(t.ckey)
        for link in node.get("links") or []:
            if (not isinstance(link, dict) or link.get("planned")
                    or link.get("unmanaged") is True):
                continue
            named = link.get("kuma")
            if named and (not shadow or named in mapped):
                # a monitor tied to a place reaches the feed only folded into
                # that place: there is no answer of its own to set beside
                continue
            key = signals.service_key(nid, link)
            ckey = f"k:{key}" if named else f"s:{key}"
            if ckey in seen or key in quiet:
                continue
            spec = spec_of(link)
            if spec["type"] == "off":
                continue
            url = signals._check_url(link.get("url")) or ""
            kind = spec["type"] or ("http" if url else "")
            if not kind:
                continue
            t = _make(ckey, key, "shadow" if named else "service", nid, kind, spec, url, ip,
                      rolls_up=nid not in watched and not named)
            if t:
                out.append(t)
                seen.add(t.ckey)
    return out


# ── asking ──────────────────────────────────────────────────────────────────

def _ms(start):
    return int(round((time.monotonic() - start) * 1000))


def _codes_ok(code, expect):
    """Whether a status is in a list like `200-299,401`."""
    for part in expect.replace(" ", "").split(","):
        if not part:
            continue
        low, _, high = part.partition("-")
        try:
            if int(low) <= code <= int(high or low):
                return True
        except ValueError:
            continue
    return False


def _json_ok(body, expect):
    """`path=value`: the dotted path into the answer's JSON equals the value,
    written as JSON writes it (`healthy=true`, `status=ok`, `count=3`)."""
    path, sep, want = expect.partition("=")
    if not sep:
        return False
    try:
        value = json.loads(body)
    except ValueError:
        return False
    for step in [p for p in path.strip().split(".") if p]:
        if isinstance(value, dict) and step in value:
            value = value[step]
        elif isinstance(value, list) and step.isdigit() and int(step) < len(value):
            value = value[int(step)]
        else:
            return False
    seen = value if isinstance(value, str) else json.dumps(value)
    return seen == want.strip()


def _read(resp, cap=BODY_MAX):
    raw = getattr(resp, "raw", None)
    data = raw.read(cap, decode_content=True) if raw is not None else b""
    return (data or b"")[:cap].decode("utf-8", "replace")


def certificate(der):
    """{expires, issuer, names} of a DER certificate, or {}."""
    if not der:
        return {}
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        cert = x509.load_der_x509_certificate(der)
        try:
            names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            names = [a.value for a in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)]
        issuer = [a.value for a in cert.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)] or \
                 [a.value for a in cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)]
        return {"expires": cert.not_valid_after_utc.date().isoformat(),
                "issuer": str(issuer[0])[:120] if issuer else "",
                "names": [str(n)[:253] for n in names][:10]}
    except Exception as e:  # noqa: BLE001 - a certificate that cannot be read says nothing
        log.debug("watch: a certificate could not be read (%s)", type(e).__name__)
        return {}


def peer_certificate(t):
    """{expires, issuer, names} of the certificate an https check's address
    presents, or {}. Its own short handshake, sending nothing: a streamed
    answer does not keep the socket it came on (2026-11-15)."""
    import ssl
    host, port = _parts(t.url)
    if not host or not t.url.lower().startswith("https://") or refused_host(host):
        return {}
    if _resolves_refused(host, port):
        return {}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE        # read, never judged: a self-signed one is still seen
    try:
        ipaddress.ip_address(host)
        sni = None
    except ValueError:
        sni = host
    try:
        with socket.create_connection((host, port), timeout=t.timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=sni) as tls:
                return certificate(tls.getpeercert(binary_form=True))
    except (OSError, ValueError) as e:     # ssl.SSLError is an OSError
        log.debug("watch: no certificate read (%s)", type(e).__name__)
        return {}


def _http(t):
    import requests
    start = time.monotonic()
    resp, state, extra = None, None, {}
    host, port = _parts(t.url)
    if _resolves_refused(host, port):
        log.debug("watch: %s resolves to an address no check asks", host)
        return None, _ms(start), {}
    try:
        resp = requests.get(t.url, timeout=t.timeout, allow_redirects=False, verify=False,
                            stream=True, headers=_UA)
        code = resp.status_code
        if t.type == "http":
            if t.expect:
                state = signals.HEALTHY if _codes_ok(code, t.expect) else signals.DOWN
            else:
                state = signals.HEALTHY if code < 500 else signals.DEGRADED
        elif code >= 400:
            state = signals.DOWN
        else:
            body = _read(resp)
            found = (t.expect in body) if t.type == "keyword" else _json_ok(body, t.expect)
            state = signals.HEALTHY if found else signals.DOWN
    except (requests.ConnectionError, requests.Timeout):
        state = signals.DOWN
    except Exception as e:  # noqa: BLE001 - one bad address never stops the round
        log.debug("watch: one address could not be asked (%s)", type(e).__name__)
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001 - closing is a courtesy
                pass
    return state, _ms(start), extra


def _tcp(t):
    start = time.monotonic()
    if _resolves_refused(t.host, t.port):
        log.debug("watch: %s resolves to an address no check asks", t.host)
        return None, _ms(start), {}
    try:
        with socket.create_connection((t.host, t.port), timeout=t.timeout):
            pass
        return signals.HEALTHY, _ms(start), {}
    except OSError:          # refused, unreachable, timed out, or a name that does not resolve
        return signals.DOWN, _ms(start), {}


def _dns(t):
    start = time.monotonic()
    try:
        found = {info[4][0] for info in socket.getaddrinfo(t.host, None)}
    except socket.gaierror:
        return signals.DOWN, _ms(start), {}
    except OSError:
        return None, _ms(start), {}
    want = t.expect
    ok = not want or want in found
    return (signals.HEALTHY if ok else signals.DOWN), _ms(start), {}


def probe(t):
    """Ask one check once: (state or None, milliseconds, extra). None is "could
    not be asked", which says nothing about the thing."""
    if t.type == "tcp":
        return _tcp(t)
    if t.type == "dns":
        return _dns(t)
    return _http(t)


def _run(due, budget, certs=()):
    """({ckey: (state, ms, extra)} for every check that answered inside the
    budget, {ckey} of the checks the round never got to start). The
    certificates read for `certs` ride in the extra as `tls`."""
    import warnings
    from concurrent.futures import ThreadPoolExecutor, wait

    if not due and not certs:
        return {}, set()
    pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="atlas-check")
    try:
        try:
            from urllib3.exceptions import InsecureRequestWarning
        except ImportError:          # no urllib3: no http check can run either
            InsecureRequestWarning = Warning
        # an unverified certificate makes urllib3 warn on every request: the
        # filter is set in this thread, only while the round runs (as before)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            asked = {pool.submit(probe, t): t.ckey for t in due}
            read = {pool.submit(peer_certificate, t): t.ckey for t in certs}
            done, _ = wait([*asked, *read], timeout=budget)
            # a check still waiting for a worker was never asked: it stays due,
            # and goes first next round (a run of slow ones cannot starve it)
            unstarted = {ckey for f, ckey in asked.items() if f not in done and f.cancel()}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)   # what has not answered is unknown
    out = {}
    for future in done:
        if future not in asked:
            continue
        try:
            out[asked[future]] = future.result()
        except Exception:  # noqa: BLE001 - a check that broke says nothing
            continue
    for future in done:
        if future not in read:
            continue
        try:
            seen = future.result()
        except Exception:  # noqa: BLE001 - a certificate that could not be read says nothing
            continue
        state, ms, extra = out.get(read[future], (None, None, {}))
        out[read[future]] = (state, ms, {**extra, "tls": seen or {}, "tls_read": True})
    return out, unstarted


# ── the schedule ────────────────────────────────────────────────────────────

def per_minute():
    raw = os.environ.get("ATLAS_CHECKS_PER_MINUTE", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return PER_MINUTE
    return value if value >= 10 else PER_MINUTE


_stretch_logged = [None]


def stretch(ts, cap=None):
    """How much every interval is stretched so the map stays under the cap
    (1.0 when it already does). Logged once each time it changes."""
    cap = cap or per_minute()
    load = sum(60.0 / t.every for t in ts)
    factor = max(1.0, load / cap) if cap else 1.0
    rounded = round(factor, 2)
    if rounded != _stretch_logged[0]:
        _stretch_logged[0] = rounded
        if factor > 1.0:
            log.warning("watch: %d checks would ask %.0f times a minute, over the %d allowed; "
                        "every interval is stretched %.2f times", len(ts), load, cap, factor)
    return factor


def due_at(entry, t, factor=1.0):
    """When a check is next asked (epoch seconds); 0 for one never asked."""
    if not entry or not isinstance(entry.get("asked"), (int, float)):
        return 0
    fails = entry.get("fails") or 0
    if 0 < fails <= t.retries:
        return entry["asked"] + min(RETRY_EVERY, t.every)
    return entry["asked"] + t.every * factor


def judge(entry, t, answer, now):
    """The stored entry after an answer. A healthy answer is believed at once;
    any other is believed once it has been seen `retries + 1` times in a row,
    and until then the check keeps the state it had."""
    entry = dict(entry or {})
    state, ms, extra = answer
    if extra.get("tls_read"):
        # a certificate read rides beside the answer, tried again in TLS_EVERY
        # either way. It belongs to the address it was read from: one read
        # from another address, or none at all, is not kept for this one
        entry["tls_at"], entry["tls_from"] = now, t.url
        if extra.get("tls"):
            entry["tls"], entry["tls_url"] = extra["tls"], t.url
        elif entry.get("tls_url") != t.url:
            entry.pop("tls", None)
            entry.pop("tls_url", None)
    if state is None and ms is None:
        return entry                  # only the certificate was read this round
    entry["asked"] = now
    if state is None:
        return entry
    entry["heard"] = now              # when it last said anything: what ages a state
    entry["ms"] = ms
    if state == signals.HEALTHY:
        entry["fails"] = 0
        entry["state"] = state
        entry["since"] = now if entry.get("said") != state else entry.get("since", now)
        entry["said"] = state
        return entry
    fails = (entry.get("fails") or 0) + 1
    entry["fails"] = fails
    entry["said"] = state
    if fails > t.retries:
        if entry.get("state") != state:
            entry["since"] = now
        entry["state"] = state
    return entry


def path_of(path=None):
    return path or os.path.join(settings.DATA_DIR, FILE)


def load(path=None):
    """The stored checks: {"v", "at", "checks"}. Anything unreadable, or from
    before checks had schedules, is an empty store."""
    try:
        with open(path_of(path), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {"v": VERSION, "at": None, "checks": {}}
    if not isinstance(raw, dict) or raw.get("v") != VERSION or not isinstance(raw.get("checks"), dict):
        return {"v": VERSION, "at": None, "checks": {}}
    at = raw.get("at")
    return {"v": VERSION, "at": at if isinstance(at, (int, float)) else None,
            "checks": {k: v for k, v in raw["checks"].items() if isinstance(v, dict)}}


def _cert_due(entry, t, now):
    """Whether an https check reads its certificate this round: never read
    yet, read from another address (the service moved), or last read
    TLS_EVERY ago."""
    entry = entry or {}
    read_at = entry.get("tls_at")
    return (not isinstance(read_at, (int, float)) or entry.get("tls_from") != t.url
            or now - read_at >= TLS_EVERY)


def _advance(store, ts, now, budget, fixed):
    """The store after one round: what is due is asked, most overdue first."""
    factor = stretch(ts)
    checks = store["checks"]
    # what the map shows first, then shadow; within each, most overdue first
    due = sorted((t for t in ts if due_at(checks.get(t.ckey), t, factor) <= now),
                 key=lambda t: (t.kind in SHADOW_KINDS, due_at(checks.get(t.ckey), t, factor)))
    certs = [t for t in due if t.url.lower().startswith("https://")
             and _cert_due(checks.get(t.ckey), t, now)]
    heard, unstarted = _run(due, budget, certs)
    asked = {t.ckey for t in due} - unstarted
    after = now if fixed else time.time()
    out = {}
    for t in ts:
        entry = checks.get(t.ckey)
        if t.ckey in heard:
            entry = judge(entry, t, heard[t.ckey], after)
        if t.ckey in asked and (entry or {}).get("asked") != after:
            # asked, no answer in time: unknown, asked again when next due
            entry = {**(entry or {}), "asked": after}
        if entry:
            out[t.ckey] = entry
    return {"v": VERSION, "at": after, "checks": out}   # a check no longer charted is dropped


#: Where a process keeps its checks when the data directory cannot be written
#: (a read-only mount): the same schedule, held in memory, never shared.
_memory = {}
_memory_lock = threading.Lock()


def tick(data, path=None, now=None, budget=TICK_BUDGET, ts=None):
    """One round: ask what is due, store what was heard. Returns the store, or
    None when another worker holds the round (its store will do)."""
    import filelock
    import jsonio
    ts = targets(data) if ts is None else ts
    where = path_of(path)
    fixed = now is not None                    # a test's clock: the round takes no time
    try:
        with filelock.exclusive(filelock.lock_for(where), timeout=0):
            store = _advance(load(where), ts, now if fixed else time.time(), budget, fixed)
            try:
                jsonio.write_json_atomic(where, store, keep_backup=False)
            except OSError as e:
                log.warning("watch: the round could not be stored (%s)", type(e).__name__)
            return store
    except filelock.LockTimeout:
        return None
    except OSError as e:
        # a data directory that cannot be written: no shared store, so this
        # process keeps its own, in memory, on the same schedule
        log.debug("watch: no shared store here (%s); keeping one in memory", type(e).__name__)
        if not _memory_lock.acquire(blocking=False):
            return _memory.get(where)
        try:
            kept = _memory.get(where) or {"v": VERSION, "at": None, "checks": {}}
            _memory[where] = _advance(kept, ts, now if fixed else time.time(), budget, fixed)
            return _memory[where]
        finally:
            _memory_lock.release()


def stale_after(t, factor=1.0):
    """How long an answer is served: three intervals as stretched, five
    minutes at least."""
    return max(3 * t.every * factor, 300)


def as_feed(store, ts, now=None, factor=None):
    """{"services": {key: {state, ms, tls?}}, "nodes": {place: {state}}} from a
    store, cut to what the map charts now. A place's own check decides its
    marker; otherwise it takes the worst of its services' (down only when all
    are). A state not heard for three intervals (five minutes at least) is
    not served: a check that stops answering is unknown, never its last word.
    A certificate is served only for the address it was read from."""
    now = time.time() if now is None else now
    factor = stretch(ts) if factor is None else factor
    checks = (store or {}).get("checks") or {}
    services, nodes, rolled = {}, {}, {}
    own = set()
    for t in ts:
        if t.kind in SHADOW_KINDS:
            continue                  # Kuma's to say: compared in shadow.py, never served
        entry = checks.get(t.ckey)
        if not entry or entry.get("state") not in signals.NODE_STATES:
            continue
        heard = entry.get("heard")
        if not isinstance(heard, (int, float)) or now - heard > stale_after(t, factor):
            continue
        if t.kind == "place":
            nodes[t.place] = {"state": entry["state"]}
            own.add(t.place)
            continue
        info = {"state": entry["state"]}
        if isinstance(entry.get("ms"), int):
            info["ms"] = entry["ms"]
        if isinstance(entry.get("tls"), dict) and entry.get("tls_url") == t.url:
            info["tls"] = entry["tls"]
        services[t.key] = info
        if t.rolls_up:
            rolled.setdefault(t.place, []).append(entry["state"])
    for place, states in rolled.items():
        if place in own:
            continue
        if all(s == signals.HEALTHY for s in states):
            nodes[place] = {"state": signals.HEALTHY}
        elif all(s == signals.DOWN for s in states):
            nodes[place] = {"state": signals.DOWN}
        else:
            nodes[place] = {"state": signals.DEGRADED}
    return {"services": services, "nodes": nodes}


# ── the thread ──────────────────────────────────────────────────────────────

_started = False
_lock = threading.Lock()


def poll_every():
    """Seconds between rounds; 0 turns the thread off."""
    raw = os.environ.get("ATLAS_CHECKS_POLL", str(POLL)).strip()
    try:
        value = int(raw)
    except ValueError:
        return POLL
    if value == 0:
        return 0
    return value if value >= 2 else POLL


def _round(app):
    try:
        import integrations
        if "checks" not in integrations.enabled_sources():
            return
        with app.app_context():
            from context import atlas
            data, _, _ = atlas().dataset()
        tick(data)
    except Exception as e:  # noqa: BLE001 - the watch must never take a worker down
        log.warning("watch: a round failed: %s: %s", type(e).__name__, e)


def start(app, stop=None):
    """Start the round loop once per process. Returns the thread, or None."""
    global _started
    every = poll_every()
    if not every:
        log.info("watch: off (ATLAS_CHECKS_POLL=0)")
        return None
    with _lock:
        if _started:
            return None
        stop = stop or threading.Event()

        def loop():
            while not stop.wait(every):
                _round(app)

        t = threading.Thread(target=loop, name="atlas-watch", daemon=True)
        t.start()
        _started = True
    log.info("watch: asking what is due every %ss", every)
    return t
