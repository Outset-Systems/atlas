"""The places table — `GET /api/v2/places/roster`.

One row per place this viewer may see, built here on the server so a hidden
place never reaches the browser (2026-11-13). Every column is something the
Atlas already holds: the approved map and its stamps, the live feed it already
builds, the repair windows and the certificates. It fetches nothing new and
stores nothing.

The rows are made from the dataset after `redact_for_groups` and from the feed
after `_redact_feed`, the same two cuts `/lab-data` and `/signals` make, so a
viewer reads the same states in the table as on the map. An API token reads it
as it reads those two (`api_tokens.READ_PATHS`): a full token sees what a
viewer with no groups sees, and a cloud token is refused at the gate.

The answer:

    {"stamp": the dataset's stamp, as the Desk sends it back in `expect`,
     "generated_at": when this answer was made, UTC,
     "zones": [{"id", "name"}],
     "collections": [{"id", "name", "note", "places": [ids]}],
     "rows": [{"id", "name", "state", "cause", "zone", "zone_name", "kind",
               "role", "addresses", "services", "confirmed_by",
               "charted_source", "reviewed", "reviewed_at", "reviewed_by"
               (admins only), "changed_since_review", "unchecked",
               "maintenance": {"now", "next"}, "cert", "collections", "depends_on"}]}

`addresses` lists the place's `ip` and `mac` (the catalogue's two address
fields), then `ipv6`, `hostname` and `fqdn` when a hand edit has added them,
each only when it holds a value.

**One page of it** (2026-11-15, stage 5): any of `text`, `state`, `zone`,
`kind`, `collection`, `unchecked`, `stale_days`, `sort`, `dir`, `limit`,
`offset` filters, sorts and pages the rows by NODES' own rules
(`roster_query.py`), and adds `total` (how many matched), `offset` and
`limit`. With none, the answer is every row, as it always was.
"""

import logging

from flask import jsonify, make_response, request

import certs
import maintenance
import provenance
import roster_query
import schema
from engines.base import NODE_STATES
from engines.places import unmanaged_ids
from context import atlas
from jsonio import iso_utc
from redaction import no_store, redact_for_groups, sees_everything, viewer_groups
from security import is_admin

from . import bp
from .feeds import _redact_feed, build_feed

log = logging.getLogger("atlas.api.v2")

ROSTER_PATH = "/places/roster"

#: The fields a place's addresses are read from, in this order: the catalogue's
#: `ip` and `mac`, then keys a hand-edited map is known to carry.
ADDRESS_FIELDS = ("ip", "mac", "ipv6", "hostname", "fqdn")


def _addresses(node):
    out = []
    for key in ADDRESS_FIELDS:
        value = node.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in schema.NONE_MARKS:
            out.append(value.strip())
    return out


def _ids(value):
    return [v for v in schema.as_list(value) if isinstance(v, str) and v]


def _upcoming(windows, data=None):
    """{place id: the soonest upcoming start of a window that covers it}: the
    places it names and the members of the collections it names, as this
    viewer's map lists them (2026-11-14)."""
    out = {}
    for window in windows:
        if window.get("state") != "upcoming" or not window.get("occurrence_start"):
            continue
        for node_id in maintenance.window_places(window, data):
            start = window["occurrence_start"]
            if node_id not in out or start < out[node_id]:
                out[node_id] = start
    return out


def _mode_since(windows, data=None):
    """{place id: when the oldest maintenance mode covering it began}: the
    `open` windows active now (2026-11-14). NODES shows how long, since a
    mode has no end and only the digest (with alerts on) names one left on."""
    out = {}
    for window in windows:
        if window.get("open") is not True or window.get("state") != "active":
            continue
        began = window.get("starts")
        if not isinstance(began, str) or not began:
            continue
        for node_id in maintenance.window_places(window, data):
            if node_id not in out or began < out[node_id]:
                out[node_id] = began
    return out


def _section(data, key):
    """A list section, or none when a hand edit wrote it as a number or an
    object (round 13: the roster 500'd for every reader)."""
    value = data.get(key)
    return value if isinstance(value, list) else []


def _collections(data):
    out = []
    listed = data.get("collections")
    for entry in listed if isinstance(listed, list) else []:   # a hand edit's 5 is none
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        out.append({"id": entry["id"], "name": entry.get("name"), "note": entry.get("note"),
                    "unmanaged": entry.get("unmanaged") is True,
                    # each member once: a hand edit's ["a", "a"] counts one
                    "places": list(dict.fromkeys(_ids(entry.get("places")))),
                    # its services by key (stage 3b); this viewer's map, so their own
                    "services": list(dict.fromkeys(_ids(entry.get("services"))))})
    return out


