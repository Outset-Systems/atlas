import base64
import collections
import json
import re

import schema

MAX_BODY = 4096
TITLE_MAX = 200
TAG_MAX, TAGS_MAX = 32, 8
LINK_MAX = 2000

_URL_CHARS = re.compile(r"^[\x21-\x7e]+$")
_TAG = re.compile(r"[^A-Za-z0-9_+\-]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f\x80-\x9f  ]")



def _text(value):
    if value is None:
        return ""
    return str(value).encode("utf-8", "replace").decode("utf-8")


def _one_line(value, limit):
    text = re.sub(r"\s+", " ", _CONTROL.sub(" ", _text(value))).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _header(value):
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
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:max(0, limit - 3)].decode("utf-8", "ignore") + "…"


def _fit_json(build, text):
    def encode(t):
        return json.dumps(build(t), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    whole = encode(text)
    if len(whole) <= MAX_BODY:
        return whole
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(encode(text[:mid] + "…")) <= MAX_BODY:
            lo = mid
        else:
            hi = mid - 1
    return encode(text[:lo] + "…")


Prepared = collections.namedtuple("Prepared", "title body high link tags")


def prepared(message):
    if isinstance(message, Prepared):
        return message
    message = message if isinstance(message, dict) else {}
    return Prepared(_one_line(message.get("title"), TITLE_MAX), _text(message.get("body")),
                    message.get("priority") == "high", _link(message.get("link")),
                    _tags(message.get("tags")))


def base_headers(content_type):
    return {"User-Agent": "Atlas-alerts", "Content-Type": content_type}


header_text = _header


def plain_body(text):
    return _cut_bytes(text, MAX_BODY).encode("utf-8")


def json_body(build, text):
    return _fit_json(build, text)
