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
    value = data.get(key)
    return value if isinstance(value, list) else []


def _collections(data):
    out = []
    listed = data.get("collections")
    for entry in listed if isinstance(listed, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        out.append({"id": entry["id"], "name": entry.get("name"), "note": entry.get("note"),
                    "unmanaged": entry.get("unmanaged") is True,
                    "places": list(dict.fromkeys(_ids(entry.get("places")))),
                    "services": list(dict.fromkeys(_ids(entry.get("services"))))})
    return out


def build(data, feed, admin, stamp, now=None):
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
    unmanaged = unmanaged_ids(data)
    windows = maintenance.annotated()
    upcoming = _upcoming(windows, data)
    mode_since = _mode_since(windows, data)
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
    except Exception as e:
        log.warning("v2 roster: no stamp: %s", e)
        stamp = None

    groups = viewer_groups()
    admin = sees_everything(groups) and is_admin()
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
