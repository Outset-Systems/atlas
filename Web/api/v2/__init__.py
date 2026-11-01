"""API v2 — the Atlas's HTTP API, one blueprint at `/api/v2/`.

It replaced the original unversioned routes group by group, each proven
against the old one before the switch; the old routes were removed in
v1.41.0. What remains outside it is `/api/status` (`api/status.py` — the
fleet card contract the Hub and Kuma probe on every app) and the pages
(`views.py`, `auth_routes.py`).

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

from flask import Blueprint

URL_PREFIX = "/api/v2"

bp = Blueprint("api_v2", __name__, url_prefix=URL_PREFIX)

#: The monitoring contract: `/api/status` answers anonymously so Kuma and the
#: Hub can probe it, and `/api/v2/health` — the same payload — must too.
HEALTH_PATH = URL_PREFIX + "/health"

#: Exact paths under v2 that the app-wide gate lets through unauthenticated.
#: Deliberately a tuple of literals: adding to it is a security decision that
#: should show up in a diff of this file, not be computed.
#: The app manifest (APP_MANIFEST.md): answers anonymously with the card +
#: auth shape only; the schedule (the rites) needs a signed-in viewer.
MANIFEST_PATH = URL_PREFIX + "/manifest"
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


# Route modules attach to `bp` at import, and that import happens HERE — at
# package import, before any app can register the blueprint. Flask refuses a
# route added to an already-registered blueprint, and `tests/appfixture.py`
# builds several apps per process, so "import inside init_app()" would work
# for the first app and assert on the second.
from . import health  # noqa: E402,F401
from . import reads  # noqa: E402,F401  — the map's reads: lab-data, maps
from . import writes  # noqa: E402,F401  — the layout writes: positions, rack
from . import feeds  # noqa: E402,F401  — signals, rites, events
from . import probes  # noqa: E402,F401  — embeddable, whois
from . import beat  # noqa: E402,F401  — the machine beat
from . import admin  # noqa: E402,F401  — the editor (nested bp)
from . import sites  # noqa: E402,F401  — multi-site reads (db only)
from . import ingest_v2  # noqa: E402,F401  — relay ingest (nested bp)
from . import accounts_v2  # noqa: E402,F401  — accounts (nested bp)
from . import vitals  # noqa: E402,F401  — native card vitals (v1.34.0)
from . import charts  # noqa: E402,F401  — native watchings (v1.35.0)
from . import manifest  # noqa: E402,F401  — the app manifest + the shared Calendar's day (step 4)
from . import trust  # noqa: E402,F401  — THE TRUST view (generated; admin only)
from . import mcp  # noqa: E402,F401  — the MCP endpoint (API tokens only)
from . import tripwires  # noqa: E402,F401  — TRIPWIRES: the webhook (nested bp) + admin reads
