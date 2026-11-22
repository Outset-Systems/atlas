import logging

from flask import current_app, jsonify, make_response, request

import filelock
import topology_layout as layout
from context import atlas
from redaction import private_no_cache, redact_for_groups

from . import bp
from .auth import write_required

log = logging.getLogger("atlas.api.v2")


def _path():
    ext = current_app.extensions
    if "atlas_topology_layout" not in ext:
        ext["atlas_topology_layout"] = atlas().config.TOPOLOGY_LAYOUT_PATH
    return ext["atlas_topology_layout"]


@bp.route("/topology/layout")
def topology_layout_read():
    ctx = atlas()
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError) as e:
        log.error("v2 topology layout: dataset unreadable: %s", e)
        return jsonify({"error": "dataset unreadable"}), 500
    seen, _ = redact_for_groups(data)
    doc = layout.read(_path())
    body = layout.for_viewer(doc, layout.known_ids(seen))
    body["stamp"] = layout.stamp_of(doc if seen is data else body)
    return private_no_cache(make_response(jsonify(body)))


@bp.route("/topology/layout", methods=["POST"])
@write_required
def topology_layout_write():
    try:
        cards, expect, replace = layout.parse(request.get_json(silent=True))
    except layout.BadBody as e:
        return jsonify({"error": str(e)}), 400
    ctx = atlas()
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        return jsonify({"error": "dataset unreadable"}), 500
    try:
        result = layout.save(_path(), layout.known_ids(data), cards, expect, replace)
    except layout.StaleError as e:
        return jsonify({"error": "someone else moved cards on this map while you were "
                                 "arranging it; it has been read again",
                        "stamp": e.stamp}), 409
    except filelock.LockTimeout:
        resp = jsonify({"error": "another save is holding the drawing: try again in a moment"})
        resp.headers["Retry-After"] = "2"
        return resp, 503
    except OSError as e:
        return jsonify({"error": f"could not save: {e}"}), 500
    log.info("topology layout saved via v2: %d cards (%d total)", result["saved"], result["total"])
    return jsonify({"ok": True, **result})
