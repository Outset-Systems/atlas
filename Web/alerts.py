import datetime
import hashlib
import json
import logging
import os
import re
import time
from urllib.parse import quote

import schema
import settings
from filelock import LockTimeout, exclusive, lock_for
from jsonio import iso_utc
from jsonstore import JsonStore
from engines.base import NODE_STATES

log = logging.getLogger("atlas.live.alerts")

TARGET_KINDS = ("place", "collection", "network", "service")
OLD_TARGET_KINDS = {"set": "collection"}


def rule_on(rule):
    return rule.get("enabled", True) is True or rule.get("enabled") is None


def target_kind(kind):
    return OLD_TARGET_KINDS.get(kind, kind) if isinstance(kind, str) else kind
MAX_RULES = 100
TIMER_FAULTS = 3
MAX_DESTINATIONS = 20
MAX_FOR_MINUTES = 1440
MAX_TIMERS = 500
PER_DESTINATION_PER_MINUTE = 6
PER_HOUR = 30
LOCK_WAIT = 2.0
LIST_CAP = 12

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

STATE_WORDS = {"down": "is down", "degraded": "is degraded", "healthy": "is back up",
               "slumbering": "is asleep", "maintenance": "is under maintenance"}

DIGEST_DEFAULTS = {"enabled": False, "hour": 8, "destination": None, "cert_days": 30,
                   "review_days": 90, "drift": False, "uncharted": False}

UNCHARTED_REFUSED = ("the digest cannot list uncharted devices yet: no feed the poll "
                     "already builds carries them")


def _sender():
    import alert_send
    return alert_send


