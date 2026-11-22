import logging
import time

import settings
from jsonio import iso_utc
from jsonstore import JsonStore
from engines.base import NODE_STATES

log = logging.getLogger("atlas.live.events")

KEEP = 2000

TRACKED = tuple(sorted(NODE_STATES))

_GRAVITY = {"down": "grave", "degraded": "warn", "maintenance": "planned",
            "healthy": "clear", "slumbering": "quiet"}


def _now():
    return iso_utc()


def _shape(stored):
    if not isinstance(stored, dict):
        return {"seq": 0, "state": {}, "behind": {}, "events": []}
    seq = stored.get("seq")
    if not (isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0):
        events = stored.get("events") if isinstance(stored.get("events"), list) else []
        seq = max([e["id"] for e in events if isinstance(e, dict) and isinstance(e.get("id"), int)
                   and not isinstance(e.get("id"), bool)] + [0])
    return {
        "seq": seq,
        "state": stored.get("state") if isinstance(stored.get("state"), dict) else {},
        "behind": stored.get("behind") if isinstance(stored.get("behind"), dict) else {},
        "events": stored.get("events") if isinstance(stored.get("events"), list) else [],
    }


_STORE = JsonStore(lambda: settings.EVENTS_PATH, _shape)


def locked():
    return _STORE.locked()


def load():
    return _STORE.load()


def next_id(store):
    store["seq"] += 1
    return store["seq"]


def commit(store):
    if len(store["events"]) > KEEP:
        store["events"] = store["events"][-KEEP:]
    _STORE.save(store)


def _observed(feed):
    out = {}
    for node_id, info in (feed.get("nodes") or {}).items():
        info = info or {}
        state = info.get("state")
        if state in TRACKED:
            out[f"node:{node_id}"] = ("node", node_id, state, info.get("cause"))
    for name, info in (feed.get("services") or {}).items():
        state = (info or {}).get("state")
        if state in TRACKED:
            out[f"service:{name}"] = ("service", name, state, None)
    for key, info in (feed.get("rites") or {}).items():
        state = (info or {}).get("state")
        if state in TRACKED:
            out[f"rite:{key}"] = ("rite", key, state, None)
    return out


def record(feed, label_for=None):
    observed = _observed(feed)
    forget = [f"node:{n}" for n in feed.get("unmanaged") or [] if isinstance(n, str)]
    forget += [f"service:{s}" for s in feed.get("unmanaged_services") or [] if isinstance(s, str)]
    if not observed and not forget:
        return []

    with locked():
        store = load()
        known = store["state"]
        behind = store["behind"]
        fresh = []
        seeded = False
        for key in forget:
            if key in known or key in behind:
                known.pop(key, None)
                behind.pop(key, None)
                seeded = True

        for key, (kind, target, state, cause) in sorted(observed.items()):
            previous = known.get(key)
            was_behind = behind.get(key)
            now_behind = cause if (cause and state == "down") else None
            if was_behind != now_behind:
                if now_behind:
                    behind[key] = now_behind
                else:
                    behind.pop(key, None)
                seeded = True
            outlived = (previous == state == "down" and was_behind and not now_behind)
            if previous == state and not outlived:
                continue
            known[key] = state
            seeded = True
            if previous is None:
                continue
            event_id = next_id(store)
            gravity = ("consequence" if (cause and state == "down")
                       else _GRAVITY.get(state, "clear"))
            event = {
                "id": event_id,
                "at": _now(),
                "kind": kind,
                "target": target,
                "name": (label_for(kind, target) if label_for else target),
                "from": previous,
                "to": state,
                "gravity": gravity,
                "ack": None,
            }
            if cause:
                event["cause"] = cause
            if outlived:
                event["outlived"] = True
            fresh.append(event)

        if not fresh and not seeded:
            return []

        store["events"].extend(fresh)
        commit(store)

    for event in fresh:
        log.info("event: %s %s %s -> %s", event["kind"], event["target"],
                 event["from"], event["to"])
    return fresh


def for_viewer(event):
    if "sent" in event:
        event = {k: v for k, v in event.items() if k != "sent"}
    ack = event.get("ack")
    if not isinstance(ack, dict):
        return event
    return {**event, "ack": {"at": ack.get("at")}}


def listing(limit=100, visible=None, unacked_only=False, visible_services=None,
            visible_rites=None):
    store = _STORE.load()
    out = []
    for event in reversed(store["events"]):
        if unacked_only and event.get("ack"):
            continue
        kind = event.get("kind")
        if visible is not None and kind == "node" \
                and event.get("target") not in visible:
            continue
        if visible_services is not None and kind == "service" \
                and event.get("target") not in visible_services:
            continue
        if visible_rites is not None and kind == "rite" \
                and event.get("target") not in visible_rites:
            continue
        if visible is not None and "cause" in event and event["cause"] not in visible:
            event = {k: v for k, v in event.items() if k != "cause"}
        out.append(event)
        if len(out) >= limit:
            break
    return out


def _counts(rows):
    day_ago = iso_utc(time.time() - 86400)
    return {
        "total": len(rows),
        "unacked": sum(1 for e in rows if not e.get("ack")
                       and e.get("gravity") in ("grave", "warn")),
        "last_24h": sum(1 for e in rows if e.get("at", "") >= day_ago),
    }


def counts(visible=None, visible_services=None, visible_rites=None):
    return _counts(listing(limit=KEEP, visible=visible, visible_services=visible_services,
                           visible_rites=visible_rites))


SENT_KEEP = 10


def note_sent(event_ids, to, at=None):
    wanted = {int(i) for i in event_ids or [] if isinstance(i, int) and not isinstance(i, bool)}
    if not wanted:
        return 0
    at = at or _now()
    noted = 0
    with _STORE.locked():
        store = _STORE.load()
        for event in store["events"]:
            if event.get("id") in wanted:
                sent = event.get("sent") if isinstance(event.get("sent"), list) else []
                event["sent"] = (sent + [{"to": str(to)[:80], "at": at}])[-SENT_KEEP:]
                noted += 1
        if noted:
            _STORE.save(store)
    return noted


def since(seq):
    return [e for e in _STORE.load()["events"]
            if isinstance(e, dict) and isinstance(e.get("id"), int) and e["id"] > seq]


def current_seq():
    return _STORE.load()["seq"]


def readable_seq():
    import os
    from jsonio import read_json
    path = settings.EVENTS_PATH
    if not os.path.exists(path):
        return 0
    raw = read_json(path)
    if not isinstance(raw, dict):
        return None
    return _shape(raw)["seq"]


def acknowledge(event_id, actor, note=""):
    with _STORE.locked():
        store = _STORE.load()
        for event in store["events"]:
            if event.get("id") == int(event_id):
                if event.get("ack"):
                    return event
                event["ack"] = {"by": actor, "at": _now(),
                                "note": str(note or "")[:300]}
                _STORE.save(store)
                log.info("event %s acknowledged by %s%s", event_id, actor,
                         f": {note}" if note else "")
                return event
    return None

