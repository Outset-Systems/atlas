"""Layout overlays — the small files that sit *over* the dataset.

`positions.json` (marker x/y, written by Settings → Save to map) and
`rack.json` (U-slots, written by THE ARMORY → Rearrange) are not inventory.
They are where *this* deployment decided things should sit, deliberately never
shipped so a deploy can't clobber a hand-placed layout. They are merged over
the dataset at serve time.

There were two copies of this — `_read_positions`/`_apply_positions` and a
near-identical rack twin — differing only in what they keyed on and how they
bounds-checked. Two copies of a merge-over-the-truth rule is two chances for
them to disagree about what happens when the file is corrupt. Now there is one
`Overlay`, and each instance supplies the three things that genuinely differ:
how an entry is keyed, how a submitted value is cleaned, and how it is applied.

**Precedence.** The overlay wins over the dataset — that is the whole point of
it. But now that the editor can set x/y directly, an overlay entry for a place
whose position was just edited would silently undo the edit. So the editor
clears the overlay entry for anything it writes: see `drop()`.
"""

import logging
import re

import schema
from filelock import exclusive, lock_for
from jsonio import read_json_dict, write_json_atomic

log = logging.getLogger("atlas.data.overlays")


class Overlay:
    """One overlay file: read, merge, validated write."""

    def __init__(self, path, section, key_of, apply_to, clean, cache_tag):
        self.path = path
        self.section = section        # dataset section it overlays
        self._key_of = key_of         # entry -> stable key
        self._apply_to = apply_to     # (entry, value) -> None, mutates the copy
        self._clean = clean           # (data, submitted) -> {key: value}
        self._tag = cache_tag         # one letter, for the ETag fragment

    # -- read ---------------------------------------------------------------
    def read(self):
        return read_json_dict(self.path)

    def key_of(self, entry):
        return self._key_of(entry)

    def apply(self, data):
        """Return (dataset, etag_fragment) with the overlay merged in.

        Shallow-copies only the section it touches — the caller may be holding
        the mtime-cached dataset, which must never be mutated in place.
        """
        saved = self.read()
        if not saved:
            return data, ""
        out = dict(data)
        out[self.section] = [dict(e) for e in data.get(self.section, [])]
        for entry in out[self.section]:
            value = saved.get(self.key_of(entry))
            if value is not None:
                self._apply_to(entry, value)
        return out, f"{self._tag}{len(saved)}"

    # -- write --------------------------------------------------------------
    # Both writers below are read-modify-write and take the same lock as the
    # dataset writer, for the same reason: two admins saving marker positions
    # at once would otherwise lose one set of moves, and could collide on the
    # temp file. Small stakes, identical bug.
    def _lock_path(self):
        return lock_for(self.path)

    def merge(self, data, submitted):
        """Validate and merge a submission. Returns (saved_count, total)."""
        clean = self._clean(data, submitted)
        with exclusive(self._lock_path()):
            merged = self.read()
            merged.update(clean)
            write_json_atomic(self.path, merged, indent=1, newline=False)
        return len(clean), len(merged)

    def drop(self, keys):
        """Forget the overlay for these keys — the dataset is the truth again.

        Called when the editor writes the same property directly. Without it,
        an old saved position would quietly override every future edit and the
        field in the form would look broken.
        """
        with exclusive(self._lock_path()):
            saved = self.read()
            gone = [k for k in keys if k in saved]
            if not gone:
                return 0
            for k in gone:
                saved.pop(k, None)
            write_json_atomic(self.path, saved, indent=1, newline=False)
        log.info("dropped %d %s overlay entr%s superseded by an edit",
                 len(gone), self.section, "y" if len(gone) == 1 else "ies")
        return len(gone)


# ── positions.json — moved markers ───────────────────────────────────────────

def _position_key(node):
    return node.get("id")


def _position_apply(node, value):
    if isinstance(value, dict) and isinstance(value.get("x"), (int, float)) \
            and isinstance(value.get("y"), (int, float)):
        node["x"], node["y"] = value["x"], value["y"]


def _position_clean(data, submitted):
    """Only known places, only positions that land on (or just off) the table."""
    valid = {n.get("id") for n in data.get("nodes", [])}
    clean = {}
    for node_id, p in submitted.items():
        if node_id not in valid or not isinstance(p, dict):
            continue
        x, y = p.get("x"), p.get("y")
        # y may exceed 100 by design — THE WILD lives in the void below.
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) \
                and 0 <= x <= 100 and schema.PERCENT_MIN <= y <= schema.PERCENT_MAX:
            clean[node_id] = {"x": round(float(x), 2), "y": round(float(y), 2)}
    return clean


# ── rack.json — rearranged U-slots ───────────────────────────────────────────

def slot_key(slot):
    """A rack slot's stable key: its node id, else a slug of its name.

    Shared with the front-end, which computes the same key — if these two ever
    disagree, a saved rearrangement silently applies to the wrong vessel.
    """
    if slot.get("node"):
        return slot["node"]
    name = str(slot.get("name", ""))
    if slot.get("rack"):           # two racks may each hold a "Patch Panel"
        name = f"{slot['rack']} {name}"
    return "slot:" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def top_u(slot):
    """The highest U a slot occupies — `U3–U4` is anchored at 4."""
    numbers = [int(x) for x in re.findall(r"\d+", str(slot.get("u", "")))]
    return max(numbers) if numbers else 1


def u_label(top, size):
    return f"U{top}" if size <= 1 else f"U{top - size + 1}–{top}"


def _rack_apply(slot, value):
    if isinstance(value, int):
        slot["u"] = u_label(value, int(slot.get("size", 1) or 1))


def _rack_clean(data, submitted):
    """Only known slots, only positions that fit inside the rack.

    The front-end already prevents overlaps; this is the bounds check that
    stops a hand-crafted POST from parking a 2U box at U1.
    """
    rack = data.get("rack", [])
    racks = [r.get("id") for r in data.get("racks") or [] if isinstance(r, dict)]

    def home(slot):            # unset or unknown means the first rack, as in rack-model.js
        return slot.get("rack") if slot.get("rack") in racks else (racks[0] if racks else "")

    heights = {}
    for s in rack:
        heights[home(s)] = max(heights.get(home(s), 1), top_u(s))
    slots = {slot_key(s): s for s in rack}
    sizes = {key: int(s.get("size", 1) or 1) for key, s in slots.items()}
    clean = {}
    for key, top in submitted.items():
        if key not in sizes:
            continue
        try:
            top = int(top)
        except (TypeError, ValueError):
            continue
        if sizes[key] <= top <= heights[home(slots[key])]:
            clean[key] = top
    return clean


def build(positions_path, rack_path):
    """The two overlays this deployment uses."""
    return {
        "positions": Overlay(positions_path, "nodes", _position_key,
                             _position_apply, _position_clean, "p"),
        "rack": Overlay(rack_path, "rack", slot_key,
                        _rack_apply, _rack_clean, "r"),
    }
