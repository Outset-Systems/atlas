"""Whether a service will actually render inside the Atlas, or must open away.

The map's point is that you never leave it. Every outward button used to be
`target="_blank"` — honest, but it throws you out of the world. THE VIEWING
GLASS shows the same page in a pane over the map instead. That only works when
the page *lets* itself be framed, and three separate things decide it, two of
which are not ours:

  1. **Our own CSP.** `frame-src` lists what this page may embed. The Atlas
     shipped `'self'` plus `ATLAS_EMBED_HOSTS` (the Chronicle's Grafana), so
     every other origin was refused by our own header before the remote one
     ever got a say. `origins()` widens that list to the origins the dataset
     already points at: a service the map links to is a service the map may
     show. `ATLAS_EMBED_SERVICES=0` turns that back off.
  2. **Their `X-Frame-Options` / `frame-ancestors`.** Not negotiable from here,
     and invisible to the browser as anything but a blank pane — a framed page
     that refuses gives no event you can catch cross-origin. So we ask the
     service directly, once, and cache the answer. That is `verdict()`.
  3. **Mixed content.** An `http://` service inside an `https://` Atlas is
     blocked outright. The browser knows its own scheme, so that check lives in
     the front-end, where it costs nothing and can never be wrong.

Fail-silent, like `signals.py`: a probe that times out answers **unknown**, never
raises, and the front-end treats unknown as "try it and see" — the glass falls
back to a new tab if the pane never paints. A refusal we are sure of is worth a
straight jump to the tab; a refusal we guessed at is worth an attempt.

Nothing here ever probes a URL the client names. `verdict()` is only ever
reached through `/api/embeddable`, which refuses any URL that is not already in
the dataset — the prober is not an open fetcher wearing the app's network
position.
"""

import logging
import re
import threading
import time
from urllib.parse import urlsplit

log = logging.getLogger("atlas.web.embeddable")

#: Hard per-probe timeout. A slow service must never stall the click that asked.
TIMEOUT = 2.5

#: How long a verdict stands. Long enough that clicking around costs nothing,
#: short enough that flipping `allow_embedding` on a dashboard is noticed the
#: same afternoon.
TTL = 900.0

#: What a CSP source expression may look like once we've built it. Everything
#: that reaches the header is matched against this first — the dataset is
#: admin-written, but a URL is still user input and a header is still a header.
_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9._\-]+(?::\d{1,5})?$")

# Verdict reasons, kept as constants because the front-end shows them verbatim.
R_REFUSED = "it refuses to be framed"
R_UNREACHABLE = "it could not be reached to ask"
R_NOT_HTTP = "it is not an http(s) address"
R_OK = "it allows framing"
R_OFF = "probing is switched off"


def origin_of(url):
    """`scheme://host[:port]` for an absolute http(s) URL, else None.

    Relative URLs (`report/security`, which the Abyss uses for the staged
    markdown pages) return None on purpose: they are already `'self'`.
    """
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
    """Every outward address the map offers, in dataset order, deduplicated.

    One list, because both consumers want the same one: the CSP wants their
    origins, and `/api/embeddable` wants to know whether a URL it was handed is
    one of ours before it will go and knock on it.
    """
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
    """The distinct, header-safe origins those URLs live at, sorted."""
    return sorted({o for o in map(origin_of, urls_of(data)) if o})


#: One-entry memo for the charted-URL set, keyed on the dataset stamp the
#: reader already hands back (mtime in file mode, the site stamp in db mode).
#: Rebuilding the set per request cost ~100 µs a call for a value that changes
#: only when the dataset does. `id(data)` rides along because two different
#: temp datasets can land on the same mtime within filesystem resolution.
_charted = {"key": None, "urls": frozenset()}


def charted(data, stamp=None):
    """Every outward URL the map offers, as a set, memoized per dataset."""
    key = (stamp, id(data))
    if _charted["key"] != key:
        _charted["key"] = key
        _charted["urls"] = frozenset(urls_of(data))
    return _charted["urls"]


def frame_src(data, configured=""):
    """The full `frame-src` source list for the CSP header.

    `configured` is `ATLAS_EMBED_HOSTS`, kept first and kept in whatever form it
    was typed: an operator may legitimately write a bare host, a wildcard or a
    scheme, none of which `origin_of` would synthesise.

    But it is going into a header, so a `;` or a newline anywhere in it voids
    **the whole value**, not just the offending token. Dropping token-by-token
    looks safer and is not: `"http://fine:1; default-src *"` splits into three
    words, only the first of which carries the semicolon, and quietly keeping
    the other two would have put a bare `*` in `frame-src`. There is no valid
    reason for either character to appear here, so the safe reading of one is
    "this variable is malformed", and the safe response is to ignore it and say
    so rather than to guess which half was meant.
    """
    parts = ["'self'"]
    raw = configured or ""
    if ";" in raw or "\n" in raw or "\r" in raw:
        log.error("ATLAS_EMBED_HOSTS contains a ';' or a newline and has been "
                  "ignored entirely — it is a space-separated list of origins, "
                  "not a CSP fragment")
        raw = ""
    for token in raw.split():
        if token not in parts:
            parts.append(token)
    # `data=None` IS the "configured hosts only" switch — the caller passing no
    # dataset (ATLAS_EMBED_SERVICES=0, or an unreadable read) is the whole story,
    # so there is no separate flag for it to disagree with.
    if data:
        for origin in origins(data):
            if origin not in parts:
                parts.append(origin)
    return " ".join(parts)


