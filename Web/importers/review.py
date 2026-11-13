"""The review step — what a connected system knows, against what the map already has.

The SolarWinds Network Sonar shape: discovery, a results wizard, then import, with
an ignore list, and never a background sync. Each system's importer turns its answer
into plain CANDIDATES. `annotate` says which of them the map already has, and `plan`
turns the ones an admin ticked into ordinary dataset ops for `store.apply`, so an
import lands in the change log and can be undone like any edit.

Nothing here talks to a network or writes anything. The fetching is in
`connections.py`; the only writer is the store.

A candidate is a dict, built by `place`, `service`, `zone`, `port`, `route` or
`monitor`:

    key     "proxmox:qemu/101", stable across fetches. Ticks and the ignore list
            use it, and it is stamped on what it becomes as `origin`.
    type    place | service | zone | port | route | monitor
    group   the heading it is listed under
    name, ip, detail     what the review row shows
    parent  the key of its host: a guest's node, a stack's server, a port's switch,
            one end of a route
    peer    a route's other end

A service has nowhere to stand of its own: it becomes a row in its host's `links`,
so it needs a host that is on the map or ticked with it. So does a port (a row in
`interfaces`), and a route needs both its ends. A guest does not: it lands without
a `parent` when its host is not charted.

A monitor (Uptime Kuma) is a tie, not a thing: which place it lights. It is matched
to a place on the map by address or name, and lands in that place's `monitors`.
A place arriving from another system can bring its monitors with it (`watch`), so
one review charts a switch and wires its health in the same change.

What a remote system says is untrusted text. `clean` and `address` are why a
stranger's control characters or a hostname in an address field cannot reach the
dataset, and strict validation in the store is the backstop.
"""

import ipaddress
import re
from urllib.parse import urlsplit

import discovery
from layoutgrid import BAND_LABEL_X, BAND_STEP, BAND_TOP, Y_MAX

from .common import UNCHARTED_SLUG, UNCHARTED_ZONE, UNKNOWN_ZONE_FIELDS, slugify

#: Long enough for any real name, short enough that a hostile one cannot fill a card.
_MAX_TEXT = 120

NEW, CHARTED, CLASH, IGNORED = "new", "charted", "clash", "ignored"


def clean(text, limit=_MAX_TEXT):
    """Remote text as one printable line, or "" for anything that is not text."""
    if not isinstance(text, (str, int, float)) or isinstance(text, bool):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(text)).strip()[:limit]


def address(text):
    """The IP inside whatever a system calls an address, or "—".

    `tcp://10.0.0.5:2375`, `10.0.0.5:9001`, `https://10.0.0.5:8120`, `10.0.0.5/24`.
    A hostname is not an address the map can use, and a bad one in one row would
    otherwise fail the whole import at the validator.
    """
    raw = clean(text)
    if not raw:
        return "—"
    host = urlsplit(raw if "://" in raw else f"//{raw}").hostname or ""
    try:
        return str(ipaddress.ip_address(host or raw.split("/")[0]))
    except ValueError:
        return "—"


def _candidate(key, shape, group, name, **rest):
    return {"key": key, "type": shape, "group": group, "name": clean(name) or key,
            "ip": "—", "detail": "", "parent": None, **rest}


def place(key, group, name, kind, role, *, ip="—", hw="", parent=None, scroll=None, detail=None,
          also=(), mac=""):
    """`also` is every other address the thing answers at (a gateway has one per
    network). The map may know it by any of them; only `ip` is ever written."""
    row = _candidate(key, "place", group, name, kind=kind, role=clean(role), ip=ip, hw=clean(hw),
                     parent=parent, detail=clean(hw if detail is None else detail))
    if also:
        row["also"] = [a for a in also if _real_ip(a)]
    if mac:
        row["mac"] = clean(mac, 17)
    if isinstance(scroll, str) and scroll.strip():
        row["scroll"] = clean(scroll, 400)
    return row


