"""OVERVIEW — the realm's own facts on one page (2026-11-13).

One module both readers call: the MCP tool `atlas_overview` takes `summary`,
and `GET /api/v2/overview` (`api/v2/overview.py`) takes `build`, which grows
the same reading into the page's tiles. It lives here, not in `reports.py`,
because that module is the staged markdown scrolls and knows nothing about the
map; and not in `mcp_tools.py`, because a route must not import the MCP
surface to read the realm.

Nothing here reads a request or decides who may see what. Every function is
handed a dataset and a feed that are ALREADY the reader's (`redact_for_groups`
and `_redact_feed`), plus, where free text has to be checked, the pattern of
the hidden places' words (`redaction.hidden_words`). It stores nothing and
fetches nothing: every tile is something the Atlas already holds.
"""

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

#: How far ahead the maintenance tile looks, and the other tiles' edges.
MAINTENANCE_DAYS = 7
CERT_DAYS = 30
REVIEW_DAYS = 90
CHANGES_DAYS = 7
#: How many rows a tile lists. Its count is always the whole number.
UNACKED_SHOWN = 8
REVIEW_SHOWN = 8
CHANGES_SHOWN = 8
DRIFT_SHOWN = 12
#: The two favourites tiles, in the page's order (`links[].favourite`).
FAVOURITE_KINDS = ("internal", "external")
#: The sources with a console of their own to open, and the setting that holds
#: each one's address (engines/registry.py `needs`). The decoy feed is an API
#: with nothing to look at; Atlas's own checks, a relay and a file have no
#: address at all.
SOURCE_CONSOLES = {"kuma": "ATLAS_KUMA_URL", "prometheus": "ATLAS_PROM_URL",
                   "unifi": "ATLAS_UNIFI_URL"}

STATES = ("healthy", "degraded", "down", "slumbering", "maintenance")
#: The places that make the "down now" tile, worst first.
_FAULTS = ("down", "degraded")
_EVENT_KEYS = ("id", "at", "kind", "target", "name", "from", "to")


def _state(entry):
    return (entry or {}).get("state") if isinstance(entry, dict) else None


def summary(data, feed):
    """The lab at a glance, as `atlas_overview` has always answered it: zones,
    how many places, services and roads, a health tally over the feed, the
    sources and how much of the map a person has reviewed."""
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


# ── the tiles ────────────────────────────────────────────────────────────────

def _places(data):
    return [n for n in data.get("nodes") or []
            if isinstance(n, dict) and isinstance(n.get("id"), str)]


def _ref(node):
    return {"id": node["id"], "name": node.get("name")}


def _name_key(node):
    return str(node.get("name") or node.get("id") or "").casefold()


def states(data, feed):
    """Places by live state. Counted over the reader's places, not the feed's
    rows: a feed can hold an id the map does not chart. No state is unknown."""
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
    """Each place that is down or degraded on its own account, with what depends
    on it. A place the feed explains by another visible place (`cause`) is that
    place's fallout, not a root. A cause this reader may not see was already
    taken off by `_redact_feed`, so that place stands as its own root.

    `downstream` is every visible place that needs it, directly or through
    another, from `parent` and `depends_on` only (`dependencies.needed_by`,
    the walk `atlas_impact` uses). `declared` says whether any visible place
    names it at all: false is "nothing is declared to depend on this", which is
    not "nothing is affected"."""
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
    """Events nobody has acknowledged, newest first: the listing the ANNALS
    gives this reader. For anyone but an admin that is the door every
    non-admin reading takes (`tripwires.listing_without_trips`), gated by the
    reader's places, monitors and jobs. `count` is every such event, of any
    gravity (the ANNALS' own badge counts the grave and the warning only)."""
    if admin:
        rows = events.listing(limit=events.KEEP, unacked_only=True)
    else:
        rows = tripwires.listing_without_trips(
            limit=events.KEEP, visible={n["id"] for n in _places(data)}, unacked_only=True,
            visible_services=_monitors(data),
            visible_rites=heartbeats.keys_of(data.get("rites")))
    items = [{k: row.get(k) for k in _EVENT_KEYS} for row in rows[:UNACKED_SHOWN]]
    return {"count": len(rows), "items": items}


def _monitors(data):
    """The monitors on the reader's own map. `data` is already redacted, so
    every place and link on it is one they are cleared for."""
    out = set()
    for node in _places(data):
        for link in node.get("links") or []:
            if isinstance(link, dict):
                out.add(service_key(node["id"], link))
    out.update(monitor_map(data))
    return out


