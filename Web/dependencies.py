import logging

log = logging.getLogger("atlas.live.dependencies")

_last_said = None

_FAULTED = ("down",)
_PLANNED = ("maintenance",)


def _placed(node):
    return isinstance(node, dict) and isinstance(node.get("id"), str) and bool(node["id"])


def declared_edges(data):
    edges = {}
    known = {n["id"] for n in data.get("nodes", []) or [] if _placed(n)}
    for node in data.get("nodes", []) or []:
        if not _placed(node):
            continue
        ancestors = []
        parent = node.get("parent")
        if isinstance(parent, str) and parent in known:
            ancestors.append(parent)
        deps = node.get("depends_on")
        for dep in deps if isinstance(deps, list) else []:
            if isinstance(dep, str) and dep in known and dep not in ancestors \
                    and dep != node.get("id"):
                ancestors.append(dep)
        if ancestors:
            edges[node["id"]] = ancestors
    return edges


def walk(start, step, known):
    seen, queue = [], list(step(start))
    while queue:
        nxt = queue.pop(0)
        if nxt == start or nxt in seen or nxt not in known:
            continue
        seen.append(nxt)
        queue.extend(step(nxt))
    return seen


def needs(edges, node_id, known):
    return walk(node_id, lambda n: edges.get(n, []), known)


def needed_by(edges, node_id, known):
    return walk(node_id, lambda n: [k for k, v in edges.items() if n in v], known)


def _root_cause(node_id, edges, states, seen=None):
    seen = seen if seen is not None else set()
    if node_id in seen:
        return None
    seen.add(node_id)

    for ancestor in edges.get(node_id, []):
        state = states.get(ancestor)
        if state in _FAULTED or state in _PLANNED:
            higher = _root_cause(ancestor, edges, states, seen)
            return higher or ancestor
    return None


def resolve(data, feed):
    nodes = feed.get("nodes") or {}
    states = {node_id: (info or {}).get("state") for node_id, info in nodes.items()}
    edges = declared_edges(data)
    if not edges:
        return {}

    out = {}
    for node_id, state in states.items():
        if state not in _FAULTED:
            continue
        cause = _root_cause(node_id, edges, states)
        if not cause or cause == node_id:
            continue
        via = next((a for a in edges.get(node_id, [])
                    if states.get(a) in _FAULTED or states.get(a) in _PLANNED), cause)
        out[node_id] = {
            "cause": cause,
            "via": via,
            "planned": states.get(cause) in _PLANNED,
        }
    return out


def apply_to(data, feed):
    consequences = resolve(data, feed)
    if not consequences:
        feed["causes"] = {}
        return feed

    nodes = dict(feed.get("nodes") or {})
    grouped = {}
    for node_id, info in consequences.items():
        nodes[node_id] = {**nodes.get(node_id, {}),
                          "cause": info["cause"], "via": info["via"]}
        if info["planned"]:
            nodes[node_id]["planned"] = True
        grouped.setdefault(info["cause"], []).append(node_id)

    feed["nodes"] = nodes
    feed["causes"] = {cause: sorted(ids) for cause, ids in grouped.items()}
    global _last_said
    said = "; ".join(f"{cause} explains {len(ids)}" for cause, ids in sorted(grouped.items()))
    if said != _last_said:
        _last_said = said
        log.info("dependency suppression: %s", said)
    return feed
