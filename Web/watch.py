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
import engines.authority as authority
from engines.base import DEGRADED, DOWN, HEALTHY, NODE_STATES, monitor_map
from engines.checks import _check_url
from engines.places import service_key, services_of, unmanaged_ids, unmanaged_service_keys

log = logging.getLogger("atlas.live.watch")

TYPES = ("http", "tcp", "dns", "keyword", "json")
SHADOW_KINDS = ("shadow", "shadow-place")
EVERY, EVERY_MIN, EVERY_MAX = 60, 20, 3600
RETRIES, RETRIES_MAX = 1, 5
TIMEOUT, TIMEOUT_MIN, TIMEOUT_MAX = 3.0, 1.0, 10.0
RETRY_EVERY = 20
BODY_MAX = 64 * 1024
TLS_EVERY = 6 * 3600
WORKERS = 8
PER_MINUTE = 600
POLL = 5
TICK_BUDGET = 25.0
FILE = "checks.json"
VERSION = 2

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
NO_ANSWER = "no answer: the check could not be asked, or did not finish in time"
NOT_HEALTHY = "the answer was not a healthy one"

_UA = {"User-Agent": "Atlas-check"}
_METADATA = frozenset(map(ipaddress.ip_address, ("fd00:ec2::254", "100.100.100.200", "192.0.0.192")))


@dataclass(frozen=True)
class Target:
    ckey: str
    key: str
    kind: str
    place: str
    type: str
    url: str = ""
    host: str = ""
    port: int = 0
    expect: str = ""
    every: int = EVERY
    retries: int = RETRIES
    timeout: float = TIMEOUT
    rolls_up: bool = True



def _bounded(value, default, low, high, cast):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return cast(min(max(value, low), high))


_NUMERIC = re.compile(r"^[0-9a-fA-FxX.]+$")


def _refused_ip(ip):
    if ip.version == 4 and ip in ipaddress.ip_network("0.0.0.0/8"):
        return True
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip in _METADATA


def refused_host(host):
    text = str(host or "").strip().strip("[]")
    try:
        ip = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return bool(_NUMERIC.match(text)) and any(c.isdigit() for c in text)
    return _refused_ip(ip)


def _resolves_refused(host, port):
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
    text = str(value or "").strip()
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return ""
    return text


def _parts(url):
    try:
        u = urlsplit(url)
        port = u.port or (443 if u.scheme == "https" else 80)
        return u.hostname or "", port
    except ValueError:
        return "", 0


def spec_of(entry):
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
    if kind in ("http", "keyword", "json"):
        asked = _check_url(spec["host"]) or url
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
    out, seen = [], set()
    if not isinstance(data, dict):
        return out
    watched = {nid for nid in monitor_map(data).values() if nid}
    unmanaged = unmanaged_ids(data)
    quiet = unmanaged_service_keys(data)
    meta = data.get("meta")
    shadow = isinstance(meta, dict) and meta.get("shadow_kuma") is True
    mapped = set(monitor_map(data))
    for node in data.get("nodes") or []:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or node.get("planned"):
            continue
        nid = node["id"]
        if nid in unmanaged:
            continue
        ip = _address(node.get("ip"))
        own = spec_of(node)
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
            tied = bool(named) and shadow and named in mapped
            asks = authority.service_check(bool(named), tied, shadow)
            if asks is None:
                continue
            key = service_key(nid, link)
            ckey = f"k:{key}" if named else f"s:{key}"
            if ckey in seen or key in quiet:
                continue
            spec = spec_of(link)
            if spec["type"] == "off":
                continue
            url = _check_url(link.get("url")) or ""
            kind = spec["type"] or ("http" if url else "")
            if not kind:
                continue
            t = _make(ckey, key, asks, nid, kind, spec, url, ip,
                      rolls_up=authority.rolls_up(nid in watched, bool(named)))
            if t:
                out.append(t)
                seen.add(t.ckey)
    return out



def _ms(start):
    return int(round((time.monotonic() - start) * 1000))