def upcoming_maintenance(data, hidden, now):
    """Repair windows open now or opening within `MAINTENANCE_DAYS`, each with
    the reader's places in it. A window whose places are all hidden is not
    listed, and neither is one whose id or reason names a hidden place
    (`hidden` is `redaction.hidden_words` over the whole map, None for a reader
    who sees everything): the reason is an admin's free text."""
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
        # the places it names and its collections' members, as this reader's
        # map lists them: a hidden member is not in it (2026-11-14)
        named = sorted(maintenance.window_places(window, data))
        places = [_ref(by_id[n]) for n in named if n in by_id]
        # nothing this reader sees: not listed. A window on a collection of
        # hidden places resolves to nothing on this reader's map (stage 3
        # review), so "named but none seen" is not enough of a test
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
    """Certificates with `CERT_DAYS` or fewer left, lapsed ones included,
    soonest first. `place` is the place it is tied to, when the reader sees it."""
    by_id = {n["id"]: n for n in _places(data)}
    out = []
    for cert in data.get("certs") or []:
        if not isinstance(cert, dict):
            continue
        days = certs.days_left(cert, now)
        if days is None or days > CERT_DAYS:
            continue
        place = cert.get("place")
        place = place if isinstance(place, str) else None   # a list is no place (2026-11-13)
        out.append({"name": cert.get("name"),
                    "place": _ref(by_id[place]) if place in by_id else None,
                    "days": days, "expires": cert.get("expires")})
    out.sort(key=lambda c: (c["days"], str(c["name"] or "")))
    return out


def _reviewed_at(node):
    """When a person last reviewed this place, or None when the map holds no
    review for it: never reviewed, or charted before the map kept provenance."""
    mark = node.get(provenance.KEY) if isinstance(node.get(provenance.KEY), dict) else {}
    at = mark.get("reviewed_at")
    return at if mark.get("reviewed") is True and isinstance(at, str) and at else None


def review(data, now):
    """`unchecked` counts `provenance.unchecked`. `stale` counts the places
    with no review at all, or one older than `REVIEW_DAYS`. The list is the
    stale ones, never-reviewed first, then the oldest review. When and whether,
    never who."""
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
    """For an admin, the last entries in the change log (`journal`: the store's
    `revisions`, newest first), which name who. For anyone else only how many
    of their places changed in `CHANGES_DAYS`, from the `changed_at` stamps,
    and nothing that names a person or a place."""
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
    """`(scheme, host, port)` of a URL, lower-cased with the scheme's own port
    filled in; None when it is not an http(s) address."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except (AttributeError, ValueError):
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts.scheme, parts.hostname.lower(), port or (443 if parts.scheme == "https" else 80)


def source_doors(data, setting):
    """Where each source's own console opens, for an admin: `{name: {"url",
    "open_in"}}`. `setting` reads a connection setting by name
    (`integrations.get`).

    The page frames an address only when the map charts it (the frame list and
    the framing verdict are both built from the map's links), so a source whose
    address is a charted service's is sent as that service's own URL, spelt as
    the map spells it, and opens the way that service says. Any other address
    is sent bare (no sign-in, query or fragment) and opens in a tab."""
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
    """Whether every source answered on the last build. An admin is told which,
    when each last answered in this worker and, for a source with a console of
    its own, where that opens (`source_doors`); anyone else only how many."""
    told = feed.get("sources") or {}
    at = feed.get("sources_at") or {}
    silent = sum(1 for v in told.values() if v != "ok")
    items = []
    for name, said in (told.items() if admin else ()):
        item = {"name": name, "ok": said == "ok", "last_ok": at.get(name)}
        item.update((doors or {}).get(name) or {})
        items.append(item)
    return {"all_ok": silent == 0, "silent": silent, "items": items}


def favourites(data):
    """The services marked as a favourite, the internal ones and the external
    ones apart, in the map's own order. From a dataset that is already this
    reader's, so a service they may not see is not here. One address charted
    on two places (a public door and the proxy behind it) is listed once."""
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
                              "open_in": link.get("open_in") or "auto", "place": _ref(node)})
    return out


def drift(feed):
    """The monitors the sources watch and the map has not charted. Admin only."""
    found = feed.get("drift") if isinstance(feed.get("drift"), dict) else {}
    names = [n for n in found.get("uncharted") or [] if isinstance(n, str)]
    return {"count": len(names), "items": names[:DRIFT_SHOWN]}


def build(data, feed, admin, *, hidden=None, journal=None, now=None, doors=None):
    """The OVERVIEW answer from a dataset and a feed that are already this
    reader's. `hidden` is `redaction.hidden_words` for a reader who does not see
    everything; `journal` the change log, read only for an admin; `doors` is
    `source_doors`, an admin's too."""
    now = now or datetime.now(timezone.utc)
    out = {"generated_at": iso_utc(now.timestamp()), "admin": bool(admin),
           "states": states(data, feed),
           "down": down(data, feed),
           "unacked": unacked(data, admin),
           "maintenance": upcoming_maintenance(data, None if admin else hidden, now),
           "certs": lapsing_certs(data, now),
           "review": review(data, now),
           "changes": changes(data, admin, journal, now),
           "sources": sources(feed, admin, doors),
           "favourites": favourites(data)}
    if admin:
        out["drift"] = drift(feed)
    return out
