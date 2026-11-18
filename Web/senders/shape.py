"""THE SHAPES: how every kind's message is cleaned and cut to fit (2026-11-17).

Moved here, unchanged, from `alert_send.py`, so a kind's `build` reads them
without importing the guard back. The guard (`alert_send.py`) imports every
name here and still checks what a kind built before anything leaves.
"""

import base64
import collections
import json
import re

import schema

MAX_BODY = 4096          # bytes of request body, after encoding
TITLE_MAX = 200          # characters
TAG_MAX, TAGS_MAX = 32, 8
LINK_MAX = 2000

#: What a URL may carry at all: printable ASCII, no space, no backslash.
_URL_CHARS = re.compile(r"^[\x21-\x7e]+$")
_TAG = re.compile(r"[^A-Za-z0-9_+\-]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f\x80-\x9f  ]")


# ── The shapes: what every kind's request is cleaned and cut by ─────────────

def _text(value):
    """Text that encodes as UTF-8 (a lone surrogate becomes '?')."""
    if value is None:
        return ""
    return str(value).encode("utf-8", "replace").decode("utf-8")


def _one_line(value, limit):
    text = re.sub(r"\s+", " ", _CONTROL.sub(" ", _text(value))).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _header(value):
    """A header value: one line, and ASCII, as RFC 2047 when it is not
    (ntfy decodes `=?UTF-8?B?…?=`)."""
    if value.isascii():
        return value
    return "=?UTF-8?B?" + base64.b64encode(value.encode("utf-8")).decode("ascii") + "?="


def _link(value):
    if not isinstance(value, str):
        return None
    link = value.strip()
    if (not link or len(link) > LINK_MAX or not _URL_CHARS.match(link)
            or not link.lower().startswith(("http://", "https://"))
            or schema.carries_credentials(link)):
        return None
    return link


def _tags(value):
    out = []
    for tag in value if isinstance(value, (list, tuple)) else ():
        tag = _TAG.sub("", _text(tag))[:TAG_MAX]
        if tag and tag not in out:
            out.append(tag)
        if len(out) >= TAGS_MAX:
            break
    return out


def _cut_bytes(text, limit):
    """`text` in at most `limit` UTF-8 bytes, ending in '…' when cut, never
    splitting a character."""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:max(0, limit - 3)].decode("utf-8", "ignore") + "…"


def _fit_json(build, text):
    """The JSON bytes of `build(text)` in at most MAX_BODY bytes, cutting only
    the text: the structure is always whole."""
    def encode(t):
        return json.dumps(build(t), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    whole = encode(text)
    if len(whole) <= MAX_BODY:
        return whole
    lo, hi = 0, len(text)
    while lo < hi:                       # the longest prefix that fits
        mid = (lo + hi + 1) // 2
        if len(encode(text[:mid] + "…")) <= MAX_BODY:
            lo = mid
        else:
            hi = mid - 1
    return encode(text[:lo] + "…")


#: A message as the guard cleaned it: `title` one line of at most TITLE_MAX
#: characters, `body` text that encodes, `high`, `link` (None unless it is a
#: plain http(s) address with no credentials) and `tags`.
Prepared = collections.namedtuple("Prepared", "title body high link tags")


def prepared(message):
    """`message` cleaned for any kind (a `Prepared` is returned as it is), so a
    kind's `build` never sees a raw title, link or tag."""
    if isinstance(message, Prepared):
        return message
    message = message if isinstance(message, dict) else {}
    return Prepared(_one_line(message.get("title"), TITLE_MAX), _text(message.get("body")),
                    message.get("priority") == "high", _link(message.get("link")),
                    _tags(message.get("tags")))


def base_headers(content_type):
    """The headers every kind starts from."""
    return {"User-Agent": "Atlas-alerts", "Content-Type": content_type}


#: A header value, ASCII, as RFC 2047 when it is not.
header_text = _header


def plain_body(text):
    """A text body in at most MAX_BODY bytes, ending in '…' when cut."""
    return _cut_bytes(text, MAX_BODY).encode("utf-8")


def json_body(build, text):
    """The JSON of `build(text)` in at most MAX_BODY bytes, cutting only the text."""
    return _fit_json(build, text)
