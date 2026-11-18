"""TOPOLOGY's rules on the server (2026-11-17): the twin of the client's
`static/js/topology-model.js` for the questions the server asks of the wiring.

The dataset becomes a graph of things (places, then stubs) and links (cables,
then routes, then parent ties); the heads of the network come from the data;
everything hangs below a head by cable, then a guest by its host, then by
route, then by parent. The
same input gives the same answers as the client, case for case: both read
`tests/topology_cases.json`, and a change to a rule is made in both or in
neither.

    build_graph(data)         -> {"things", "links", "by_id", "link_by_id"}
    vlan_number(value)        -> a VLAN number or None
    vlan_label(link)          -> 'U10' | 'U1 T10,20' | 'T10,20' | ''
    heads(graph)              -> [thing id, ...]
    layers(graph)             -> {id: {"depth", "up", "head", "loose"}}, in thing order
    path_to_head(graph, id)   -> {"things": [id, ..., head], "links": [link ids, bottom first]}
    connections(graph)        -> [{"id", "name", "to", "toId", "port", "farPort",
                                   "vlan", "poe", "path"}]

A thing and a link are plain dicts with the client's field names (`aPort`,
`bPort`, `toId`, `farPort` kept as the client writes them, so a row here and a
row there compare as they are). Standard library only. Hand-edited data is
read leniently, as the client reads it: a missing section, a row that is not
an object, an id already seen, or a cable whose end is gone is skipped, never
raised on. Nothing here changes what it is given.

Where the two can differ: lower-casing (`str.lower` against `toLowerCase`) for
a handful of letters outside ASCII, and the sort of names with characters
beyond the Basic Multilingual Plane (code points here, UTF-16 units there).
"""

import math
import re

#: The stub kinds that count as network gear.
INFRA_STUBS = ("internet", "switch", "patch")
#: The order a thing prefers to hang by.
LAYERS = ("cable", "route", "parent")
#: What the drawing joins a path's names with.
PATH_JOIN = " › "

_NO_ADDRESS = frozenset(("", "—", "-", "–"))
_VLAN_TEXT = re.compile(r"^\s*[0-9]{1,4}\s*$")
_WATTS_TEXT = re.compile(r"^\s*[0-9]+(\.[0-9]+)?\s*$")


# ── reading hand-edited values ──────────────────────────────────────────────

def _is_obj(v):
    return isinstance(v, dict)


def _rows(v):
    return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []


def _ok_id(v):
    return isinstance(v, str) and v != ""


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _js_number_text(n):
    """A finite number as JavaScript's String() writes it, for the numbers a
    map holds: 4 and 4.0 are '4', 7.5 is '7.5'."""
    if isinstance(n, float) and n.is_integer() and abs(n) < 1e21:
        return str(int(n))
    return repr(n) if isinstance(n, float) else str(n)


def _words(v):
    if isinstance(v, str):
        return v.strip()
    if _is_number(v) and math.isfinite(v):
        return _js_number_text(v)
    return ""


def vlan_number(value):
    """A VLAN as a number: an integer 0 to 4095, or a string of digits that
    is one. Anything else (blank, the em dash placeholder, words) is None."""
    n = None
    if _is_number(value):
        n = value
    elif isinstance(value, str) and _VLAN_TEXT.match(value):
        n = int(value.strip())
    if n is None or not math.isfinite(n) or float(n) != int(n):
        return None
    n = int(n)
    return n if 0 <= n <= 4095 else None


def _tagged_list(value):
    """A tagged list read leniently: numbers only, each once, ascending."""
    if not isinstance(value, list):
        return []
    return sorted({n for n in map(vlan_number, value) if n is not None})


def _watts(value):
    """Watts as a positive number (a whole one as an int), or None."""
    n = None
    if _is_number(value):
        n = value
    elif isinstance(value, str) and _WATTS_TEXT.match(value):
        n = float(value)
    if n is None or not math.isfinite(n) or n <= 0:
        return None
    return int(n) if float(n).is_integer() else n


def _pair_key(a, b):
    return f"{a}\x00{b}" if a < b else f"{b}\x00{a}"


