"""The `kuma` source: Uptime Kuma's `/metrics` as place and service states."""

from engines.base import (
    DEGRADED, DOWN, HEALTHY, MAINTENANCE, _Adapter, _TIMEOUT, _read_secret, _worse,
    monitor_map,
)
import engines.runtime as runtime


class KumaAdapter(_Adapter):
    """Uptime-Kuma metrics/status → node & service states.

    Live (the wiring was Wave 2): given a Kuma URL and an API key it makes a
    real, fully fail-silent HTTP call. It never imports at module load so a
    missing `requests` in some minimal image can't break the app.
    """

    name = "kuma"

    def __init__(self, url, api_key, monitor_map=None, verify=True):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.monitor_map = monitor_map or {}
        self.verify = verify

    def use_map(self, data):
        self.monitor_map = monitor_map(data)

    def _fetch(self):
        # Kuma's /metrics is Prometheus format behind HTTP Basic auth: the username
        # is ignored, the password is the API key (NOT a Bearer token).
        resp = runtime.get(
            self.url + "/metrics",
            auth=("", self.api_key) if self.api_key else None,
            timeout=_TIMEOUT,
            verify=self.verify,
        )
        return _parse_kuma_metrics(resp.text, self.monitor_map)


# Kuma monitor_status values → Atlas marker states (0 down · 1 up · 2 pending · 3 maint)
_KUMA_STATE = {0: DOWN, 1: HEALTHY, 2: DEGRADED, 3: MAINTENANCE}


def _parse_kuma_metrics(text, monitor_map):
    """Turn Kuma's Prometheus-format /metrics into node + service states.

    Mapped monitors (in monitor_map) → `nodes` under their node id (K1 marker states).
    Unmapped monitors → `services` keyed by monitor name (K4 per-service dots); a
    service link in the dataset opts into a dot via its own `kuma` field. With no
    map configured at all, every monitor is treated as a node (mock / name-match).

    Several monitors may point at one place; the place takes the worst of them.
    """
    nodes, services = {}, {}
    for line in text.splitlines():
        if not line.startswith("monitor_status{"):
            continue
        try:
            name = line.split('monitor_name="', 1)[1].split('"', 1)[0]
            value = int(float(line.rsplit(" ", 1)[1]))
        except (IndexError, ValueError):
            continue
        state = {"state": _KUMA_STATE.get(value, DOWN)}
        target = monitor_map.get(name)
        if target is not None:
            prior = (nodes.get(target) or {}).get("state")
            nodes[target] = {"state": _worse(prior, state["state"])}
        elif monitor_map:
            services[name] = state       # unmapped → per-service (keyed by monitor name)
        else:
            nodes[name] = state          # no map → name-match (mock / identity)
    out = {"nodes": nodes}
    if services:
        out["services"] = services
    return out


def _kuma_adapter(url):
    import integrations
    return KumaAdapter(url, _read_secret("ATLAS_KUMA_API_KEY"),
                       verify=not integrations.flag("ATLAS_KUMA_INSECURE", False))
