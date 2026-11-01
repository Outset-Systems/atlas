"""The review step — what a connected system knows, against what the map already has.

The SolarWinds Network Sonar shape: discovery, a results wizard, then import, with
an ignore list, and never a background sync. Each system's importer turns its answer
into plain CANDIDATES. `annotate` says which of them the map already has, and `plan`
turns the ones an admin ticked into ordinary dataset ops for `store.apply`, so an
import lands in the change log and can be undone like any edit.

Nothing here talks to a network or writes anything. The fetching is in
`connections.py`; the only writer is the store.

A candidate is a dict, built by `place`, `service` or `zone`:

    key     "proxmox:qemu/101", stable across fetches. Ticks and the ignore list
            use it, and it is stamped on what it becomes as `origin`.
    type    place | service | zone
    group   the heading it is listed under
    name, ip, detail     what the review row shows
    parent  the key of its host: a guest's node, a stack's server

A service has nowhere to stand of its own: it becomes a row in its host's `links`,
so it needs a host that is on the map or ticked with it. A guest does not: it lands
without a `parent` when its host is not charted.

What a remote system says is untrusted text. `clean` and `address` are why a
stranger's control characters or a hostname in an address field cannot reach the
dataset, and strict validation in the store is the backstop.
"""

import ipaddress
import re
from urllib.parse import urlsplit

import discovery
from store.layout import _BAND_LABEL_X, _BAND_STEP, _BAND_TOP, _Y_MAX

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


def place(key, group, name, kind, role, *, ip="—", hw="", parent=None, scroll=None, detail=None):
    row = _candidate(key, "place", group, name, kind=kind, role=clean(role), ip=ip, hw=clean(hw),
                     parent=parent, detail=clean(hw if detail is None else detail))
    if isinstance(scroll, str) and scroll.strip():
        row["scroll"] = clean(scroll, 400)
    return row


def service(key, group, name, url, parent, about, detail=""):
    return _candidate(key, "service", group, name, url=url, parent=parent,
                      about=clean(about, 240), detail=clean(detail))


def zone(key, group, name, vlan, subnet, hue):
    return _candidate(key, "zone", group, name, vlan=vlan, subnet=clean(subnet) or "—", hue=hue,
                      detail=f"vlan {vlan}" + (f" · {clean(subnet)}" if subnet else ""))


def _real_ip(ip):
    return ip if isinstance(ip, str) and ip not in ("", "—") else None


def _names_of(name):
    """A name, and its first label: `nas.home.example` is the place called NAS."""
    full = slugify(name)
    return {full, slugify(str(name).split(".")[0])}


class _Map:
    """The dataset, indexed the three ways a candidate can already be on it."""

    def __init__(self, data):
        self.nodes = {n.get("id"): n for n in data.get("nodes", []) or []}
        self.zones = data.get("zones", []) or []
        self.by_origin, self.by_ip, self.by_name = {}, {}, {}
        for n in self.nodes.values():
            if n.get("origin"):
                self.by_origin[n["origin"]] = n
            if _real_ip(n.get("ip")):
                self.by_ip[n["ip"]] = n
            for name in (n.get("id"), n.get("name")):
                if name:
                    self.by_name.setdefault(slugify(name), n)

    def find_place(self, row):
        """(status, node). The same name at a different address is a CLASH: two
        things or a move, and only a person can say which."""
        if row["key"] in self.by_origin:
            return CHARTED, self.by_origin[row["key"]]
        ip = _real_ip(row["ip"])
        if ip and ip in self.by_ip:
            return CHARTED, self.by_ip[ip]
        for name in _names_of(row["name"]):
            node = self.by_name.get(name)
            if node is None:
                continue
            theirs = _real_ip(node.get("ip"))
            return (CLASH if ip and theirs and ip != theirs else CHARTED), node
        return NEW, None

    def find_zone(self, row):
        for z in self.zones:
            if row["key"] == z.get("origin") or str(row["vlan"]) == str(z.get("vlan")) \
                    or slugify(row["name"]) in (z.get("id"), slugify(z.get("name"))):
                return z
        return None

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
    for row in sorted(candidates, key=lambda c: c["type"] == "service"):
        row = {**row, "matched": "", "zone": "", "note": "", "blocked": False}
        by_key[row["key"]] = row
        if row["type"] == "zone":
            found = chart.find_zone(row)
            row["status"], row["matched"] = (CHARTED, found.get("id")) if found else (NEW, "")
        elif row["type"] == "place":
            row["status"], node = chart.find_place(row)
            row["matched"] = node.get("id") if node else ""
            if row["status"] == CLASH:
                row["note"] = f"The map has {node.get('name')} at {node.get('ip')}."
            elif row["status"] == NEW:
                row["zone"] = discovery.zone_for_ip(data, row["ip"]) or ""
        else:
            _annotate_service(row, by_key.get(row["parent"]), chart)
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
    for row in services:
        host = by_key[row["parent"]]
        if host["status"] != CHARTED and host not in places:
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
    for row in services:
        host = by_key[row["parent"]]
        target = ids.get(host["key"]) or host["matched"]
        link = {"label": row["name"], "url": row["url"], "desc": row["about"], "open_in": "tab"}
        if target in added:
            added[target].setdefault("links", []).append(link)
        else:
            node = next(n for n in data.get("nodes", []) if n.get("id") == target)
            edits.setdefault(target, list(node.get("links") or [])).append(link)

    ops += [{"op": "insert", "section": "nodes", "body": d} for d in drafts]
    ops += [{"op": "upsert", "section": "nodes", "id": node, "body": {"links": links}}
            for node, links in edits.items()]
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
            "label_x": _BAND_LABEL_X,
            "label_y": min(_BAND_TOP + _BAND_STEP * len(scratch["zones"]), _Y_MAX)}


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
        drafts.append(node)
    for row, node in zip(places, drafts):
        host = by_key.get(row["parent"])
        if host is not None:
            parent = ids.get(host["key"]) or (host["matched"] if host["status"] == CHARTED else "")
            if parent:
                node["parent"] = parent
    return drafts, ids
