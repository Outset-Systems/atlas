"""`GET /api/status` — the fleet-wide the suite card contract, kept on purpose.

The one unversioned API path that survived the v1 removal (v1.41.0,
the API migration plan). The Hub and Kuma probe `/api/status` on every app in the
suite; it stays until that contract changes fleet-wide, and it answers
anonymously (`hub_auth.auth.DEFAULT_EXEMPT`) for exactly that reason.

It is deliberately the SAME payload `GET /api/v2/health` builds — one function,
two addresses — so the pair cannot drift; `tests/test_api_v2_health.py` runs the
parity harness over them to prove it. Its own blueprint, not `api_v2`'s: every
`api_v2.*` endpoint lives under `/api/v2/` and the namespace test pins that.
"""

from flask import Blueprint, jsonify

from .v2.health import card

bp = Blueprint("api_status", __name__)


@bp.route("/api/status")
def status():
    return jsonify(card())


@bp.route("/api/manifest")
def manifest():
    """The app manifest at the contract's address (APP_MANIFEST.md: the Hub
    reads `<url>/api/manifest`). Same builder as `/api/v2/manifest`."""
    from .v2.manifest import manifest_response
    return manifest_response()
