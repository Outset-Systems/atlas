import logging

from flask import jsonify, make_response

import favourite_opens
import integrations
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
    admin = sees_everything(groups) and is_admin()
    data = redact_for_groups(raw)[0]
    feed = build_feed(ctx)
    journal = None
    if admin:
        try:
            journal = ctx.store.revisions(limit=overview.CHANGES_SHOWN)
        except Exception as e:
            log.warning("v2 overview: change log unreadable: %s", e)
            journal = []
    else:
        feed = _redact_feed(ctx, feed, groups, data=raw)
    body = overview.build(data, feed, admin, hidden=None if admin else hidden_words(raw, groups),
                          journal=journal,
                          doors=overview.source_doors(data, integrations.get) if admin else None,
                          opens=favourite_opens.load())
    return no_store(make_response(jsonify(body)))
