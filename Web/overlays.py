import logging
import re

import schema
from filelock import exclusive, lock_for
from jsonio import read_json_dict, write_json_atomic

log = logging.getLogger("atlas.data.overlays")


class Overlay:

    def __init__(self, path, section, key_of, apply_to, clean, cache_tag):
        self.path = path
        self.section = section
        self._key_of = key_of
        self._apply_to = apply_to
        self._clean = clean
        self._tag = cache_tag

    def read(self):
        return read_json_dict(self.path)

    def key_of(self, entry):
        return self._key_of(entry)

    def apply(self, data):
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

    def _lock_path(self):
        return lock_for(self.path)

    def merge(self, data, submitted):
        clean = self._clean(data, submitted)
        with exclusive(self._lock_path()):
            merged = self.read()
            merged.update(clean)
            write_json_atomic(self.path, merged, indent=1, newline=False)
        return len(clean), len(merged)

    def drop(self, keys):
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



def _position_key(node):
    return node.get("id")


def _position_apply(node, value):
    if isinstance(value, dict) and isinstance(value.get("x"), (int, float)) \
            and isinstance(value.get("y"), (int, float)):
        node["x"], node["y"] = value["x"], value["y"]


def _position_clean(data, submitted):
    valid = {n.get("id") for n in data.get("nodes", [])}
    clean = {}
    for node_id, p in submitted.items():
        if node_id not in valid or not isinstance(p, dict):
            continue
        x, y = p.get("x"), p.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) \
                and 0 <= x <= 100 and schema.PERCENT_MIN <= y <= schema.PERCENT_MAX:
            clean[node_id] = {"x": round(float(x), 2), "y": round(float(y), 2)}
    return clean



def slot_key(slot):
    if slot.get("node"):
        return slot["node"]
    name = str(slot.get("name", ""))
    if slot.get("rack"):
        name = f"{slot['rack']} {name}"
    return "slot:" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def top_u(slot):
    numbers = [int(x) for x in re.findall(r"\d+", str(slot.get("u", "")))]
    return max(numbers) if numbers else 1


def u_label(top, size):
    return f"U{top}" if size <= 1 else f"U{top - size + 1}–{top}"


def _rack_apply(slot, value):
    if isinstance(value, int):
        slot["u"] = u_label(value, int(slot.get("size", 1) or 1))


def _rack_clean(data, submitted):
    rack = data.get("rack", [])
    racks = [r.get("id") for r in data.get("racks") or [] if isinstance(r, dict)]

    def home(slot):
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
    return {
        "positions": Overlay(positions_path, "nodes", _position_key,
                             _position_apply, _position_clean, "p"),
        "rack": Overlay(rack_path, "rack", slot_key,
                        _rack_apply, _rack_clean, "r"),
    }