def _codes_ok(code, expect):
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
    except Exception as e:
        log.debug("watch: a certificate could not be read (%s)", type(e).__name__)
        return {}


def peer_certificate(t):
    import ssl
    host, port = _parts(t.url)
    if not host or not t.url.lower().startswith("https://") or refused_host(host):
        return {}
    if _resolves_refused(host, port):
        return {}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ipaddress.ip_address(host)
        sni = None
    except ValueError:
        sni = host
    try:
        with socket.create_connection((host, port), timeout=t.timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=sni) as tls:
                return certificate(tls.getpeercert(binary_form=True))
    except (OSError, ValueError) as e:
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
                state = HEALTHY if _codes_ok(code, t.expect) else DOWN
                extra = {"why": "status", "status": code}
            else:
                state = HEALTHY if code < 500 else DEGRADED
                extra = {"why": "server-error", "status": code}
        elif code >= 400:
            state = DOWN
            extra = {"why": "status", "status": code}
        else:
            body = _read(resp)
            found = (t.expect in body) if t.type == "keyword" else _json_ok(body, t.expect)
            state = HEALTHY if found else DOWN
            extra = {"why": t.type}
        if state == HEALTHY:
            extra = {}
    except requests.Timeout:
        state, extra = DOWN, {"why": "timeout"}
    except requests.ConnectionError:
        state, extra = DOWN, {"why": "unreachable"}
    except Exception as e:
        log.debug("watch: one address could not be asked (%s)", type(e).__name__)
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
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
        return HEALTHY, _ms(start), {}
    except socket.timeout:
        return DOWN, _ms(start), {"why": "timeout"}
    except ConnectionRefusedError:
        return DOWN, _ms(start), {"why": "refused"}
    except socket.gaierror:
        return DOWN, _ms(start), {"why": "no-name"}
    except OSError:
        return DOWN, _ms(start), {"why": "unreachable"}


def _dns(t):
    start = time.monotonic()
    try:
        found = {info[4][0] for info in socket.getaddrinfo(t.host, None)}
    except socket.gaierror:
        return DOWN, _ms(start), {"why": "no-name"}
    except OSError:
        return None, _ms(start), {}
    want = t.expect
    if not want or want in found:
        return HEALTHY, _ms(start), {}
    return DOWN, _ms(start), {"why": "address"}


def probe(t):
    if t.type == "tcp":
        return _tcp(t)
    if t.type == "dns":
        return _dns(t)
    return _http(t)


def _run(due, budget, certs=()):
    import warnings
    from concurrent.futures import ThreadPoolExecutor, wait

    if not due and not certs:
        return {}, set()
    pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="atlas-check")
    try:
        try:
            from urllib3.exceptions import InsecureRequestWarning
        except ImportError:
            InsecureRequestWarning = Warning
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            asked = {pool.submit(probe, t): t.ckey for t in due}
            read = {pool.submit(peer_certificate, t): t.ckey for t in certs}
            done, _ = wait([*asked, *read], timeout=budget)
            unstarted = {ckey for f, ckey in asked.items() if f not in done and f.cancel()}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    out = {}
    for future in done:
        if future not in asked:
            continue
        try:
            out[asked[future]] = future.result()
        except Exception:
            continue
    for future in done:
        if future not in read:
            continue
        try:
            seen = future.result()
        except Exception:
            continue
        state, ms, extra = out.get(read[future], (None, None, {}))
        out[read[future]] = (state, ms, {**extra, "tls": seen or {}, "tls_read": True})
    return out, unstarted



def per_minute():
    return settings.env_int("ATLAS_CHECKS_PER_MINUTE", PER_MINUTE, 10)


_stretch_logged = [None]


def stretch(ts, cap=None):
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
    if not entry or not isinstance(entry.get("asked"), (int, float)):
        return 0
    fails = entry.get("fails") or 0
    if 0 < fails <= t.retries:
        return entry["asked"] + min(RETRY_EVERY, t.every)
    return entry["asked"] + t.every * factor


