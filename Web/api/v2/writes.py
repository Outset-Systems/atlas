"""Layout writes — `POST /api/v2/positions`, `POST /api/v2/rack`.

The smallest write shape in the app. The whole gate rides on
`security.write_refusal()` (via `api.v2.auth.write_required`), and every other
write surface inherits this exact refusal behaviour.

The body is validated through `schemas.OverlayWrite` (pydantic), with the
failure mapped to the one-sentence 400 the front end shows. The overlay
objects (`ctx.overlays`) own the files and their locks.
"""

import logging

from flask import jsonify, request
from pydantic import ValidationError

from context import atlas

from . import bp
from .auth import write_required
from .schemas import OverlayWrite

log = logging.getLogger("atlas.api.v2")


def _save_overlay(name, unit):
    """Shared body of the two layout writes — the write gate is the
    decorator, pydantic does the shape check, the overlay does the merge."""
    try:
        body = OverlayWrite.model_validate(request.get_json(silent=True)).root
    except ValidationError:
        return jsonify({"error": "expected an object of key -> value"}), 400
    ctx = atlas()
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        return jsonify({"error": "dataset unreadable"}), 500
    try:
        saved, total = ctx.overlays[name].merge(data, body)
    except OSError as e:
        return jsonify({"error": f"could not save: {e}"}), 500
    log.info("%s saved via v2: %d %s (%d total)", name, saved, unit, total)
    return jsonify({"ok": True, "saved": saved, "total": total})


@bp.route("/positions", methods=["POST"])
@write_required
def positions():
    """Persist moved markers (Settings → Save to map)."""
    return _save_overlay("positions", "places")


@bp.route("/rack", methods=["POST"])
@write_required
def rack():
    """Persist a rearranged rack (THE ARMORY → Rearrange → Save)."""
    return _save_overlay("rack", "vessels")
