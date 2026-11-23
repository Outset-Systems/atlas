from flask import Blueprint, abort, jsonify, request

URL_PREFIX = "/api/v2"

bp = Blueprint("api_v2", __name__, url_prefix=URL_PREFIX)

HEALTH_PATH = URL_PREFIX + "/health"

MANIFEST_PATH = URL_PREFIX + "/manifest"

EXEMPT_PATHS = (HEALTH_PATH, MANIFEST_PATH, "/api/manifest")

INGEST_URL_PREFIX = URL_PREFIX + "/ingest"


def init_app(app):
    app.register_blueprint(bp)
    return True


TEXT_LIMIT = 4096
NAME_LIMIT = 256


def _refuse(sentence):
    response = jsonify({"ok": False, "error": sentence})
    response.status_code = 422
    abort(response)


def _body():
    body = request.get_json(silent=True)
    if not body:
        return {}
    if not isinstance(body, dict):
        _refuse("The request body must be a JSON object.")
    return body


def _count(name, default, most):
    value = request.args.get(name, type=int)
    if value is None or value < 1:
        return default
    return min(value, most)


def _part(body, key):
    value = body.get(key)
    if not value:
        return {}
    if not isinstance(value, dict):
        _refuse(f"`{key}` must be a JSON object.")
    return value


def _text(body, key, limit=TEXT_LIMIT):
    value = body.get(key)
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        _refuse(f"`{key}` must be text.")
    value = str(value)
    if len(value) > limit:
        _refuse(f"`{key}` is too long.")
    return value


def _texts(body, key, limit=TEXT_LIMIT, most=200):
    value = body.get(key)
    if not value:
        return []
    if not isinstance(value, (list, tuple)) or len(value) > most:
        _refuse(f"`{key}` must be a list.")
    out = []
    for member in value:
        if isinstance(member, bool) or not isinstance(member, (str, int, float)):
            _refuse(f"`{key}` must be a list of text.")
        member = str(member)
        if len(member) > limit:
            _refuse(f"`{key}` holds something too long.")
        out.append(member)
    return out


from . import health
from . import reads
from . import writes
from . import topology_layout
from . import feeds
from . import roster
from . import names
from . import overview
from . import favourites
from . import topology_sheet
from . import probes
from . import beat
from . import admin
from . import checks
from . import sites
from . import ingest_v2
from . import accounts_v2
from . import vitals
from . import charts
from . import manifest
from . import trust
from . import mcp
from . import reference
from . import tripwires
