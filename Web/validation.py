import ipaddress

import schema



def _label(section_key, entry, index):
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


label_of = _label


def _ids(data, section_key):
    s = schema.get(section_key)
    if not s or not s["id_field"]:
        return set()
    entries = data.get(section_key)
    entries = entries if isinstance(entries, list) else []
    return {e.get(s["id_field"]) for e in entries
            if isinstance(e, dict) and isinstance(e.get(s["id_field"]), (str, int, float, type(None)))}


def _check_refs(problems, label, section_key, entry, known):
    for path, inner, target, _ in schema.ref_fields(section_key):
        if inner is not None:
            subs = entry.get(path)
            for i, sub in enumerate(subs if isinstance(subs, list) else []):
                if not isinstance(sub, dict):
                    continue
                for val in schema.as_list(sub.get(inner)):
                    if isinstance(val, (list, dict)):
                        continue
                    if val and val not in known.get(target, set()):
                        problems.append(
                            f"{label}: {path}[{i}] reaches unknown "
                            f"{target.rstrip('s')} {val!r}")
            continue
        for val in schema.as_list(entry.get(path)):
            if isinstance(val, (list, dict)):
                continue
            if val and val not in known.get(target, set()):
                problems.append(f"{label}: unknown {path} {val!r}")


_ADDRESS_OWNING_KINDS = ("physical", "vm")


def _check_addressing(problems, data):
    seen = {}
    nodes = data.get("nodes")
    for n in nodes if isinstance(nodes, list) else []:
        if not isinstance(n, dict) or n.get("kind") not in _ADDRESS_OWNING_KINDS:
            continue
        ip = n.get("ip")
        if not isinstance(ip, str) or ip in schema.NONE_MARKS:
            continue
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr in seen:
            problems.append(
                f"node {n.get('id')!r}: address {ip} is already claimed by "
                f"{seen[addr]!r}")
        else:
            seen[addr] = n.get("id")


def _check_prefix_ranges(problems, data):
    for p in data.get("prefixes", []) or []:
        if not isinstance(p, dict):
            continue
        cidr = p.get("cidr")
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except (ValueError, TypeError):
            continue
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
    problems = []
    if isinstance(data, dict) and any(k in data for k in schema.RENAMED_SECTIONS):
        data = schema.upgrade(dict(data))
    if not isinstance(data, dict):
        return ["dataset must be an object"]

    known = {key: _ids(data, key) for key in schema.SECTIONS}

    for key in schema.SECTION_ORDER:
        s = schema.get(key)
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
    import names
    problems.extend(names.problems(data))
    return problems


def _end(cable, side):
    place, stub = cable.get(side), cable.get(side + "_stub")
    place = place if place not in (None, "") else None
    stub = stub if stub not in (None, "") else None
    if (place is None) == (stub is None):
        return None
    return ("place", place) if place is not None else ("stub", stub)


def _port(cable, side):
    port = cable.get(side + "_port")
    return port.strip().casefold() if isinstance(port, str) else ""


def _check_cables(problems, data, strict):
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
                continue
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
    import watch
    from engines.checks import _check_url
    kind = spec["type"]
    asked = _check_url(url) if url else None
    if kind in ("http", "keyword", "json"):
        target = _check_url(spec["host"]) or asked
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
            continue
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

