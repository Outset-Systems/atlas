"""THE TRUST view — `GET /api/v2/trust`.

Serves `Web/trust.json`, which the trust-map generator derives from the compose
files and the nginx vhosts and which is baked into the image at build. Read
that tool's header for why this one section of the map is generated rather
than surveyed.

ADMIN ONLY, unlike the map itself. The body is a list of the addresses each
app will believe a client identity from — the shortest possible description of
where to aim a forged header. The map's own redaction is group-shaped and
tuned for places and services; this is not a place, so it gets the blunt
answer instead.

Served from the image, so it is exactly as old as the running build. A
deployment whose config has moved since the last generate would show a stale
answer confidently — which is the failure this view exists to prevent — so
`stale_risk` carries the app version and the caller is told to re-run the
generator, and the trust-map generator --check` is the mechanical form of the same
question.
"""
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
@admin_required
def trust():
    try:
        with open(_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        # Never invent an empty-but-fine answer: "nothing trusts anything"
        # and "the file did not ship" look identical to a reader, and one of
        # them is a clean bill of health.
        log.warning("v2 trust: %s is missing from the image", _PATH)
        return jsonify({"error": "this instance has no trust map: nothing has "
                                 "been checked here"}), 503
    except (OSError, ValueError) as e:
        log.error("v2 trust: %s unreadable: %s", _PATH, e)
        return jsonify({"error": f"trust map unreadable: {e}"}), 500

    data["version"] = settings.APP_VERSION
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp
