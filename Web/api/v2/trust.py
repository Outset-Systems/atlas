import json
import logging
import os

from flask import jsonify

import settings
from .auth import admin_required

from . import bp

log = logging.getLogger("atlas.api.v2")

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "trust.json")


@bp.route("/trust")
def trust():
    if settings.DEMO_TRUST:
        return _served(settings.DEMO_TRUST)
    return _admin_trust()


@admin_required
def _admin_trust():
    return _served(_PATH)


def _served(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        log.warning("v2 trust: %s is missing from the image", path)
        return jsonify({"error": "this instance has no trust map: nothing has "
                                 "been checked here"}), 503
    except (OSError, ValueError) as e:
        log.error("v2 trust: %s unreadable: %s", path, e)
        return jsonify({"error": f"trust map unreadable: {e}"}), 500

    data["version"] = settings.APP_VERSION
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp
