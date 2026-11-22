import hashlib
import json
import math

from filelock import exclusive, lock_for
from jsonio import read_json_dict, write_json_atomic

VERSION = 1
LIMIT = 1_000_000
MAX_CARDS = 20_000

BAD_BODY = "expected {cards: {id: {x, y} or null}, expect, replace}"


class StaleError(Exception):

    def __init__(self, stamp):
        super().__init__("the layout changed since it was read")
        self.stamp = stamp


class BadBody(ValueError):
    pass


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or abs(value) > LIMIT:
        return None
    return round(float(value), 1)


def _point(value):
    if not isinstance(value, dict):
        return None
    x, y = _number(value.get("x")), _number(value.get("y"))
    if x is None or y is None:
        return None
    return {"x": x, "y": y}


def _clean(doc):
    cards = doc.get("cards") if isinstance(doc, dict) else None
    out = {}
    for key, value in (cards or {}).items() if isinstance(cards, dict) else ():
        p = _point(value)
        if isinstance(key, str) and key and p is not None:
            out[key] = p
    return {"v": VERSION, "cards": out}


def read(path):
    return _clean(read_json_dict(path))


def stamp_of(doc):
    blob = json.dumps(_clean(doc), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def stamp(path):
    return stamp_of(read(path))


def known_ids(data):
    out = set()
    for section in ("nodes", "stubs"):
        rows = data.get(section) if isinstance(data, dict) else None
        for entry in rows if isinstance(rows, list) else []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
                out.add(entry["id"])
    return out


def parse(body):
    if not isinstance(body, dict) or not isinstance(body.get("cards"), dict):
        raise BadBody(BAD_BODY)
    cards = body["cards"]
    if len(cards) > MAX_CARDS:
        raise BadBody(f"too many cards in one save (max {MAX_CARDS})")
    clean = {}
    for key, value in cards.items():
        if not isinstance(key, str) or not key:
            raise BadBody(BAD_BODY)
        if value is None:
            clean[key] = None
            continue
        p = _point(value)
        if p is None:
            raise BadBody(f"card {key[:60]!r}: x and y must be numbers within {LIMIT}")
        clean[key] = p
    expect = body.get("expect")
    if expect is not None and not isinstance(expect, str):
        raise BadBody(BAD_BODY)
    replace = body.get("replace", False)
    if not isinstance(replace, bool):
        raise BadBody(BAD_BODY)
    return clean, expect, replace


def save(path, known, cards, expect=None, replace=False):
    with exclusive(lock_for(path)):
        doc = read(path)
        if expect and expect != stamp_of(doc):
            raise StaleError(stamp_of(doc))
        merged = {} if replace else dict(doc["cards"])
        saved = 0
        for key, value in cards.items():
            if value is None:
                if key in merged:
                    merged.pop(key)
                    saved += 1
            elif key in known:
                merged[key] = value
                saved += 1
        merged = {k: v for k, v in merged.items() if k in known}
        out = {"v": VERSION, "cards": merged}
        write_json_atomic(path, out, indent=1, newline=False)
    return {"saved": saved, "total": len(merged), "stamp": stamp_of(out)}


def for_viewer(doc, visible):
    return {"v": VERSION, "cards": {k: v for k, v in doc["cards"].items() if k in visible}}
