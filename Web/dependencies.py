"""Dependency-aware alarm suppression — one fault, one alarm.

When the gateway goes dark, everything behind it stops answering, and the
map reports ten places down. There is one fault. Ten alarms for one fault is
how a monitoring system trains you to ignore it.

This collapses the consequences into their cause: a place that is down *and*
sits behind something else that is down is reported as a consequence, with the
root named. The marker stays red — it genuinely is down, and softening that
would be a lie — but the colophon, the beacon and the unacknowledged queue all
count the cause once instead of the crater ten times.

**Only declared dependencies count.** This is the whole design, and it is what
Zabbix does with trigger dependencies for the same reason: a monitoring system
that hides a real outage because it *guessed* a topology is worse than a noisy
one. Two sources, both explicit:

  * `nodes[].parent` — containment. A VM cannot be up if its hypervisor is
    down; that is not an inference, it is what "parent" means.
  * `nodes[].depends_on` — an operator saying "this needs that".

`routes[]` and `reaches[]` are deliberately NOT used. They describe topology
and connectivity, not need. The monitoring host `reaches` the NAS, but it does not stop
working when the NAS does. Worse, in this lab the monitoring observes from
The edge in the DMZ, so "the gateway is down, therefore the app host is
unreachable" is false — they are on the same segment. Inferring dependency
from those fields would suppress alarms that are real.
"""

import logging

log = logging.getLogger("atlas.live.dependencies")

#: States that mean "this thing is not answering", for the purposes of asking
#: whether a dependent's own silence is explained by it.
_FAULTED = ("down",)
#: ...and states that mean the silence was arranged in advance.
_PLANNED = ("maintenance",)


def _placed(node):
    """True for a place this module can reason about: an object with a text id.
    A hand-edited entry without one is served with a warning, so it must not
    stop the feed (11-12 audit: one id-less place 500'd `/api/v2/signals` and
    stopped the annalist here)."""
    return isinstance(node, dict) and isinstance(node.get("id"), str) and bool(node["id"])


def declared_edges(data):
    """{node_id: [ancestors]} — only what the dataset actually asserts."""
    edges = {}
    known = {n["id"] for n in data.get("nodes", []) or [] if _placed(n)}
    for node in data.get("nodes", []) or []:
        if not _placed(node):
            continue
        ancestors = []
        parent = node.get("parent")
        if isinstance(parent, str) and parent in known:        # a list is no parent
            ancestors.append(parent)
        for dep in node.get("depends_on") or []:
            if isinstance(dep, str) and dep in known and dep not in ancestors \
                    and dep != node.get("id"):
                ancestors.append(dep)
        if ancestors:
            edges[node["id"]] = ancestors
    return edges


def walk(start, step, known):
    """Every place reached from `start` by repeating `step`, breadth first, in
    the order first reached. `start` itself is never in it, and neither is an id
    outside `known`. Loop-safe: a hand-edited map can always hold one."""
    seen, queue = [], list(step(start))
    while queue:
        nxt = queue.pop(0)
        if nxt == start or nxt in seen or nxt not in known:
            continue
        seen.append(nxt)
        queue.extend(step(nxt))
    return seen


def needs(edges, node_id, known):
    """What `node_id` cannot work without, transitively (`edges` from
    `declared_edges`)."""
    return walk(node_id, lambda n: edges.get(n, []), known)


def needed_by(edges, node_id, known):
    """What stops working if `node_id` does, transitively: everything that
    declares it, or declares something that does."""
    return walk(node_id, lambda n: [k for k, v in edges.items() if n in v], known)


def _root_cause(node_id, edges, states, seen=None):
    """The highest faulted ancestor explaining this node, or None.

    Walks up while ancestors are themselves faulted, so A→B→C with all three
    dark blames C, not B: the operator wants the thing to go and fix, not the
    nearest domino. Cycle-safe — a dataset can always be hand-edited into a
    loop, and a loop must not hang a request.
    """
    seen = seen if seen is not None else set()
    if node_id in seen:
        return None
    seen.add(node_id)

    for ancestor in edges.get(node_id, []):
        state = states.get(ancestor)
        if state in _FAULTED or state in _PLANNED:
            # keep climbing: the ancestor may itself be a consequence
            higher = _root_cause(ancestor, edges, states, seen)
            return higher or ancestor
    return None


def resolve(data, feed):
    """Annotate a feed with cause/consequence.

    Returns `{node_id: {"cause": root, "via": ancestor, "planned": bool}}` for
    every faulted node whose silence a declared dependency explains. Nodes with
    no faulted ancestor are untouched — their alarm is their own.
    """
    nodes = feed.get("nodes") or {}
    states = {node_id: (info or {}).get("state") for node_id, info in nodes.items()}
    edges = declared_edges(data)
    if not edges:
        return {}

    out = {}
    for node_id, state in states.items():
        if state not in _FAULTED:
            continue                      # only a fault can be a consequence
        cause = _root_cause(node_id, edges, states)
        if not cause or cause == node_id:
            continue
        via = next((a for a in edges.get(node_id, [])
                    if states.get(a) in _FAULTED or states.get(a) in _PLANNED), cause)
        out[node_id] = {
            "cause": cause,
            "via": via,
            # the root was taken down on purpose, so this is fallout from
            # planned work rather than an incident
            "planned": states.get(cause) in _PLANNED,
        }
    return out


def apply_to(data, feed):
    """Fold the analysis into the feed, in place-ish. Returns the feed.

    Adds `cause`/`planned` to each consequent node and a `causes` summary the
    front-end uses to say "the gateway has gone dark — 9 places behind it"
    instead of "10 places are dark".
    """
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
    log.info("dependency suppression: %s",
             "; ".join(f"{cause} explains {len(ids)}" for cause, ids in grouped.items()))
    return feed
