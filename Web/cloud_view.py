import heartbeats
import provenance

NOT_SETTLED = "\x00cloud-view: not checked by a person"

META = ("title", "surveyed")
ZONE = ("id", "name")
NODE = ("id", "name", "kind", "zone", "role", "parent", "depends_on", "reaches", "planned", "off_map")
LINK = ("label", "path", "kuma")
MARK = ("source", "charted_at", "changed_at", "reviewed", "reviewed_at")
ROUTE = ("from", "to", "kind")
RITE = ("name", "key", "cadence", "when", "expect_every", "grace")
EVENT = ("id", "at", "kind", "from", "to", "gravity")

SEALED = frozenset({
    "address", "ip", "mac", "url", "about", "desc", "host", "kuma", "hw", "lore", "origin",
    "monitors", "os", "scroll", "container", "embed", "subnet", "vlan", "cidr", "location",
    "peer", "accounts", "source_ip"})

INSTRUCTIONS = (" This token has the reduced view for a cloud tool. It lists only places a "
                "person has checked and nothing has changed since, and it withholds every "
                "address, service URL, hardware detail and note. atlas_overview says how many "
                "places are withheld. A place that is not listed may still exist, so never "
                "conclude that the lab has nothing else, and you cannot look a place up by "
                "its address.")


def active():
    import api_tokens
    token = api_tokens.current()
    return bool(token) and api_tokens.profile_of(token) == api_tokens.CLOUD


def _open(node):
    return isinstance(node, dict) and not node.get("require_group")


def standing(data):
    places = [n for n in data.get("nodes") or [] if _open(n)]
    readable = sum(1 for n in places if provenance.settled(n))
    return {"readable": readable, "withheld": len(places) - readable}


def withhold(data):
    nodes = [({**n, "require_group": NOT_SETTLED} if _open(n) and not provenance.settled(n) else n)
             for n in data.get("nodes") or []]
    return {**data, "nodes": nodes}


def _pick(entry, keys):
    return {k: entry[k] for k in keys if k in entry} if isinstance(entry, dict) else {}


def project(data, words=None):
    out = {"meta": _pick(data.get("meta"), META), "zones": [], "nodes": [],
           "routes": [_pick(r, ROUTE) for r in data.get("routes") or [] if isinstance(r, dict)],
           "rites": [_pick(r, RITE) for r in data.get("rites") or [] if isinstance(r, dict)
                     and not (words and words.search(str(r.get("name") or "")))]}
    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        place = _pick(node, NODE)
        mark = _pick(node.get(provenance.KEY), MARK)
        if mark:
            place[provenance.KEY] = mark
        place["links"] = [_pick(l, LINK) for l in node.get("links") or [] if isinstance(l, dict)]
        out["nodes"].append(place)
    lived_in = {place.get("zone") for place in out["nodes"] if isinstance(place.get("zone"), str)}
    out["zones"] = [_pick(z, ZONE) for z in data.get("zones") or []
                    if isinstance(z, dict) and z.get("id") in lived_in]
    return out


def _monitors(view):
    out = {}
    for node in view.get("nodes") or []:
        for link in node.get("links") or []:
            if link.get("kuma"):
                out.setdefault(link["kuma"], (node.get("id"), link.get("label")))
    return out


def services(states, view):
    joins = _monitors(view)
    rows = []
    for monitor, state in (states or {}).items():
        if monitor in joins:
            on, label = joins[monitor]
            rows.append({"service": label, "on": on, "state": state})
    return rows


def events(rows, view, limit):
    names = {n.get("id"): n.get("name") for n in view.get("nodes") or []}
    rites = {heartbeats.key_for(r): r.get("name") for r in view.get("rites") or []}
    joins = _monitors(view)
    out = []
    for event in rows:
        kind, target = event.get("kind"), event.get("target")
        row = _pick(event, EVENT)
        if kind == "node" and target in names:
            row.update(target=target, name=names[target] or target)
        elif kind == "service" and target in joins:
            on, label = joins[target]
            row.update(on=on, name=label)
        elif kind == "rite" and target in rites:
            row.update(target=target, name=rites[target] or target)
        else:
            continue
        if event.get("cause") in names:
            row["cause"] = event["cause"]
        if isinstance(event.get("ack"), dict):
            row["ack"] = {"at": event["ack"].get("at")}
        out.append(row)
        if len(out) >= limit:
            break
    return out


def seal(value):
    if isinstance(value, dict):
        return {k: seal(v) for k, v in value.items() if k not in SEALED}
    if isinstance(value, list):
        return [seal(v) for v in value]
    return value
