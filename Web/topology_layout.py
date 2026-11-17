"""TOPOLOGY's layout (2026-11-17): where an admin put each card on the canvas.

A file beside `positions.json` (`ATLAS_TOPOLOGY_LAYOUT`, default
`<data dir>/topology-layout.json`), one per map, never shipped, so a deploy
cannot clobber a hand-placed drawing:

    {"v": 1, "cards": {"<place or stub id>": {"x": 412.0, "y": 160.0}}}

It is not map data, as marker positions are not: no revision, no undo entry,
no change log. It is read by `GET /api/v2/topology/layout` and written by
`POST /api/v2/topology/layout` (api/v2/topology_layout.py).

What it shares with `positions.json` (overlays.py): the write gate
(`security.write_refusal`), the lock beside the file and the atomic write, a
one-sentence 400 for a body of the wrong shape, and only known things kept
(a place or a stub on the map; anything else is dropped and counted as not
saved). What it adds, from the repairs store (maintenance.py): a STAMP, a
short hash of the file, which a write sends back as `expect` and which is
compared inside the lock, so two admins dragging at once get a 409 rather
than one losing the other's moves.

The positions are the canvas's own units (a card is 176 x 64): any finite
number, rounded to a tenth, within +/- LIMIT. A reader is given only the
cards of the places and stubs on their own redacted map (`for_viewer`), so a
hidden place's id, and a stub the redaction withheld, never leave here."""

import hashlib
import json
import math

from filelock import exclusive, lock_for
from jsonio import read_json_dict, write_json_atomic

VERSION = 1
#: How far from the origin a card may be put, either way.
LIMIT = 1_000_000
#: The most cards one write may name.
MAX_CARDS = 20_000

BAD_BODY = "expected {cards: {id: {x, y} or null}, expect, replace}"


class StaleError(Exception):
    """The layout changed after the page read it: `expect` no longer matches."""

    def __init__(self, stamp):
        super().__init__("the layout changed since it was read")
        self.stamp = stamp


class BadBody(ValueError):
    """A body of the wrong shape; its message is the 400's sentence."""


def _number(value):
    """A finite number within LIMIT (never a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or abs(value) > LIMIT:
        return None
    return round(float(value), 1)


def _point(value):
    """{x, y} cleaned, or None when it is not one."""
    if not isinstance(value, dict):
        return None
    x, y = _number(value.get("x")), _number(value.get("y"))
    if x is None or y is None:
        return None
    return {"x": x, "y": y}


def _clean(doc):
    """The file as read, narrowed to its shape: anything else reads as empty."""
    cards = doc.get("cards") if isinstance(doc, dict) else None
    out = {}
    for key, value in (cards or {}).items() if isinstance(cards, dict) else ():
        p = _point(value)
        if isinstance(key, str) and key and p is not None:
            out[key] = p
    return {"v": VERSION, "cards": out}


def read(path):
    """The layout on file, `{"v": 1, "cards": {...}}`; empty when there is none."""
    return _clean(read_json_dict(path))


def stamp_of(doc):
    """A cheap version token for the layout, as the repairs store makes one."""
    blob = json.dumps(_clean(doc), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def stamp(path):
    return stamp_of(read(path))


def known_ids(data):
    """The things a card can be: every place and every stub on the map."""
    out = set()
    for section in ("nodes", "stubs"):
        rows = data.get(section) if isinstance(data, dict) else None
        for entry in rows if isinstance(rows, list) else []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
                out.add(entry["id"])
    return out


def parse(body):
    """(cards, expect, replace) from a request body, or BadBody.

    `cards` maps an id to `{x, y}` (put it there) or null (forget it, so it
    is laid out again). `replace` true makes `cards` the whole layout, which
    is how Re-arrange throws it away (`{"cards": {}, "replace": true}`).
    `expect` is the stamp the page read; leaving it out skips the check."""
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
    """Merge `cards` into the layout under its lock. Returns
    {saved, total, stamp}: `saved` counts the cards put or forgotten, and an
    id that is not a place or stub on the map is neither. Cards of things no
    longer on the map are dropped from the file as it is written. Raises
    StaleError when `expect` is given and the file has moved on."""
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
    """The layout as a reader with these visible ids is given it."""
    return {"v": VERSION, "cards": {k: v for k, v in doc["cards"].items() if k in visible}}
