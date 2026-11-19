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

A cable (2026-11-17) is a physical connection a system reports, port to port.
It is offered only when both its ends are places already on the map, and it is
matched to the map's cables by its ends and ports, never by id. A cable a person
drew (or another system wrote) is never changed: where the system reads it
otherwise, the row says so in words and cannot be ticked. A cable this same
system wrote before may be offered as an update. See `_annotate_cables`.

What a remote system says is untrusted text. `clean` and `address` are why a
stranger's control characters or a hostname in an address field cannot reach the
dataset, and strict validation in the store is the backstop.
"""

import ipaddress
import re
from urllib.parse import urlsplit

import discovery
import schema
import topology
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


#: A cable's fields a system may state, besides its ends, in the dataset's names.
CABLE_FIELDS = ("kind", "vlan", "tagged", "poe_w", "speed", "state")
#: Where the cables a system reads otherwise than the map are listed.
DIFFERS_GROUP = "Cables the map has otherwise"


def cable(key, group, a, b, *, source, by, a_port="", b_port="", kind="copper", speed="",
          poe_w=None, vlan=None, tagged=None, name=""):
    """A cable between two things in the same review, by their keys, as the
    system states it. `source` is what the dataset's `source` will say (the
    system's key, `unifi`); `by` is how the review's words name the system
    (`UniFi`). Only what is given is written: no speed, no PoE, no VLAN unless
    the system said so. `state` is always `confirmed`: the system saw it."""
    fields = {"kind": kind, "state": "confirmed"}
    if clean(speed):
        fields["speed"] = clean(speed)
    if isinstance(poe_w, (int, float)) and not isinstance(poe_w, bool) and poe_w > 0:
        fields["poe_w"] = poe_w
    if schema.vlan_number(vlan) is not None:
        fields["vlan"] = schema.vlan_number(vlan)
    tagged = [v for v in (schema.vlan_number(t) for t in tagged or ()) if v is not None]
    if tagged:
        fields["tagged"] = sorted(set(tagged) - {fields.get("vlan")})
    bits = [kind, fields.get("speed", ""), topology.vlan_label(fields),
            f"PoE {fields['poe_w']:g} W" if "poe_w" in fields else ""]
    return _candidate(key, "cable", group, name or "cable", parent=a, peer=b,
                      a_port=clean(a_port, 40), b_port=clean(b_port, 40), cable=fields,
                      source=clean(source, 40), by=clean(by, 40),
                      detail=" · ".join(b for b in bits if b))


#: Rows that stand on another row, so they are read after the rows they stand on.
_DEPENDENT = ("service", "port", "route", "monitor", "fact", "cable")


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
        # the wiring, as it stands: cables by position, stubs by id
        self.cables = [c for c in data.get("cables") or [] if isinstance(c, dict)] \
            if isinstance(data.get("cables"), list) else []
        self.stubs = {s.get("id"): s for s in data.get("stubs") or []
                      if isinstance(s, dict) and isinstance(s.get("id"), str)} \
            if isinstance(data.get("stubs"), list) else {}
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
            if isinstance(n.get("mac"), str) and schema.mac_key(n["mac"]):
                self.by_mac.setdefault(schema.mac_key(n["mac"]), n)
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
        mac = schema.mac_key(row.get("mac"))
        if mac and mac in self.by_mac:
            return CHARTED, self.by_mac[mac]   # the same card, whatever its address now
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
    rows, by_key, cables = [], {}, []
    # hosts first, so a service can read its host's row whatever the listing order
    for row in sorted(candidates, key=lambda c: c["type"] in _DEPENDENT):
        row = {**row, "matched": "", "zone": "", "note": "", "blocked": False}
        by_key[row["key"]] = row
        if row["type"] == "cable":
            cables.append(row)                 # read together, once every place is placed
            continue
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
    for row in _annotate_cables(cables, by_key, chart):
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


# ── cables (2026-11-17) ──────────────────────────────────────────────────────

def _port_word(port):
    """A port as the dataset names it, or "" for none."""
    if isinstance(port, bool) or not isinstance(port, (str, int)):
        return ""
    return str(port).strip()


def _same_port(x, y):
    return x.casefold() == y.casefold()


def _map_ends(c):
    """A map cable's two ends as [(what, id, port)], `what` being place or
    stub; None when an end names neither, which validation reports."""
    out = []
    for side in ("a", "b"):
        place, stub = c.get(side), c.get(side + "_stub")
        if isinstance(place, str) and place:
            out.append(("place", place, _port_word(c.get(side + "_port"))))
        elif isinstance(stub, str) and stub:
            out.append(("stub", stub, _port_word(c.get(side + "_port"))))
        else:
            return None
    return out


def _between(ends, a, b):
    """The map cable's ports turned to face (a, b), when it runs between those
    two places; None otherwise. The second answer is True when it was turned."""
    if ends is None or any(e[0] != "place" for e in ends):
        return None, False
    if (ends[0][1], ends[1][1]) == (a, b):
        return (ends[0][2], ends[1][2]), False
    if (ends[0][1], ends[1][1]) == (b, a):
        return (ends[1][2], ends[0][2]), True
    return None, False


def _fit(theirs, ours):
    """None when the two name different ports at an end; else how many ports
    they agree on. A port one side leaves blank agrees with any."""
    score = 0
    for t, o in zip(theirs, ours):
        if t and o:
            if not _same_port(t, o):
                return None
            score += 1
    return score


def _place_name(chart, pid):
    return clean((chart.nodes.get(pid) or {}).get("name")) or pid


def _end_name(chart, end):
    what, ident, _ = end
    if what == "stub":
        return f"the stub {clean((chart.stubs.get(ident) or {}).get('name')) or ident}"
    return _place_name(chart, ident)


def _at(port, name):
    return f"port {port} on {name}" if port else name


def _states_otherwise(field, theirs, ours):
    """Whether the map's value for a field is not what the system states."""
    if field == "vlan":
        return schema.vlan_number(theirs) != ours
    if field == "tagged":
        listed = theirs if isinstance(theirs, list) else []
        return sorted({schema.vlan_number(v) for v in listed} - {None}) != ours
    if field == "poe_w":
        try:
            return float(theirs) != float(ours)
        except (TypeError, ValueError):
            return True
    return str(theirs or "").strip().casefold() != str(ours).strip().casefold()