def service(key, group, name, url, parent, about, detail=""):
    return _candidate(key, "service", group, name, url=url, parent=parent,
                      about=clean(about, 240), detail=clean(detail))


def zone(key, group, name, vlan, subnet, hue):
    return _candidate(key, "zone", group, name, vlan=vlan, subnet=clean(subnet) or "—", hue=hue,
                      detail=f"vlan {vlan}" + (f" · {clean(subnet)}" if subnet else ""))


def port(key, group, name, parent, *, kind="rj45", speed="", vlan=None, poe=False, detail="",
         peer=""):
    return _candidate(key, "port", group, name, parent=parent, kind=kind, speed=clean(speed),
                      vlan=vlan, poe=bool(poe), detail=clean(detail), peer=clean(peer))


#: What a fact may add: to a place, and to a port on it.
FACT_FIELDS = {"place": ("mac", "hw"), "port": ("peer", "speed")}


def fact(key, group, name, parent, adds, *, port=None):
    """What a system knows about something the map already has: a place's MAC, what
    is on the other end of a port. `parent` is the place's own row; `port` names
    the port on it when the fact is about one. A place the same review is adding
    carries these itself, so a fact only ever lands on the map as it stands."""
    on = "port" if port is not None else "place"
    adds = {k: clean(v) for k, v in (adds or {}).items() if k in FACT_FIELDS[on] and clean(v)}
    row = _candidate(key, "fact", group, name, parent=parent, adds=adds,
                     detail=" · ".join(f"{k} {v}" for k, v in adds.items()))
    if port is not None:
        row["port"] = clean(port)
    return row


def route(key, group, a, b, detail=""):
    """A link between two places in the same review, by their keys."""
    return _candidate(key, "route", group, detail or "link", parent=a, peer=b, detail=clean(detail))


def monitor(key, name, host, detail=""):
    return _candidate(key, "monitor", "Monitors", name, host=clean(host), ip=address(host),
                      detail=clean(detail, 240))


#: Rows that stand on another row, so they are read after the rows they stand on.
_DEPENDENT = ("service", "port", "route", "monitor", "fact")


def _real_ip(ip):
    return ip if isinstance(ip, str) and ip not in ("", "—") else None


def _names_of(name):
    """A name, and its first label: `nas.home.example` is the place called NAS."""
    full = slugify(name)
    return {full, slugify(str(name).split(".")[0])}


def _watches(host, name, by_ip, by_name):
    """What a monitor watches: the place at its address, else the place its host
    name or its own name is. Exact names only: a guessed tie lights the wrong
    marker, which is worse than lighting none."""
    ip = _real_ip(address(host))
    if ip:
        return by_ip.get(ip)
    for word in ([*_names_of(host)] if host else []) + [slugify(name)]:
        if word in by_name:
            return by_name[word]
    return None


def watch(candidates, monitors):
    """Give each place in `candidates` the Kuma monitors that watch it, so they
    land with it. `monitors` is `kuma.parse_metrics` output. Returns how many
    places gained one."""
    places = [c for c in candidates if c["type"] == "place"]
    by_ip = {c["ip"]: c for c in places if _real_ip(c["ip"])}
    by_name = {}
    for c in places:
        for word in _names_of(c["name"]):
            by_name.setdefault(word, c)
    for m in monitors:
        row = _watches(m.get("host"), m.get("name"), by_ip, by_name)
        if row is not None:
            row.setdefault("monitors", []).append(m["name"])
    watched = [row for row in places if row.get("monitors")]
    for row in watched:
        row["detail"] = clean(" · ".join(b for b in (row["detail"], f"Kuma: {', '.join(row['monitors'])}")
                                         if b), 240)
    return len(watched)