# ── the graph ───────────────────────────────────────────────────────────────

def build_graph(data):
    """The dataset as things and links, as the client's `buildGraph`.

    A thing is {id, type: 'place'|'stub', name, kind, sub, ip, zone, parent,
    planned, unmanaged, infra, order}; a link is {id, layer:
    'cable'|'route'|'parent', a, b, aPort, bPort, kind, state, vlan, tagged,
    poe, speed, source, note, lane, lanes, shadowed}. See topology-model.js
    for each field's rule."""
    d = data if _is_obj(data) else {}
    things, by_id = [], {}

    for n in _rows(d.get("nodes")):
        nid = n.get("id")
        if not _ok_id(nid) or nid in by_id:
            continue
        ip = _words(n.get("ip"))
        kind = _words(n.get("kind"))
        address = "" if ip in _NO_ADDRESS else ip
        t = {"id": nid, "type": "place", "name": _words(n.get("name")) or nid, "kind": kind,
             "sub": address, "ip": address,
             "zone": n.get("zone") if _ok_id(n.get("zone")) else None,
             "parent": n.get("parent") if _ok_id(n.get("parent")) else None,
             "planned": n.get("planned") is True, "unmanaged": n.get("unmanaged") is True,
             "infra": kind == "network", "order": len(things)}
        things.append(t)
        by_id[nid] = t
    for s in _rows(d.get("stubs")):
        sid = s.get("id")
        if not _ok_id(sid) or sid in by_id:
            continue
        kind = _words(s.get("kind"))
        t = {"id": sid, "type": "stub", "name": _words(s.get("name")) or sid, "kind": kind,
             "sub": kind, "ip": "", "zone": None, "parent": None, "planned": False,
             "unmanaged": False, "infra": kind in INFRA_STUBS, "order": len(things)}
        things.append(t)
        by_id[sid] = t
    # a parent is kept only when it is another place (it may be listed later)
    for t in things:
        p = t["parent"]
        if p is not None and (p == t["id"] or p not in by_id or by_id[p]["type"] != "place"):
            t["parent"] = None

    links, link_by_id = [], {}
    cabled, routed = set(), set()

    def add(link):
        links.append(link)
        link_by_id[link["id"]] = link

    def free_id(want, fallback):
        if _ok_id(want) and want not in link_by_id:
            return want
        lid, n = fallback, 2
        while lid in link_by_id:
            lid = f"{fallback}:{n}"
            n += 1
        return lid

    def end(c, side):
        place, stub = c.get(side), c.get(f"{side}_stub")
        if _ok_id(place) and place in by_id:
            return place
        if _ok_id(stub) and stub in by_id:
            return stub
        return None

    def bare(lid, layer, a, b, kind):
        return {"id": lid, "layer": layer, "a": a, "b": b, "aPort": "", "bPort": "",
                "kind": kind, "state": None, "vlan": None, "tagged": [], "poe": None,
                "speed": "", "source": "", "note": "", "lane": 0, "lanes": 1, "shadowed": False}

    for i, c in enumerate(_rows(d.get("cables"))):
        a, b = end(c, "a"), end(c, "b")
        if a is None or b is None or a == b:
            continue
        cabled.add(_pair_key(a, b))
        add({"id": free_id(c.get("id"), f"cable:{i}"), "layer": "cable", "a": a, "b": b,
             "aPort": _words(c.get("a_port")), "bPort": _words(c.get("b_port")),
             "kind": _words(c.get("kind")) or "copper",
             "state": "assumed" if c.get("state") == "assumed" else "confirmed",
             "vlan": vlan_number(c.get("vlan")), "tagged": _tagged_list(c.get("tagged")),
             "poe": _watts(c.get("poe_w")), "speed": _words(c.get("speed")),
             "source": _words(c.get("source")), "note": _words(c.get("note")),
             "lane": 0, "lanes": 1, "shadowed": False})
    for r in _rows(d.get("routes")):
        a, b = r.get("from"), r.get("to")
        if not _ok_id(a) or not _ok_id(b) or a == b or a not in by_id or b not in by_id:
            continue
        routed.add(_pair_key(a, b))
        link = bare(free_id(None, f"route:{a}:{b}"), "route", a, b, _words(r.get("kind")) or "vlan")
        link["shadowed"] = _pair_key(a, b) in cabled
        add(link)
    for t in things:
        if t["parent"] is None:
            continue
        key = _pair_key(t["parent"], t["id"])
        if key in cabled or key in routed:
            continue
        add(bare(free_id(None, f"parent:{t['id']}"), "parent", t["parent"], t["id"], "parent"))
    _set_lanes(links)
    return {"things": things, "links": links, "by_id": by_id, "link_by_id": link_by_id}


