"""THE CLOUD VIEW — what an API token made for a cloud AI tool may read.

A cloud tool sends every answer it reads to its model's vendor. The Atlas cannot
see where a client sends things, so the owner says it when the token is made
(`api_tokens.CLOUD`), and a token that says so gets this view. It is smaller
than a full token's in three ways, each enforced here and nowhere else:

  1. **Only places a person has checked, and nothing has changed since**
     (`provenance.settled`). A place an import wrote, a place charted before the
     map kept provenance, and a reviewed place an import has added to since are
     withheld whole: not listed, not counted in the health, not named in an
     event. `withhold` marks them with a group nobody holds, so the scrubbing
     that already hides a `require_group` place (`redaction.py`) hides these the
     same way, references and all. The owner is told how many, and the agent is
     told too, so neither reads the lab as smaller than it is.

  2. **A short list of fields** (`project`). An allow-list: what is not named
     here does not leave, including any key a later release or a hand edit adds.
     No address, MAC, URL, hardware, note, monitor name, job host, rack, prefix,
     port or certificate.

  3. **Names read from the view, not from the record** (`events`, `services`).
     An event row keeps the name its place had when it was written, and the
     health feed is keyed by monitor name. Both are rebuilt from what this view
     holds, so a name it withholds cannot come back through either.

`seal` then takes a second pass over every answer and drops any key that names a
withheld kind of thing, in case a tool builds one some other way.

Four things carry no review of their own. A network is given only when a place
this view holds sits in it, since an import can chart a network and a network
of nothing but withheld places says what they are. A route is given unless one
of its ends is a withheld place, which the same scrubbing drops. A scheduled
job is given by its name, and left out when that name names a withheld place.
The map's title is given.

What still leaves: the names of checked places and services, what they are for,
how they connect and whether they are well. This reduces what a cloud tool
reads. It does not make sending a map to a vendor safe.

The MCP endpoint is the only door a cloud token opens (`api_tokens.gate`): the
read routes serve the dataset whole and have no use for this view.
"""

import heartbeats
import provenance

#: A group no token and no person holds. A place carrying it is hidden by the
#: same code that hides any `require_group` place.
NOT_SETTLED = "\x00cloud-view: not checked by a person"

META = ("title", "surveyed")
ZONE = ("id", "name")
NODE = ("id", "name", "kind", "zone", "role", "parent", "depends_on", "reaches", "planned", "off_map")
#: `kuma` is the join to a service's live state and nothing else: `services` and
#: `events` read it, and `seal` keeps it out of every answer.
LINK = ("label", "path", "kuma")
MARK = ("source", "charted_at", "changed_at", "reviewed", "reviewed_at")
ROUTE = ("from", "to", "kind")
#: What `heartbeats` needs to say whether a job ran, and the job's own name.
RITE = ("name", "key", "cadence", "when", "expect_every", "grace")
EVENT = ("id", "at", "kind", "from", "to", "gravity")

#: Keys that never appear in an answer to a cloud token, whatever built it.
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
    """True when the request in hand is from a cloud token."""
    import api_tokens
    token = api_tokens.current()
    return bool(token) and api_tokens.profile_of(token) == api_tokens.CLOUD


def _open(node):
    """A place a token with no groups could read at all."""
    return isinstance(node, dict) and not node.get("require_group")


def standing(data):
    """`{"readable", "withheld"}` over the places a token could otherwise read."""
    places = [n for n in data.get("nodes") or [] if _open(n)]
    readable = sum(1 for n in places if provenance.settled(n))
    return {"readable": readable, "withheld": len(places) - readable}


def withhold(data):
    """`data` with every place this view may not read marked as hidden.

    A shallow copy: the nodes list is new and a marked node is a new dict, so
    the caller's dataset is untouched. Run it before `redact_for_groups`, which
    then drops the marked places and scrubs every reference to them.
    """
    nodes = [({**n, "require_group": NOT_SETTLED} if _open(n) and not provenance.settled(n) else n)
             for n in data.get("nodes") or []]
    return {**data, "nodes": nodes}


def _pick(entry, keys):
    return {k: entry[k] for k in keys if k in entry} if isinstance(entry, dict) else {}


def project(data, words=None):
    """The redacted map cut down to the fields a cloud token may read.

    `words` is the pattern for the withheld places' names (`redaction.hidden_words`
    over the marked map). The scrub has already dropped a job that names one in
    its `host` or its `note`; this view sends the job's `name`, so that is
    checked here.
    """
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
    # a network is named only when a place this view holds sits in it
    lived_in = {place.get("zone") for place in out["nodes"] if isinstance(place.get("zone"), str)}
    out["zones"] = [_pick(z, ZONE) for z in data.get("zones") or []
                    if isinstance(z, dict) and z.get("id") in lived_in]
    return out


def _monitors(view):
    """{monitor name: (place id, service label)} for the services this view holds."""
    out = {}
    for node in view.get("nodes") or []:
        for link in node.get("links") or []:
            if link.get("kuma"):
                out.setdefault(link["kuma"], (node.get("id"), link.get("label")))
    return out


def services(states, view):
    """`{monitor: state}` as rows that name a service by its label and its place.
    A monitor this view does not chart on a service is left out."""
    joins = _monitors(view)
    rows = []
    for monitor, state in (states or {}).items():
        if monitor in joins:
            on, label = joins[monitor]
            rows.append({"service": label, "on": on, "state": state})
    return rows


def events(rows, view, limit):
    """The annals for this view: each row named from the view as it is now.

    A stored row carries the name its place had when it was written, and a
    service row's target is its monitor's name. Neither is repeated: a place is
    named as the view names it today, a service by its label and its place, and
    a row about anything this view does not hold is left out.
    """
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
    """`value` without any key that names a withheld kind of thing. A new value."""
    if isinstance(value, dict):
        return {k: seal(v) for k, v in value.items() if k not in SEALED}
    if isinstance(value, list):
        return [seal(v) for v in value]
    return value