class _Map:
    """The dataset, indexed the three ways a candidate can already be on it."""

    def __init__(self, data):
        self.nodes = {n.get("id"): n for n in data.get("nodes", []) or []}
        self.zones = data.get("zones", []) or []
        self.routes = {frozenset((r.get("from"), r.get("to")))
                       for r in data.get("routes", []) or [] if isinstance(r, dict)}
        self.port_at = {}                      # (device, name) → (its index, the port)
        for index, i in enumerate(data.get("interfaces", []) or []):
            if isinstance(i, dict):
                self.port_at.setdefault((i.get("device"), str(i.get("name"))), (index, i))
        self.ports = set(self.port_at)
        # every monitor that already lights something, and what it lights
        self.tied = {}
        for n in self.nodes.values():
            for name in n.get("monitors") or []:
                self.tied.setdefault(name, n.get("id"))
            for link in n.get("links") or []:
                if link.get("kuma"):
                    self.tied.setdefault(link["kuma"], n.get("id"))
        for name, node_id in (((data.get("signals") or {}).get("kuma")) or {}).items():
            self.tied.setdefault(name, node_id)
        self.by_origin, self.by_ip, self.by_name, self.at_ip, self.by_mac = {}, {}, {}, {}, {}
        for n in self.nodes.values():
            if n.get("origin"):
                self.by_origin[n["origin"]] = n
            if isinstance(n.get("mac"), str) and n["mac"]:
                self.by_mac.setdefault(n["mac"].lower(), n)
            if _real_ip(n.get("ip")):
                self.by_ip[n["ip"]] = n
                self.at_ip.setdefault(n["ip"], []).append(n)
            for name in (n.get("id"), n.get("name")):
                if name:
                    self.by_name.setdefault(slugify(name), n)

    def find_place(self, row):
        """(status, node). The same name at a different address is a CLASH: two
        things or a move, and only a person can say which."""
        if row["key"] in self.by_origin:
            return CHARTED, self.by_origin[row["key"]]
        if row.get("mac") and row["mac"].lower() in self.by_mac:
            return CHARTED, self.by_mac[row["mac"].lower()]   # the same card, whatever its address now
        ip = _real_ip(row["ip"])
        held = ([ip] if ip else []) + list(row.get("also") or [])
        for addr in held:
            if addr in self.at_ip:
                return CHARTED, self._the_one_at(addr, row)
        for name in _names_of(row["name"]):
            node = self.by_name.get(name)
            if node is None:
                continue
            theirs = _real_ip(node.get("ip"))
            return (CLASH if ip and theirs and theirs not in held else CHARTED), node
        return NEW, None

    def _the_one_at(self, addr, row):
        """Several places can be drawn at one address: a machine, and the software
        on it that someone gave a marker of its own. A candidate from a system
        that lists machines is the one with its name, else the machine."""
        there = self.at_ip[addr]
        if len(there) == 1:
            return there[0]
        names = _names_of(row["name"])
        for node in there:
            if names & {slugify(node.get("id") or ""), slugify(node.get("name") or "")}:
                return node
        machines = [n for n in there if n.get("kind") in ("vm", "physical")]
        return machines[0] if machines else self.by_ip[addr]

    def find_zone(self, row):
        """By what it was imported as, then by VLAN, then by name. The number is
        what a network is; the name is what someone called it, and two systems
        can disagree about that."""
        vlan = row.get("vlan")
        tests = (lambda z: bool(z.get("origin")) and row["key"] == z.get("origin"),
                 lambda z: vlan not in (None, "") and z.get("vlan") not in (None, "")
                 and str(vlan) == str(z.get("vlan")),
                 lambda z: slugify(row["name"]) in (z.get("id"), slugify(z.get("name") or "")))
        for test in tests:
            for z in self.zones:
                if test(z):
                    return z
        return None

    def watched_by(self, row):
        return _watches(row.get("host"), row["name"], self.by_ip, self.by_name)

    def has_service(self, node, row):
        """A link of the same name or address. The address is what a re-import
        matches on: the name may have been edited since."""
        return any(str(link.get("label", "")).lower() == row["name"].lower()
                   or link.get("url") == row["url"] for link in node.get("links") or [])


