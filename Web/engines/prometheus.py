"""The `prometheus` source: a fixed list of queries, for the plaque numbers
and the per-place patch survey."""

from engines.base import _Adapter, _TIMEOUT
import engines.runtime as runtime


class PrometheusAdapter(_Adapter):
    """Whitelisted PromQL → plaque numbers & sparklines.

    Never a free-form proxy: only the queries in `_PROM_QUERIES` and
    `_PATCH_QUERIES` are ever issued. Live (the wiring was Wave 2); it needs
    only a route from the app to the Prometheus address.
    """

    name = "prometheus"

    # label -> instant PromQL. Whitelist only; the client can never inject a query.
    _PROM_QUERIES = {
        "watchfires_up": "count(up == 1)",
        "watchfires_total": "count(up)",
    }
    # per-instance patch survey (weekly textfile collector, 2026-07-11)
    _PATCH_QUERIES = {
        "patches_pending": "apt_upgrades_pending",
        "patches_security": "apt_upgrades_security_pending",
        "reboot_required": "node_reboot_required",
        "patch_surveyed": "patch_survey_timestamp_seconds",
    }

    def __init__(self, url):
        self.url = url.rstrip("/")
        self.ip_map = {}   # "10.0.20.5" -> node id (set from the dataset)

    def use_map(self, data):
        self.ip_map = ip_map(data)

    def _query(self, q):
        r = runtime.get(self.url + "/api/v1/query", params={"query": q}, timeout=_TIMEOUT)
        return r.json().get("data", {}).get("result", [])

    def _fetch(self):
        metrics = {}
        for label, q in self._PROM_QUERIES.items():
            result = self._query(q)
            if result:
                metrics[label] = float(result[0]["value"][1])
        nodes = {}
        for key, q in self._PATCH_QUERIES.items():
            for r in self._query(q):
                ip = (r.get("metric", {}).get("instance") or "").split(":")[0]
                nid = self.ip_map.get(ip)
                if nid:
                    nodes.setdefault(nid, {})[key] = float(r["value"][1])
        out = {"metrics": metrics}
        if nodes:
            out["nodes"] = nodes
        return out


def ip_map(data):
    """{address: place id} from a dataset: which place a Prometheus `instance`
    belongs to."""
    return {n["ip"]: n["id"] for n in data.get("nodes", []) or []
            if isinstance(n, dict) and n.get("id") and n.get("ip") and n["ip"] != "—"}


def _prometheus_adapter(url):
    return PrometheusAdapter(url)