def build(data, feed, admin, stamp, now=None):
    """The roster from a dataset and a feed that are already this viewer's."""
    zones = [{"id": z.get("id"), "name": z.get("name")}
             for z in _section(data, "zones") if isinstance(z, dict)]
    zone_names = {z["id"]: z["name"] for z in zones}
    collections = _collections(data)
    member_of = {}
    for s in collections:
        for place in s["places"]:
            member_of.setdefault(place, []).append(s["id"])
    live = feed.get("nodes") or {}
    confirmed = feed.get("confirmed_by") or {}
    under = set(feed.get("maintenance") or [])
    unmanaged = unmanaged_ids(data)   # this viewer's map: its own places only
    windows = maintenance.annotated()
    upcoming = _upcoming(windows, data)
    mode_since = _mode_since(windows, data)
    # indexed once, not scanned per row (stage 5: places × certificates)
    nearest_cert = certs.nearest_by_place([c for c in _section(data, "certs") if isinstance(c, dict)], now)

    rows = []
    for node in _section(data, "nodes"):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            continue
        nid = node["id"]
        info = live.get(nid) if isinstance(live.get(nid), dict) else {}
        state = info.get("state") if info.get("state") in NODE_STATES else None
        cause = info.get("cause") if isinstance(info.get("cause"), str) else None
        mark = node.get(provenance.KEY) if isinstance(node.get(provenance.KEY), dict) else {}
        described = provenance.describe(node)
        row = {
            "id": nid,
            "name": node.get("name"),
            "state": state,
            "cause": cause,
            "zone": node.get("zone") if isinstance(node.get("zone"), str) else None,
            "zone_name": zone_names.get(node.get("zone")) if isinstance(node.get("zone"), str)
            else None,
            "kind": node.get("kind") if isinstance(node.get("kind"), str) else None,
            "role": node.get("role") if isinstance(node.get("role"), str) else None,
            "addresses": _addresses(node),
            "services": len([l for l in node.get("links") or [] if isinstance(l, dict)]),
            "confirmed_by": confirmed.get(nid) if state else None,
            "charted_source": mark.get("source") if isinstance(mark.get("source"), str) else None,
            "reviewed": described.get("reviewed"),
            "reviewed_at": mark.get("reviewed_at") if isinstance(mark.get("reviewed_at"), str) else None,
            "changed_since_review": described.get(provenance.UNSEEN) is True,
            "unchecked": provenance.unchecked(node),
            "maintenance": {"now": nid in under, "next": upcoming.get(nid),
                            "mode_since": mode_since.get(nid) if nid in under else None},
            "unmanaged": nid in unmanaged,
            "cert": nearest_cert.get(nid),
            "collections": member_of.get(nid, []),
            "depends_on": _ids(node.get("depends_on")),
        }
        if admin:
            # WHO reviewed it is for a viewer who sees everything (`provenance.for_viewer`)
            by = mark.get("reviewed_by")
            row["reviewed_by"] = by if isinstance(by, str) else None
        rows.append(row)
    return {"stamp": stamp, "generated_at": iso_utc(), "zones": zones, "collections": collections,
            "rows": rows}


@bp.route(ROSTER_PATH)
def places_roster():
    ctx = atlas()
    try:
        raw, _, _ = ctx.dataset()
    except (OSError, ValueError) as e:
        log.error("v2 roster: lab data unreadable: %s", e)
        return jsonify({"error": f"lab data unreadable: {e}"}), 500
    try:
        stamp = ctx.store.stamp()
    except Exception as e:  # noqa: BLE001 — a store that cannot say its stamp still has rows
        log.warning("v2 roster: no stamp: %s", e)
        stamp = None

    groups = viewer_groups()
    # a look-only standalone Atlas shows every place to every visitor
    # (groups None) but has no admin: what is an admin's stays an admin's
    admin = sees_everything(groups) and is_admin()
    # asked for one page (stage 5): checked before the work, so a bad
    # parameter costs nothing
    query = None
    if roster_query.wanted(request.args):
        try:
            query = roster_query.parse(request.args)
        except roster_query.QueryError as e:
            return jsonify({"error": str(e)}), 400
    data = redact_for_groups(raw)[0]
    feed = build_feed(ctx)
    if not admin:
        feed = _redact_feed(ctx, feed, groups, data=raw)
    roster = build(data, feed, admin, stamp)
    if query:
        roster = roster_query.apply(roster, query)
    return no_store(make_response(jsonify(roster)))