def _shape(raw):
    raw = raw if isinstance(raw, dict) else {}
    rules = raw.get("rules")
    dests = raw.get("destinations")
    digest = raw.get("digest") if isinstance(raw.get("digest"), dict) else {}
    rules = [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []
    rules = [{**r, "target": {**r["target"], "kind": target_kind(r["target"].get("kind"))}}
             if isinstance(r.get("target"), dict) and target_kind(r["target"].get("kind"))
             != r["target"].get("kind") else r for r in rules]
    return {
        "rules": rules,
        "digest": {**DIGEST_DEFAULTS, **{k: v for k, v in digest.items() if k in DIGEST_DEFAULTS}},
        "destinations": [d for d in dests if isinstance(d, dict)] if isinstance(dests, list) else [],
    }


_STORE = JsonStore(lambda: settings.ALERTS_PATH, _shape)


class StaleError(Exception):
    pass


def _stamp_of(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:16]


def read():
    doc = _STORE.load()
    return doc, _stamp_of(doc)


def save(doc, expect=None):
    with _STORE.locked():
        stored = _STORE.load()
        if expect is not None and expect != _stamp_of(stored):
            raise StaleError("the alerts changed since they were read")
        _STORE.save(_shape(doc))
        return _stamp_of(_STORE.load())


def normalize(doc):
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
            r["target"] = {"kind": target_kind(r["target"].get("kind")), "id": r["target"].get("id")}
    out["destinations"] = [{k: d.get(k) for k in ("id", "name", "kind", "url", "secret",
                                                  "secret_origin")}
                           for d in out["destinations"]]
    for d in out["destinations"]:
        if isinstance(d["secret"], str) and not d["secret"].strip():
            d["secret"] = None
    return out


def _int_in(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def clean_data(data):
    data = data if isinstance(data, dict) else {}
    nodes = [n for n in data.get("nodes") or []
             if isinstance(n, dict) and isinstance(n.get("id"), str) and n["id"]]
    return {**data, "nodes": nodes}


def public_view(data):
    import redaction
    return redaction.redact(clean_data(data), frozenset(), token=True)[0]


def _objects(data):
    data = data if isinstance(data, dict) else {}
    nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    return {**data, "nodes": [n for n in nodes if isinstance(n, dict)]}


def hidden_pattern(data):
    import redaction
    return redaction.hidden_words(_objects(data), frozenset())


def hidden_slug_pattern(data):
    import redaction
    return redaction.hidden_slugs(_objects(data), frozenset())


def _visible_targets(view):
    places = {n["id"]: n for n in view.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    listed = view.get("collections")
    collections = {s["id"]: s for s in (listed if isinstance(listed, list) else [])
                   if isinstance(s, dict) and isinstance(s.get("id"), str)}
    networks = {n["zone"] for n in places.values() if isinstance(n.get("zone"), str) and n["zone"]}
    return places, collections, networks


def _visible_services(view):
    from engines.places import service_places
    return service_places(view)


def _visible_all(view):
    return (*_visible_targets(view), _visible_services(view))


def _target_in(target, visible):
    if not isinstance(target, dict):
        return False
    places, collections, networks = visible[:3]
    services = visible[3] if len(visible) > 3 else {}
    kind, tid = target_kind(target.get("kind")), target.get("id")
    if not isinstance(tid, str):
        return False
    return ((kind == "place" and tid in places) or (kind == "collection" and tid in collections)
            or (kind == "network" and tid in networks) or (kind == "service" and tid in services))


def suspended(doc, data):
    visible = _visible_all(public_view(data))
    return [r.get("id") for r in doc.get("rules") or []
            if rule_on(r) and not _target_in(r.get("target"), visible)]


def held_places(data):
    seen = set(_visible_targets(public_view(data))[0])
    return sorted(n["id"] for n in clean_data(data).get("nodes") or [] if n["id"] not in seen)


def validate(doc, data):
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
        if isinstance(did, str):
            dest_ids.add(did)
        problems += [f"destination {label}: {p}" for p in sender.check_destination(d) or []]

    visible = _visible_all(public_view(data))
    stored, stored_enabled = {}, {}
    for r in read()[0].get("rules") or []:
        if not isinstance(r, dict):
            continue
        t = r.get("target")
        if isinstance(r.get("id"), str) and isinstance(t, dict):
            stored[r["id"]] = (target_kind(t.get("kind")), t.get("id"))
        if isinstance(r.get("id"), str) and "enabled" in r:
            stored_enabled[r["id"]] = r["enabled"]
    rule_ids = set()
    for i, r in enumerate(rules):
        rid = r.get("id")
        label = rid if isinstance(rid, str) and _ID.match(rid) else f"#{i + 1}"
        if not (isinstance(rid, str) and _ID.match(rid)):
            problems.append(f"rule {label}: its id must be lower-case letters, digits and dashes")
        elif rid in rule_ids:
            problems.append(f"rule {label}: the id is used twice")
        if isinstance(rid, str):
            rule_ids.add(rid)
        if not isinstance(r.get("name"), str) or len(r["name"]) > 80:
            problems.append(f"rule {label}: its name must be text of at most 80 characters")
        if not isinstance(r.get("note"), str) or len(r["note"]) > 300:
            problems.append(f"rule {label}: its note must be text of at most 300 characters")
        if not isinstance(r.get("enabled"), bool) and not (
                isinstance(rid, str) and rid in stored_enabled
                and isinstance(stored_enabled[rid], bool) == isinstance(r.get("enabled"), bool)
                and stored_enabled[rid] == r.get("enabled")):
            problems.append(f"rule {label}: enabled must be true or false")
        target = r.get("target")
        if not (isinstance(target, dict) and target_kind(target.get("kind")) in TARGET_KINDS
                and isinstance(target.get("id"), str) and target["id"]):
            problems.append(f"rule {label}: its target must be a place, a collection, a network or a service")
        elif not _target_in(target, visible) and (
                not isinstance(rid, str)
                or stored.get(rid) != (target_kind(target.get("kind")), target.get("id"))):
            problems.append(f"rule {label}: that {target_kind(target['kind'])} cannot be alerted on. It is "
                            "not on the map, or a viewer with no access groups cannot see it, "
                            "and a message about it could not be sent without naming it")
        to = r.get("to")
        if not (isinstance(to, list) and to and all(isinstance(s, str) and s in NODE_STATES for s in to)):
            problems.append(f"rule {label}: it needs one or more states from "
                            + ", ".join(sorted(NODE_STATES)))
        if not _int_in(r.get("for_minutes"), 0, MAX_FOR_MINUTES):
            problems.append(f"rule {label}: how long it must stay is a whole number of "
                            f"minutes from 0 to {MAX_FOR_MINUTES}")
        if not (isinstance(r.get("destination"), str) and r["destination"] in dest_ids):
            problems.append(f"rule {label}: it sends to a destination that does not exist")

    if not isinstance(digest.get("enabled"), bool):
        problems.append("digest: enabled must be true or false")
    if not _int_in(digest.get("hour"), 0, 23):
        problems.append("digest: the hour is a whole number from 0 to 23 (the server's local time)")
    if digest.get("enabled") and not (isinstance(digest.get("destination"), str)
                                      and digest["destination"] in dest_ids):
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
    out = {**doc, "destinations": []}
    for d in doc.get("destinations") or []:
        shown = {k: v for k, v in d.items() if k != "secret_origin"}
        shown["secret_bound"] = bool(d.get("secret") and d.get("secret_origin"))
        out["destinations"].append(shown)
    return out


def _state_shape(raw):
    raw = raw if isinstance(raw, dict) else {}

    def times(value):
        return [t for t in value if isinstance(t, (int, float))] if isinstance(value, list) else []

    sent = raw.get("sent") if isinstance(raw.get("sent"), dict) else {}
    folded = raw.get("folded") if isinstance(raw.get("folded"), dict) else {}
    seq = raw.get("seq")
    return {
        "seq": seq if isinstance(seq, int) and not isinstance(seq, bool) else None,
        "timers": [t for t in raw.get("timers") or []
                   if isinstance(t, dict) and isinstance(t.get("rule"), str)
                   and isinstance(t.get("target"), str)
                   and isinstance(t.get("due"), (int, float)) and not isinstance(t.get("due"), bool)
                   and isinstance(t.get("event"), int) and not isinstance(t.get("event"), bool)
                   and isinstance(t.get("state"), str)]
        if isinstance(raw.get("timers"), list) else [],
        "sent": {k: times(v) for k, v in sent.items()},
        "all": times(raw.get("all")),
        "folded": {k: {**v, "events": [e for e in v.get("events")
                                       if isinstance(e, int) and not isinstance(e, bool)]
                       if isinstance(v.get("events"), list) else []}
                   for k, v in folded.items()
                   if isinstance(v, dict) and isinstance(v.get("count"), int)
                   and not isinstance(v.get("count"), bool) and v["count"] > 0},
        "digest_day": raw.get("digest_day") if isinstance(raw.get("digest_day"), str) else None,
        "last_tick": raw.get("last_tick") if isinstance(raw.get("last_tick"), str) else None,
    }


_STATE = JsonStore(lambda: settings.ALERTS_STATE_PATH, _state_shape)


def last_tick():
    return _STATE.load()["last_tick"]


def _matches(rule, place_id, places, collections):
    target = rule.get("target")
    if not isinstance(target, dict):
        return False
    kind, tid = target_kind(target.get("kind")), target.get("id")
    if not isinstance(tid, str):
        return False
    if kind == "place":
        return place_id == tid
    if kind == "collection":
        members = schema.as_list((collections.get(tid) or {}).get("places"))
        return place_id in members
    if kind == "network":
        return bool(tid) and (places.get(place_id) or {}).get("zone") == tid
    return False


def _matches_service(rule, key, services, collections):
    target = rule.get("target")
    if not isinstance(target, dict):
        return False
    kind, tid = target_kind(target.get("kind")), target.get("id")
    if not isinstance(tid, str) or key not in services:
        return False
    if kind == "service":
        return tid == key
    if kind == "collection":
        return key in schema.as_list((collections.get(tid) or {}).get("services"))
    return False


def _rules_for(place_id, state, rules, places, collections):
    return [r for r in rules
            if _matches(r, place_id, places, collections) and state in (r.get("to") or [])]


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
    if isinstance(at, str) and len(at) >= 16 and at.endswith("Z"):
        return at[:10] + " " + at[11:16] + " UTC"
    return str(at or "")


def compose(subject, state, event, view, pfeed, edges, known, behind=None):
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


def compose_service(key, state, event, view, services):
    places, _, _ = _visible_targets(view)
    pid = services.get(key)
    place = _name(places, pid) if pid else ""
    label = key
    for link in (places.get(pid) or {}).get("links") or []:
        from engines.places import service_key
        if isinstance(link, dict) and service_key(pid, link) == key:
            label = str(link.get("label") or key)
            break
    event = event or {}
    lines = [f"Service: {label}" + (f" on {place}" if place else "")]
    if event.get("from"):
        lines.append(f"What changed: {state} at {_when(event.get('at'))}, was {event['from']}")
    else:
        lines.append(f"What changed: {state}")
    link = _link("place=" + quote(pid, safe="")) if pid else _link()
    return {"title": f"{label}{' on ' + place if place else ''} {STATE_WORDS.get(state, 'changed to ' + state)}",
            "body": "\n".join(lines),
            "priority": "high" if state == "down" else "default",
            "link": link, "tags": [state, "service"]}


MODE_DAYS = 7


def _mode_left_on(view, places, now):
    import maintenance
    cutoff = datetime.datetime.fromtimestamp(now - MODE_DAYS * 86400, datetime.timezone.utc)
    listed = view.get("collections")
    col_names = ({c["id"]: str(c.get("name") or c["id"]) for c in listed
                  if isinstance(c, dict) and isinstance(c.get("id"), str)} if isinstance(listed, list) else {})
    try:
        windows = maintenance.read()["windows"]
    except Exception:
        return []
    found = {}
    for window in windows:
        if window.get("open") is not True:
            continue
        began = maintenance.parse_when(window.get("starts"))
        if began is None or began > cutoff:
            continue
        day = began.strftime("%Y-%m-%d")
        named = window.get("collections") if isinstance(window.get("collections"), list) else []
        for cid in named:
            if isinstance(cid, str) and cid in col_names:
                found.setdefault(f"the collection {col_names[cid]}", (began, day))
        through = set()
        for cid in named:
            if isinstance(cid, str) and cid in col_names:
                through |= maintenance.window_places({"collections": [cid]}, view)
        for pid in maintenance.window_places({"nodes": window.get("nodes")}, view):
            if pid in places and pid not in through:
                found.setdefault(_name(places, pid), (began, day))
        svc = _visible_services(view)
        for key in window.get("services") if isinstance(window.get("services"), list) else []:
            if isinstance(key, str) and key in svc:
                label = key
                for link in (places.get(svc[key]) or {}).get("links") or []:
                    from engines.places import service_key
                    if isinstance(link, dict) and service_key(svc[key], link) == key:
                        label = str(link.get("label") or key)
                found.setdefault(f"{label} on {_name(places, svc[key])}", (began, day))
    return [f"{label} (since {day})" for label, (_, day) in sorted(found.items(), key=lambda kv: kv[1][0])]


def compose_digest(digest, view, feed, hidden, now):
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
            continue
        last = mark.get("reviewed_at") if mark.get("reviewed") else None
        since = last or mark.get("charted_at")
        if isinstance(since, str) and since and since < cutoff:
            stale.append(_name(places, pid))
    if stale:
        sections.append(f"Not reviewed in {digest['review_days']} days: " + _listed(sorted(stale)))

    left = _mode_left_on(view, places, now)
    if left:
        sections.append(f"In maintenance mode more than {MODE_DAYS} days: " + _listed(left))

    if digest.get("drift"):
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
    link = str(message.get("link") or "")
    base = settings.PUBLIC_URL or ""
    if base and link.startswith(base):
        link = link[len(base):]
    return [str(message.get("title") or ""), str(message.get("body") or ""),
            link, " ".join(map(str, message.get("tags") or []))]


def public_feed(feed, data, ctx=None):
    from api.v2.feeds import _redact_feed
    bare = {k: v for k, v in (feed or {}).items() if k != "rites"}
    return _redact_feed(ctx, bare, frozenset(), data=clean_data(data))


class _Run:

    def __init__(self, state, dests, hidden, now, hidden_slugs=None):
        self.state, self.dests, self.hidden, self.now = state, dests, hidden, now
        self.hidden_slugs = hidden_slugs
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
        self.logs.append(self._entry(rule_id, dest, event_ids, "blocked", why=why))

    def fold(self, dest, event_ids):
        bucket = self.state["folded"].setdefault(dest["id"], {"count": 0, "events": []})
        bucket["count"] += 1
        bucket["events"] = ((bucket.get("events") or []) + list(event_ids))[-100:]

    def deliver(self, rule_id, dest, message, event_ids, folded=None):
        if any((self.hidden and self.hidden.search(t))
               or (self.hidden_slugs and self.hidden_slugs.in_text(t))
               for t in _texts(message)):
            self.logs.append(self._entry(rule_id, dest, event_ids, "blocked",
                                         why="would name a hidden place", folded=folded))
            return "blocked"
        if not self.allowed(dest["id"]):
            self.fold(dest, event_ids)
            return "folded"
        try:
            result = _sender().send(dest, message) or {}
        except Exception as e:
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
        for dest_id, bucket in list(self.state["folded"].items()):
            try:
                self._send_fold(dest_id, bucket)
            except Exception:
                log.warning("alerts: dropped a folded message it could not read (%s)",
                            dest_id, exc_info=True)
                self.state["folded"].pop(dest_id, None)

    def _send_fold(self, dest_id, bucket):
        dest = self.dests.get(dest_id)
        if dest is None:
            self.state["folded"].pop(dest_id, None)
            return
        if not bucket.get("count") or not self.allowed(dest_id):
            return
        n = bucket["count"]
        message = {"title": f"Atlas: {n} more change{'s' if n != 1 else ''}",
                   "body": f"and {n} more change{'s' if n != 1 else ''}, see Atlas",
                   "priority": "default", "link": _link(), "tags": ["folded"]}
        events_covered = [e for e in bucket.get("events") or [] if isinstance(e, int)]
        self.state["folded"].pop(dest_id, None)
        self.deliver("fold", dest, message, events_covered, folded=n)


def _idle():
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
            run = _Run(state, dests, hidden_pattern(data), now, hidden_slug_pattern(data))
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
    sender = _sender()
    for entry in run.logs:
        try:
            sender.log_delivery(entry)
        except Exception as e:
            log.warning("alerts: could not log a delivery: %s", type(e).__name__, exc_info=True)
    if run.notes:
        import events
        for ids, to, at in run.notes:
            try:
                events.note_sent(ids, to, at)
            except Exception as e:
                log.warning("alerts: could not note a send on the annals: %s", type(e).__name__, exc_info=True)


def _tick_locked(run, doc, feed, data, now, ctx):
    import events
    from dependencies import declared_edges

    state, dests = run.state, run.dests
    seq_now = events.current_seq()
    trusted = events.readable_seq() if isinstance(state["seq"], int) and state["seq"] > seq_now else None
    if isinstance(trusted, int) and state["seq"] > trusted:
        log.warning("alerts: the sequence was ahead of the annals (%s > %s); starting from now",
                    state["seq"], trusted)
        state["seq"] = trusted
    if state["seq"] is None:
        seq = seq_now
        fresh = []
    else:
        fresh = [e for e in events.since(state["seq"])
                 if isinstance(e, dict) and isinstance(e.get("id"), int) and not isinstance(e.get("id"), bool)]
        seq = max([state["seq"]] + [e["id"] for e in fresh])

    view = public_view(data)
    pfeed = public_feed(feed, data, ctx)
    places, collections, _ = _visible_targets(view)
    services = _visible_services(view)
    rules = [r for r in doc["rules"]
             if rule_on(r) and isinstance(r.get("destination"), str)
             and r["destination"] in dests and isinstance(r.get("id"), str)
             and isinstance(r.get("target"), dict) and isinstance(r.get("to"), list)
             and all(isinstance(s, str) for s in r["to"])
             and _int_in(r.get("for_minutes") if r.get("for_minutes") is not None else 0,
                         0, MAX_FOR_MINUTES)]
    by_id = {r["id"]: r for r in rules}

    timers = state["timers"]
    is_node = lambda t: (t.get("kind") or "node") == "node"
    for ev in fresh:
        target = ev.get("target")
        if ev.get("kind") == "service" and isinstance(target, str) and target in services:
            for rule in rules:
                try:
                    if not _matches_service(rule, target, services, collections):
                        continue
                    timers = [t for t in timers if not (t.get("kind") == "service"
                                                        and t.get("rule") == rule["id"] and t.get("target") == target)]
                    if isinstance(ev.get("to"), str) and ev["to"] in rule["to"]:
                        timers.append({"rule": rule["id"], "event": ev["id"], "target": target, "kind": "service",
                                       "state": ev["to"], "due": now + 60 * int(rule.get("for_minutes") or 0)})
                except Exception:
                    log.warning("alerts: skipped rule %s on annals event %s it could not read",
                                rule.get("id"), ev.get("id"), exc_info=True)
            continue
        if ev.get("kind") != "node" or not isinstance(target, str) or target not in places:
            continue
        for rule in rules:
            try:
                if not _matches(rule, target, places, collections):
                    continue
                timers = [t for t in timers if not (is_node(t) and t.get("rule") == rule["id"] and t.get("target") == target)]
                if isinstance(ev.get("to"), str) and ev["to"] in rule["to"]:
                    timers.append({"rule": rule["id"], "event": ev["id"], "target": target,
                                   "state": ev["to"], "due": now + 60 * int(rule.get("for_minutes") or 0)})
            except Exception:
                log.warning("alerts: skipped rule %s on annals event %s it could not read",
                            rule.get("id"), ev.get("id"), exc_info=True)
    timers = timers[-MAX_TIMERS:]
    state["seq"], state["timers"] = seq, timers

    run.send_folds()

    annals = {e["id"]: e for e in events.load()["events"]
              if isinstance(e, dict) and isinstance(e.get("id"), int)}
    nodes = pfeed.get("nodes") or {}
    under = {m for m in pfeed.get("maintenance") or [] if isinstance(m, str)} \
        if isinstance(pfeed.get("maintenance"), list) else set()
    svc_states = pfeed.get("services") if isinstance(pfeed.get("services"), dict) else {}
    svc_under = {k for k in pfeed.get("maintenance_services") or [] if isinstance(k, str)} \
        if isinstance(pfeed.get("maintenance_services"), list) else set()
    pending, due, due_services = [], [], []
    for t in timers:
        try:
            if not isinstance(t.get("due"), (int, float)) or t.get("rule") not in by_id:
                continue
            if t["due"] > now:
                pending.append(t)
                continue
            if t.get("kind") == "service":
                key = t.get("target")
                sinfo = svc_states.get(key) if isinstance(svc_states.get(key), dict) else {}
                event = annals.get(t.get("event")) or {}
                if key not in services or sinfo.get("state") != t.get("state"):
                    continue
                if event.get("ack") or key in svc_under:
                    continue
                pid = services[key]
                pinfo = nodes.get(pid) if isinstance(nodes.get(pid), dict) else {}
                if pid in under or pinfo.get("state") in ("down", "maintenance") or pinfo.get("planned"):
                    pending.append(t)
                    continue
                if not _matches_service(by_id[t["rule"]], key, services, collections):
                    continue
                if t.get("state") not in by_id[t["rule"]]["to"]:
                    continue
                due_services.append((by_id[t["rule"]], t))
                continue
            info = nodes.get(t.get("target")) or {}
            info = info if isinstance(info, dict) else {}
            event = annals.get(t.get("event")) or {}
            if t.get("target") not in places or info.get("state") != t.get("state"):
                continue
            if event.get("ack"):
                continue
            if t["target"] in under or info.get("planned"):
                continue
            if not _matches(by_id[t["rule"]], t["target"], places, collections):
                continue
            if t.get("state") not in by_id[t["rule"]]["to"]:
                continue
            due.append((by_id[t["rule"]], t, info))
        except Exception:
            faults = (t.get("faults") if isinstance(t.get("faults"), int) else 0) + 1
            if faults >= TIMER_FAULTS:
                log.warning("alerts: dropped a timer after %d faults (rule %s, place %s)",
                            faults, t.get("rule"), t.get("target"), exc_info=True)
            else:
                if faults == 1:
                    log.warning("alerts: kept a timer it could not read this tick", exc_info=True)
                pending.append({**t, "faults": faults})

    messages = {}
    folded_into = []
    for rule, t, info in due:
        pid = t["target"]
        root = info.get("cause")
        root = root if isinstance(root, str) else None
        if root and root != pid and root in places:
            root_info = nodes.get(root)
            root_state = root_info.get("state") if isinstance(root_info, dict) else None
            root_rules = _rules_for(root, root_state, rules, places, collections)
            if root_rules:
                folded_into.append((root, root_rules, t))
                continue
        key = (pid, rule["destination"])
        m = messages.setdefault(key, {"subject": pid, "state": t["state"], "rule": rule,
                                      "event": annals.get(t.get("event")), "events": [],
                                      "behind": root if root in places else None})
        m["events"].append(t.get("event"))
    waiting = {(t.get("rule"), t.get("target")) for t in pending if is_node(t)}
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
                    "state": (nodes.get(root) or {}).get("state") if isinstance(nodes.get(root), dict) else None,
                    "events": []}
            m["events"].append(t.get("event"))

    try:
        edges = declared_edges(view) if messages else {}
    except Exception:
        log.warning("alerts: could not read what depends on what", exc_info=True)
        edges = {}
    known = set(places)
    state["timers"] = pending
    if messages:
        for (pid, dest_id), m in sorted(messages.items()):
            try:
                message = compose(pid, m["state"], m["event"], view, pfeed, edges, known,
                                  behind=m["behind"])
            except Exception as e:
                log.warning("alerts: could not compose a message: %s", type(e).__name__, exc_info=True)
                run.failed(m["rule"]["id"], dests[dest_id], m["events"],
                           "the message could not be put together")
                continue
            run.deliver(m["rule"]["id"], dests[dest_id], message, m["events"])
    svc_messages = {}
    for rule, t in due_services:
        m = svc_messages.setdefault((t["target"], rule["destination"]), {
            "rule": rule, "state": t["state"], "event": annals.get(t.get("event")), "events": []})
        m["events"].append(t.get("event"))
    for (key, dest_id), m in sorted(svc_messages.items()):
        try:
            message = compose_service(key, m["state"], m["event"], view, services)
        except Exception as e:
            log.warning("alerts: could not compose a message: %s", type(e).__name__, exc_info=True)
            run.failed(m["rule"]["id"], dests[dest_id], m["events"], "the message could not be put together")
            continue
        run.deliver(m["rule"]["id"], dests[dest_id], message, m["events"])

    digest = doc["digest"]
    if digest.get("enabled") and isinstance(digest.get("destination"), str) \
            and digest["destination"] in dests:
        local = time.localtime(now)
        today = time.strftime("%Y-%m-%d", local)
        hour = digest.get("hour") if _int_in(digest.get("hour"), 0, 23) else None
        if hour is not None and local.tm_hour >= hour and state["digest_day"] != today:
            state["digest_day"] = today
            dest = dests[digest["destination"]]
            try:
                message = compose_digest(digest, view, feed, run.hidden, now)
            except Exception as e:
                log.warning("alerts: could not compose the digest: %s", type(e).__name__, exc_info=True)
                run.failed("digest", dest, [], "the digest could not be put together")
                message = None
            if message:
                run.deliver("digest", dest, message, [])


def instance_title(data):
    meta = (data or {}).get("meta") if isinstance(data, dict) else None
    title = meta.get("title") if isinstance(meta, dict) else None
    return str(title or settings.APP_NAME)


def trial_message(data):
    return {"title": f"Atlas test from {instance_title(data)}",
            "body": "This is a test. If you can read it, alerts reach this destination.",
            "priority": "default", "link": None, "tags": ["test"]}
