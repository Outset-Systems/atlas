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
import engines.authority as authority

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

#: Why an answer was not a healthy one (2026-11-16): the code a probe gives
#: and the store keeps, and the words a person reads. Fixed words only: never
#: an exception's own text, never anything the service sent.
WHY = {
    "timeout": "no answer inside the timeout",
    "refused": "the connection was refused",
    "unreachable": "no connection could be made",
    "no-name": "the name did not resolve",
    "status": "answered with a status that was not expected",
    "server-error": "answered with a server error",
    "keyword": "the keyword was not in the answer",
    "json": "the value in the JSON answer was not the one expected",
    "address": "the name resolved, but not to the address expected",
}
#: The words for an ask that got no answer at all: the address could not be
#: asked, or the check did not finish in time.
NO_ANSWER = "no answer: the check could not be asked, or did not finish in time"
#: The words for a failed answer stored before the reasons were kept.
NOT_HEALTHY = "the answer was not a healthy one"

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
        # who speaks for it (engines/authority.py): a monitor the owner named
        # first, then Atlas's own check; beside the monitor only as a shadow
        kind = authority.place_check(nid in watched, shadow)
        if own["type"] in TYPES and kind:
            ckey = f"kp:{nid}" if kind == authority.SHADOW_PLACE else f"p:{nid}"
            t = _make(ckey, nid, kind, nid, own["type"], own, "", ip)
            if t:
                out.append(t)
                seen.add(t.ckey)
        for link in node.get("links") or []:
            if (not isinstance(link, dict) or link.get("planned")
                    or link.get("unmanaged") is True):
                continue
            named = link.get("kuma")
            # a monitor tied to a place reaches the feed only folded into
            # that place: there is no answer of its own to set beside
            tied = bool(named) and shadow and named in mapped
            asks = authority.service_check(bool(named), tied, shadow)
            if asks is None:
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
            t = _make(ckey, key, asks, nid, kind, spec, url, ip,
                      rolls_up=authority.rolls_up(nid in watched, bool(named)))
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
                extra = {"why": "status", "status": code}
            else:
                state = signals.HEALTHY if code < 500 else signals.DEGRADED
                extra = {"why": "server-error", "status": code}
        elif code >= 400:
            state = signals.DOWN
            extra = {"why": "status", "status": code}
        else:
            body = _read(resp)
            found = (t.expect in body) if t.type == "keyword" else _json_ok(body, t.expect)
            state = signals.HEALTHY if found else signals.DOWN
            extra = {"why": t.type}
        if state == signals.HEALTHY:
            extra = {}
    except requests.Timeout:   # before ConnectionError: a connect timeout is both
        state, extra = signals.DOWN, {"why": "timeout"}
    except requests.ConnectionError:
        state, extra = signals.DOWN, {"why": "unreachable"}
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
    except socket.timeout:   # TimeoutError
        return signals.DOWN, _ms(start), {"why": "timeout"}
    except ConnectionRefusedError:
        return signals.DOWN, _ms(start), {"why": "refused"}
    except socket.gaierror:
        return signals.DOWN, _ms(start), {"why": "no-name"}
    except OSError:          # unreachable, reset, or anything else the socket says
        return signals.DOWN, _ms(start), {"why": "unreachable"}


