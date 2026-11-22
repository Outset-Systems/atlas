from engines.base import _Adapter, _TIMEOUT
import engines.runtime as runtime


class PrometheusAdapter(_Adapter):

    name = "prometheus"

    _PROM_QUERIES = {
        "watchfires_up": "count(up == 1)",
        "watchfires_total": "count(up)",
    }
    _PATCH_QUERIES = {
        "patches_pending": "apt_upgrades_pending",
        "patches_security": "apt_upgrades_security_pending",
        "reboot_required": "node_reboot_required",
        "patch_surveyed": "patch_checked_timestamp_seconds",
    }

    def __init__(self, url):
        self.url = url.rstrip("/")
        self.ip_map = {}

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
    return {n["ip"]: n["id"] for n in data.get("nodes", []) or []
            if isinstance(n, dict) and n.get("id") and n.get("ip") and n["ip"] != "—"}


def _prometheus_adapter(url):
    return PrometheusAdapter(url)