def judge(entry, t, answer, now):
    entry = dict(entry or {})
    state, ms, extra = answer
    if extra.get("tls_read"):
        entry["tls_at"], entry["tls_from"] = now, t.url
        if extra.get("tls"):
            entry["tls"], entry["tls_url"] = extra["tls"], t.url
        elif entry.get("tls_url") != t.url:
            entry.pop("tls", None)
            entry.pop("tls_url", None)
    if state is None and ms is None:
        return entry
    entry["asked"] = now
    if state is None:
        return entry
    entry["heard"] = now
    entry["ms"] = ms
    why, code = extra.get("why"), extra.get("status")
    entry.pop("why", None)
    entry.pop("status", None)
    if state != HEALTHY and why in WHY:
        entry["why"] = why
        if isinstance(code, int) and not isinstance(code, bool):
            entry["status"] = code
    if state == HEALTHY:
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
    entry = entry or {}
    read_at = entry.get("tls_at")
    return (not isinstance(read_at, (int, float)) or entry.get("tls_from") != t.url
            or now - read_at >= TLS_EVERY)


def _advance(store, ts, now, budget, fixed):
    factor = stretch(ts)
    checks = store["checks"]
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
            entry = {**(entry or {}), "asked": after}
        if entry:
            out[t.ckey] = entry
    return {"v": VERSION, "at": after, "checks": out}


_memory = {}
_memory_lock = threading.Lock()


def tick(data, path=None, now=None, budget=TICK_BUDGET, ts=None):
    import filelock
    ts = targets(data) if ts is None else ts
    where = path_of(path)
    fixed = now is not None
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
        log.debug("watch: no shared store here (%s); keeping one in memory", type(e).__name__)
        if not _memory_lock.acquire(blocking=False):
            return _memory.get(where)
        try:
            kept = _memory.get(where) or {"v": VERSION, "at": None, "checks": {}}
            _memory[where] = _advance(kept, ts, now if fixed else time.time(), budget, fixed)
            return _memory[where]
        finally:
            _memory_lock.release()


CARRY_WAIT = 2.0


def _asks_same(a, b):
    return (a.type, a.url, a.host, a.port, a.expect) == (b.type, b.url, b.host, b.port, b.expect)


def carry(before, after, moves, path=None, wait=CARRY_WAIT):
    import filelock
    import jsonio
    kinds = (authority.SERVICE, authority.SHADOW)
    was = {t.key: t for t in targets(before) if t.kind in kinds}
    now = {t.key: t for t in targets(after) if t.kind in kinds}
    wanted = []
    for old, news in (moves or {}).items():
        a = was.get(old)
        for new in news if isinstance(news, (list, tuple)) else []:
            b = now.get(new)
            if a is not None and b is not None and a.ckey != b.ckey and _asks_same(a, b):
                wanted.append((a.ckey, b.ckey))
                break
    if not wanted:
        return 0
    where = path_of(path)
    with filelock.exclusive(filelock.lock_for(where), timeout=wait):
        store = load(where)
        checks = store["checks"]
        taken = {a: checks.pop(a) for a, _ in wanted if a in checks}
        moved = 0
        for a, b in wanted:
            heard = (checks.get(b) or {}).get("heard")
            if a in taken and not isinstance(heard, (int, float)):
                checks[b] = taken.pop(a)
                moved += 1
        for a, entry in taken.items():
            checks.setdefault(a, entry)
        if moved:
            jsonio.write_json_atomic(where, store, keep_backup=False)
    return moved


def stale_after(t, factor=1.0):
    return max(3 * t.every * factor, 300)


def as_feed(store, ts, now=None, factor=None):
    now = time.time() if now is None else now
    factor = stretch(ts) if factor is None else factor
    checks = (store or {}).get("checks") or {}
    services, nodes, rolled = {}, {}, {}
    own = set()
    for t in ts:
        if t.kind in SHADOW_KINDS:
            continue
        entry = checks.get(t.ckey)
        if not entry or entry.get("state") not in NODE_STATES:
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
        if all(s == HEALTHY for s in states):
            nodes[place] = {"state": HEALTHY}
        elif all(s == DOWN for s in states):
            nodes[place] = {"state": DOWN}
        else:
            nodes[place] = {"state": DEGRADED}
    return {"services": services, "nodes": nodes}



