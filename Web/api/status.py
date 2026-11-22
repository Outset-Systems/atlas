from flask import Blueprint, jsonify

from .v2.health import card

bp = Blueprint("api_status", __name__)


@bp.route("/api/status")
def status():
    return jsonify(card())


@bp.route("/api/manifest")
def manifest():
    from .v2.manifest import manifest_response
    return manifest_response()