def _vlan_words(c):
    return topology.vlan_label({"vlan": c.get("vlan"), "tagged": c.get("tagged")}) or "no VLAN"


def _differs_from_hand(c, row):
    """What a cable someone else wrote says otherwise, in words: its VLANs,
    where both it and the system state them. A port it leaves blank is not a
    disagreement: it is a cable with less written on it."""
    want = row["cable"]
    clash = any(f in want and c.get(f) not in (None, "", [])
                and _states_otherwise(f, c.get(f), want[f]) for f in ("vlan", "tagged"))
    return [f"the map says {_vlan_words(c)}, {row['by']} says {_vlan_words(want)}"] if clash else []


def _changes_words(c, changes):
    out = []
    for field, value in changes.items():
        was = c.get(field)
        if field.endswith("_port"):
            out.append(f"port {value}" + (f", was {was}" if was else ""))
        elif field in ("vlan", "tagged"):
            continue
        elif field not in ("a", "b", "a_stub", "b_stub") and value is not None:
            out.append(f"{field.replace('_w', '')} {value}" + (f", was {was}" if was not in (None, "") else ""))
    if "vlan" in changes or "tagged" in changes:
        out.append(f"{_vlan_words({**c, **changes})}, was {_vlan_words(c)}")
    return out


def _differ(row, words):
    """A cable the map has otherwise: listed, never ticked, never written."""
    row.update(status=NEW, blocked=True, differs=words, group=DIFFERS_GROUP,
               note=f"{'; '.join(words)}. The map's cable stays as it is: change it by hand "
                    f"if {row['by']} is right.")