def annotate(candidates, data, ignored=()):
    """Every candidate as a review row: its `status`, and what it `matched` on the map.

    `zone` says where a place would land, or "" when its address names no realm.
    `blocked` is a service with no host to stand on, and `note` is the reason.
    """
    chart = _Map(data)
    ignored = set(ignored)
    rows, by_key = [], {}
    # hosts first, so a service can read its host's row whatever the listing order
    for row in sorted(candidates, key=lambda c: c["type"] in _DEPENDENT):
        row = {**row, "matched": "", "zone": "", "note": "", "blocked": False}
        by_key[row["key"]] = row
        if row["type"] == "zone":
            found = chart.find_zone(row)
            row["status"], row["matched"] = (CHARTED, found.get("id")) if found else (NEW, "")
            if found and slugify(row["name"]) not in (found.get("id"), slugify(found.get("name") or "")):
                row["note"] = f"The map calls this realm {found.get('name') or found.get('id')}."
        elif row["type"] == "place":
            row["status"], node = chart.find_place(row)
            row["matched"] = node.get("id") if node else ""
            if row["status"] == CLASH:
                row["note"] = f"The map has {node.get('name')} at {node.get('ip')}."
            elif row["status"] == NEW:
                row["zone"] = discovery.zone_for_ip(data, row["ip"]) or ""
        elif row["type"] == "service":
            _annotate_service(row, by_key.get(row["parent"]), chart)
        elif row["type"] == "port":
            _annotate_port(row, by_key.get(row["parent"]), chart)
        elif row["type"] == "route":
            _annotate_route(row, by_key.get(row["parent"]), by_key.get(row["peer"]), chart)
        elif row["type"] == "fact":
            if not _annotate_fact(row, by_key.get(row["parent"]), chart):
                continue                       # its place is not on the map: the place brings it
        else:
            _annotate_monitor(row, chart)
        if row["key"] in ignored and row["status"] != CHARTED:
            row["status"] = IGNORED
        rows.append(row)
    return rows


def _annotate_service(row, host, chart):
    row["status"] = NEW
    if host is None:
        row.update(blocked=True, note="This Atlas cannot tell which host it runs on.")
    elif host["status"] == IGNORED:
        row.update(blocked=True, note=f"Its host, {host['name']}, is ignored.")
    elif host["status"] == CHARTED and chart.has_service(chart.nodes[host["matched"]], row):
        row.update(status=CHARTED, matched=host["matched"])


def _stands_on(row, host, what):
    """The blocking half every dependent row shares: True when `host` can carry it."""
    if host is None:
        row.update(blocked=True, note=f"This Atlas cannot tell which {what} it is on.")
    elif host["status"] == IGNORED:
        row.update(blocked=True, note=f"{host['name']} is ignored.")
    else:
        return True
    return False


def _annotate_port(row, host, chart):
    row["status"] = NEW
    if _stands_on(row, host, "device") and host["status"] == CHARTED \
            and (host["matched"], row["name"]) in chart.ports:
        row.update(status=CHARTED, matched=host["matched"])


def _annotate_route(row, a, b, chart):
    row["status"] = NEW
    if not (_stands_on(row, a, "place") and _stands_on(row, b, "place")):
        return
    row["name"] = clean(f"{a['name']} ↔ {b['name']}")
    if a["status"] == CHARTED and b["status"] == CHARTED:
        if a["matched"] == b["matched"]:
            row.update(blocked=True, note="Both ends are the same place on the map.")
        elif frozenset((a["matched"], b["matched"])) in chart.routes:
            row.update(status=CHARTED, matched=f"{a['matched']} ↔ {b['matched']}")