# ── The probe ────────────────────────────────────────────────────────────────
_cache = {}
_lock = threading.Lock()


def _parse_frame_ancestors(csp):
    """The `frame-ancestors` sources from a CSP header, or None if absent.

    Absent is not the same as empty: a header with no `frame-ancestors`
    directive says nothing about framing, while `frame-ancestors 'none'` is a
    flat refusal. Returning None for the first keeps them distinguishable.
    """
    for directive in (csp or "").split(";"):
        bits = directive.strip().split()
        if bits and bits[0].lower() == "frame-ancestors":
            return [b.lower() for b in bits[1:]]
    return None


def _judge(headers, self_origin, target_origin=None):
    """(embeddable, reason) from a response's headers. None = can't tell.

    `self_origin` is where the Atlas is served from; `target_origin` where the
    thing being judged is. They matter because `SAMEORIGIN` and `'self'` are
    written from the *service's* point of view — for the Atlas's own report
    pages those are a yes, and for everything else a no.
    """
    xfo = (headers.get("X-Frame-Options") or "").strip().lower()
    ancestors = _parse_frame_ancestors(headers.get("Content-Security-Policy"))
    ours = bool(self_origin) and (target_origin or "").lower() == self_origin.lower()

    # CSP wins where both are present — that is what browsers do.
    if ancestors is not None:
        if "'none'" in ancestors:
            return False, R_REFUSED
        if "*" in ancestors or (self_origin and self_origin.lower() in ancestors):
            return True, R_OK
        if "'self'" in ancestors and len(ancestors) == 1:
            return (True, R_OK) if ours else (False, R_REFUSED)
        # Something specific that isn't us, or a form we don't model (a scheme
        # source, a wildcard host). Say so rather than guessing a refusal: the
        # glass will try, and a blank pane is recoverable in one click.
        return None, "its framing rule is one we can't read from here"

    if xfo.startswith("deny"):
        return False, R_REFUSED
    if xfo.startswith("sameorigin"):
        return (True, R_OK) if ours else (False, R_REFUSED)
    if xfo.startswith("allow-from"):
        return (True, R_OK) if self_origin and self_origin.lower() in xfo else (False, R_REFUSED)
    return True, R_OK


def _probe(url, self_origin):
    """Ask the service, once. Never raises."""
    try:
        import requests  # local import: optional dep, exactly as signals.py
    except ImportError:                                    # pragma: no cover
        return None, R_UNREACHABLE

    for method in ("head", "get"):
        try:
            resp = getattr(requests, method)(
                url, timeout=TIMEOUT, allow_redirects=True,
                stream=(method == "get"),
            )
        except Exception as e:                             # noqa: BLE001
            # A transport failure (refused, timed out, no route) answers the
            # question: a GET would only wait out the same timeout again, and
            # cross-VLAN unreachability is the *routine* case in this lab —
            # retrying it doubled how long a request thread stayed pinned.
            log.debug("embeddable: %s %s failed (%s)", method, url, e)
            return None, R_UNREACHABLE
        try:
            # A 405/501 to HEAD is common enough on app servers that treating
            # it as an answer would mislabel half a lab; fall through to GET.
            if method == "head" and resp.status_code in (400, 403, 405, 501):
                continue
            # judge where it *ended up* — a redirect can land somewhere with
            # entirely different framing rules
            landed = origin_of(getattr(resp, "url", "") or url) or origin_of(url)
            return _judge(resp.headers, self_origin, landed)
        finally:
            resp.close()
    return None, R_UNREACHABLE


def _answer(url, ok, reason):
    """The verdict shape, defined once — see `verdict()`'s docstring."""
    return {"url": url, "embeddable": ok, "reason": reason, "checked": time.time()}


def verdict(url, self_origin="", enabled=True):
    """`{"url", "embeddable", "reason", "checked"}` for one dataset URL.

    `embeddable` is True (frame it), False (don't bother — it will refuse) or
    None (unknown; the caller should try and fall back). Cached for `TTL`.
    """
    if origin_of(url) is None:
        stripped = url.strip() if isinstance(url, str) else ""
        # Relative — `report/security` and friends are served by this app, so
        # they are `'self'` and always frame. Protocol-relative `//host` is
        # NOT relative: it inherits the page's scheme and goes off-origin, and
        # `schema.py`'s link rule refuses it for the same reason.
        if stripped and "://" not in stripped and not stripped.startswith("//"):
            return _answer(url, True, "it is served by the Atlas itself")
        return _answer(url, False, R_NOT_HTTP)

    if not enabled:
        return _answer(url, None, R_OFF)

    now = time.monotonic()
    with _lock:
        hit = _cache.get(url)
        if hit and (now - hit[1]) < TTL:
            return dict(hit[0])

    ok, reason = _probe(url, self_origin)
    out = _answer(url, ok, reason)
    with _lock:
        _cache[url] = (out, now)
    return dict(out)


def forget():
    """Drop every cached verdict. For the tests, and for a future 're-ask'."""
    with _lock:
        _cache.clear()
