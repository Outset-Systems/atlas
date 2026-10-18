"""`GET /api/v2/health` — the app's health, in the suite card shape.

Same body as `GET /api/status` (the fleet card contract, built by
`hub_auth.app_status`), same anonymous reachability (see
`api.v2.EXEMPT_PATHS`). Since the v1 removal (v1.41.0) the payload is built
ONCE, here, in `card()`, and `api/status.py` serves the same function at the
unversioned address — the duplication that existed while both surfaces were
live is gone, and `tests/test_api_v2_health.py` still runs the parity harness
over the pair so a future edit to one address cannot quietly leave the other
behind.
"""

import logging

from flask import jsonify

import settings
from context import atlas
from jsonio import iso_utc
from hub_auth import app_status

from . import bp

log = logging.getLogger("atlas.api.v2")


def _relay_metric(ctx):
    """The relay's freshness — reported, never load-bearing. db mode only."""
    if ctx.backend != "db":
        return []
    from signals import RELAY_MAX_AGE, relay_age_seconds
    age = relay_age_seconds(ctx.site)
    if age is None:
        return []
    stale = age > RELAY_MAX_AGE
    return [{"label": "Relay Stale (min)" if stale else "Relay Age (min)",
             "value": int(age // 60)}]


def card():
    """The status payload — the Hub renders its card from `summary` alone."""
    ctx = atlas()
    healthy, nodes, zones, services, mtime, problems = True, 0, 0, 0, 0, []
    try:
        data, mtime, problems = ctx.dataset()
        nodes = len(data.get("nodes", []))
        zones = len(data.get("zones", []))
        services = sum(len(n.get("links", [])) for n in data.get("nodes", []))
    except (OSError, ValueError) as e:
        log.error("health: lab-data unreadable: %s", e)
        healthy = False
    # 🔴 APP_BRAND, not APP_NAME. Both addresses are gate-exempt so Kuma and the
    # Hub can probe them — which means they answer ANONYMOUSLY on the public
    # door, where the sign-in page beside them carefully says only "The Atlas".
    # The realm names itself once you are inside, not before (v1.21.3).
    #
    # Safe for the Hub: its cards render from `summary` alone and it labels
    # them from its OWN app config, never from this field.
    return app_status(
        app_key=settings.APP_KEY,
        name=settings.APP_BRAND,
        version=settings.APP_VERSION,
        healthy=healthy and not problems,
        summary={
            "headline_metric": nodes,
            "headline_label": "Places Charted",
            "secondary_metrics": [
                {"label": "Realms", "value": zones},
                {"label": "Services", "value": services},
                *_relay_metric(ctx),
                *([{"label": "Data Problems", "value": len(problems)}] if problems else []),
            ],
            "latest_activity": iso_utc(mtime),
        },
        icon="map",
        accent=settings.ACCENT_COLOR,
    )


@bp.route("/health")
def health():
    return jsonify(card())