def _dns(t):
    start = time.monotonic()
    try:
        found = {info[4][0] for info in socket.getaddrinfo(t.host, None)}
    except socket.gaierror:
        return signals.DOWN, _ms(start), {"why": "no-name"}
    except OSError:
        return None, _ms(start), {}
    want = t.expect
    if not want or want in found:
        return signals.HEALTHY, _ms(start), {}
    return signals.DOWN, _ms(start), {"why": "address"}


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
    return settings.env_int("ATLAS_CHECKS_PER_MINUTE", PER_MINUTE, 10)


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
    # why the last answer was not a healthy one, as a code from WHY (and the
    # status it came with), never the exception's text or what the service sent
    why, code = extra.get("why"), extra.get("status")
    entry.pop("why", None)
    entry.pop("status", None)
    if state != signals.HEALTHY and why in WHY:
        entry["why"] = why
        if isinstance(code, int) and not isinstance(code, bool):
            entry["status"] = code
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
    ts = targets(data) if ts is None else ts
    where = path_of(path)
    fixed = now is not None                    # a test's clock: the round takes no time
    try:
        with filelock.writing_now(where) as save:
            store = _advance(load(where), ts, now if fixed else time.time(), budget, fixed)
            try:
                save(store)
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


# ── one check, read or asked now (2026-11-16) ───────────────────────────────
#
# What `GET /api/v2/checks/<key>` and `POST /api/v2/admin/checks/run` stand on
# (api/v2/checks.py). Plain functions: who may see what is the route's to say.

#: The kinds of target that are a place's own check, or a shadow of one.
_PLACE_KINDS = (authority.PLACE, authority.SHADOW_PLACE)


def find(data, key, ts=None):
    """The Target the map gives `key` (a place id or a service key), or None.
    Only `targets(data)` is looked in, so nothing the map does not chart is
    ever found. A key that is both a place id and a monitor's name is the
    place's: a place's own check is looked for first."""
    ts = targets(data) if ts is None else ts
    if not isinstance(key, str) or not key:
        return None
    mine = [t for t in ts if t.key == key]
    return next((t for t in mine if t.kind in _PLACE_KINDS), None) or (mine[0] if mine else None)


def not_asked(data, key):
    """Why a thing on the map has no check Atlas asks, for a key `find` did
    not find: {"why": "unmanaged"}, {"why": "kuma", "monitor": name} (a
    monitor watches it and "Check beside Kuma" is off, or the monitor is
    tied to a place), or None (no check is charted, or it is not on the map)."""
    if not isinstance(data, dict) or not isinstance(key, str):
        return None
    nodes = [n for n in (data.get("nodes") if isinstance(data.get("nodes"), list) else [])
             if isinstance(n, dict) and isinstance(n.get("id"), str)]
    unmanaged = signals.unmanaged_ids(data)
    monitors = signals.monitor_map(data)
    if any(n["id"] == key for n in nodes):
        if key in unmanaged:
            return {"why": "unmanaged"}
        named = sorted(m for m, nid in monitors.items() if nid == key)
        return {"why": "kuma", "monitor": named[0]} if named else None
    if key in signals.services_of(data, unmanaged) | signals.unmanaged_service_keys(data):
        return {"why": "unmanaged"}
    named = key in monitors or any(
        isinstance(link, dict) and link.get("kuma") == key
        for n in nodes for link in (n.get("links") if isinstance(n.get("links"), list) else []))
    return {"why": "kuma", "monitor": key} if named else None


