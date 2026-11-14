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
     "sets": [{"id", "name", "note", "places": [ids]}],
     "rows": [{"id", "name", "state", "cause", "zone", "zone_name", "kind",
               "role", "addresses", "services", "confirmed_by",
               "charted_source", "reviewed", "reviewed_at", "reviewed_by"
               (admins only), "changed_since_review", "unchecked",
               "maintenance": {"now", "next"}, "cert", "sets", "depends_on"}]}

`addresses` lists the place's `ip` and `mac` (the catalogue's two address
fields), then `ipv6`, `hostname` and `fqdn` when a hand edit has added them,
each only when it holds a value.
"""

import logging

from flask import jsonify, make_response

import certs
import maintenance
import provenance
import schema
import signals
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


def _upcoming(windows):
    """{place id: the soonest upcoming start of a window that names it}."""
    out = {}
    for window in windows:
        if window.get("state") != "upcoming" or not window.get("occurrence_start"):
            continue
        for node_id in window.get("nodes") or []:
            node_id = str(node_id)
            start = window["occurrence_start"]
            if node_id not in out or start < out[node_id]:
                out[node_id] = start
    return out


def _sets(data):
    out = []
    for entry in data.get("sets") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        out.append({"id": entry["id"], "name": entry.get("name"), "note": entry.get("note"),
                    "places": _ids(entry.get("places"))})
    return out


def build(data, feed, admin, stamp, now=None):
    """The roster from a dataset and a feed that are already this viewer's."""
    zones = [{"id": z.get("id"), "name": z.get("name")}
             for z in data.get("zones") or [] if isinstance(z, dict)]
    zone_names = {z["id"]: z["name"] for z in zones}
    sets = _sets(data)
    member_of = {}
    for s in sets:
        for place in s["places"]:
            member_of.setdefault(place, []).append(s["id"])
    live = feed.get("nodes") or {}
    confirmed = feed.get("confirmed_by") or {}
    under = set(feed.get("maintenance") or [])
    upcoming = _upcoming(maintenance.annotated())
    cert_list = [c for c in data.get("certs") or [] if isinstance(c, dict)]

    rows = []
    for node in data.get("nodes") or []:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            continue
        nid = node["id"]
        info = live.get(nid) if isinstance(live.get(nid), dict) else {}
        state = info.get("state") if info.get("state") in signals.NODE_STATES else None
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
            "maintenance": {"now": nid in under, "next": upcoming.get(nid)},
            "cert": certs.nearest_for_place(cert_list, nid, now),
            "sets": member_of.get(nid, []),
            "depends_on": _ids(node.get("depends_on")),
        }
        if admin:
            # WHO reviewed it is for a viewer who sees everything (`provenance.for_viewer`)
            by = mark.get("reviewed_by")
            row["reviewed_by"] = by if isinstance(by, str) else None
        rows.append(row)
    return {"stamp": stamp, "generated_at": iso_utc(), "zones": zones, "sets": sets, "rows": rows}


@bp.route(ROSTER_PATH)
def places_roster():
    ctx = atlas()
    try:
        raw, _, _ = ctx.dataset()
    except (OSError, ValueError) as e:
        log.error("v2 roster: lab data unreadable: %s", e)
        return jsonify({"error": f"lab data unreadable: {e}"}), 500
    try:
        _, stamp = ctx.store.read()
    except Exception as e:  # noqa: BLE001 — a store that cannot say its stamp still has rows
        log.warning("v2 roster: no stamp: %s", e)
        stamp = None

    groups = viewer_groups()
    # a look-only standalone Atlas shows every place to every visitor
    # (groups None) but has no admin: what is an admin's stays an admin's
    admin = sees_everything(groups) and is_admin()
    data = redact_for_groups(raw)[0]
    feed = build_feed(ctx)
    if not admin:
        feed = _redact_feed(ctx, feed, groups, data=raw)
    return no_store(make_response(jsonify(build(data, feed, admin, stamp))))
