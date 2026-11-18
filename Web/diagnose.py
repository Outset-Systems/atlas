"""Where does it break? (2026-11-17): one charted place, asked as a chain.

From the Atlas host, in order, and stopping at the first step that fails:

1. the path: each thing on the place's chain from the head of the network
   down to it (topology.py's `path_to_head`, read head first: cables, then
   a guest from its host, then routes, then parent ties), nearest the head
   first. A stub, and a place with no address, is listed as not asked,
   never guessed;
2. DNS: the place's charted name, when it has one (the name its own check
   asks, else the host of one of its own service addresses), resolves;
3. the place itself: its own check, asked exactly as "Check now" asks it
   (`watch.ask_now`, so its answer is stored where a round would store it),
   else a tcp connection to its address on a port the map charts for it;
4. the internet: only when the operator names an outside address
   (`ATLAS_DIAGNOSE_OUTSIDE=host:port`). Unset, the step is absent.

What may be asked is the watch engine's rule (watch.py) and nothing wider:
only addresses the map charts, plus the one outside address the operator
named, each through `watch._make` (so a metadata or link-local address is
never asked, written or resolved). The request names a place by id; it never
carries an address. A place a Kuma monitor watches is not asked while "Check
beside Kuma" is off; one marked unmanaged or planned is not asked at all; a
place the viewer may not see is listed with no id and no name.

What it costs: one ask per step that is asked, out of the same per-minute
budget a round and "Check now" spend (`watch.per_minute`). The whole cost is
weighed before anything is asked: when the minute cannot cover it, nothing is.
Only the place's own check is stored; the other steps are counted beside the
store (`watch.spend_by_hand`), by this worker.
"""

import ipaddress
import logging
import re
import threading
import time

import engines.authority as authority
import settings
import topology
import watch
from engines.base import HEALTHY
from engines.checks import _check_url
from engines.places import unmanaged_ids

log = logging.getLogger("atlas.live.diagnose")

#: The steps, in the order they are asked.
STEPS = ("hop", "dns", "place", "internet")
#: The states a step ends in.
UP, DOWN, SKIPPED = "up", "down", "skipped"

#: Why a step was not asked: the code an answer carries, and its words.
WHY = {
    "hidden": "a place you may not see",
    "stub": "a stub: there is no address to ask",
    "no-address": "it has no address on the map",
    "no-port": "no port is charted for it: it has no check of its own and no service at its address",
    "off": "its check is off: Atlas never asks it",
    "planned": "it is planned, not built",
    "unmanaged": "it is marked unmanaged: Atlas does not watch it",
    "kuma": "a Kuma monitor is named for it, and Check beside Kuma is off",
    "not-asked": "it could not be asked: its address is one no check may ask, or it did not resolve to one",
    "busy": "its check was asked by another worker a moment ago",
    "stopped": "not asked: an earlier step failed",
    "late": "not asked: the steps before it took too long",
}

#: How long one step that is no check of its own may take.
STEP_TIMEOUT = watch.TIMEOUT

_HOSTNAME = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9_-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9_-]{1,63}(?<!-))*\.?$")
_HOST_PORT = re.compile(r"^(?:\[(?P<v6>[0-9A-Fa-f:.]+)\]|(?P<host>[A-Za-z0-9._-]+)):(?P<port>[0-9]{1,5})$")

#: When each place was last diagnosed, per store path, by this worker.
_last = {}
_last_lock = threading.Lock()
#: What each hop last answered, and when: (store path, its check's key) -> (at,
#: the step's answer). Emptied when it grows past HOPS_KEPT.
_hops = {}
HOPS_KEPT = 2000
#: Held while a diagnose is weighed against the budget and its cost spent.
_weigh_lock = threading.Lock()
#: Seconds the whole chain may take; steps past it are listed as not asked.
DEADLINE = 45.0


# ── what is asked ───────────────────────────────────────────────────────────

def outside():
    """The Target the internet step asks, or None when no outside address is
    named, or the one named cannot be asked (logged)."""
    raw = settings.diagnose_outside()
    if not raw:
        return None
    m = _HOST_PORT.match(raw)
    port = int(m.group("port")) if m else 0
    host = (m.group("v6") or m.group("host")) if m else ""
    if host and m.group("v6"):
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            host = ""
    if not host or not 0 < port < 65536:
        log.warning("diagnose: ATLAS_DIAGNOSE_OUTSIDE is not host:port; the internet step is off")
        return None
    spec = {"type": "tcp", "host": host, "port": port, "expect": "", "every": watch.EVERY,
            "retries": 0, "timeout": STEP_TIMEOUT}
    t = watch._make("d:outside", "outside", "diagnose", "", "tcp", spec, "", "")
    if t is None:
        log.warning("diagnose: ATLAS_DIAGNOSE_OUTSIDE names an address no check may ask; "
                    "the internet step is off")
    return t


def _is_name(host):
    """A DNS name: not an address, not a bare number, a host name's letters."""
    if not host or watch.refused_host(host):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
        return False
    except ValueError:
        pass
    return bool(_HOSTNAME.match(host)) and any(c.isalpha() for c in host)


def _live_links(node):
    return [link for link in (node.get("links") if isinstance(node.get("links"), list) else [])
            if isinstance(link, dict) and not link.get("planned") and link.get("unmanaged") is not True]


def dns_name(node):
    """The place's charted DNS name, or '': the host its own check asks, else
    the host of the first of its own service addresses that is a name. Never
    its id or its display name, which are the map's words, not names."""
    host = watch.spec_of(node)["host"]
    if host.lower().startswith(("http://", "https://")):
        host = watch._parts(host)[0]
    if _is_name(host):
        return host
    for link in _live_links(node):
        url = _check_url(link.get("url")) or ""
        name = watch._parts(url)[0] if url else ""
        if _is_name(name):
            return name
    return ""


def _charted_port(node, ip, ts, pid):
    """A port the map charts for the place's own address: its `check_port`,
    else the port of one of its services at that address that Atlas asks
    (`ts`, so a service whose check is off, one a Kuma monitor watches while
    "Check beside Kuma" is off, or one marked unmanaged lends no port). 0
    when none."""
    own = watch.spec_of(node)
    if own["port"]:
        return own["port"]
    for t in ts:
        if t.place != pid or t.kind in (authority.PLACE, authority.SHADOW_PLACE):
            continue
        host, port = watch._parts(t.url) if t.url else (t.host, t.port)
        if host == ip and port:
            return port
    return 0


def _plain(node, pid, ts):
    """(Target, None) for a tcp connection to the place's address on a port
    the map charts, or (None, why). A place whose check is `off` is never
    asked."""
    if node.get("check") == "off":
        return None, "off"
    ip = watch._address(node.get("ip"))
    if not ip:
        return None, "no-address"
    port = _charted_port(node, ip, ts, pid)
    if not port:
        return None, "no-port"
    own = watch.spec_of(node)
    spec = {**own, "type": "tcp", "host": ip, "port": port, "expect": "", "retries": 0}
    t = watch._make(f"d:{pid}", pid, "diagnose", pid, "tcp", spec, "", ip)
    return (t, None) if t else (None, "not-asked")


def _own(ts, pid):
    """The place's own check (or its shadow beside Kuma), or None. Only a
    place target of this very place: never a service that shares its name."""
    return next((t for t in ts if t.kind in (authority.PLACE, authority.SHADOW_PLACE)
                 and t.place == pid and t.key == pid), None)


def _hop_target(data, ts, node, pid):
    """(Target, None) for a place on the path, or (None, why)."""
    if node.get("planned"):
        return None, "planned"
    if pid in unmanaged_ids(data):
        return None, "unmanaged"
    t = _own(ts, pid)
    if t is not None:
        return t, None
    why = watch.not_asked(data, pid)
    if why and why["why"] in ("kuma", "unmanaged"):
        return None, why["why"]
    return _plain(node, pid, ts)


# ── the answer ──────────────────────────────────────────────────────────────

def _step(step, thing, name, t=None, state=None, why=None):
    return {"step": step, "thing": thing, "name": name, "asks": watch.asks(t) if t else None,
            "state": state, "why": why, "ms": None, "error": None}


def _skip(step, thing, name, why, t=None):
    return _step(step, thing, name, t, SKIPPED, why)