def _annotate_fact(row, host, chart):
    """NEW while the map lacks any of it, CHARTED once it holds all of it. A fact
    never overwrites what a person wrote: `hw` is offered only for a place this
    system imported, and a port's words only where the map has none."""
    row["status"] = NEW
    if host is None or host["status"] != CHARTED:
        return False
    node = chart.nodes[host["matched"]]
    if "port" in row:
        found = chart.port_at.get((host["matched"], row["port"]))
        if found is None:
            return False                       # the port row carries the same words
        have = found[1]
        missing = {k: v for k, v in row["adds"].items() if not have.get(k)}
    else:
        have, ours = node, node.get("origin") == host["key"]
        missing = {k: v for k, v in row["adds"].items()
                   if have.get(k) != v and (k != "hw" or ours) and (k == "hw" or not have.get(k))}
    row["adds"] = missing
    row["detail"] = " · ".join(f"{k} {v}" for k, v in missing.items())
    if not missing:
        row.update(status=CHARTED, matched=host["matched"])
    return True


def _annotate_monitor(row, chart):
    row["status"] = NEW
    if row["name"] in chart.tied:
        row.update(status=CHARTED, matched=chart.tied[row["name"]])
        return
    node = chart.watched_by(row)
    if node is None:
        row.update(blocked=True, note=f"No place on the map answers to {row.get('host') or 'its address'}.")
    else:
        row.update(place=node.get("id"), note=f"watches {node.get('name') or node.get('id')}")


def plan(rows, picks, data, *, label, fallback=""):
    """The ops that put the ticked rows on the map. Raises PlanError, writing nothing.

    `rows` is `annotate`'s output from a fetch made just now, so what lands is what
    the system says at this moment, not what a browser sends back.
    `fallback` is the realm for a place whose address names none; blank is the
    Uncharted realm, which is created if the map has not got it.
    """
    by_key = {r["key"]: r for r in rows}
    problems = []
    for key in picks:
        row = by_key.get(key)
        if row is None:
            problems.append(f"{key} is no longer there. Review it again.")
        elif row["status"] not in (NEW, CLASH) or row["blocked"]:
            problems.append(f"{row['name']} cannot be added: it is {row['status']}.")
    if problems:
        raise PlanError(problems)
    chosen = [by_key[k] for k in dict.fromkeys(picks)]

    zones = [r for r in chosen if r["type"] == "zone"]
    places = [r for r in chosen if r["type"] == "place"]
    services = [r for r in chosen if r["type"] == "service"]
    ports = [r for r in chosen if r["type"] == "port"]
    routes = [r for r in chosen if r["type"] == "route"]
    monitors = [r for r in chosen if r["type"] == "monitor"]
    facts = [r for r in chosen if r["type"] == "fact"]
    chart = _Map(data)
    for row in services + ports + routes:
        for end in (row["parent"], row.get("peer")):
            host = by_key.get(end)
            if host is not None and host["status"] != CHARTED and host not in places:
                problems.append(f"{row['name']} needs {host['name']} on the map, or ticked with it.")
    if problems:
        raise PlanError(problems)

    ops, scratch = [], {**data, "zones": list(data.get("zones", []) or [])}
    for row in zones:
        body = _zone_body(row, scratch)
        scratch["zones"].append(body)
        ops.append({"op": "insert", "section": "zones", "body": body})

    drafts, ids = _drafts(places, by_key, scratch, label, fallback)
    realms = {z.get("id") for z in scratch["zones"]}
    if UNCHARTED_SLUG not in realms and any(d["zone"] == UNCHARTED_SLUG for d in drafts):
        body = {"id": UNCHARTED_SLUG, **UNCHARTED_ZONE, **UNKNOWN_ZONE_FIELDS}
        scratch["zones"].append(body)
        ops.append({"op": "insert", "section": "zones", "body": body})
    drafts = discovery.place_drafts(scratch, drafts)

    added, edits = {d["id"]: d for d in drafts}, {}
    on_map = {n.get("id"): n for n in data.get("nodes", []) or []}

    def at(key):
        """The node a row's host is or becomes."""
        return ids.get(key) or by_key[key]["matched"]

    def append(target, field, item):
        """Add to a list on a place, whether it lands in this import or is on the map."""
        if target in added:
            added[target].setdefault(field, []).append(item)
        else:
            body = edits.setdefault(target, {})
            body.setdefault(field, list(on_map[target].get(field) or [])).append(item)

    for row in services:
        append(at(row["parent"]), "links",
               {"label": row["name"], "url": row["url"], "desc": row["about"], "open_in": "tab"})
    for row in monitors:
        append(row["place"], "monitors", row["name"])
    port_edits = []
    for row in facts:
        target = by_key[row["parent"]]["matched"]
        if "port" in row:
            index = chart.port_at[(target, row["port"])][0]
            port_edits.append({"op": "upsert", "section": "interfaces", "index": index,
                               "body": dict(row["adds"])})
        else:
            edits.setdefault(target, {}).update(row["adds"])

    ops += [{"op": "insert", "section": "nodes", "body": d} for d in drafts]
    ops += [{"op": "upsert", "section": "nodes", "id": node, "body": body}
            for node, body in edits.items()]
    ops += port_edits                           # by position, so before any port is added
    for row in ports:
        body = {"device": at(row["parent"]), "name": row["name"], "kind": row["kind"],
                "note": f"from {label}"}
        body.update({k: row[k] for k in ("speed", "vlan", "peer") if row.get(k) not in (None, "")})
        if row.get("poe"):
            body["poe"] = True
        ops.append({"op": "insert", "section": "interfaces", "body": body})
    for row in routes:
        ops.append({"op": "insert", "section": "routes",
                    "body": {"from": at(row["parent"]), "to": at(row["peer"]), "kind": "vlan"}})
    if not ops:
        raise PlanError(["Nothing was ticked."])
    return ops