def _set_lanes(links):
    groups = {}
    for link in links:
        groups.setdefault(f"{link['layer']}\x00{_pair_key(link['a'], link['b'])}", []).append(link)
    for group in groups.values():
        for i, link in enumerate(group):
            link["lane"], link["lanes"] = i, len(group)


def _cached(graph, name, make):
    cache = graph.setdefault("_cache", {})
    if name not in cache:
        cache[name] = make()
    return cache[name]


def _adjacency(graph):
    """Each thing's links in link order, as (link, other, index)."""
    def make():
        adj = {t["id"]: [] for t in graph["things"]}
        for index, link in enumerate(graph["links"]):
            if link["a"] not in adj or link["b"] not in adj:
                continue
            adj[link["a"]].append((link, link["b"], index))
            adj[link["b"]].append((link, link["a"], index))
        return adj
    return _cached(graph, "adj", make)


def _degree(adj, tid):
    return len(adj.get(tid) or ())


# ── VLAN notation ───────────────────────────────────────────────────────────

def vlan_label(link):
    """A cable's VLANs in switch notation: `U10`, `U1 T10,20,99`, `T10,20`
    or ''. Takes a link or a raw cable."""
    if not _is_obj(link):
        return ""
    u = vlan_number(link.get("vlan"))
    t = _tagged_list(link.get("tagged"))
    parts = []
    if u is not None:
        parts.append(f"U{u}")
    if t:
        parts.append("T" + ",".join(str(n) for n in t))
    return " ".join(parts)


# ── heads ───────────────────────────────────────────────────────────────────

def heads(graph):
    """The things on the top row, at least one per connected piece, in thing
    order. A thing with no link is loose and never a head. Per piece, the
    first rule that applies: every internet stub in it; else the inside end
    of a wan route (the end with more links, the `from` end on a tie; of
    several, a network-kind one first, then the most links, then the first
    listed); else the network-kind place with the most links; else the thing
    with the most links. Ties go to the thing listed first."""
    return _cached(graph, "heads", lambda: _heads(graph))


def _heads(graph):
    adj = _adjacency(graph)
    things, by_id = graph["things"], graph["by_id"]
    root = {t["id"]: t["id"] for t in things}

    def find(tid):
        r = tid
        while root[r] != r:
            r = root[r]
        while root[tid] != r:
            nxt = root[tid]
            root[tid] = r
            tid = nxt
        return r

    for link in graph["links"]:
        if link["a"] not in root or link["b"] not in root:
            continue
        ra, rb = find(link["a"]), find(link["b"])
        if ra != rb:
            root[ra] = rb
    pieces = {}
    for t in things:
        if not _degree(adj, t["id"]):
            continue
        pieces.setdefault(find(t["id"]), []).append(t)
    wan_inside = {}
    for link in graph["links"]:
        if link["layer"] != "route" or link["kind"] != "wan" or link["a"] not in by_id:
            continue
        inside = link["a"] if _degree(adj, link["a"]) >= _degree(adj, link["b"]) else link["b"]
        wan_inside.setdefault(find(inside), set()).add(inside)

    def best(members, prefer_network):
        win = None
        for t in members:
            if win is None:
                win = t
                continue
            tn = prefer_network and t["type"] == "place" and t["kind"] == "network"
            wn = prefer_network and win["type"] == "place" and win["kind"] == "network"
            if tn != wn:
                if tn:
                    win = t
                continue
            dt, dw = _degree(adj, t["id"]), _degree(adj, win["id"])
            if dt > dw or (dt == dw and t["order"] < win["order"]):
                win = t
        return win

    out = []
    for r, members in pieces.items():
        lines = [t for t in members if t["type"] == "stub" and t["kind"] == "internet"]
        if lines:
            out.extend(lines)
            continue
        if r in wan_inside:
            out.append(best([t for t in members if t["id"] in wan_inside[r]], True))
            continue
        gear = [t for t in members if t["type"] == "place" and t["kind"] == "network"]
        out.append(best(gear or members, False))
    return [t["id"] for t in sorted(out, key=lambda t: t["order"])]


