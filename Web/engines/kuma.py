from engines.base import (
    DEGRADED, DOWN, HEALTHY, MAINTENANCE, _Adapter, _TIMEOUT, _read_secret, _worse,
    monitor_map,
)
import engines.runtime as runtime


class KumaAdapter(_Adapter):

    name = "kuma"

    def __init__(self, url, api_key, monitor_map=None, verify=True):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.monitor_map = monitor_map or {}
        self.verify = verify

    def use_map(self, data):
        self.monitor_map = monitor_map(data)

    def _fetch(self):
        resp = runtime.get(
            self.url + "/metrics",
            auth=("", self.api_key) if self.api_key else None,
            timeout=_TIMEOUT,
            verify=self.verify,
        )
        return _parse_kuma_metrics(resp.text, self.monitor_map)


_KUMA_STATE = {0: DOWN, 1: HEALTHY, 2: DEGRADED, 3: MAINTENANCE}


def _parse_kuma_metrics(text, monitor_map):
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
            services[name] = state
        else:
            nodes[name] = state
    out = {"nodes": nodes}
    if services:
        out["services"] = services
    return out


def _kuma_adapter(url):
    import integrations
    return KumaAdapter(url, _read_secret("ATLAS_KUMA_API_KEY"),
                       verify=not integrations.flag("ATLAS_KUMA_INSECURE", False))