def _when(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    import jsonio
    return jsonio.iso_utc(value)


def asks(t):
    """What a check asks, in words: its URL, an address and port, or a name."""
    if t.type == "tcp":
        return f"{t.host} port {t.port}"
    if t.type == "dns":
        return f"the name {t.host}"
    return t.url


def answer_for(store, t, now=None, factor=1.0):
    """One check's last answer from a store, for a person to read. Every name
    and address in it is the map's own; the caller cuts it for its viewer
    (the certificate's `names` above all). The fields:

    `state` is what the feed serves for it now (None when it was never heard,
    or was last heard too long ago: `stale`); `said` is what the last answer
    said, which differs from `state` while a failure is still inside its
    retries (`fails` of `retries + 1`); `error` says in fixed words why the
    last answer was not a healthy one, or that the last ask got no answer."""
    now = time.time() if now is None else now
    entry = ((store or {}).get("checks") or {}).get(t.ckey)
    entry = entry if isinstance(entry, dict) else {}
    said = entry.get("said") if entry.get("said") in signals.NODE_STATES else None
    held = entry.get("state") if entry.get("state") in signals.NODE_STATES else None
    heard, asked = entry.get("heard"), entry.get("asked")
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)   # noqa: E731
    stale = bool(held) and (not numeric(heard) or now - heard > stale_after(t, factor))
    answered = numeric(asked) and numeric(heard) and heard >= asked
    if numeric(asked) and not answered:
        error = NO_ANSWER
    elif said and said != signals.HEALTHY:
        why = entry.get("why")
        error = (WHY.get(why) if isinstance(why, str) else None) or NOT_HEALTHY
    else:
        error = None
    code = entry.get("status")
    tls = entry.get("tls") if isinstance(entry.get("tls"), dict) and entry.get("tls_url") == t.url else None
    fails = entry.get("fails")
    return {
        "key": t.key,
        "thing": "place" if t.kind in _PLACE_KINDS else "service",
        "authority": t.kind,
        "place": t.place,
        "type": t.type,
        "asks": asks(t),
        "url": t.url or None,
        "host": t.host or None,
        "port": t.port or None,
        "expect": t.expect or None,
        "every": t.every,
        "retries": t.retries,
        "timeout": t.timeout,
        "state": None if stale else held,
        "stale": stale,
        "said": said,
        "fails": fails if isinstance(fails, int) and not isinstance(fails, bool) else 0,
        "since": _when(entry.get("since")) if held else None,
        "asked_at": _when(asked),
        "heard_at": _when(heard),
        "ms": entry.get("ms") if isinstance(entry.get("ms"), int) and not isinstance(entry.get("ms"), bool) else None,
        "error": error,
        "status": code if error and isinstance(code, int) and not isinstance(code, bool) else None,
        "tls": dict(tls) if tls else None,
    }


#: Asks made by hand that the store does not keep (2026-11-17): the steps of
#: "Where does it break?" (diagnose.py) ask hops, a name and an outside
#: address that are no check of their own, so nothing of theirs is stored;
#: they are counted here, per store path, so they spend the same per-minute
#: budget. Held by this process only: each worker counts its own.
_by_hand = {}
_by_hand_lock = threading.Lock()


def spend_by_hand(path, count, now):
    """Count `count` asks made now by hand against the budget of the store
    at `path`."""
    where = path_of(path)
    with _by_hand_lock:
        kept = [at for at in _by_hand.get(where, ()) if 0 <= now - at < 60]
        kept.extend([now] * max(0, int(count)))
        _by_hand[where] = kept


def asked_by_hand(path, now):
    """When each ask counted by `spend_by_hand` in the last minute was made."""
    with _by_hand_lock:
        return [at for at in _by_hand.get(path_of(path), ()) if 0 <= now - at < 60]


def recent_asks(store, now, path=None):
    """When each check was asked in the last minute, ascending: the stored
    ones, and with `path` the ones counted by hand beside that store."""
    checks = (store or {}).get("checks") or {}
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)   # noqa: E731
    recent = [e["asked"] for e in checks.values()
              if isinstance(e, dict) and numeric(e.get("asked")) and 0 <= now - e["asked"] < 60]
    if path is not None:
        recent.extend(asked_by_hand(path, now))
    return sorted(recent)


def manual_wait(store, t, now, cap=None, path=None):
    """Seconds before `t` may be asked by hand, or 0 when it may be now.

    Two rules, both the worker's own: one check is not asked again inside the
    shortest interval a check may have (EVERY_MIN), and the map-wide budget
    (`per_minute`) is spent when as many checks were asked in the last minute
    as it allows. The store keeps when each check was last asked, so that count
    is of checks asked, at least what the minute spent; with `path`, the asks
    counted by hand beside that store (`spend_by_hand`) count too."""
    checks = (store or {}).get("checks") or {}
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)   # noqa: E731
    last = (checks.get(t.ckey) or {}).get("asked")
    if numeric(last) and 0 <= now - last < EVERY_MIN:
        return max(1, int(EVERY_MIN - (now - last) + 0.999))
    cap = cap or per_minute()
    recent = recent_asks(store, now, path)
    if len(recent) >= cap:
        return max(1, int(recent[len(recent) - cap] + 60 - now + 0.999))
    return 0


