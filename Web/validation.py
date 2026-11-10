"""Dataset validation — driven by the field catalogue in `schema.py`.

Shared by the Flask app, atlasctl, and the write path. Doctrine unchanged
since the hand-edited era: **warnings, not rejections**. A hand-edited dataset
should still render as much as possible, but every deviation must be visible
in the log and in `/api/status` so an edit never breaks the map silently.

`strict=True` flips that for one caller only — `store/dataset.py`, which
refuses a *write* that would introduce problems. A human editing JSON gets
warnings; a form submission gets a refusal, because there a refusal is
actionable and the map on disk stays good.

The rules themselves live in `schema.py`; this module only walks the dataset,
applies them, and adds the checks that span more than one entry (duplicate
ids, dangling references, addresses claimed twice).
"""

import ipaddress

import schema



def _label(section_key, entry, index):
    """How an entry is named in a problem line: `node 'app-host'` / `route #3`."""
    s = schema.get(section_key)
    noun = s["noun"] if s else section_key
    if isinstance(entry, dict):
        id_field = s["id_field"] if s else None
        if id_field and entry.get(id_field) is not None:
            return f"{noun} {entry[id_field]!r}"
        title_field = s["title_field"] if s else None
        if title_field and entry.get(title_field):
            return f"{noun} {entry[title_field]!r}"
    return f"{noun} #{index + 1}"


def _ids(data, section_key):
    """The set of identities in a section, for reference checking."""
    s = schema.get(section_key)
    if not s or not s["id_field"]:
        return set()
    # an id that is a list or an object is not an identity; the field check says so,
    # and this must not crash on it first (a set cannot hold one)
    return {e.get(s["id_field"]) for e in data.get(section_key, []) or []
            if isinstance(e, dict) and isinstance(e.get(s["id_field"]), (str, int, float, type(None)))}


def _check_refs(problems, label, section_key, entry, known):
    """Every dangling reference in one entry."""
    for path, target in schema.refs_of(section_key):
        if "." in path:                      # a reference inside a sub-object
            outer, inner = path.split(".", 1)
            for i, sub in enumerate(entry.get(outer) or []):
                if not isinstance(sub, dict):
                    continue
                for val in _as_list(sub.get(inner)):
                    if val and val not in known.get(target, set()):
                        problems.append(
                            f"{label}: {outer}[{i}] reaches unknown "
                            f"{target.rstrip('s')} {val!r}")
            continue
        for val in _as_list(entry.get(path)):
            if val and val not in known.get(target, set()):
                # "unknown zone 'x'" / "unknown host 'y'" — the field name reads
                # better than the target section in every case we have.
                problems.append(f"{label}: unknown {path} {val!r}")


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# Kinds whose address is a claim on the wire. A `network` place is often a
# *service* charted as its own marker (Traefik and Pangolin both answer on
# The edge's address), so sharing there is a modelling choice, not a conflict.
_ADDRESS_OWNING_KINDS = ("physical", "vm")


def _check_addressing(problems, data):
    """IPAM sanity: one address claimed by two real hosts.

    Two servers on one address is always a fault — a typo or a genuine
    conflict — and catching it is exactly what a map is for. Being *outside*
    every charted prefix is not reported: plenty of real hosts live on
    unmodelled segments. THE LEDGER surfaces those visually instead.
    """
    seen = {}
    for n in data.get("nodes", []) or []:
        if not isinstance(n, dict) or n.get("kind") not in _ADDRESS_OWNING_KINDS:
            continue
        ip = n.get("ip")
        if not isinstance(ip, str) or ip in schema.NONE_MARKS:
            continue
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue                      # already reported by the field check
        if addr in seen:
            problems.append(
                f"node {n.get('id')!r}: address {ip} is already claimed by "
                f"{seen[addr]!r}")
        else:
            seen[addr] = n.get("id")


def _check_prefix_ranges(problems, data):
    """A DHCP pool or reservation must actually sit inside its prefix."""
    for p in data.get("prefixes", []) or []:
        if not isinstance(p, dict):
            continue
        cidr = p.get("cidr")
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except (ValueError, TypeError):
            continue                      # already reported by the field check
        for i, r in enumerate(p.get("ranges") or []):
            if not isinstance(r, dict):
                continue
            for end in ("start", "end"):
                val = r.get(end)
                try:
                    addr = ipaddress.ip_address(val)
                except (ValueError, TypeError):
                    continue
                if addr not in net:
                    problems.append(
                        f"prefix {p.get('id')!r}: ranges[{i}] {end} {val} "
                        f"is outside {cidr}")
            try:
                if ipaddress.ip_address(r["start"]) > ipaddress.ip_address(r["end"]):
                    problems.append(
                        f"prefix {p.get('id')!r}: ranges[{i}] starts after it ends")
            except (KeyError, ValueError, TypeError):
                pass


