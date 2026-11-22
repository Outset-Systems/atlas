import logging
import re
import threading
import time
from collections import Counter
from urllib.parse import urlsplit

log = logging.getLogger("atlas.web.embeddable")

TIMEOUT = 2.5

TTL = 900.0

_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9._\-]+(?::\d{1,5})?$")

R_REFUSED = "it refuses to be framed"
R_UNREACHABLE = "it could not be reached to ask"
R_NOT_HTTP = "it is not an http(s) address"
R_OK = "it allows framing"
R_OFF = "probing is switched off"
R_UNLISTED = "this map links to more services than one page may list for the glass"


def origin_of(url):
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    origin = f"{parts.scheme}://{parts.netloc}"
    return origin if _ORIGIN_RE.match(origin) else None


def urls_of(data):
    seen, out = set(), []

    def take(value):
        if isinstance(value, str) and value.strip() and value.strip() not in seen:
            seen.add(value.strip())
            out.append(value.strip())

    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        for link in node.get("links") or []:
            if isinstance(link, dict):
                take(link.get("url"))
    for key in ("chronicle", "abyss"):
        for item in data.get(key) or []:
            if isinstance(item, dict):
                take(item.get("url"))
                take(item.get("embed"))
    return out


def origins(data):
    return sorted({o for o in map(origin_of, urls_of(data)) if o})


_charted = (None, frozenset())


def charted(data, stamp=None):
    global _charted
    key = (stamp, id(data))
    have_key, have_urls = _charted
    if have_key == key:
        return have_urls
    urls = frozenset(urls_of(data))
    _charted = (key, urls)
    return urls


FRAME_SRC_BUDGET = 24_000


def ranked_origins(data):
    counts = Counter(o for o in map(origin_of, urls_of(data)) if o)
    return sorted(counts, key=lambda o: (-counts[o], o))


def pinned_origins(data):
    out = set()
    for key in ("chronicle", "abyss"):
        for item in data.get(key) or []:
            if isinstance(item, dict):
                out.update(o for o in (origin_of(item.get("url")), origin_of(item.get("embed"))) if o)
    return out


_BUDGET = object()


def frame_src(data, configured="", budget=_BUDGET):
    return frame_list(data, configured, budget)[0]


def frame_list(data, configured="", budget=_BUDGET):
    parts = ["'self'"]
    raw = configured or ""
    if ";" in raw or "\n" in raw or "\r" in raw:
        log.error("ATLAS_EMBED_HOSTS contains a ';' or a newline and has been "
                  "ignored entirely — it is a space-separated list of origins, "
                  "not a CSP fragment")
        raw = ""
    have = set(parts)
    for token in raw.split():
        if token not in have:
            have.add(token)
            parts.append(token)
    kept, dropped = [], set()
    if data:
        room = FRAME_SRC_BUDGET if budget is _BUDGET else budget
        for origin in sorted(pinned_origins(data) - have):
            have.add(origin)
            kept.append(origin)
            if room is not None:
                room -= len(origin) + 1
        for origin in ranked_origins(data):
            if origin in have:
                continue
            have.add(origin)
            if room is not None:
                if dropped or len(origin) + 1 > room:
                    dropped.add(origin)
                    continue
                room -= len(origin) + 1
            kept.append(origin)
    parts.extend(sorted(kept))
    return " ".join(parts), frozenset(dropped)


_cache = {}
_lock = threading.Lock()


def _parse_frame_ancestors(csp):
    for directive in (csp or "").split(";"):
        bits = directive.strip().split()
        if bits and bits[0].lower() == "frame-ancestors":
            return [b.lower() for b in bits[1:]]
    return None


def _judge(headers, self_origin, target_origin=None):
    xfo = (headers.get("X-Frame-Options") or "").strip().lower()
    ancestors = _parse_frame_ancestors(headers.get("Content-Security-Policy"))
    ours = bool(self_origin) and (target_origin or "").lower() == self_origin.lower()

    if ancestors is not None:
        if "'none'" in ancestors:
            return False, R_REFUSED
        if "*" in ancestors or (self_origin and self_origin.lower() in ancestors):
            return True, R_OK
        if "'self'" in ancestors and len(ancestors) == 1:
            return (True, R_OK) if ours else (False, R_REFUSED)
        return None, "its framing rule is one we can't read from here"

    if xfo.startswith("deny"):
        return False, R_REFUSED
    if xfo.startswith("sameorigin"):
        return (True, R_OK) if ours else (False, R_REFUSED)
    if xfo.startswith("allow-from"):
        return (True, R_OK) if self_origin and self_origin.lower() in xfo else (False, R_REFUSED)
    return True, R_OK


_FRAMING = ("X-Frame-Options", "Content-Security-Policy")


def _probe(url, self_origin):
    answer = _ask(url)
    if answer is None:
        return None, R_UNREACHABLE
    headers, landed = answer
    return _judge(headers, self_origin, landed)


def _ask(url):
    try:
        import requests
    except ImportError:
        return None

    for method in ("head", "get"):
        try:
            resp = getattr(requests, method)(
                url, timeout=TIMEOUT, allow_redirects=True,
                stream=(method == "get"),
            )
        except Exception as e:
            log.debug("embeddable: %s %s failed (%s)", method, url, e)
            return None
        try:
            if method == "head" and resp.status_code in (400, 403, 405, 501):
                continue
            landed = origin_of(getattr(resp, "url", "") or url) or origin_of(url)
            headers = {name: resp.headers.get(name) for name in _FRAMING
                       if resp.headers.get(name) is not None}
            return headers, landed
        finally:
            resp.close()
    return None


def _answer(url, ok, reason):
    return {"url": url, "embeddable": ok, "reason": reason, "checked": time.time()}


def unlisted(url):
    return {**_answer(url, False, R_UNLISTED), "ours": True}


def verdict(url, self_origin="", enabled=True):
    if origin_of(url) is None:
        stripped = url.strip() if isinstance(url, str) else ""
        if stripped and "://" not in stripped and not stripped.startswith("//"):
            return _answer(url, True, "it is served by the Atlas itself")
        return _answer(url, False, R_NOT_HTTP)

    if not enabled:
        return _answer(url, None, R_OFF)

    now = time.monotonic()
    with _lock:
        hit = _cache.get(url)
    if hit and (now - hit[1]) < TTL:
        answer, checked = hit[0], hit[2]
    else:
        answer, checked = _ask(url), time.time()
        with _lock:
            _cache[url] = (answer, now, checked)
    if answer is None:
        ok, reason = None, R_UNREACHABLE
    else:
        ok, reason = _judge(answer[0], self_origin, answer[1])
    return {**_answer(url, ok, reason), "checked": checked}


def forget():
    with _lock:
        _cache.clear()
