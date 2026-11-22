from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import certs
import dependencies
import events
import heartbeats
import maintenance
import provenance
import tripwires
from engines.base import NODE_STATES, monitor_map
from engines.places import service_key
from jsonio import iso_utc
from redaction import bare_url

MAINTENANCE_DAYS = 7
CERT_DAYS = 30
REVIEW_DAYS = 90
CHANGES_DAYS = 7
UNACKED_SHOWN = 8
REVIEW_SHOWN = 8
CHANGES_SHOWN = 8
DRIFT_SHOWN = 12
FAVOURITE_KINDS = ("internal", "external")
SOURCE_CONSOLES = {"kuma": "ATLAS_KUMA_URL", "prometheus": "ATLAS_PROM_URL",
                   "unifi": "ATLAS_UNIFI_URL"}

CRITICAL_DAYS = 30
CRITICAL_SENT = 200

STATES = ("healthy", "degraded", "down", "slumbering", "maintenance")
_FAULTS = ("down", "degraded")
_EVENT_KEYS = ("id", "at", "kind", "target", "name", "from", "to")


def _state(entry):
    return (entry or {}).get("state") if isinstance(entry, dict) else None


def summary(data, feed):
    nodes = data.get("nodes") or []
    tally = {"places": {}, "services": {}}
    for kind, rows in (("places", feed.get("nodes") or {}), ("services", feed.get("services") or {})):
        for row in rows.values():
            state = _state(row) or "unknown"
            tally[kind][state] = tally[kind].get(state, 0) + 1
    return {"title": (data.get("meta") or {}).get("title"),
            "surveyed": (data.get("meta") or {}).get("surveyed"),
            "zones": [z.get("name") or z.get("id") for z in data.get("zones") or []],
            "places": len(nodes),
            "services": sum(len(n.get("links") or []) for n in nodes),
            "roads": len(data.get("routes") or []),
            "health": tally, "sources": feed.get("sources") or {},
            "provenance": provenance.summary(nodes)}



def _places(data):
    return [n for n in data.get("nodes") or []
            if isinstance(n, dict) and isinstance(n.get("id"), str)]


def _ref(node):
    return {"id": node["id"], "name": node.get("name")}


def _name_key(node):
    return str(node.get("name") or node.get("id") or "").casefold()


def states(data, feed):
    live = feed.get("nodes") or {}
    out = {s: 0 for s in STATES}
    out["unknown"] = 0
    places = _places(data)
    for node in places:
        state = _state(live.get(node["id"]))
        out[state if state in NODE_STATES else "unknown"] += 1
    out["total"] = len(places)
    return out


def down(data, feed):
    live = feed.get("nodes") or {}
    by_id = {n["id"]: n for n in _places(data)}
    edges = dependencies.declared_edges(data)
    named = {need for needs in edges.values() for need in needs}
    out = []
    for nid, node in by_id.items():
        info = live.get(nid) if isinstance(live.get(nid), dict) else {}
        state = _state(info)
        if state not in _FAULTS:
            continue
        cause = info.get("cause") if isinstance(info.get("cause"), str) else None
        if cause in by_id and cause != nid:
            continue
        out.append({"id": nid, "name": node.get("name"), "state": state,
                    "cause": cause if cause in by_id else None,
                    "downstream": [_ref(by_id[d]) for d in dependencies.needed_by(edges, nid, by_id)],
                    "declared": nid in named})
    out.sort(key=lambda r: (_FAULTS.index(r["state"]), _name_key(r), r["id"]))
    return out


def unacked(data, admin):
    if admin:
        rows = events.listing(limit=events.KEEP, unacked_only=True)
    else:
        rows = tripwires.listing_without_trips(
            limit=events.KEEP, visible={n["id"] for n in _places(data)}, unacked_only=True,
            visible_services=_monitors(data),
            visible_rites=heartbeats.keys_of(data.get("rites")))
    items = [{k: row.get(k) for k in _EVENT_KEYS} for row in rows[:UNACKED_SHOWN]]
    return {"count": len(rows), "items": items}


def _service_places(data):
    out = {}
    for node in _places(data):
        for link in node.get("links") or []:
            if isinstance(link, dict):
                out.setdefault(service_key(node["id"], link), _ref(node))
    return out


