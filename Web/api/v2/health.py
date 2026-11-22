import logging

from flask import jsonify

import settings
from context import atlas
from jsonio import iso_utc
from hub_auth import app_status

from . import bp

log = logging.getLogger("atlas.api.v2")


def _relay_metric(ctx):
    if ctx.backend != "db":
        return []
    from engines.relay import RELAY_MAX_AGE, relay_age_seconds
    age = relay_age_seconds(ctx.site)
    if age is None:
        return []
    stale = age > RELAY_MAX_AGE
    return [{"label": "Relay Stale (min)" if stale else "Relay Age (min)",
             "value": int(age // 60)}]


def card():
    ctx = atlas()
    healthy, nodes, zones, services, mtime, problems = True, 0, 0, 0, 0, []
    try:
        data, mtime, problems = ctx.dataset()
        places = [n for n in data.get("nodes") or [] if isinstance(n, dict)]
        nodes = len(places)
        zones = len(data.get("zones") or [])
        services = sum(len(n.get("links") or []) for n in places)
    except (OSError, ValueError) as e:
        log.error("health: lab-data unreadable: %s", e)
        healthy = False
    out = app_status(
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
    import annalist
    out["annalist"] = annalist.liveness()
    return out


@bp.route("/health")
def health():
    return jsonify(card())
