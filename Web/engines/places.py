"""THE MAP'S KEYS: which feed key a service link is filed under, and which
places and services are not ours to watch (2026-11-17).

Moved here, unchanged, from `signals.py`, which imports every name back, so
`signals.service_key` and the rest read as before. Pure: a dataset in, keys
out; `schema` is imported where it is used.
"""

from engines.base import monitor_map


def service_key(node_id, link):
    """The feed key of one service link: the Kuma monitor it names, else
    `<place id>/<label>`. The page computes the same key (`svcKey` in
    config.js), which is how a built-in check finds its dot."""
    monitor = link.get("kuma")
    if isinstance(monitor, str) and monitor:
        return monitor
    # a hand edit's list or number names no monitor: the place's own key (round 15)
    label = link.get("label")
    return f"{node_id}/{label if isinstance(label, str) else ''}"


# ── UNMANAGED (2026-11-14, the owner's Q4 answer) ────────────────────────────
def unmanaged_ids(data):
    """The places not ours to watch: marked `unmanaged: true` themselves, or
    in a collection marked so. Only `True` counts (a hand edit's "yes" is not)."""
    import schema
    data = data if isinstance(data, dict) else {}
    nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    out = {n["id"] for n in nodes
           if isinstance(n, dict) and isinstance(n.get("id"), str) and n.get("unmanaged") is True}
    listed = data.get("collections")
    for c in listed if isinstance(listed, list) else []:
        if isinstance(c, dict) and c.get("unmanaged") is True:
            out.update(p for p in schema.as_list(c.get("places")) if isinstance(p, str) and p)
    return out


def services_of(data, place_ids):
    """The service keys (monitor names, or `<place>/<label>`) the feed files
    under these places: a place's own links and the monitors charted on it."""
    if not place_ids or not isinstance(data, dict):
        return set()
    out = {m for m, pid in monitor_map(data).items() if pid in place_ids}
    for node in data.get("nodes") if isinstance(data.get("nodes"), list) else []:
        if isinstance(node, dict) and node.get("id") in place_ids:
            for link in node.get("links") if isinstance(node.get("links"), list) else []:
                if isinstance(link, dict):
                    out.add(service_key(node["id"], link))
    return out


# ── SERVICES AS WATCHED THINGS (2026-11-15, stage 3b) ────────────────────────
def service_places(data):
    """{service key: place id} for every service link on the map: the key the
    feed files it under (`service_key`). Two links naming one monitor share
    a key, and the first place keeps it."""
    out = {}
    data = data if isinstance(data, dict) else {}
    for node in data.get("nodes") if isinstance(data.get("nodes"), list) else []:
        if not (isinstance(node, dict) and isinstance(node.get("id"), str)):
            continue
        for link in node.get("links") if isinstance(node.get("links"), list) else []:
            if isinstance(link, dict):
                out.setdefault(service_key(node["id"], link), node["id"])
    return out


def unmanaged_service_keys(data):
    """The services not ours to watch on their own: a link marked
    `unmanaged: true`, or a service in a collection marked so. (A service on
    an unmanaged place goes with it: `services_of`.)"""
    import schema
    out = set()
    data = data if isinstance(data, dict) else {}
    for node in data.get("nodes") if isinstance(data.get("nodes"), list) else []:
        if not (isinstance(node, dict) and isinstance(node.get("id"), str)):
            continue
        for link in node.get("links") if isinstance(node.get("links"), list) else []:
            if isinstance(link, dict) and link.get("unmanaged") is True:
                out.add(service_key(node["id"], link))
    listed = data.get("collections")
    for c in listed if isinstance(listed, list) else []:
        if isinstance(c, dict) and c.get("unmanaged") is True:
            out.update(k for k in schema.as_list(c.get("services")) if isinstance(k, str) and k)
    return out