# ── layers ──────────────────────────────────────────────────────────────────

def layers(graph):
    """For each thing, in thing order: {depth, up, head, loose}. `up` is
    {id, link, layer} (what it hangs from, by which link, of which layer), or
    None for a head and a loose thing. A loose thing (nothing reaches it) is
    {depth: None, up: None, head: None, loose: True}.

    The walk: heads at depth 0; cables breadth first, a depth at a time, each
    depth's things in thing order and each thing's cables in link order, the
    first to reach a thing winning. When cables reach nothing more, a guest
    hangs from its host (2026-11-17): every place not yet reached whose
    `parent` is reached hangs from it, one hop, by whatever joins the two
    (the route between them, else the parent tie), and cables are walked
    again. When no host adds anything, a thing not yet reached with a route
    to a reached one hangs by that route, one hop (least depth of the
    reached end, then its thing order, then link order); a guest whose host
    is not reached yet waits and takes no route in this step. When that
    adds nothing either, the guests still waiting hang by their routes. The
    parent ties left are tried the same way only when no route adds
    anything. Until nothing is added."""
    return _cached(graph, "layers", lambda: _layers(graph))


def _layers(graph):
    adj = _adjacency(graph)
    by_id = graph["by_id"]
    info = {}
    since = {"host": [], "route": [], "wait": [], "parent": []}
    # each host's guests, in thing order: the places whose `parent` it is
    guests = {}
    for t in graph["things"]:
        if t["parent"] is not None and t["parent"] in by_id:
            guests.setdefault(t["parent"], []).append(t["id"])

    def order(tid):
        return by_id[tid]["order"]

    def reach(tid, entry):
        info[tid] = entry
        since["host"].append(tid)
        since["route"].append(tid)
        since["wait"].append(tid)
        since["parent"].append(tid)

    def flood(seeds):
        buckets = {}
        lo, hi = math.inf, -1
        for tid in seeds:
            d = info[tid]["depth"]
            buckets.setdefault(d, []).append(tid)
            lo, hi = min(lo, d), max(hi, d)
        d = lo
        while d <= hi:
            bucket = buckets.get(d)
            if bucket:
                bucket.sort(key=order)
                for tid in bucket:
                    head = info[tid]["head"]
                    for link, other, _ in adj[tid]:
                        if link["layer"] != "cable" or other in info:
                            continue
                        reach(other, {"depth": d + 1, "up": {"id": tid, "link": link["id"], "layer": "cable"},
                                      "head": head, "loose": False})
                        buckets.setdefault(d + 1, []).append(other)
                        hi = max(hi, d + 1)
            d += 1

    def waits(tid):
        """A guest whose host is not reached yet waits for it: no route
        takes it while its host may still be reached."""
        p = by_id[tid]["parent"]
        return p is not None and p in by_id and p not in info

    def attach(layer, sources, skip=None):
        candidates = set()
        for tid in sources:
            for link, other, _ in adj[tid]:
                if link["layer"] == layer and other not in info and not (skip and skip(other)):
                    candidates.add(other)
        chosen = []
        for tid in sorted(candidates, key=order):
            win = None
            for link, other, index in adj[tid]:
                if link["layer"] != layer or other not in info:
                    continue
                d, o = info[other]["depth"], order(other)
                if win is None or (d, o, index) < (win["d"], win["o"], win["index"]):
                    win = {"d": d, "o": o, "index": index, "other": other, "link": link}
            chosen.append((tid, win))
        for tid, win in chosen:
            reach(tid, {"depth": win["d"] + 1, "up": {"id": win["other"], "link": win["link"]["id"], "layer": layer},
                        "head": info[win["other"]]["head"], "loose": False})
        return [tid for tid, _ in chosen]

    def attach_host(sources):
        """A guest hangs from its host: each unreached guest of a thing in
        `sources`, by the first link (in link order) that joins the two and
        is no cable. A guest nothing joins to its host is left for the routes."""
        chosen = []
        for host in sources:
            for tid in guests.get(host, ()):
                if tid in info:
                    continue
                via = next((link for link, other, _ in adj[tid]
                            if other == host and link["layer"] != "cable"), None)
                if via is not None:
                    chosen.append((tid, host, via))
        chosen.sort(key=lambda c: order(c[0]))
        for tid, host, link in chosen:
            above = info[host]
            reach(tid, {"depth": above["depth"] + 1,
                        "up": {"id": host, "link": link["id"], "layer": link["layer"]},
                        "head": above["head"], "loose": False})
        return [tid for tid, _, _ in chosen]

    tops = heads(graph)
    for tid in tops:
        reach(tid, {"depth": 0, "up": None, "head": tid, "loose": False})
    flood(tops)
    while True:
        via_host, since["host"] = since["host"], []
        added = attach_host(via_host)
        if not added:
            via_route, since["route"] = since["route"], []
            added = attach("route", via_route, waits)
        if not added:
            # nothing else moves: the guests still waiting hang by their routes
            via_wait, since["wait"] = since["wait"], []
            added = attach("route", via_wait)
        if not added:
            via_parent, since["parent"] = since["parent"], []
            added = attach("parent", via_parent)
        if not added:
            break
        flood(added)

    return {t["id"]: info.get(t["id"]) or {"depth": None, "up": None, "head": None, "loose": True}
            for t in graph["things"]}