def _settled(later, key_state):
    for ev in later:
        if ev.get("to") != "down":
            return {"status": "cleared", "cleared_at": ev.get("at"), "after": ev.get("to")}
    if key_state == "down":
        return {"status": "down", "cleared_at": None, "after": None}
    if key_state in NODE_STATES:
        return {"status": "cleared", "cleared_at": None, "after": key_state}
    return {"status": "unknown", "cleared_at": None, "after": None}


def critical(data, admin, now):
    edge = iso_utc((now - timedelta(days=CRITICAL_DAYS)).timestamp())
    store = events.load()
    every = [e for e in store["events"] if isinstance(e, dict)]
    if admin:
        rows = events.listing(limit=events.KEEP)
    else:
        rows = tripwires.listing_without_trips(
            limit=events.KEEP, visible={n["id"] for n in _places(data)},
            visible_services=_monitors(data),
            visible_rites=heartbeats.keys_of(data.get("rites")))
    grave = [e for e in rows if e.get("gravity") == "grave" and str(e.get("at") or "") >= edge]
    by_target = {}
    for ev in every:
        by_target.setdefault((ev.get("kind"), ev.get("target")), []).append(ev)
    places = {n["id"]: n for n in _places(data)}
    served = _service_places(data)
    known = store.get("state") or {}
    items = []
    for ev in grave[:CRITICAL_SENT]:
        kind, target = ev.get("kind"), ev.get("target")
        if kind == "tripwire":
            how = {"status": "acknowledged" if ev.get("ack") else "open",
                   "cleared_at": None, "after": None}
        else:
            eid = ev.get("id") if isinstance(ev.get("id"), int) else -1
            later = [x for x in by_target.get((kind, target), [])
                     if isinstance(x.get("id"), int) and x["id"] > eid]
            how = _settled(later, known.get(f"{kind}:{target}"))
        where = None
        if kind == "node" and target in places:
            where = _ref(places[target])
        elif kind == "service":
            where = served.get(target)
        items.append({"id": ev.get("id"), "at": ev.get("at"), "kind": kind, "target": target,
                      "name": ev.get("name") or target, "to": ev.get("to"),
                      "place": where, **how})
    oldest = next((e.get("at") for e in every if e.get("at")), None)
    since = oldest if len(every) >= events.KEEP and oldest and oldest > edge else None
    return {"days": CRITICAL_DAYS, "count": len(grave), "since": since, "items": items}


def _monitors(data):
    out = set()
    for node in _places(data):
        for link in node.get("links") or []:
            if isinstance(link, dict):
                out.add(service_key(node["id"], link))
    out.update(monitor_map(data))
    return out


def upcoming_maintenance(data, hidden, now):
    by_id = {n["id"]: n for n in _places(data)}
    until = now + timedelta(days=MAINTENANCE_DAYS)
    out = []
    for window in maintenance.annotated(now):
        state = window.get("state")
        if state == "upcoming":
            start = maintenance.parse_when(window.get("occurrence_start"))
            if start is None or start > until:
                continue
        elif state != "active":
            continue
        named = sorted(maintenance.window_places(window, data))
        places = [_ref(by_id[n]) for n in named if n in by_id]
        if not places:
            continue
        wid, reason = window.get("id"), window.get("reason")
        if hidden is not None and hidden.search(f"{wid or ''} {reason or ''}"):
            continue
        out.append({"window": wid, "reason": reason,
                    "starts": window.get("occurrence_start"), "ends": window.get("occurrence_end"),
                    "now": state == "active", "places": places})
    return out


def lapsing_certs(data, now):
    by_id = {n["id"]: n for n in _places(data)}
    out = []
    for cert in data.get("certs") or []:
        if not isinstance(cert, dict):
            continue
        days = certs.days_left(cert, now)
        if days is None or days > CERT_DAYS:
            continue
        place = cert.get("place")
        place = place if isinstance(place, str) else None
        out.append({"name": cert.get("name"),
                    "place": _ref(by_id[place]) if place in by_id else None,
                    "days": days, "expires": cert.get("expires")})
    out.sort(key=lambda c: (c["days"], str(c["name"] or "")))
    return out


def _reviewed_at(node):
    mark = node.get(provenance.KEY) if isinstance(node.get(provenance.KEY), dict) else {}
    at = mark.get("reviewed_at")
    return at if mark.get("reviewed") is True and isinstance(at, str) and at else None