def validate(data, strict=False):
    """Return a list of human-readable problems (empty = clean).

    Every catalogued section is walked: field types and required keys from
    `schema.check_entry`, then duplicate identities, then dangling references,
    then the cross-entry addressing checks.
    """
    problems = []
    if not isinstance(data, dict):
        return ["dataset must be an object"]

    known = {key: _ids(data, key) for key in schema.SECTIONS}

    for key in schema.SECTION_ORDER:
        s = schema.get(key)
        # Sections owned by another store are catalogued so the editor can
        # render them, but they are not part of the dataset and must not be
        # judged as if a missing one were a problem.
        if s is None or s["store"] != "dataset":
            continue

        if s["kind"] == "object":
            entry = data.get(key)
            if entry is None:
                continue
            if not isinstance(entry, dict):
                problems.append(f"{key}: must be an object")
                continue
            for problem in schema.check_entry(key, entry, strict=strict):
                problems.append(f"{key}: {problem}")
            continue

        entries = data.get(key)
        if entries is None:
            continue
        if not isinstance(entries, list):
            problems.append(f"{key}: must be a list")
            continue

        id_field = s["id_field"]
        seen_ids = set()
        for i, entry in enumerate(entries):
            label = _label(key, entry, i)
            entry_problems = schema.check_entry(key, entry, strict=strict)
            for problem in entry_problems:
                problems.append(f"{label}: {problem}")
            if not isinstance(entry, dict):
                continue
            if id_field:
                eid = entry.get(id_field)
                if eid is not None:
                    if eid in seen_ids:
                        problems.append(f"{label}: duplicate {id_field}")
                    seen_ids.add(eid)
            _check_refs(problems, label, key, entry, known)

    _check_addressing(problems, data)
    _check_prefix_ranges(problems, data)
    _check_regions(problems, data)
    _check_tripwire_sensors(problems, data)
    return problems


def _check_tripwire_sensors(problems, data):
    """TRIPWIRES: a trip is attributed by the name its tool reports
    (`sensor`, else the id). Two stones answering to one name means a trip
    could land on either — the same reason two stones may not share an id."""
    stones = data.get("stones")
    if not isinstance(stones, list):
        return
    claimed = {}
    for s in stones:
        if not isinstance(s, dict) or not isinstance(s.get("sensor"), str):
            continue
        key = s["sensor"].strip().lower()
        if not key:
            continue
        if key in claimed and claimed[key] != s.get("id"):
            problems.append(f"stone '{s.get('id')}': reported as {s['sensor']!r}, "
                            f"which stone '{claimed[key]}' already answers to")
        claimed.setdefault(key, s.get("id"))


def _check_regions(problems, data):
    """REGIONS (v1.49.0): a rectangle that fits its map, a parent chain that
    ends, and pinned places that name real places with real positions."""
    regions = data.get("regions")
    if not isinstance(regions, list):
        return
    by_id = {r.get("id"): r for r in regions if isinstance(r, dict)}
    node_ids = {n.get("id") for n in data.get("nodes") or [] if isinstance(n, dict)}
    for r in regions:
        if not isinstance(r, dict):
            continue
        label = f"region '{r.get('id')}'"
        try:
            x, y, w, h = (float(r.get(k)) for k in ("x", "y", "w", "h"))
        except (TypeError, ValueError):
            continue                      # check_entry already said so
        if w <= 0 or h <= 0:
            problems.append(f"{label}: width and height must be more than 0")
        elif x < 0 or y < 0 or x + w > 100.0001 or y + h > 100.0001:
            problems.append(f"{label}: the rectangle runs off its map "
                            f"({x:g}+{w:g} across, {y:g}+{h:g} down; both must stay within 100)")
        seen, cur = set(), r
        while cur and cur.get("parent"):
            if cur.get("id") in seen:
                problems.append(f"{label}: its `parent` chain loops back on itself")
                break
            seen.add(cur.get("id"))
            cur = by_id.get(cur.get("parent"))
        places = r.get("places")
        if places in (None, ""):
            continue
        if not isinstance(places, dict):
            problems.append(f"{label}: `places` must be an object of place-id → {{x, y}}")
            continue
        for pid, pos in places.items():
            if pid not in node_ids:
                problems.append(f"{label}: pins an unknown place '{pid}'")
            elif not (isinstance(pos, dict) and all(
                    isinstance(pos.get(k), (int, float)) and -50 <= pos.get(k) <= 150
                    for k in ("x", "y"))):
                problems.append(f"{label}: '{pid}' needs numeric x and y")

