"""THE ANNALS — what befell the realm, and when.

The map has always shown the present tense. A place goes dark, the marker
turns red, someone fixes it, the marker turns gold, and nothing anywhere
remembers it happened. "Did the app host drop last night?" had no answer but
Kuma's own history, which is per-monitor and off the map.

This is the memory: a state transition, the moment it is first observed, with
somewhere to write down what it turned out to be. Zabbix's event log and
acknowledgement, at the scale this actually needs — one JSON file, no database.

Since 2026-07-28 the same log carries THE RITES: a scheduled job that stops
reporting is a state transition exactly like a host going dark, and wanting
"I know, the download host is off this week" to be expressible about a backup is the same
want that produced acknowledgement in the first place.

**Where the events come from.** `SignalsHub.feed()` caches for 30 seconds and
marks a cached read `cached: True`. Recording only on a *fresh* build means the
work happens once per source poll, not once per browser refresh. Two gunicorn
workers each poll independently, so both will see the same transition; the
write lock plus the stored last-seen state makes the second a no-op rather
than a duplicate.

**What is deliberately not an event.** The first observation of anything only
seeds the state — booting the app must not write forty "unknown -> healthy"
rows. A target vanishing from the feed is not a transition either: a monitor
being deleted is not the host going down, and guessing would fill the annals
with fiction.
"""

import logging
import time

import settings
from jsonio import iso_utc
from jsonstore import JsonStore

log = logging.getLogger("atlas.live.events")

#: How many events to keep. ~200 bytes each, so the cap is a few hundred KB.
KEEP = 2000

#: States worth remembering a move between. A transition into or out of any of
#: these is an event; anything else is noise.
TRACKED = ("healthy", "degraded", "down", "maintenance", "slumbering")

#: How an event reads in the log, by where it landed. "consequence" is not a
#: state — it is a `down` whose cause is something else that is also down, so it
#: is recorded but never joins the queue of things demanding a human.
_GRAVITY = {"down": "grave", "degraded": "warn", "maintenance": "planned",
            "healthy": "clear", "slumbering": "quiet"}


def _now():
    return iso_utc()


def _shape(stored):
    if not isinstance(stored, dict):
        return {"seq": 0, "state": {}, "events": []}
    return {
        "seq": stored.get("seq") or 0,
        "state": stored.get("state") if isinstance(stored.get("state"), dict) else {},
        "events": stored.get("events") if isinstance(stored.get("events"), list) else [],
    }


#: THE ANNALS: {seq, state, events}. Path read live so a settings reload lands.
_STORE = JsonStore(lambda: settings.EVENTS_PATH, _shape)


def _observed(feed):
    """{key: (kind, target, state, cause)} for everything the feed has an opinion on."""
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
    # THE RITES report the same way a place does — a rite that stops turning is
    # a fault, and one that has never reported is not yet anything, so
    # `heartbeats.as_feed()` simply omits it and the seeding rule above does
    # the rest.
    for key, info in (feed.get("rites") or {}).items():
        state = (info or {}).get("state")
        if state in TRACKED:
            out[f"rite:{key}"] = ("rite", key, state, None)
    return out


def record(feed, label_for=None):
    """Append an event for every state change since the last observation.

    Returns the events written (usually none). `label_for(kind, target)` gives
    a human name for the annals — the place's display name rather than its id.
    """
    observed = _observed(feed)
    if not observed:
        return []

    with _STORE.locked():
        store = _STORE.load()
        known = store["state"]
        fresh = []
        # `known` is the same object as store["state"], so comparing them later
        # would always be equal — track the change explicitly or first sightings
        # never get persisted and every poll re-seeds them.
        seeded = False

        for key, (kind, target, state, cause) in sorted(observed.items()):
            previous = known.get(key)
            if previous == state:
                continue
            known[key] = state
            seeded = True
            if previous is None:
                # first sighting — seed, don't narrate
                continue
            store["seq"] += 1
            # A fault explained by something else that is also down is a
            # consequence: recorded in full, but it must not add a second
            # thing to acknowledge for one fault.
            gravity = ("consequence" if (cause and state == "down")
                       else _GRAVITY.get(state, "clear"))
            event = {
                "id": store["seq"],
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
            fresh.append(event)

        if not fresh and not seeded:
            return []                       # nothing moved; don't touch the disk

        store["events"].extend(fresh)
        if len(store["events"]) > KEEP:
            store["events"] = store["events"][-KEEP:]
        _STORE.save(store)

    for event in fresh:
        log.info("event: %s %s %s -> %s", event["kind"], event["target"],
                 event["from"], event["to"])
    return fresh


def listing(limit=100, visible=None, unacked_only=False, since_id=None):
    """The annals, newest first.

    `visible` is the set of node ids the viewer is cleared to see. Events are
    derived from the map, so they inherit its redaction: a node hidden behind
    `require_group` must not surface in the history either. `None` means no
    gate applies (an admin, or standalone).
    """
    store = _STORE.load()
    out = []
    for event in reversed(store["events"]):
        if unacked_only and event.get("ack"):
            continue
        if since_id is not None and event.get("id", 0) <= since_id:
            continue
        if visible is not None and event.get("kind") == "node" \
                and event.get("target") not in visible:
            continue
        out.append(event)
        if len(out) >= limit:
            break
    return out


def counts(visible=None):
    """Totals for the chrome: how much is unacknowledged, how busy it's been."""
    events = listing(limit=KEEP, visible=visible)
    day_ago = iso_utc(time.time() - 86400)
    return {
        "total": len(events),
        "unacked": sum(1 for e in events if not e.get("ack")
                       and e.get("gravity") in ("grave", "warn")),
        "last_24h": sum(1 for e in events if e.get("at", "") >= day_ago),
    }


def acknowledge(event_id, actor, note=""):
    """Mark an event as seen, by whom, with what it turned out to be.

    Acknowledging is the difference between a log and an operations tool: it
    says a human looked, and leaves the reason behind for the next person.
    """
    with _STORE.locked():
        store = _STORE.load()
        for event in store["events"]:
            if event.get("id") == int(event_id):
                if event.get("ack"):
                    return event            # already acknowledged; idempotent
                event["ack"] = {"by": actor, "at": _now(),
                                "note": str(note or "")[:300]}
                _STORE.save(store)
                log.info("event %s acknowledged by %s%s", event_id, actor,
                         f": {note}" if note else "")
                return event
    return None