def review(data, now):
    edge = iso_utc((now - timedelta(days=REVIEW_DAYS)).timestamp())
    places = _places(data)
    stale = []
    for node in places:
        at = _reviewed_at(node)
        if at is None or at < edge:
            stale.append((at is not None, at or "", _name_key(node), node))
    stale.sort(key=lambda t: t[:3])
    return {"unchecked": sum(1 for n in places if provenance.unchecked(n)),
            "stale": len(stale),
            "items": [{**_ref(n), "reviewed_at": _reviewed_at(n)} for *_, n in stale[:REVIEW_SHOWN]]}


def _journal_line(entry):
    summary_ = entry.get("summary")
    if isinstance(summary_, list):
        summary_ = "; ".join(str(s) for s in summary_ if s)
    return {"at": entry.get("at"), "by": entry.get("actor"),
            "summary": summary_ if isinstance(summary_, str) else None}


def changes(data, admin, journal, now):
    if admin:
        return {"items": [_journal_line(e) for e in (journal or [])[:CHANGES_SHOWN]
                          if isinstance(e, dict)]}
    edge = iso_utc((now - timedelta(days=CHANGES_DAYS)).timestamp())
    count = 0
    for node in _places(data):
        mark = node.get(provenance.KEY) if isinstance(node.get(provenance.KEY), dict) else {}
        at = mark.get("changed_at")
        if isinstance(at, str) and at >= edge:
            count += 1
    return {"count_7d": count}


def _origin(url):
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except (AttributeError, ValueError):
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts.scheme, parts.hostname.lower(), port or (443 if parts.scheme == "https" else 80)


def source_doors(data, setting):
    charted = {}
    for node in _places(data):
        for link in node.get("links") or []:
            if not isinstance(link, dict) or not isinstance(link.get("url"), str):
                continue
            origin = _origin(link["url"])
            if origin:
                charted.setdefault(origin, link)
    doors = {}
    for name, key in SOURCE_CONSOLES.items():
        base = setting(key)
        origin = _origin(base) if isinstance(base, str) else None
        if not origin:
            continue
        link = charted.get(origin)
        if link:
            doors[name] = {"url": link["url"], "open_in": link.get("open_in") or "auto"}
        else:
            doors[name] = {"url": bare_url(base.strip()), "open_in": "tab"}
    return doors


def sources(feed, admin, doors=None):
    told = feed.get("sources") or {}
    at = feed.get("sources_at") or {}
    silent = sum(1 for v in told.values() if v != "ok")
    items = []
    for name, said in (told.items() if admin else ()):
        item = {"name": name, "ok": said == "ok", "last_ok": at.get(name)}
        item.update((doors or {}).get(name) or {})
        items.append(item)
    return {"all_ok": silent == 0, "silent": silent, "items": items}


def favourites(data, opens=None):
    opens = opens or {}
    out = {kind: [] for kind in FAVOURITE_KINDS}
    seen = {kind: set() for kind in FAVOURITE_KINDS}
    for node in _places(data):
        for link in node.get("links") or []:
            if not isinstance(link, dict):
                continue
            kind, url = link.get("favourite"), link.get("url")
            if kind not in out or not isinstance(url, str) or not url.strip():
                continue
            if url.strip() in seen[kind]:
                continue
            seen[kind].add(url.strip())
            out[kind].append({"label": link.get("label") or url, "url": url,
                              "open_in": link.get("open_in") or "auto", "place": _ref(node),
                              "opens": int(opens.get(url.strip()) or 0)})
    for kind in out:
        out[kind].sort(key=lambda f: -f["opens"])
    return out


def favourite_urls(data):
    return {f["url"].strip() for kind in favourites(data).values() for f in kind}


def drift(feed):
    found = feed.get("drift") if isinstance(feed.get("drift"), dict) else {}
    names = [n for n in found.get("uncharted") or [] if isinstance(n, str)]
    return {"count": len(names), "items": names[:DRIFT_SHOWN]}


def build(data, feed, admin, *, hidden=None, journal=None, now=None, doors=None, opens=None):
    now = now or datetime.now(timezone.utc)
    out = {"generated_at": iso_utc(now.timestamp()), "admin": bool(admin),
           "states": states(data, feed),
           "down": down(data, feed),
           "unacked": unacked(data, admin),
           "critical": critical(data, admin, now),
           "maintenance": upcoming_maintenance(data, None if admin else hidden, now),
           "certs": lapsing_certs(data, now),
           "review": review(data, now),
           "changes": changes(data, admin, journal, now),
           "sources": sources(feed, admin, doors),
           "favourites": favourites(data, opens)}
    if admin:
        out["drift"] = drift(feed)
    return out
