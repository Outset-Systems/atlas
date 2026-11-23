import re

import schema

LEVELS = schema.PREMISE_LEVELS
_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}
_DESKLIKE = re.compile(r"(desk|cube|cubicle|seat|workstation)\b", re.IGNORECASE)
_BOX = ("x", "y", "w", "h")


def _entries(data):
    rows = data.get("premises") if isinstance(data, dict) else None
    return [p for p in rows if isinstance(p, dict)] if isinstance(rows, list) else []


def problems(data):
    out = []
    rows = _entries(data)
    by_id = {p.get("id"): p for p in rows if isinstance(p.get("id"), str)}
    for p in rows:
        pid = p.get("id")
        label = f"premise {pid!r}"
        level = p.get("level")
        if level not in _RANK:
            continue
        parent = p.get("parent")
        if not parent:
            if level != "site":
                out.append(f"{label}: a {level} must be inside something (only a site "
                           f"stands alone)")
        elif parent == pid:
            out.append(f"{label}: cannot be inside itself")
        elif isinstance(parent, str) and parent in by_id:
            plevel = by_id[parent].get("level")
            if plevel in _RANK and _RANK[plevel] >= _RANK[level]:
                out.append(f"{label}: a {level} cannot be inside a {plevel} "
                           f"({parent!r}); its parent must be broader")
        given = [k for k in _BOX if p.get(k) not in (None, "")]
        if given and len(given) != len(_BOX):
            out.append(f"{label}: its box needs all of Left, Top, Width and Height, "
                       f"or none")
        if all(isinstance(p.get(k), (int, float)) for k in ("w", "h")) and \
                (p.get("w") <= 0 or p.get("h") <= 0):
            out.append(f"{label}: its box needs a width and a height above 0")
    return out



def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower()).strip("-") or "premise"


def _key(text):
    return " ".join(str(text).split()).casefold()


def resolve_path(data, path, made=None):
    segs = [s.strip() for s in str(path or "").replace("›", "/").split("/") if s.strip()]
    if not segs:
        return None, []
    if len(segs) > len(LEVELS):
        raise ValueError(f"a premise path has at most {len(LEVELS)} parts "
                         f"(site/building/floor/room/desk): {path!r}")
    made = made if made is not None else []
    rows = _entries(data) + made
    used = {p.get("id") for p in rows}
    parent = None
    floor_rank = -1
    new = []
    for depth, seg in enumerate(segs):
        hit = next((p for p in rows if (p.get("parent") or None) == parent
                    and (p.get("id") == seg or _key(p.get("name", "")) == _key(seg))), None)
        if hit is None:
            rank = max(depth, floor_rank + 1)
            if depth == len(segs) - 1 and _DESKLIKE.match(seg) and rank < _RANK["desk"]:
                rank = _RANK["desk"]
            if rank >= len(LEVELS):
                raise ValueError(f"{seg!r} would sit below a desk: {path!r}")
            level = LEVELS[rank]
            base = _slug(f"{parent}-{seg}" if parent else seg)
            pid, n = base, 2
            while pid in used:
                pid, n = f"{base}-{n}", n + 1
            hit = {"id": pid, "name": seg, "level": level}
            if parent:
                hit["parent"] = parent
            used.add(pid)
            rows.append(hit)
            made.append(hit)
            new.append(hit)
        parent = hit.get("id")
        floor_rank = _RANK.get(hit.get("level"), depth)
    return parent, new



def lineage(data, pid):
    by_id = {p.get("id"): p for p in _entries(data) if isinstance(p.get("id"), str)}
    out = []
    at = pid
    while isinstance(at, str) and at in by_id and at not in out and len(out) < 16:
        out.insert(0, at)
        parent = by_id[at].get("parent")
        at = parent if isinstance(parent, str) and parent != at else None
    return out


def where_each(data):
    rows = _entries(data)
    if not rows:
        return {}
    ids = {p.get("id") for p in rows if isinstance(p.get("id"), str)}
    named = {}
    for p in rows:
        k = _key(p.get("name", "")) if isinstance(p.get("name"), str) else ""
        if k:
            named[k] = None if k in named else p.get("id")

    def said(ref, text):
        if isinstance(ref, str) and ref in ids:
            return ref
        k = _key(text) if isinstance(text, str) else ""
        return named.get(k) if k else None

    nodes = [n for n in data.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)]
    racks = [r for r in data.get("racks") or [] if isinstance(r, dict) and r.get("id")]
    first = racks[0]["id"] if racks else ""
    known = {r["id"] for r in racks}
    rack_at = {r["id"]: said(r.get("premise"), r.get("location")) for r in racks}
    out, racked = {}, set()
    for section in ("rack", "rack_rear"):
        for slot in data.get(section) or []:
            if not isinstance(slot, dict) or not isinstance(slot.get("node"), str) or not slot["node"]:
                continue
            if slot["node"] in racked:
                continue
            racked.add(slot["node"])
            rid = slot.get("rack") if slot.get("rack") in known else first
            if rack_at.get(rid):
                out[slot["node"]] = rack_at[rid]
    vms = [v for v in data.get("vms") or [] if isinstance(v, dict) and isinstance(v.get("id"), str)]
    guests = {v["id"] for v in vms} | {n["id"] for n in nodes if n.get("kind") == "vm"}
    for n in nodes:
        if n["id"] in racked or n["id"] in guests:
            continue
        at = said(n.get("premise"), n.get("location"))
        if at:
            out[n["id"]] = at
    host_of = {v["id"]: v.get("host") for v in vms}
    for n in nodes:
        if n["id"] in guests and not host_of.get(n["id"]) and n.get("parent"):
            host_of[n["id"]] = n["parent"]
    for gid in guests:
        host, hops = host_of.get(gid), 0
        while host and host in guests and hops < 8:
            host, hops = host_of.get(host), hops + 1
        if host and host in out:
            out[gid] = out[host]
    return out
