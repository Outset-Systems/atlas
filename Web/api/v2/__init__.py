"""API v2 — the Atlas's HTTP API, one blueprint at `/api/v2/`.

It replaced the original unversioned routes group by group, each proven
against the old one before the switch; the old routes were removed in
v1.41.0. What remains outside it is the two unversioned paths in
`api/status.py` (`/api/status`, the fleet card contract the Hub and Kuma probe
on every app, and `/api/manifest`, the app manifest at the address the Hub
reads) and the pages (`views.py`, `auth_routes.py`).

The blueprint NAME is the namespace: every endpoint here is `api_v2.<name>` —
or `api_v2.<child>.<name>` for the four NESTED surfaces (`admin`, `ingest`,
`tripwires_ingest`, `auth`; note `api_v2.auth.*` names the accounts blueprint,
while `api.v2.auth` the MODULE is the authorisation adapter) — and `tests/test_api_v2_health.py`
asserts over the url map that nothing else wears that name.

What v2 does NOT do, on purpose:

* It installs no authentication gate of its own. The app-wide
  `before_request` in `create_app()` (`atlas_auth.require_atlas_auth`) already
  fronts every path, `/api/v2/*` included. `EXEMPT_PATHS` is the one list of
  v2 paths that gate must let through anonymously; `create_app()` passes it in.
* It reimplements no authorisation. `api.v2.auth` is an adapter over
  `security.py` / `redaction.py` / `atlas_auth.py`.
* The surfaces that exist only in some postures (sites: db mode; ingest: db +
  opt-in; accounts: sessions) fence themselves per request with a 404, so
  the url map is identical in every mode.
"""

from flask import Blueprint, abort, jsonify, request

URL_PREFIX = "/api/v2"

bp = Blueprint("api_v2", __name__, url_prefix=URL_PREFIX)

#: The monitoring contract: `/api/status` answers anonymously so Kuma and the
#: Hub can probe it, and `/api/v2/health` — the same payload — must too.
HEALTH_PATH = URL_PREFIX + "/health"

#: The app manifest (APP_MANIFEST.md): answers anonymously with the card +
#: auth shape only; the schedule (the rites) needs a signed-in viewer.
MANIFEST_PATH = URL_PREFIX + "/manifest"

#: Exact paths the app-wide gate lets through unauthenticated: two under v2,
#: and the manifest's unversioned address (`api/status.py`).
#: Deliberately a tuple written out here: adding to it is a security decision
#: that should show up in a diff of this file, not be computed.
EXEMPT_PATHS = (HEALTH_PATH, MANIFEST_PATH, "/api/manifest")

#: The relay ingest workstation: exempt BY PREFIX in `create_app` — a push agent
#: has no session; its per-site bearer token (checked in `ingest.authenticate`)
#: is the whole credential. The TRIPWIRES webhook (`/ingest/tripwires`) lives
#: under the same prefix and the same rule: its credential
#: (`tripwires.authenticate`) is the whole boundary.
INGEST_URL_PREFIX = URL_PREFIX + "/ingest"


def init_app(app):
    """Mount v2. Returns True so `app.config["API_V2_ENABLED"]` reads like the
    other posture flags — always on; v2 has no mode it is absent in."""
    app.register_blueprint(bp)
    return True


# ── Reading a request body (2026-11-18) ──────────────────────────────────────
# One reader for the body and three for what is in it, so a route says what it
# expects and gets exactly that or never runs. Before these, `_body()` handed
# back whatever JSON arrived: `[1]`, `"x"` or `7` is truthy, so `or {}` kept
# it, the route's first `.get` raised, and seventeen admin routes, the beat
# and the sign-in answered 500 to a body a stranger could send.
#: The longest text a body's field may carry where a route names no cap.
TEXT_LIMIT = 4096
#: The longest sign-in name. The account store takes far less; this is only
#: what may reach the sign-in log, which records the name on every attempt.
NAME_LIMIT = 256


