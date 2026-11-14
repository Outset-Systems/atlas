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
from signals import NODE_STATES

log = logging.getLogger("atlas.live.events")

#: How many events to keep. ~200 bytes each, so the cap is a few hundred KB.
KEEP = 2000

#: States worth remembering a move between. A transition into or out of any of
#: these is an event; anything else is noise. The marker states, as the signals
#: layer spells them; a tuple, so an unhashable junk state is simply not in it.
TRACKED = tuple(sorted(NODE_STATES))

#: How an event reads in the log, by where it landed. "consequence" is not a
#: state — it is a `down` whose cause is something else that is also down, so it
#: is recorded but never joins the queue of things demanding a human.
_GRAVITY = {"down": "grave", "degraded": "warn", "maintenance": "planned",
            "healthy": "clear", "slumbering": "quiet"}


def _now():
    return iso_utc()


def _shape(stored):
    if not isinstance(stored, dict):
        return {"seq": 0, "state": {}, "behind": {}, "events": []}
    return {
        "seq": stored.get("seq") or 0,
        "state": stored.get("state") if isinstance(stored.get("state"), dict) else {},
        # WHAT A FAULT WAS BEHIND (2026-11-13): {key: cause id} for every target
        # last seen down as a consequence. Kept apart from `state`, whose values
        # stay plain strings, so a store written before this reads unchanged.
        "behind": stored.get("behind") if isinstance(stored.get("behind"), dict) else {},
        "events": stored.get("events") if isinstance(stored.get("events"), list) else [],
    }


#: THE ANNALS: {seq, state, events}. Path read live so a settings reload lands.
_STORE = JsonStore(lambda: settings.EVENTS_PATH, _shape)


# ── writing to the annals: one lock, one load, one numbering, one save ──────
# Everything that appends an event goes through these four, so the id sequence
# and the cap are kept in one place (`record` below, `tripwires.record`).
def locked():
    """The annals' write lock, held across a load, a change and a `commit`."""
    return _STORE.locked()


def load():
    """The annals as stored: {seq, state, events}."""
    return _STORE.load()


def next_id(store):
    """Take the next event id from a loaded store."""
    store["seq"] += 1
    return store["seq"]


def commit(store):
    """Trim a loaded store to the newest KEEP events and save it."""
    if len(store["events"]) > KEEP:
        store["events"] = store["events"][-KEEP:]
    _STORE.save(store)


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

    with locked():
        store = load()
        known = store["state"]
        behind = store["behind"]
        fresh = []
        # `known` is the same object as store["state"], so comparing them later
        # would always be equal — track the change explicitly or first sightings
        # never get persisted and every poll re-seeds them.
        seeded = False

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
            # A CONSEQUENCE THAT OUTLIVES ITS CAUSE (11-12 audit): a VM down
            # behind its host, the host back, the VM still down. Down equals
            # down, so this used to say nothing, and the VM's own outage never
            # reached the queue of things to acknowledge. Its own fault starts
            # now, so it is an event of its own: `outlived`, naming no cause
            # (the cause may be a place this reader is not cleared for).
            outlived = (previous == state == "down" and was_behind and not now_behind)
            if previous == state and not outlived:
                continue
            known[key] = state
            seeded = True
            if previous is None:
                # first sighting — seed, don't narrate
                continue
            event_id = next_id(store)
            # A fault explained by something else that is also down is a
            # consequence: recorded in full, but it must not add a second
            # thing to acknowledge for one fault.
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
            return []                       # nothing moved; don't touch the disk

        store["events"].extend(fresh)
        commit(store)

    for event in fresh:
        log.info("event: %s %s %s -> %s", event["kind"], event["target"],
                 event["from"], event["to"])
    return fresh


def for_viewer(event):
    """An event as someone who is not an admin reads it: that it was
    acknowledged and when, not by whom or in what words. Returns a copy.

    The same rule as a place's provenance (`provenance.for_viewer`): when and
    whether, not who. An ack's `by` is an admin's sign-in name and its `note` is
    whatever they typed, about a place this viewer may not be cleared for.
    """
    # ALERTS (2026-11-13): where a send went is an admin's own wiring (the
    # destination's name), never a viewer's or a token's
    if "sent" in event:
        event = {k: v for k, v in event.items() if k != "sent"}
    ack = event.get("ack")
    if not isinstance(ack, dict):
        return event
    return {**event, "ack": {"at": ack.get("at")}}


def listing(limit=100, visible=None, unacked_only=False, visible_services=None,
            visible_rites=None):
    """The annals, newest first.

    `visible` is the set of node ids the viewer is cleared to see. Events are
    derived from the map, so they inherit its redaction: a node hidden behind
    `require_group` must not surface in the history either. `None` means no
    gate applies (an admin, or standalone).

    `visible_services` is the same gate for service events, whose target is
    a monitor name rather than a node id (`redaction.visible_monitors`). A
    service row names its monitor, and a monitor charted on a hidden place —
    or on a hidden link of a visible one — is exactly what the node gate was
    there to keep out of the history.

    `visible_rites` is that gate for rite events, whose target is a rite's key
    (`heartbeats.keys_of` over the viewer's redacted rites). A rite that names
    a hidden place is dropped from `/rites`; without this its row stayed here,
    by name and state.
    """
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
        # a visible place can be dark BEHIND a hidden one, which names it
        if visible is not None and "cause" in event and event["cause"] not in visible:
            event = {k: v for k, v in event.items() if k != "cause"}
        out.append(event)
        if len(out) >= limit:
            break
    return out


def _counts(rows):
    """The chrome's totals over an already-filtered page of events."""
    day_ago = iso_utc(time.time() - 86400)
    return {
        "total": len(rows),
        "unacked": sum(1 for e in rows if not e.get("ack")
                       and e.get("gravity") in ("grave", "warn")),
        "last_24h": sum(1 for e in rows if e.get("at", "") >= day_ago),
    }


def counts(visible=None, visible_services=None, visible_rites=None):
    """Totals for the chrome: how much is unacknowledged, how busy it's been."""
    return _counts(listing(limit=KEEP, visible=visible, visible_services=visible_services,
                           visible_rites=visible_rites))


#: How many "sent to" notes one event keeps.
SENT_KEEP = 10


def note_sent(event_ids, to, at=None):
    """Write "sent to <destination>" on each event a send covered (ALERTS,
    2026-11-13), under the annals' own lock, so the ANNALS can show where an
    alert went. `to` is the destination's name. Returns how many were noted.
    Never raises on an event that has aged out of the store."""
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
    """Every event with an id above `seq`, oldest first (ALERTS' tick reads the
    annals by sequence, so an event is considered once whichever worker sees it)."""
    return [e for e in _STORE.load()["events"]
            if isinstance(e, dict) and isinstance(e.get("id"), int) and e["id"] > seq]


def current_seq():
    """The last event id handed out."""
    return _STORE.load()["seq"]


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

