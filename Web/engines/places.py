from engines.base import monitor_map


def service_key(node_id, link):
    monitor = link.get("kuma")
    if isinstance(monitor, str) and monitor:
        return monitor
    label = link.get("label")
    return f"{node_id}/{label if isinstance(label, str) else ''}"


def unmanaged_ids(data):
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
    if not place_ids or not isinstance(data, dict):
        return set()
    out = {m for m, pid in monitor_map(data).items() if pid in place_ids}
    for node in data.get("nodes") if isinstance(data.get("nodes"), list) else []:
        if isinstance(node, dict) and node.get("id") in place_ids:
            for link in node.get("links") if isinstance(node.get("links"), list) else []:
                if isinstance(link, dict):
                    out.add(service_key(node["id"], link))
    return out


def service_places(data):
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
