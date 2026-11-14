"""ALERTS — rules and destinations, not an engine (2026-11-13).

A rule reads: when this place, set or network changes to this state and stays
there this long, send to this destination. Nothing here measures anything. It
reads the state changes THE ANNALS already records (events.py), from the feed
the annalist already builds (annalist.py), and adds no thread and no fetch:
the only network call is the send itself, through `alert_send`, which may reach
only the hosts the operator lists in `ATLAS_ALERT_HOSTS`.

Three files, all under the data directory:

* `alerts.json` (`settings.ALERTS_PATH`): the rules, the daily digest and the
  destinations, written by an admin with an `expect` stamp. A destination names
  its secret (`secret: NTFY_LAB`); the value is never here.
* `alerts-state.json` (`settings.ALERTS_STATE_PATH`), under a file lock: the
  last event sequence handled, the pending "stays for" timers, the rate-limit
  ledger, what was folded, and the last digest day.
* the delivery log, kept by `alert_send.log_delivery`.

**The tick** (`tick`) runs after each annalist build and never from a request,
so a browser's refresh never sends. It takes the state file's lock, handles
only events newer than the stored sequence, and so considers an event once
however many workers poll. It holds the lock across its sends, waiting only
`LOCK_WAIT` seconds for it: a worker that cannot have it skips that tick,
because the other worker is doing the same work.

**What a message may say** is decided by the view a viewer with no access
groups gets (`redaction.redact(data, frozenset(), token=True)` and the signals
feed cut the same way). Every word sent comes from that view, and every text is
checked against the hidden places' words before it goes; a match drops the
message and logs it `blocked`. A rule's own name and note are never sent: an
admin may have written a hidden place's name into them.

Out of this stage: tripwires (they arrive by the inbound webhook and are
admin-only wholesale, so no message composed from the no-group view can carry
them), services and rites. A tick reads `node` events only.
"""

import datetime
import hashlib
import json
import logging
import os
import re
import time
from urllib.parse import quote

import settings
from filelock import LockTimeout, exclusive, lock_for
from jsonio import iso_utc
from jsonstore import JsonStore
from signals import NODE_STATES

log = logging.getLogger("atlas.live.alerts")

TARGET_KINDS = ("place", "set", "network")
MAX_RULES = 100
MAX_DESTINATIONS = 20
MAX_FOR_MINUTES = 1440
MAX_TIMERS = 500
#: The rate limit: sends a minute to one destination, and an hour across all.
PER_DESTINATION_PER_MINUTE = 6
PER_HOUR = 30
#: How long a tick waits for the other worker's tick before skipping its own.
LOCK_WAIT = 2.0
#: How many names one list in a message carries before "and N more".
LIST_CAP = 12

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: The title's verb, per state: "<NAME> is down".
STATE_WORDS = {"down": "is down", "degraded": "is degraded", "healthy": "is back up",
               "slumbering": "is asleep", "maintenance": "is under maintenance"}

DIGEST_DEFAULTS = {"enabled": False, "hour": 8, "destination": None, "cert_days": 30,
                   "review_days": 90, "drift": False, "uncharted": False}

#: Why `uncharted` is refused (see the report in the stage's notes): no feed the
#: annalist builds carries uncharted devices. They live in the survey's inbox
#: (`discovery.listing`), a separate store of unredacted survey rows that only
#: an admin reads, so the digest does not read it.
UNCHARTED_REFUSED = ("the digest cannot list uncharted devices yet: no feed the poll "
                     "already builds carries them")


def _sender():
    """The sender (`alert_send.py`), imported when used."""
    import alert_send
    return alert_send


