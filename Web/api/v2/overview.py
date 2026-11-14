"""OVERVIEW — `GET /api/v2/overview` (2026-11-13).

The realm's own facts on one page, from what the Atlas already holds: places
by state, what is down and what depends on it, events nobody has acknowledged,
repair windows in the next week, certificates lapsing within 30 days, places
unchecked or not reviewed for 90 days, recent changes, whether each source
answers and, for an admin, the map's drift from its sources. It stores nothing
and fetches nothing new. The tiles are built in `overview.py`, which the MCP
tool `atlas_overview` reads too.

Cut the way `places/roster` is: the dataset after `redact_for_groups`, the feed
after `_redact_feed`. An API token reads it as it reads those two
(`api_tokens.READ_PATHS`): a full token sees what a viewer with no groups sees,
and a cloud token is refused at the gate. Who changed what, which source is
silent and the drift are for an admin; anyone else is told how many.

The answer:

    {"generated_at", "admin",
     "states": {"healthy", "degraded", "down", "slumbering", "maintenance",
                "unknown", "total"},
     "down": [{"id", "name", "state", "cause", "downstream": [{"id", "name"}],
               "declared"}],
     "unacked": {"count", "items": [{"id", "at", "kind", "target", "name",
                                     "from", "to"}]},
     "maintenance": [{"window", "reason", "starts", "ends", "now",
                      "places": [{"id", "name"}]}],
     "certs": [{"name", "place": {"id", "name"} | null, "days", "expires"}],
     "review": {"unchecked", "stale", "items": [{"id", "name", "reviewed_at"}]},
     "changes": {"items": [{"at", "by", "summary"}]} (an admin)
                | {"count_7d"} (anyone else),
     "sources": {"all_ok", "silent", "items": [{"name", "ok", "last_ok"}]
                 (an admin; empty for anyone else)},
     "drift": {"count", "items"} (an admin only; absent otherwise)}
"""

import logging

from flask import jsonify, make_response

import overview
from context import atlas
from security import is_admin
from redaction import (hidden_words, no_store, redact_for_groups, sees_everything,
                       viewer_groups)

from . import bp
from .feeds import _redact_feed, build_feed

log = logging.getLogger("atlas.api.v2")

OVERVIEW_PATH = "/overview"


@bp.route(OVERVIEW_PATH)
def realm_overview():
    ctx = atlas()
    try:
        raw, _, _ = ctx.dataset()
    except (OSError, ValueError) as e:
        log.error("v2 overview: lab data unreadable: %s", e)
        return jsonify({"error": f"lab data unreadable: {e}"}), 500

    groups = viewer_groups()
    # a look-only standalone Atlas shows every place to every visitor
    # (groups None) but has no admin: what is an admin's stays an admin's
    admin = sees_everything(groups) and is_admin()
    data = redact_for_groups(raw)[0]
    feed = build_feed(ctx)
    journal = None
    if admin:
        try:
            journal = ctx.store.revisions(limit=overview.CHANGES_SHOWN)
        except Exception as e:  # noqa: BLE001 — a change log that cannot be read is an empty tile
            log.warning("v2 overview: change log unreadable: %s", e)
            journal = []
    else:
        feed = _redact_feed(ctx, feed, groups, data=raw)
    body = overview.build(data, feed, admin, hidden=None if admin else hidden_words(raw, groups),
                          journal=journal)
    return no_store(make_response(jsonify(body)))