def _cable_id(a, a_port, b, b_port, ids):
    """The id a new cable is written under: its two ends and ports, so the same
    cable on the same map is offered under the same id on every review."""
    ends = sorted([(a, a_port), (b, b_port)])
    base = "--".join(slugify(p) + (f".{slugify(q)}" if q else "") for p, q in ends)
    cid, n = base, 2
    while cid in ids:
        cid, n = f"{base}-{n}", n + 1
    return cid


def _annotate_cables(rows, by_key, chart):
    """The cable rows, read against the map's cables. Returns the rows kept.

    A cable whose ends are not both places on the map is dropped: no cable and
    no stub. Then, for each kept row:

    * the map has the same cable (same two places, and no port the two name
      differently): nothing is offered, unless this system wrote that cable and
      now states something else about it, when the row is an update;
    * the map gives one of its ports to something else, or runs a cable between
      the same two places on another port: if that cable is this system's own,
      the row is an update of it; if anyone else wrote it, the row lists the
      disagreement in words and cannot be ticked;
    * otherwise the row is a new cable.

    Matching is by ends and ports, never by id, so a renamed place keeps its
    cables matched."""
    live = []
    for row in rows:
        a, b = by_key.get(row["parent"]), by_key.get(row["peer"])
        if a is None or b is None or a["status"] != CHARTED or b["status"] != CHARTED \
                or a["matched"] == b["matched"]:
            continue
        row["ends"] = [[a["matched"], row["a_port"]], [b["matched"], row["b_port"]]]
        row["name"] = clean(" ↔ ".join(_place_name(chart, end) + (f" port {port}" if port else "")
                                       for end, port in row["ends"]), 240)
        live.append(row)
    ends = [_map_ends(c) for c in chart.cables]
    # each row's own cable on the map first, the closest fit winning, so two
    # cables between the same pair (an aggregate) each find their own
    same, held = {}, set()
    for row in live:
        (A, ap), (B, bp) = row["ends"]
        best = None
        for i, e in enumerate(ends):
            theirs, _ = _between(e, A, B)
            score = None if i in held or theirs is None else _fit(theirs, (ap, bp))
            if score is not None and (best is None or score > best[1]):
                best = (i, score)
        if best is not None:
            same[row["key"]] = best[0]
            held.add(best[0])
    ids = {c.get("id") for c in chart.cables}
    claimed = set()
    for row in live:
        if row["key"] in same:
            _against_its_own(row, chart, same[row["key"]], ends)
        else:
            _against_the_rest(row, chart, ends, held, claimed, ids)
    return live


#: Readings of the moment, not facts about the wire: a link renegotiates, a
#: camera draws a little more at night. Written where the map has none, never
#: offered as a change, or every review would offer the same cable again.
_READINGS = ("speed", "poe_w")


def _stated_changes(c, row):
    """What the system states about a cable of its own that the map has
    otherwise: the kind, the state and the VLANs; a reading only where the
    map has none."""
    out = {}
    for field in CABLE_FIELDS:
        if field not in row["cable"]:
            continue
        if field in _READINGS and c.get(field) not in (None, ""):
            continue
        if _states_otherwise(field, c.get(field), row["cable"][field]):
            out[field] = row["cable"][field]
    return out


def _own(c, row):
    return (c.get("source") or "hand") == row["source"]


