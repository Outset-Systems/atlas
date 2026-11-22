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

STEPS = ("hop", "dns", "place", "internet")
UP, DOWN, SKIPPED = "up", "down", "skipped"

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

STEP_TIMEOUT = watch.TIMEOUT

_HOSTNAME = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9_-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9_-]{1,63}(?<!-))*\.?$")
_HOST_PORT = re.compile(r"^(?:\[(?P<v6>[0-9A-Fa-f:.]+)\]|(?P<host>[A-Za-z0-9._-]+)):(?P<port>[0-9]{1,5})$")

_last = {}
_last_lock = threading.Lock()
_hops = {}
HOPS_KEPT = 2000
_weigh_lock = threading.Lock()
DEADLINE = 45.0



def outside():
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
    return next((t for t in ts if t.kind in (authority.PLACE, authority.SHADOW_PLACE)
                 and t.place == pid and t.key == pid), None)


def _hop_target(data, ts, node, pid):
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



def _step(step, thing, name, t=None, state=None, why=None):
    return {"step": step, "thing": thing, "name": name, "asks": watch.asks(t) if t else None,
            "state": state, "why": why, "ms": None, "error": None}


def _skip(step, thing, name, why, t=None):
    return _step(step, thing, name, t, SKIPPED, why)


def _judged(step, answer):
    if answer is None:
        step.update(state=DOWN, error=watch.NO_ANSWER)
        return step
    state, ms, extra = answer
    if state is None:
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
        if over > len(recent):
            return "spent", 60
        return "spent", max(1, int(recent[over - 1] + 60 - now + 0.999))
    return None


def diagnose(data, pid, hidden=frozenset(), path=None, now=None):
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
            nodes.setdefault(n["id"], n)
    ts = watch.targets(data)

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

    hide = lambda tid: None if tid in hidden else tid
    link_by_id = graph["link_by_id"]
    shown_links = [None if (link_by_id[lid]["a"] in hidden or link_by_id[lid]["b"] in hidden) else lid
                   for lid in links]
    return "asked", {"id": pid, "name": name, "asked": True, "steps": steps, "broke_at": broke,
                     "path": {"things": [hide(tid) for tid in things], "links": shown_links}}


def _ask_own(step, data, pid, ts, path, now):
    outcome, value = watch.ask_now(data, pid, path=path, now=now, ts=ts)
    if outcome != "asked":
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