class PlanError(Exception):
    """The ticks cannot be honoured. `problems` says why, in plain sentences."""

    def __init__(self, problems):
        super().__init__(problems[0])
        self.problems = problems


def _zone_body(row, scratch):
    slug = slugify(row["name"])
    if slug in {z.get("id") for z in scratch["zones"]}:
        slug = f"vlan-{row['vlan']}"
    return {"id": slug, "name": row["name"], "vlan": row["vlan"], "subnet": row["subnet"],
            "hue": row["hue"], "lore": "Newly surveyed ground.", "origin": row["key"],
            "label_x": BAND_LABEL_X,
            "label_y": min(BAND_TOP + BAND_STEP * len(scratch["zones"]), Y_MAX)}


def _drafts(places, by_key, scratch, label, fallback):
    """Each ticked place as a node, through `discovery.as_node` like a survey row or
    a CSV line. Ids come first, so a guest ticked with its host can name it."""
    taken = {n.get("id") for n in scratch.get("nodes", []) or []}
    drafts, ids = [], {}
    for row in places:
        node = discovery.as_node({"ip": _real_ip(row["ip"]), "hostname": row["name"]}, scratch, taken)
        taken.add(node["id"])
        ids[row["key"]] = node["id"]
        node.update({
            "name": row["name"].upper(), "kind": row["kind"], "origin": row["key"],
            "role": row["role"] or f"imported from {label} · not yet described",
            "lore": "Newly charted, its story not yet written.",
            "ip": row["ip"], "hw": row["hw"],
            "zone": discovery.zone_for_ip(scratch, row["ip"]) or fallback or UNCHARTED_SLUG,
        })
        if row.get("scroll"):
            node["scroll"] = row["scroll"]
        if row.get("mac"):
            node["mac"] = row["mac"]
        if row.get("monitors"):
            node["monitors"] = list(row["monitors"])
        drafts.append(node)
    for row, node in zip(places, drafts):
        host = by_key.get(row["parent"])
        if host is not None:
            parent = ids.get(host["key"]) or (host["matched"] if host["status"] == CHARTED else "")
            if parent:
                node["parent"] = parent
    return drafts, ids