# ── questions asked of it ───────────────────────────────────────────────────

def path_to_head(graph, tid):
    """The chain from a thing up to its head: {things: [id, ..., head id],
    links: [link ids, bottom first]}. A head gives just itself; an unknown or
    loose thing gives two empty lists."""
    info = layers(graph)
    entry = info.get(tid) if isinstance(tid, str) else None
    if not entry or entry["loose"]:
        return {"things": [], "links": []}
    things, links = [tid], []
    at = entry
    while at["up"]:
        things.append(at["up"]["id"])
        links.append(at["up"]["link"])
        at = info[at["up"]["id"]]
    return {"things": things, "links": links}


def connections(graph):
    """The connections spreadsheet: one row per place, and per stub with a
    cable, as {id, name, to, toId, port, farPort, vlan, poe, path}. A row is
    filled only when the thing hangs by a cable (`to` the name of what it
    hangs from, `port` its own port, `farPort` the other end's, `vlan` the
    cable's `vlan_label`, `poe` its watts, `path` the names up to its head);
    otherwise each of those is '', never a guess from a route. Rows sort by
    name lower-cased, then id."""
    info = layers(graph)
    adj = _adjacency(graph)
    by_id, link_by_id = graph["by_id"], graph["link_by_id"]
    out = []
    for t in graph["things"]:
        if t["type"] == "group":
            continue
        if t["type"] == "stub" and not any(link["layer"] == "cable" for link, _, _ in adj[t["id"]]):
            continue
        row = {"id": t["id"], "name": t["name"], "to": "", "toId": "", "port": "", "farPort": "",
               "vlan": "", "poe": "", "path": ""}
        up = info[t["id"]]["up"]
        link = link_by_id.get(up["link"]) if up and up["layer"] == "cable" else None
        if link:
            mine = link["a"] == t["id"]
            row["to"] = by_id[up["id"]]["name"]
            row["toId"] = up["id"]
            row["port"] = link["aPort"] if mine else link["bPort"]
            row["farPort"] = link["bPort"] if mine else link["aPort"]
            row["vlan"] = vlan_label(link)
            row["poe"] = "" if link["poe"] is None else link["poe"]
            row["path"] = PATH_JOIN.join(by_id[i]["name"] for i in path_to_head(graph, t["id"])["things"])
        out.append(row)
    return sorted(out, key=lambda r: (r["name"].lower(), r["id"]))