def _judged(step, answer):
    """A step asked through `watch._run`: its answer, judged."""
    if answer is None:                       # not done inside the step's time
        step.update(state=DOWN, error=watch.NO_ANSWER)
        return step
    state, ms, extra = answer
    if state is None:                        # could not be asked: says nothing of the thing
        step.update(state=SKIPPED, why="not-asked", ms=None)
        return step
    step["ms"] = ms
    if state == HEALTHY:
        step["state"] = UP
    else:
        why = extra.get("why")
        step.update(state=DOWN, error=(watch.WHY.get(why) if isinstance(why, str) else None)
                    or watch.NOT_HEALTHY)
    return step


def _probe(t):
    heard, _ = watch._run([t], 2 * t.timeout + 1.0)
    return heard.get(t.ckey)


def _hop(step, t, where, at):
    """Ask a hop, or say again what it answered a moment ago. The places
    under one switch share it as a hop: diagnosing them one after another
    asked the switch each time, with nothing but the minute's cap between
    them. A hop asked inside the shortest interval a check may have
    (`watch.EVERY_MIN`) is not asked again; its last answer stands."""
    key = (where, t.ckey)
    with _last_lock:
        kept = _hops.get(key)
        if len(_hops) > HOPS_KEPT:
            _hops.clear()
    if kept and 0 <= at - kept[0] < watch.EVERY_MIN:
        step.update(kept[1])
        return step
    _judged(step, _probe(t))
    with _last_lock:
        _hops[key] = (at, {k: step[k] for k in ("state", "why", "ms", "error")})
    return step


def _wait(now, store, own, cost, pid, where):
    """("soon" | "spent", seconds) when the diagnose may not run now, else None."""
    if own is not None:
        last = ((store.get("checks") or {}).get(own.ckey) or {}).get("asked")
        if isinstance(last, (int, float)) and not isinstance(last, bool) and 0 <= now - last < watch.EVERY_MIN:
            return "soon", max(1, int(watch.EVERY_MIN - (now - last) + 0.999))
    with _last_lock:
        last = _last.get((where, pid))
    if last is not None and 0 <= now - last < watch.EVERY_MIN:
        return "soon", max(1, int(watch.EVERY_MIN - (now - last) + 0.999))
    cap = watch.per_minute()
    recent = watch.recent_asks(store, now, where)
    over = len(recent) + cost - cap
    if over > 0:
        if over > len(recent):               # more than a whole minute can cover
            return "spent", 60
        return "spent", max(1, int(recent[over - 1] + 60 - now + 0.999))
    return None


