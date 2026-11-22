import logging

from flask import jsonify, request
from pydantic import ValidationError

from context import atlas

from . import bp
from .auth import write_required
from .schemas import OverlayWrite

log = logging.getLogger("atlas.api.v2")


def _save_overlay(name, unit):
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
    return _save_overlay("positions", "places")


@bp.route("/rack", methods=["POST"])
@write_required
def rack():
    return _save_overlay("rack", "vessels")
