"""Dataset validation — driven by the field catalogue in `schema.py`.

Shared by the Flask app, atlasctl, and the write path. Doctrine unchanged
since the hand-edited era: **warnings, not rejections**. A hand-edited dataset
should still render as much as possible, but every deviation must be visible
in the log and in `/api/status` so an edit never breaks the map silently.

`strict=True` flips that for one caller only — `dataset.py`, which
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


#: How the write path finds the problems of the entries a save touched.
label_of = _label


def _ids(data, section_key):
    """The set of identities in a section, for reference checking."""
    s = schema.get(section_key)
    if not s or not s["id_field"]:
        return set()
    # an id that is a list or an object is not an identity; the field check says so,
    # and this must not crash on it first (a set cannot hold one)
    entries = data.get(section_key)
    # a list section written as a number or an object is none here (round 13);
    # the field checks name the problem
    entries = entries if isinstance(entries, list) else []
    return {e.get(s["id_field"]) for e in entries
            if isinstance(e, dict) and isinstance(e.get(s["id_field"]), (str, int, float, type(None)))}


def _check_refs(problems, label, section_key, entry, known):
    """Every dangling reference in one entry."""
    for path, inner, target, _ in schema.ref_fields(section_key):
        if inner is not None:                # a reference inside a sub-object
            subs = entry.get(path)
            for i, sub in enumerate(subs if isinstance(subs, list) else []):   # links: 5 (round 14)
                if not isinstance(sub, dict):
                    continue
                for val in schema.as_list(sub.get(inner)):
                    if isinstance(val, (list, dict)):
                        continue             # not an id: the field check says so
                    if val and val not in known.get(target, set()):
                        problems.append(
                            f"{label}: {path}[{i}] reaches unknown "
                            f"{target.rstrip('s')} {val!r}")
            continue
        for val in schema.as_list(entry.get(path)):
            if isinstance(val, (list, dict)):
                continue                     # not an id: the field check says so
            if val and val not in known.get(target, set()):
                # "unknown zone 'x'" / "unknown host 'y'" — the field name reads
                # better than the target section in every case we have.
                problems.append(f"{label}: unknown {path} {val!r}")


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
    nodes = data.get("nodes")
    for n in nodes if isinstance(nodes, list) else []:   # nodes: 5 (round 14)
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
    if isinstance(data, dict) and any(k in data for k in schema.RENAMED_SECTIONS):
        # an import or a hand-made file may still use an old section name: check
        # it as it will be stored, without touching the caller's dict
        data = schema.upgrade(dict(data))
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
                # a list or object id cannot be held in a set: the field check
                # names it, and this must not raise first (round 15)
                if eid is not None and isinstance(eid, (str, int, float)):
                    if eid in seen_ids:
                        problems.append(f"{label}: duplicate {id_field}")
                    seen_ids.add(eid)
            _check_refs(problems, label, key, entry, known)

    _check_addressing(problems, data)
    _check_prefix_ranges(problems, data)
    _check_regions(problems, data)
    _check_tripwire_sensors(problems, data)
    _check_watch(problems, data)
    _check_cables(problems, data, strict)
    return problems


def _end(cable, side):
    """(kind, id) for one end of a cable: ("place", id), ("stub", id), or None
    when the end names neither or both (the caller says which)."""
    place, stub = cable.get(side), cable.get(side + "_stub")
    place = place if place not in (None, "") else None
    stub = stub if stub not in (None, "") else None
    if (place is None) == (stub is None):
        return None
    return ("place", place) if place is not None else ("stub", stub)


def _port(cable, side):
    """The port name at one end, trimmed and in one case, or "" for none."""
    port = cable.get(side + "_port")
    return port.strip().casefold() if isinstance(port, str) else ""


def _check_cables(problems, data, strict):
    """CABLES (2026-11-16). That each end names one thing (whether it exists
    is the reference check's), that no cable runs from a port to itself, that
    the VLANs are VLANs, and that a stub is not also a place.

    A port two cables use is said only on the READ path (`strict` false), as
    a warning: a person moving a cable from one port to another may save the
    new one first, and the write must not refuse that. Like every read-path
    problem it is logged and counted on `/api/status`. A port that names no
    interface of its place is not a problem: a cable may be charted before
    the ports are."""
    cables = data.get("cables")
    used = {}
    for i, c in enumerate(cables if isinstance(cables, list) else []):
        if not isinstance(c, dict):
            continue
        label = _label("cables", c, i)
        ends = {}
        for side in ("a", "b"):
            place, stub = c.get(side), c.get(side + "_stub")
            if place not in (None, "") and stub not in (None, ""):
                problems.append(f"{label}: end {side.upper()} names both a place and a stub; "
                                "an end is one or the other")
            elif place in (None, "") and stub in (None, ""):
                problems.append(f"{label}: end {side.upper()} names no place and no stub")
            ends[side] = _end(c, side)
        a, b = ends["a"], ends["b"]
        if a is not None and a == b and _port(c, "a") == _port(c, "b"):
            problems.append(f"{label}: runs from {a[0]} {a[1]!r} to itself, "
                            "port to the same port")
        vlan = c.get("vlan")
        untagged = None
        if vlan is not None and not (isinstance(vlan, str) and vlan.strip() in schema.NONE_MARKS):
            untagged = schema.vlan_number(vlan)
            if untagged is None:
                problems.append(f"{label}: vlan {vlan!r} is not a VLAN number "
                                f"({schema.VLAN_MIN} to {schema.VLAN_MAX})")
        tagged = c.get("tagged")
        if tagged is not None and tagged != "":
            if not isinstance(tagged, list):
                problems.append(f"{label}: tagged must be a list of VLAN numbers, e.g. [10, 20]")
            else:
                seen = set()
                for v in tagged:
                    n = schema.vlan_number(v)
                    if n is None:
                        problems.append(f"{label}: tagged VLAN {v!r} is not a VLAN number "
                                        f"({schema.VLAN_MIN} to {schema.VLAN_MAX})")
                    elif n in seen:
                        problems.append(f"{label}: tagged lists VLAN {n} twice")
                    elif n == untagged:
                        problems.append(f"{label}: tagged repeats the untagged VLAN {n}")
                    seen.add(n)
        if strict:
            continue
        for side in ("a", "b"):
            end, port = ends[side], _port(c, side)
            if end is None or not port:
                continue
            try:
                key = (end, port)
                hash(key)
            except TypeError:
                continue                     # not an id: the field check says so
            if key in used and used[key] != label:
                problems.append(f"{label}: port {c.get(side + '_port')!r} of {end[0]} "
                                f"{end[1]!r} is also used by {used[key]} (a warning: "
                                "one of the two is likely mid-move)")
            used.setdefault(key, label)

    stubs = data.get("stubs")
    places = _ids(data, "nodes")
    for i, s in enumerate(stubs if isinstance(stubs, list) else []):
        if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"] in places:
            problems.append(f"{_label('stubs', s, i)}: id {s['id']!r} is also a place's id; "
                            "a cable's end would read as either")


def _check_watch(problems, data):
    """THE WATCH (2026-11-15): a check the map asks for has what it needs to
    be asked, and asks nothing it must not. A service with no address must be
    one a tcp or dns check can reach."""
    import watch
    nodes = data.get("nodes")
    for i, node in enumerate(nodes if isinstance(nodes, list) else []):
        if not isinstance(node, dict):
            continue
        label = _label("nodes", node, i)
        ip = watch._address(node.get("ip"))
        own = watch.spec_of(node)
        if own["type"] in watch.TYPES:
            why = _check_problem(own, "", ip)
            if why:
                problems.append(f"{label}: its check {why}")
        links = node.get("links")
        for j, link in enumerate(links if isinstance(links, list) else []):
            if not isinstance(link, dict):
                continue
            name = link.get("label") if isinstance(link.get("label"), str) else f"#{j + 1}"
            spec = watch.spec_of(link)
            url = link.get("url")
            if url in (None, ""):
                if spec["type"] not in ("tcp", "dns"):
                    problems.append(f"{label}: service {name!r} needs a url, or a tcp or dns check")
                    continue
            if spec["type"] in watch.TYPES and not link.get("kuma"):
                why = _check_problem(spec, url if isinstance(url, str) else "", ip)
                if why:
                    problems.append(f"{label}: service {name!r}: its check {why}")


def _check_problem(spec, url, ip):
    """Why a check could not be asked as charted, or None."""
    import signals
    import watch
    kind = spec["type"]
    asked = signals._check_url(url) if url else None
    if kind in ("http", "keyword", "json"):
        target = signals._check_url(spec["host"]) or asked
        if not target:
            return "needs an http(s) address (the service's own, or as its check address)"
        if watch.refused_host(watch._parts(target)[0]) or watch.refused_host(spec["host"]):
            return "may not ask a link-local or metadata address"
        if kind == "keyword" and not spec["expect"]:
            return "needs the text it expects"
        if kind == "json" and "=" not in spec["expect"]:
            return "needs what it expects as path=value"
        return None
    host = spec["host"]
    if host.lower().startswith(("http://", "https://")):
        host = watch._parts(host)[0]
    url_host, url_port = watch._parts(asked) if asked else ("", 0)
    host = host or url_host or (ip if kind == "tcp" else "")
    if not host:
        return "needs an address or a name to ask"
    if watch.refused_host(host):
        return "may not ask a link-local or metadata address"
    if kind == "tcp" and not (spec["port"] or url_port):
        return "needs a port"
    return None


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
        while cur and isinstance(cur.get("parent"), str) and cur["parent"]:
            if cur.get("id") in seen:
                problems.append(f"{label}: its `parent` chain loops back on itself")
                break
            seen.add(cur.get("id"))
            cur = by_id.get(cur["parent"])
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