def _refuse(sentence):
    """End the request here with a 422 saying `sentence`. Raises, so a reader
    below can be used inline; `ok` is false beside `error` because the
    accounts surface's clients key on it and everything else reads `error`."""
    response = jsonify({"ok": False, "error": sentence})
    response.status_code = 422
    abort(response)


def _body():
    """The request's JSON body as an object: `{}` when there is none, it is
    not JSON, or it is empty (`null`, `0`, `[]`, `""`). A body that is JSON,
    not empty and not an object is refused with a 422."""
    body = request.get_json(silent=True)
    if not body:
        return {}
    if not isinstance(body, dict):
        _refuse("The request body must be a JSON object.")
    return body


def _count(name, default, most):
    """A count from the query string (`?limit=`): `default` when it is absent,
    not a whole number, or below 1, and never more than `most`. A negative
    one used to reach a slice and count from the far end."""
    value = request.args.get(name, type=int)
    if value is None or value < 1:
        return default
    return min(value, most)


def _part(body, key):
    """`body[key]` as an object: `{}` when it is absent or empty, refused with
    a 422 when it is anything else (`"settings": "x"`)."""
    value = body.get(key)
    if not value:
        return {}
    if not isinstance(value, dict):
        _refuse(f"`{key}` must be a JSON object.")
    return value


def _text(body, key, limit=TEXT_LIMIT):
    """`body[key]` as text: `""` when absent or null, a number as its digits
    (a code typed into a form may arrive as one), and refused with a 422 when
    it is a list, an object or true/false, or longer than `limit`."""
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
    """`body[key]` as a list of text: `[]` when absent or empty. A single
    string is refused, not walked letter by letter; so is a member that is
    not text, and a list longer than `most`."""
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


# Route modules attach to `bp` at import, and that import happens HERE — at
# package import, before any app can register the blueprint. Flask refuses a
# route added to an already-registered blueprint, and `tests/appfixture.py`
# builds several apps per process, so "import inside init_app()" would work
# for the first app and assert on the second.
from . import health  # noqa: E402,F401
from . import reads  # noqa: E402,F401  — the map's reads: lab-data, maps
from . import writes  # noqa: E402,F401  — the layout writes: positions, rack
from . import topology_layout  # noqa: E402,F401  : TOPOLOGY's card layout, read and written (2026-11-17)
from . import feeds  # noqa: E402,F401  — signals, rites, events
from . import roster  # noqa: E402,F401  — the places table (2026-11-13)
from . import overview  # noqa: E402,F401  — OVERVIEW, the realm's own facts (2026-11-13)
from . import topology_sheet  # noqa: E402,F401  : TOPOLOGY's connections sheet, a CSV (2026-11-17)
from . import probes  # noqa: E402,F401  — embeddable, whois
from . import beat  # noqa: E402,F401  — the machine beat
from . import admin  # noqa: E402,F401  — the editor (nested bp)
from . import checks  # noqa: E402,F401  : one check, read and asked now (admin; 2026-11-16)
from . import sites  # noqa: E402,F401  — multi-site reads (db only)
from . import ingest_v2  # noqa: E402,F401  — relay ingest (nested bp)
from . import accounts_v2  # noqa: E402,F401  — accounts (nested bp)
from . import vitals  # noqa: E402,F401  — native card vitals (v1.34.0)
from . import charts  # noqa: E402,F401  — native watchings (v1.35.0)
from . import manifest  # noqa: E402,F401  — the app manifest + the shared Calendar's day (step 4)
from . import trust  # noqa: E402,F401  — THE TRUST view (generated; admin only)
from . import mcp  # noqa: E402,F401  — the MCP endpoint (API tokens only)
from . import reference  # noqa: E402,F401  — the API reference (openapi.json)
from . import tripwires  # noqa: E402,F401  — TRIPWIRES: the webhook (nested bp) + admin reads