_PLACE_KINDS = (authority.PLACE, authority.SHADOW_PLACE)


def find(data, key, ts=None):
    ts = targets(data) if ts is None else ts
    if not isinstance(key, str) or not key:
        return None
    mine = [t for t in ts if t.key == key]
    return next((t for t in mine if t.kind in _PLACE_KINDS), None) or (mine[0] if mine else None)


def not_asked(data, key):
    if not isinstance(data, dict) or not isinstance(key, str):
        return None
    nodes = [n for n in (data.get("nodes") if isinstance(data.get("nodes"), list) else [])
             if isinstance(n, dict) and isinstance(n.get("id"), str)]
    unmanaged = unmanaged_ids(data)
    monitors = monitor_map(data)
    if any(n["id"] == key for n in nodes):
        if key in unmanaged:
            return {"why": "unmanaged"}
        named = sorted(m for m, nid in monitors.items() if nid == key)
        return {"why": "kuma", "monitor": named[0]} if named else None
    if key in services_of(data, unmanaged) | unmanaged_service_keys(data):
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
    if t.type == "tcp":
        return f"{t.host} port {t.port}"
    if t.type == "dns":
        return f"the name {t.host}"
    return t.url


def answer_for(store, t, now=None, factor=1.0):
    now = time.time() if now is None else now
    entry = ((store or {}).get("checks") or {}).get(t.ckey)
    entry = entry if isinstance(entry, dict) else {}
    said = entry.get("said") if entry.get("said") in NODE_STATES else None
    held = entry.get("state") if entry.get("state") in NODE_STATES else None
    heard, asked = entry.get("heard"), entry.get("asked")
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    stale = bool(held) and (not numeric(heard) or now - heard > stale_after(t, factor))
    answered = numeric(asked) and numeric(heard) and heard >= asked
    if numeric(asked) and not answered:
        error = NO_ANSWER
    elif said and said != HEALTHY:
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


_by_hand = {}
_by_hand_lock = threading.Lock()


def spend_by_hand(path, count, now):
    where = path_of(path)
    with _by_hand_lock:
        kept = [at for at in _by_hand.get(where, ()) if 0 <= now - at < 60]
        kept.extend([now] * max(0, int(count)))
        _by_hand[where] = kept


def asked_by_hand(path, now):
    with _by_hand_lock:
        return [at for at in _by_hand.get(path_of(path), ()) if 0 <= now - at < 60]


def recent_asks(store, now, path=None):
    checks = (store or {}).get("checks") or {}
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    recent = [e["asked"] for e in checks.values()
              if isinstance(e, dict) and numeric(e.get("asked")) and 0 <= now - e["asked"] < 60]
    if path is not None:
        recent.extend(asked_by_hand(path, now))
    return sorted(recent)


def manual_wait(store, t, now, cap=None, path=None):
    checks = (store or {}).get("checks") or {}
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    last = (checks.get(t.ckey) or {}).get("asked")
    if numeric(last) and 0 <= now - last < EVERY_MIN:
        return max(1, int(EVERY_MIN - (now - last) + 0.999))
    cap = cap or per_minute()
    recent = recent_asks(store, now, path)
    if len(recent) >= cap:
        return max(1, int(recent[len(recent) - cap] + 60 - now + 0.999))
    return 0


def _ask_one(store, t, now, fixed, path=None):
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
        entry = {**(entry or {}), "asked": after}
    checks[t.ckey] = entry
    return "asked", None


def ask_now(data, key, path=None, now=None, ts=None):
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



_started = False
_lock = threading.Lock()


def poll_every():
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
    except Exception as e:
        log.warning("watch: a round failed: %s: %s", type(e).__name__, e)


def start(app, stop=None):
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