def _against_its_own(row, chart, i, ends):
    c = chart.cables[i]
    (A, ap), (B, bp) = row["ends"]
    theirs, turned = _between(ends[i], A, B)
    row["matched"] = clean(c.get("id")) or "a cable"
    if not _own(c, row):
        words = _differs_from_hand(c, row)
        if words:
            _differ(row, words)
        else:
            row["status"] = CHARTED
        return
    changes = {}
    for k, (t, o) in enumerate(zip(theirs, (ap, bp))):
        if o and not t:
            changes[("a", "b")[k ^ turned] + "_port"] = o
    changes.update(_stated_changes(c, row))
    if changes and isinstance(c.get("id"), str):
        row.update(status=NEW, updates=c["id"], changes=changes,
                   note=f"updates the cable {row['by']} gave before: {'; '.join(_changes_words(c, changes))}")
    else:
        row["status"] = CHARTED


def _against_the_rest(row, chart, ends, held, claimed, ids):
    (A, ap), (B, bp) = row["ends"]
    by, hits = row["by"], {}
    for i, e in enumerate(ends):
        if e is None:
            continue
        # a port of this cable that the map gives to something else
        for place, port, far in ((A, ap, B), (B, bp, A)):
            if not port:
                continue
            for k in (0, 1):
                what, ident, p = e[k]
                other = e[1 - k]
                if what == "place" and ident == place and p and _same_port(p, port) \
                        and not (other[0] == "place" and other[1] == far):
                    hits.setdefault(i, []).append(
                        f"the map says {_at(port, _place_name(chart, place))} goes to "
                        f"{_end_name(chart, other)}, {by} says {_place_name(chart, far)}")
        # a cable between the same two places, on another port
        theirs, _ = _between(e, A, B)
        if theirs is not None and i not in held:
            for t, o, place in zip(theirs, (ap, bp), (A, B)):
                if t and o and not _same_port(t, o):
                    hits.setdefault(i, []).append(
                        f"the map says port {t} on {_place_name(chart, place)}, {by} says port {o}")
    if not hits:
        row["cable"]["id"] = _cable_id(A, ap, B, bp, ids)
        ids.add(row["cable"]["id"])
        row["status"] = NEW
        return
    # one cable in the way, this system's own, and not another row's own
    # cable: it is offered as moved. Anything more, or anyone else's, is
    # listed and left alone.
    i = next(iter(hits)) if len(hits) == 1 else None
    c = chart.cables[i] if i is not None else {}
    if i is None or i in held or i in claimed or not _own(c, row) or not isinstance(c.get("id"), str):
        _differ(row, list(dict.fromkeys(w for ws in hits.values() for w in ws)))
        return
    claimed.add(i)
    changes = {"a": A, "b": B}
    for side, port in (("a", ap), ("b", bp)):
        if port:
            changes[side + "_port"] = port
        elif c.get(side + "_port") not in (None, ""):
            changes[side + "_port"] = None         # this system's own cable: what it no longer says goes
        if c.get(side + "_stub") not in (None, ""):
            changes[side + "_stub"] = None
    changes.update(_stated_changes(c, row))
    row.update(status=NEW, updates=c["id"], changes=changes, matched=c["id"],
               note=f"updates the cable {by} gave before: {'; '.join(dict.fromkeys(hits[i]))}")


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
    for row in (r for r in chosen if r["type"] == "cable"):
        ops.append(_cable_op(row))
    if not ops:
        raise PlanError(["Nothing was ticked."])
    return ops


def _cable_op(row):
    """A ticked cable as one op: an upsert of this system's own cable by its id,
    carrying only what changed, or a new cable in the catalogue's field order.
    Both ends are on the map already: `annotate` keeps no other cable row."""
    if row.get("updates"):
        return {"op": "upsert", "section": "cables", "id": row["updates"], "body": dict(row["changes"])}
    (a, a_port), (b, b_port) = row["ends"]
    body = {"id": row["cable"]["id"], "a": a}
    if a_port:
        body["a_port"] = a_port
    body["b"] = b
    if b_port:
        body["b_port"] = b_port
    body.update({k: row["cable"][k] for k in CABLE_FIELDS if k in row["cable"]})
    body["source"] = row["source"]
    return {"op": "insert", "section": "cables", "body": body}


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