# ── The store: rules, digest, destinations ───────────────────────────────────
def _shape(raw):
    raw = raw if isinstance(raw, dict) else {}
    rules = raw.get("rules")
    dests = raw.get("destinations")
    digest = raw.get("digest") if isinstance(raw.get("digest"), dict) else {}
    return {
        "rules": [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else [],
        "digest": {**DIGEST_DEFAULTS, **{k: v for k, v in digest.items() if k in DIGEST_DEFAULTS}},
        "destinations": [d for d in dests if isinstance(d, dict)] if isinstance(dests, list) else [],
    }


_STORE = JsonStore(lambda: settings.ALERTS_PATH, _shape)


class StaleError(Exception):
    """The file changed after the admin read it: `expect` no longer matches."""


def _stamp_of(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:16]


def read():
    """(doc, stamp): the stored rules, digest and destinations."""
    doc = _STORE.load()
    return doc, _stamp_of(doc)


def save(doc, expect=None):
    """Replace the whole document. `expect` is compared under the write's own
    lock (the maintenance rule: checked first and written later, two admins
    holding one stamp would both pass). Returns the new stamp.

    Only Atlas's own callers leave `expect` out; the admin route refuses a
    save without one (2026-11-13), and an empty one is compared, not skipped."""
    with _STORE.locked():
        stored = _STORE.load()
        if expect is not None and expect != _stamp_of(stored):
            raise StaleError("the alerts changed since they were read")
        _STORE.save(_shape(doc))
        return _stamp_of(_STORE.load())


# ── Shapes and checks ────────────────────────────────────────────────────────
def normalize(doc):
    """The document with only the fields Atlas keeps, in their places. Values
    are left as given so `validate` can name what is wrong with them."""
    doc = doc if isinstance(doc, dict) else {}
    out = _shape(doc)
    out["rules"] = [{k: r.get(k) for k in ("id", "name", "note", "enabled", "target", "to",
                                           "for_minutes", "destination")}
                    for r in out["rules"]]
    for r in out["rules"]:
        r["note"] = r["note"] if r["note"] is not None else ""
        r["enabled"] = True if r["enabled"] is None else r["enabled"]
        r["for_minutes"] = 0 if r["for_minutes"] is None else r["for_minutes"]
        if isinstance(r["target"], dict):
            r["target"] = {"kind": r["target"].get("kind"), "id": r["target"].get("id")}
    out["destinations"] = [{k: d.get(k) for k in ("id", "name", "kind", "url", "secret",
                                                  "secret_origin")}
                           for d in out["destinations"]]
    return out


def _int_in(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def clean_data(data):
    """The dataset with only the places this module can reason about: objects
    with a text id. A hand-edited stray entry is served with a warning, and it
    must not stop the tick (nor reach the redaction, which trips on it)."""
    data = data if isinstance(data, dict) else {}
    nodes = [n for n in data.get("nodes") or []
             if isinstance(n, dict) and isinstance(n.get("id"), str) and n["id"]]
    return {**data, "nodes": nodes}


def public_view(data):
    """The dataset as a viewer with no access groups (and a token) gets it."""
    import redaction
    return redaction.redact(clean_data(data), frozenset(), token=True)[0]


def hidden_pattern(data):
    """The hidden places' names, ids and addresses, as a pattern, or None."""
    import redaction
    return redaction.hidden_words(clean_data(data), frozenset())


def _visible_targets(view):
    places = {n["id"]: n for n in view.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    sets = {s["id"]: s for s in view.get("sets") or []
            if isinstance(s, dict) and isinstance(s.get("id"), str)}
    # a zone is one id, as text: a hand-edited list there names no network
    # (2026-11-13), and it must not stop the tick
    networks = {n["zone"] for n in places.values() if isinstance(n.get("zone"), str) and n["zone"]}
    return places, sets, networks


def _target_in(target, visible):
    """`target_visible` against targets already worked out (`_visible_targets`)."""
    if not isinstance(target, dict):
        return False
    places, sets, networks = visible
    kind, tid = target.get("kind"), target.get("id")
    if not isinstance(tid, str):
        return False
    return ((kind == "place" and tid in places) or (kind == "set" and tid in sets)
            or (kind == "network" and tid in networks))


def target_visible(target, view):
    """True when a rule's target survives the no-group view: a place in it, a
    set that survives it, a network with a visible place in it."""
    return _target_in(target, _visible_targets(view))


def suspended(doc, data):
    """Ids of enabled rules whose target is no longer visible to a viewer with
    no access groups. They send nothing until it is again."""
    visible = _visible_targets(public_view(data))
    return [r.get("id") for r in doc.get("rules") or []
            if r.get("enabled") and not _target_in(r.get("target"), visible)]


def validate(doc, data):
    """What is wrong with a document about to be saved, one sentence each.
    Empty when it can be saved. Never echoes a target's id: a refused target
    may be a hidden place, and the answer goes back over the wire."""
    problems = []
    sender = _sender()
    rules, dests, digest = doc.get("rules"), doc.get("destinations"), doc.get("digest")
    if not isinstance(rules, list) or not isinstance(dests, list) or not isinstance(digest, dict):
        return ["expected {rules: [...], digest: {...}, destinations: [...]}"]
    if len(rules) > MAX_RULES:
        problems.append(f"at most {MAX_RULES} rules")
    if len(dests) > MAX_DESTINATIONS:
        problems.append(f"at most {MAX_DESTINATIONS} destinations")
    if problems:
        # over a count limit, nothing else is checked (2026-11-13): an
        # oversized document is not worth working through rule by rule
        return problems

    dest_ids = set()
    for i, d in enumerate(dests):
        did = d.get("id")
        label = did if isinstance(did, str) and _ID.match(did) else f"#{i + 1}"
        if not (isinstance(did, str) and _ID.match(did)):
            problems.append(f"destination {label}: its id must be lower-case letters, "
                            "digits and dashes")
        elif did in dest_ids:
            problems.append(f"destination {label}: the id is used twice")
        dest_ids.add(did)
        problems += [f"destination {label}: {p}" for p in sender.check_destination(d) or []]

    visible = _visible_targets(public_view(data))       # once, not per rule
    rule_ids = set()
    for i, r in enumerate(rules):
        rid = r.get("id")
        label = rid if isinstance(rid, str) and _ID.match(rid) else f"#{i + 1}"
        if not (isinstance(rid, str) and _ID.match(rid)):
            problems.append(f"rule {label}: its id must be lower-case letters, digits and dashes")
        elif rid in rule_ids:
            problems.append(f"rule {label}: the id is used twice")
        rule_ids.add(rid)
        if not isinstance(r.get("name"), str) or len(r["name"]) > 80:
            problems.append(f"rule {label}: its name must be text of at most 80 characters")
        if not isinstance(r.get("note"), str) or len(r["note"]) > 300:
            problems.append(f"rule {label}: its note must be text of at most 300 characters")
        if not isinstance(r.get("enabled"), bool):
            problems.append(f"rule {label}: enabled must be true or false")
        target = r.get("target")
        if not (isinstance(target, dict) and target.get("kind") in TARGET_KINDS
                and isinstance(target.get("id"), str) and target["id"]):
            problems.append(f"rule {label}: its target must be a place, a set or a network")
        elif not _target_in(target, visible):
            problems.append(f"rule {label}: that {target['kind']} cannot be alerted on. It is "
                            "not on the map, or a viewer with no access groups cannot see it, "
                            "and a message about it could not be sent without naming it")
        to = r.get("to")
        if not (isinstance(to, list) and to and all(s in NODE_STATES for s in to)):
            problems.append(f"rule {label}: it needs one or more states from "
                            + ", ".join(sorted(NODE_STATES)))
        if not _int_in(r.get("for_minutes"), 0, MAX_FOR_MINUTES):
            problems.append(f"rule {label}: how long it must stay is a whole number of "
                            f"minutes from 0 to {MAX_FOR_MINUTES}")
        if r.get("destination") not in dest_ids:
            problems.append(f"rule {label}: it sends to a destination that does not exist")

    if not isinstance(digest.get("enabled"), bool):
        problems.append("digest: enabled must be true or false")
    if not _int_in(digest.get("hour"), 0, 23):
        problems.append("digest: the hour is a whole number from 0 to 23 (the server's local time)")
    if digest.get("enabled") and digest.get("destination") not in dest_ids:
        problems.append("digest: it sends to a destination that does not exist")
    if not _int_in(digest.get("cert_days"), 1, 365):
        problems.append("digest: certificate days are a whole number from 1 to 365")
    if not _int_in(digest.get("review_days"), 1, 3650):
        problems.append("digest: review days are a whole number from 1 to 3650")
    if not isinstance(digest.get("drift"), bool):
        problems.append("digest: drift must be true or false")
    if digest.get("uncharted") is not False:
        problems.append("digest: " + UNCHARTED_REFUSED)
    return problems


def for_reading(doc):
    """The document as a route returns it: each destination's secret by name
    only, and whether it is bound to the destination's address. No value, and
    not the origin it is bound to (that is the sender's bookkeeping)."""
    out = {**doc, "destinations": []}
    for d in doc.get("destinations") or []:
        shown = {k: v for k, v in d.items() if k != "secret_origin"}
        shown["secret_bound"] = bool(d.get("secret") and d.get("secret_origin"))
        out["destinations"].append(shown)
    return out


# ── The tick's state ─────────────────────────────────────────────────────────
def _state_shape(raw):
    raw = raw if isinstance(raw, dict) else {}

    def times(value):
        return [t for t in value if isinstance(t, (int, float))] if isinstance(value, list) else []

    sent = raw.get("sent") if isinstance(raw.get("sent"), dict) else {}
    folded = raw.get("folded") if isinstance(raw.get("folded"), dict) else {}
    seq = raw.get("seq")
    return {
        "seq": seq if isinstance(seq, int) and not isinstance(seq, bool) else None,
        "timers": [t for t in raw.get("timers") or [] if isinstance(t, dict)]
        if isinstance(raw.get("timers"), list) else [],
        "sent": {k: times(v) for k, v in sent.items()},
        "all": times(raw.get("all")),
        "folded": {k: v for k, v in folded.items()
                   if isinstance(v, dict) and isinstance(v.get("count"), int)},
        "digest_day": raw.get("digest_day") if isinstance(raw.get("digest_day"), str) else None,
        "last_tick": raw.get("last_tick") if isinstance(raw.get("last_tick"), str) else None,
    }


_STATE = JsonStore(lambda: settings.ALERTS_STATE_PATH, _state_shape)


def last_tick():
    """When any worker last finished a tick (UTC), or None."""
    return _STATE.load()["last_tick"]


# ── Matching ─────────────────────────────────────────────────────────────────
def _matches(rule, place_id, places, sets):
    target = rule.get("target") or {}
    kind, tid = target.get("kind"), target.get("id")
    if kind == "place":
        return place_id == tid
    if kind == "set":
        members = (sets.get(tid) or {}).get("places")
        return isinstance(members, list) and place_id in members
    if kind == "network":
        return bool(tid) and (places.get(place_id) or {}).get("zone") == tid
    return False


def _rules_for(place_id, state, rules, places, sets):
    return [r for r in rules if _matches(r, place_id, places, sets) and state in (r.get("to") or [])]


# ── Composing ────────────────────────────────────────────────────────────────
def _name(places, pid):
    node = places.get(pid) or {}
    return str(node.get("name") or pid)


def _listed(names):
    names = [n for n in names if n]
    if len(names) <= LIST_CAP:
        return ", ".join(names)
    return ", ".join(names[:LIST_CAP]) + f" and {len(names) - LIST_CAP} more"


def _link(query=""):
    base = settings.PUBLIC_URL
    if not base:
        return None
    if not query:
        return base
    return base + ("&" if "?" in base else "?") + query


def _when(at):
    """`2026-11-13T14:02:00Z` as `2026-11-13 14:02 UTC`."""
    if isinstance(at, str) and len(at) >= 16 and at.endswith("Z"):
        return at[:10] + " " + at[11:16] + " UTC"
    return str(at or "")


def compose(subject, state, event, view, pfeed, edges, known, behind=None):
    """One message about `subject`, from the no-group view only. Never the
    rule's name or note."""
    from dependencies import needed_by
    places, _, _ = _visible_targets(view)
    node = places.get(subject) or {}
    name = _name(places, subject)
    lines = []
    if node.get("role"):
        lines.append(f"What it is for: {node['role']}")
    event = event or {}
    if event.get("outlived"):
        lines.append(f"What changed: still {state} on its own at {_when(event.get('at'))}")
    elif event.get("from"):
        lines.append(f"What changed: {state} at {_when(event.get('at'))}, "
                     f"was {event['from']}")
    else:
        lines.append(f"What changed: {state}")
    if behind and behind in places:
        lines.append(f"Behind: {_name(places, behind)}")
    went = [i for i in (pfeed.get("causes") or {}).get(subject) or [] if i in places]
    if went:
        lines.append("Went with it: " + _listed([_name(places, i) for i in went]))
    deps = needed_by(edges, subject, known)
    if deps:
        lines.append("Depends on it: " + _listed([_name(places, i) for i in deps]))
    elif state == "down":
        lines.append("Nothing is declared to depend on it.")
    link = _link("place=" + quote(subject, safe=""))
    return {"title": f"{name} {STATE_WORDS.get(state, 'changed to ' + state)}",
            "body": "\n".join(lines),
            "priority": "high" if state == "down" else "default",
            "link": link, "tags": [state]}


def compose_digest(digest, view, feed, hidden, now):
    """The daily digest, from the no-group view, or None with nothing to say."""
    import certs
    places, _, _ = _visible_targets(view)
    sections = []

    today = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    near = []
    for cert in view.get("certs") or []:
        days = certs.days_left(cert, today) if isinstance(cert, dict) else None
        if days is None or days > digest["cert_days"]:
            continue
        place = cert.get("place")
        where = places.get(place) if isinstance(place, str) else None
        label = str(cert.get("name") or "a certificate")
        if where:
            label += f" ({_name(places, where['id'])})"
        when = f"lapsed {-days} days ago" if days < 0 else f"lapses in {days} days"
        near.append((days, f"{label}: {when}"))
    if near:
        near.sort()
        sections.append("Certificates near lapsing: " + _listed([t for _, t in near]))

    cutoff = iso_utc(now - digest["review_days"] * 86400)
    stale = []
    for pid, node in places.items():
        mark = node.get("provenance") if isinstance(node.get("provenance"), dict) else None
        if mark is None:
            continue                      # charted before provenance: unknown, not stale
        last = mark.get("reviewed_at") if mark.get("reviewed") else None
        since = last or mark.get("charted_at")
        if isinstance(since, str) and since and since < cutoff:
            stale.append(_name(places, pid))
    if stale:
        sections.append(f"Not reviewed in {digest['review_days']} days: " + _listed(sorted(stale)))

    if digest.get("drift"):
        # UNCHARTED MONITORS ARE NAMED ONLY WHILE NOTHING IS HIDDEN (2026-11-13).
        # `feed` is the raw feed: the no-group feed has no drift at all, since an
        # uncharted monitor is survey information. A monitor's name is free text
        # the map never charted, so matching it against the hidden places' words
        # misses one called something else ("nas-https" for a place named Vault).
        # While any place is hidden, the digest gives the count and no names,
        # and says nothing of why (a message never tells that something is hidden).
        names = [n for n in ((feed.get("drift") or {}).get("uncharted") or [])
                 if isinstance(n, str) and n]
        if names and hidden is None:
            sections.append("Monitors the map has not charted: " + _listed(names))
        elif names:
            sections.append(f"Monitors the map has not charted: {len(names)} (see Atlas)")

    if not sections:
        return None
    return {"title": "Atlas daily digest", "body": "\n".join(sections),
            "priority": "default", "link": _link(), "tags": ["digest"]}


def _texts(message):
    return [str(message.get("title") or ""), str(message.get("body") or ""),
            str(message.get("link") or ""), " ".join(map(str, message.get("tags") or []))]


# ── The tick ─────────────────────────────────────────────────────────────────
def public_feed(feed, data, ctx=None):
    """The feed as a viewer with no access groups gets it (`_redact_feed`),
    without the rites, whose cut reads the request's viewer and which alerts
    do not read."""
    from api.v2.feeds import _redact_feed
    bare = {k: v for k, v in (feed or {}).items() if k != "rites"}
    return _redact_feed(ctx, bare, frozenset(), data=clean_data(data))


class _Run:
    """One tick's sends: the state it charges, and what to write after the lock."""

    def __init__(self, state, dests, hidden, now):
        self.state, self.dests, self.hidden, self.now = state, dests, hidden, now
        self.logs, self.notes, self.sent = [], [], 0

    def _prune(self):
        st, now = self.state, self.now
        st["all"] = [t for t in st["all"] if now - t < 3600]
        st["sent"] = {k: [t for t in v if now - t < 60] for k, v in st["sent"].items()}
        st["sent"] = {k: v for k, v in st["sent"].items() if v}

    def allowed(self, dest_id):
        self._prune()
        return (len(self.state["sent"].get(dest_id, [])) < PER_DESTINATION_PER_MINUTE
                and len(self.state["all"]) < PER_HOUR)

    def _entry(self, rule_id, dest, event_ids, outcome, status=None, why=None, folded=None):
        entry = {"at": iso_utc(self.now), "rule": rule_id, "destination": dest.get("name"),
                 "events": list(event_ids), "outcome": outcome, "status": status, "why": why}
        if folded:
            entry["folded"] = folded
        return entry

    def failed(self, rule_id, dest, event_ids, why):
        """A message that could not be put together: nothing sent, one log line."""
        self.logs.append(self._entry(rule_id, dest, event_ids, "blocked", why=why))

    def fold(self, dest, event_ids):
        """Over the limit: counted into one "and N more changes" message at the
        next tick, whose log line carries the count (`folded`). Never dropped."""
        bucket = self.state["folded"].setdefault(dest["id"], {"count": 0, "events": []})
        bucket["count"] += 1
        bucket["events"] = ((bucket.get("events") or []) + list(event_ids))[-100:]

    def deliver(self, rule_id, dest, message, event_ids, folded=None):
        """Send one message if the limit allows, else fold it. Every send is
        logged; a delivered one notes "sent to" on its events."""
        if self.hidden and any(self.hidden.search(t) for t in _texts(message)):
            self.logs.append(self._entry(rule_id, dest, event_ids, "blocked",
                                         why="would name a hidden place", folded=folded))
            return "blocked"
        if not self.allowed(dest["id"]):
            self.fold(dest, event_ids)
            return "folded"
        try:
            result = _sender().send(dest, message) or {}
        except Exception as e:      # noqa: BLE001 — a sender fault is one failed send
            result = {"outcome": "unreachable", "status": None, "why": type(e).__name__}
        self.state["all"].append(self.now)
        self.state["sent"].setdefault(dest["id"], []).append(self.now)
        outcome = result.get("outcome") or "unreachable"
        self.logs.append(self._entry(rule_id, dest, event_ids, outcome,
                                     result.get("status"), result.get("why"), folded=folded))
        if outcome == "delivered":
            self.sent += 1
            if event_ids:
                self.notes.append((list(event_ids), dest.get("name"), iso_utc(self.now)))
        return outcome

    def send_folds(self):
        """Last tick's overflow, one message per destination, if the limit allows."""
        for dest_id, bucket in list(self.state["folded"].items()):
            dest = self.dests.get(dest_id)
            if dest is None:
                self.state["folded"].pop(dest_id, None)
                continue
            if not bucket.get("count") or not self.allowed(dest_id):
                continue
            n = bucket["count"]
            message = {"title": f"Atlas: {n} more change{'s' if n != 1 else ''}",
                       "body": f"and {n} more change{'s' if n != 1 else ''}, see Atlas",
                       "priority": "default", "link": _link(), "tags": ["folded"]}
            events_covered = [e for e in bucket.get("events") or [] if isinstance(e, int)]
            self.state["folded"].pop(dest_id, None)
            self.deliver("fold", dest, message, events_covered, folded=n)


def _idle():
    """Alerts are off: keep the sequence current, so turning them on later does
    not replay what happened while they were off. Touches nothing until a tick
    has run once (no state file appears on an instance that never used them)."""
    if not os.path.exists(settings.ALERTS_STATE_PATH):
        return
    import events
    try:
        with exclusive(lock_for(settings.ALERTS_STATE_PATH), timeout=LOCK_WAIT):
            state = _STATE.load()
            seq = events.current_seq()
            if state["seq"] == seq and not state["timers"]:
                return
            state["seq"], state["timers"] = seq, []
            _STATE.save(state)
    except LockTimeout:
        pass


def tick(feed, data, now=None, ctx=None):
    """Handle what the annals recorded since the last tick, send what is due,
    and the digest once a day. Returns a small summary. Never sends unless
    `settings.alerts_on()`."""
    if not settings.alerts_on():
        _idle()
        return {"skipped": "off"}
    now = time.time() if now is None else now
    doc, _ = read()
    run = None
    try:
        with exclusive(lock_for(settings.ALERTS_STATE_PATH), timeout=LOCK_WAIT):
            state = _STATE.load()
            dests = {d["id"]: d for d in doc["destinations"] if isinstance(d.get("id"), str)}
            run = _Run(state, dests, hidden_pattern(data), now)
            # WHAT WAS SENT IS KEPT, WHATEVER HAPPENS NEXT (2026-11-13). The state
            # used to be saved only when the whole tick finished, so a fault after
            # a send (a digest that raised) left it as it was, and the next poll
            # sent the same messages again, with no log line for any of them. It
            # is saved on the way out now, and the log lines below are written
            # whether or not the tick finished.
            try:
                _tick_locked(run, doc, feed, data, now, ctx)
                state["last_tick"] = iso_utc(now)
            finally:
                _STATE.save(state)
    except LockTimeout:
        return {"skipped": "busy"}
    finally:
        if run is not None:
            _write_after(run)
    return {"sent": run.sent, "logged": len(run.logs)}


def _write_after(run):
    """The delivery log lines and the annals' "sent to" notes. Written after
    the state's lock is let go, so no two file locks nest."""
    sender = _sender()
    for entry in run.logs:
        try:
            sender.log_delivery(entry)
        except Exception as e:      # noqa: BLE001
            log.warning("alerts: could not log a delivery: %s", type(e).__name__)
    if run.notes:
        import events
        for ids, to, at in run.notes:
            try:
                events.note_sent(ids, to, at)
            except Exception as e:  # noqa: BLE001
                log.warning("alerts: could not note a send on the annals: %s", type(e).__name__)


def _tick_locked(run, doc, feed, data, now, ctx):
    """One tick's work on `run.state`, which the caller saves however this
    ends. So the state is whole at every point a send can happen: the sequence
    moves on only together with the timers its new events started."""
    import events
    from dependencies import declared_edges

    state, dests = run.state, run.dests
    seq_now = events.current_seq()
    if state["seq"] is None:
        # the first tick ever: start from now, never replay the annals' history
        seq = seq_now
        fresh = []
    else:
        fresh = events.since(state["seq"])
        seq = max([state["seq"]] + [e["id"] for e in fresh])

    view = public_view(data)
    pfeed = public_feed(feed, data, ctx)
    places, sets, _ = _visible_targets(view)
    rules = [r for r in doc["rules"]
             if r.get("enabled") and r.get("destination") in dests and isinstance(r.get("id"), str)]
    by_id = {r["id"]: r for r in rules}

    # 1. new events start (or cancel) timers. Node events only: tripwires,
    #    services and rites are out of this stage.
    timers = state["timers"]
    for ev in fresh:
        if ev.get("kind") != "node" or ev.get("target") not in places:
            continue
        pid = ev["target"]
        for rule in rules:
            if not _matches(rule, pid, places, sets):
                continue
            timers = [t for t in timers if not (t.get("rule") == rule["id"] and t.get("target") == pid)]
            if ev.get("to") in (rule.get("to") or []):
                timers.append({"rule": rule["id"], "event": ev["id"], "target": pid,
                               "state": ev["to"], "due": now + 60 * int(rule.get("for_minutes") or 0)})
    timers = timers[-MAX_TIMERS:]
    state["seq"], state["timers"] = seq, timers

    # 2. what overflowed last tick goes first
    run.send_folds()

    # 3. the timers that are due
    annals = {e.get("id"): e for e in events.load()["events"] if isinstance(e, dict)}
    nodes = pfeed.get("nodes") or {}
    under = set(pfeed.get("maintenance") or [])
    pending, due = [], []
    for t in timers:
        if not isinstance(t.get("due"), (int, float)) or t.get("rule") not in by_id:
            continue                                  # a rule since deleted or switched off
        if t["due"] > now:
            pending.append(t)
            continue
        info = nodes.get(t.get("target")) or {}
        event = annals.get(t.get("event")) or {}
        if t.get("target") not in places or info.get("state") != t.get("state"):
            continue                                  # hidden now, or it left that state
        if event.get("ack"):
            continue                                  # a person has it: no repeats
        if t["target"] in under or info.get("planned"):
            continue                                  # inside a maintenance window: silence
        due.append((by_id[t["rule"]], t, info))

    # 4. ONE MESSAGE FOR A CASCADE. A consequence whose root cause is visible in
    #    the no-group feed, and which a rule also matches in its current state,
    #    is folded into the root: one message per root and destination in this
    #    tick, titled for the root and listing what went with it. If the root's
    #    own message is due now, that is the one. If the root fell in an earlier
    #    poll (sources rarely agree to the poll), or its own send failed, the
    #    root is sent again now with what went with it; not while the root's own
    #    "stays for" is still running (that message will list them) and not once
    #    a person has acknowledged the root. A root that is hidden was cut from
    #    the feed, so the consequence goes out as its own and never names it.
    messages = {}
    folded_into = []
    for rule, t, info in due:
        pid = t["target"]
        root = info.get("cause")
        if root and root != pid and root in places:
            root_state = (nodes.get(root) or {}).get("state")
            root_rules = _rules_for(root, root_state, rules, places, sets)
            if root_rules:
                folded_into.append((root, root_rules, t))
                continue
        key = (pid, rule["destination"])
        m = messages.setdefault(key, {"subject": pid, "state": t["state"], "rule": rule,
                                      "event": annals.get(t["event"]), "events": [],
                                      "behind": root if root in places else None})
        m["events"].append(t["event"])
    waiting = {(t.get("rule"), t.get("target")) for t in pending}
    for root, root_rules, t in folded_into:
        root_event = max((e for e in annals.values()
                          if e.get("kind") == "node" and e.get("target") == root),
                         key=lambda e: e.get("id") or 0, default=None)
        for rule in root_rules:
            key = (root, rule["destination"])
            m = messages.get(key)
            if m is None:
                if (rule["id"], root) in waiting or (root_event or {}).get("ack"):
                    continue
                m = messages[key] = {
                    "subject": root, "rule": rule, "event": root_event, "behind": None,
                    "state": (nodes.get(root) or {}).get("state"), "events": []}
            m["events"].append(t["event"])

    edges = declared_edges(view) if messages else {}
    known = set(places)
    # the due timers leave the state only here (2026-11-13): the state is
    # saved however the tick ends, so a fault between taking them out and
    # sending would lose the alert. Past this line each send is guarded.
    state["timers"] = pending
    if messages:
        for (pid, dest_id), m in sorted(messages.items()):
            try:
                message = compose(pid, m["state"], m["event"], view, pfeed, edges, known,
                                  behind=m["behind"])
            except Exception as e:  # noqa: BLE001 — one message, not the tick
                log.warning("alerts: could not compose a message: %s", type(e).__name__)
                run.failed(m["rule"]["id"], dests[dest_id], m["events"],
                           "the message could not be put together")
                continue
            run.deliver(m["rule"]["id"], dests[dest_id], message, m["events"])

    # 5. the digest, once a day at its hour (the server's local time)
    digest = doc["digest"]
    if digest.get("enabled") and digest.get("destination") in dests:
        local = time.localtime(now)
        today = time.strftime("%Y-%m-%d", local)
        if local.tm_hour >= int(digest.get("hour") or 0) and state["digest_day"] != today:
            state["digest_day"] = today
            dest = dests[digest["destination"]]
            try:
                message = compose_digest(digest, view, feed, run.hidden, now)
            except Exception as e:  # noqa: BLE001 — the digest, not the tick
                log.warning("alerts: could not compose the digest: %s", type(e).__name__)
                run.failed("digest", dest, [], "the digest could not be put together")
                message = None
            if message:
                run.deliver("digest", dest, message, [])


# ── A test send ──────────────────────────────────────────────────────────────
def instance_title(data):
    meta = (data or {}).get("meta") if isinstance(data, dict) else None
    title = meta.get("title") if isinstance(meta, dict) else None
    return str(title or settings.APP_NAME)


def trial_message(data):
    """The fixed test message: nothing about the map but its title."""
    return {"title": f"Atlas test from {instance_title(data)}",
            "body": "This is a test. If you can read it, alerts reach this destination.",
            "priority": "default", "link": None, "tags": ["test"]}