def diagnose(data, pid, hidden=frozenset(), path=None, now=None):
    """Ask the chain for the place `pid`. Returns (outcome, value):

      ("asked", answer)           every step that could be asked was, in order,
                                  until one failed
      ("soon" | "spent", seconds) the place was asked a moment ago, or the
                                  minute's budget cannot cover the steps:
                                  nothing was asked
      ("none", None)              no such place, or one in `hidden`
      ("unmanaged" | "planned", None)   a place Atlas does not ask

    `hidden` is the ids the viewer may not see. Whether the checks source is
    on is the caller's to say, before this is called."""
    fixed = now is not None
    clock = (lambda: now) if fixed else time.time
    where = watch.path_of(path)
    if not isinstance(pid, str) or not pid or pid in hidden or not isinstance(data, dict):
        return "none", None
    node = next((n for n in (data.get("nodes") if isinstance(data.get("nodes"), list) else [])
                 if isinstance(n, dict) and n.get("id") == pid), None)
    if node is None:
        return "none", None
    if pid in unmanaged_ids(data):
        return "unmanaged", None
    if node.get("planned"):
        return "planned", None

    graph = topology.build_graph(data)
    chain = topology.path_to_head(graph, pid)
    things = list(reversed(chain["things"]))
    links = list(reversed(chain["links"]))
    nodes = {}
    for n in data["nodes"]:
        if isinstance(n, dict) and isinstance(n.get("id"), str):
            nodes.setdefault(n["id"], n)       # the first with an id, as the graph keeps it
    ts = watch.targets(data)

    # the plan: every step, and the target each asks (None: not asked)
    plan = []
    for tid in things[:-1]:
        thing = graph["by_id"][tid]
        if tid in hidden:
            plan.append((_skip("hop", None, None, "hidden"), None))
        elif thing["type"] == "stub":
            plan.append((_skip("hop", tid, thing["name"], "stub"), None))
        else:
            t, why = _hop_target(data, ts, nodes[tid], tid)
            plan.append((_step("hop", tid, thing["name"], t), t) if t else
                        (_skip("hop", tid, thing["name"], why), None))
    name = graph["by_id"][pid]["name"]
    host = dns_name(node)
    if host:
        spec = {"type": "dns", "host": host, "port": 0, "expect": "", "every": watch.EVERY,
                "retries": 0, "timeout": STEP_TIMEOUT}
        t = watch._make(f"d:dns:{pid}", pid, "diagnose", pid, "dns", spec, "", "")
        plan.append((_step("dns", pid, name, t), t) if t else (_skip("dns", pid, name, "not-asked"), None))
    own = _own(ts, pid)
    if own is not None:
        plan.append((_step("place", pid, name, own), "own"))
    else:
        why = watch.not_asked(data, pid)
        if why and why["why"] == "kuma":
            plan.append((_skip("place", pid, name, "kuma"), None))
        else:
            t, why = _plain(node, pid, ts)
            plan.append((_step("place", pid, name, t), t) if t else (_skip("place", pid, name, why), None))
    t = outside()
    if t is not None:
        plan.append((_step("internet", None, "outside", t), t))

    cost = sum(1 for _, t in plan if t is not None)
    by_hand = sum(1 for _, t in plan if t is not None and t != "own")
    # Weighed and spent in one breath (2026-11-17): two diagnoses asked at
    # once each used to pass the weighing before either had spent anything,
    # and together asked past the minute's cap. The steps that are no check
    # of their own are counted now, whether or not the chain gets that far;
    # the place's own check is counted where it is stored, by `ask_now`.
    with _weigh_lock:
        store = watch.load(where)
        at = clock()
        wait = _wait(at, store, own, cost, pid, where)
        if wait:
            return wait
        with _last_lock:
            _last[(where, pid)] = at
        watch.spend_by_hand(where, by_hand, at)

    steps, broke, late = [], None, False
    for step, t in plan:
        steps.append(step)
        if t is None:
            continue
        if broke is not None:
            step.update(state=SKIPPED, why="stopped")
            continue
        # the whole chain has a deadline: a long row of slow hops must not
        # hold a worker past its own timeout
        late = late or (not fixed and time.time() - at > DEADLINE)
        if late:
            step.update(state=SKIPPED, why="late")
            continue
        if t == "own":
            _ask_own(step, data, pid, ts, path, now)
        elif step["step"] == "hop":
            _hop(step, t, where, clock())
        else:
            _judged(step, _probe(t))
        if step["state"] == DOWN:
            broke = len(steps) - 1

    hide = lambda tid: None if tid in hidden else tid   # noqa: E731
    link_by_id = graph["link_by_id"]
    shown_links = [None if (link_by_id[lid]["a"] in hidden or link_by_id[lid]["b"] in hidden) else lid
                   for lid in links]
    return "asked", {"id": pid, "name": name, "asked": True, "steps": steps, "broke_at": broke,
                     "path": {"things": [hide(tid) for tid in things], "links": shown_links}}


def _ask_own(step, data, pid, ts, path, now):
    """The place's own check, asked exactly as "Check now" asks it."""
    outcome, value = watch.ask_now(data, pid, path=path, now=now, ts=ts)
    if outcome != "asked":
        # another worker moved between the weighing and the asking: say so,
        # never a refusal halfway through the chain
        step.update(state=SKIPPED, why="busy")
        return step
    if value.get("error") == watch.NO_ANSWER or value.get("said") is None:
        step.update(state=SKIPPED, why="not-asked", error=value.get("error"))
        return step
    step["ms"] = value.get("ms")
    if value["said"] == HEALTHY:
        step["state"] = UP
    else:
        step.update(state=DOWN, error=value.get("error") or watch.NOT_HEALTHY)
    return step