def _ask_one(store, t, now, fixed, path=None):
    """Ask `t` once into `store` (in place), as a round would: the same probe,
    the certificate when it is due, and `judge`, so one failed ask counts as
    one failure against the check's retries. Only its own entry changes, and
    not the store's `at`: the round's schedule is the round's. Returns
    ("asked", None) or ("soon" | "spent", seconds to wait)."""
    checks = store.setdefault("checks", {})
    entry = checks.get(t.ckey)
    wait = manual_wait(store, t, now, path=path)
    if wait:
        last = (entry or {}).get("asked")
        soon = isinstance(last, (int, float)) and 0 <= now - last < EVERY_MIN
        return ("soon" if soon else "spent"), wait
    certs = [t] if t.url.lower().startswith("https://") and _cert_due(entry, t, now) else []
    heard, _ = _run([t], 2 * t.timeout + 1.0, certs)
    after = now if fixed else time.time()
    if t.ckey in heard:
        entry = judge(entry, t, heard[t.ckey], after)
    if (entry or {}).get("asked") != after:
        entry = {**(entry or {}), "asked": after}   # asked, no answer in time: unknown
    checks[t.ckey] = entry
    return "asked", None


def ask_now(data, key, path=None, now=None, ts=None):
    """Ask the check the map gives `key` once, now, whatever its schedule
    says, and store the answer where a round would. The target comes from
    `targets(data)` alone. Returns (outcome, value):

      ("asked", answer)   asked and stored; `answer_for` after it
      ("held", answer)    another worker holds the store (as `tick` returns
                          None): nothing was asked, the answer is the stored one
      ("soon", seconds)   this check was asked less than EVERY_MIN ago
      ("spent", seconds)  the map-wide budget for the minute is spent
      ("none", None)      the map gives `key` no check
    """
    import filelock
    ts = targets(data) if ts is None else ts
    t = find(data, key, ts)
    if t is None:
        return "none", None
    where = path_of(path)
    fixed = now is not None
    factor = stretch(ts)

    def done(store, outcome, value):
        if outcome == "asked":
            return outcome, answer_for(store, t, now, factor)
        return outcome, value

    try:
        with filelock.writing_now(where) as save:
            store = load(where)
            outcome, value = _ask_one(store, t, now if fixed else time.time(), fixed, where)
            if outcome == "asked":
                try:
                    save(store)
                except OSError as e:
                    log.warning("watch: a check asked by hand could not be stored (%s)", type(e).__name__)
            return done(store, outcome, value)
    except filelock.LockTimeout:
        return "held", answer_for(load(where), t, now, factor)
    except OSError as e:
        # no shared store here (a read-only data directory): the one `tick`
        # keeps in memory for this process, as a round would
        log.debug("watch: no shared store here (%s); asking into the one in memory", type(e).__name__)
        if not _memory_lock.acquire(blocking=False):
            return "held", answer_for(_memory.get(where), t, now, factor)
        try:
            kept = _memory.get(where) or {"v": VERSION, "at": None, "checks": {}}
            outcome, value = _ask_one(kept, t, now if fixed else time.time(), fixed, where)
            _memory[where] = kept
            return done(kept, outcome, value)
        finally:
            _memory_lock.release()


# ── the thread ──────────────────────────────────────────────────────────────

_started = False
_lock = threading.Lock()


def poll_every():
    """Seconds between rounds; 0 turns the thread off."""
    return settings.env_int("ATLAS_CHECKS_POLL", POLL, 2, zero_off=True)


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
