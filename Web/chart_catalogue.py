import envnames

WINDOWS = {
    "1h": (3600, 60),
    "6h": (6 * 3600, 300),
    "24h": (24 * 3600, 900),
    "7d": (7 * 24 * 3600, 3600),
    "21d": (21 * 24 * 3600, 3 * 3600),
    "30d": (30 * 24 * 3600, 6 * 3600),
    "1y": (365 * 24 * 3600, 24 * 3600),
}
DEFAULT_WINDOW = "21d"

_LOKI_MAX_WINDOW = "30d"


_LLM_CONTAINERS = envnames.env("ATLAS_LLM_CONTAINERS")
_LLM_TAG = envnames.env("ATLAS_LLM_LOG_TAG")
_LLM_STREAM = '{container=~"' + _LLM_CONTAINERS + '"}'

_TRAEFIK_LINE = ('{job="traefik"} | pattern `<ip> - <_> [<_>] "<method> <path> <_>" '
                 '<status> <size> <_> <_> <_> "<router>" <rest>`')
_NET_DEV = 'device!~"lo|veth.*|br.*|docker.*|virbr.*|tap.*"'

CATALOGUE = {
    "containers.cpu": dict(
        title="CPU by container", kind="series", unit="pct", source="prom",
        window=DEFAULT_WINDOW, limit=12, grafana=("example", 15),
        queries=[('sum by (name) (rate(container_cpu_usage_seconds_total'
                  '{name!=""}[$__ri])) * 100', "{{name}}")]),
    "containers.mem": dict(
        title="Memory by container", kind="series", unit="bytes", source="prom",
        window=DEFAULT_WINDOW, limit=12, grafana=("example", 9),
        queries=[('sum by (name) (container_memory_rss{name!=""})', "{{name}}")]),
    "llm.calls": dict(
        title="LLM calls — ok vs fallback", kind="bars", unit="count", source="loki",
        window=DEFAULT_WINDOW, grafana=("example", 4),
        queries=[('sum(count_over_time(' + _LLM_STREAM +
                  ' |~ "' + _LLM_TAG + ' ok" [$__step]))', "ok"),
                 ('sum(count_over_time(' + _LLM_STREAM +
                  ' |= "' + _LLM_TAG + ' FALLBACK" [$__step]))', "fallback")]),
    "llm.apps": dict(
        title="LLM calls per app", kind="series", unit="count", source="loki",
        window=DEFAULT_WINDOW, grafana=("example", 5),
        queries=[('sum by (container) (count_over_time(' + _LLM_STREAM +
                  ' |~ "' + _LLM_TAG + ' (ok|FALLBACK)" [$__step]))', "{{container}}")]),
    "patch.pending": dict(
        title="Pending upgrades by host", kind="series", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("example", 4),
        queries=[("apt_upgrades_pending", "{{host}}")]),
    "edge.bans": dict(
        title="Active decisions, by origin", kind="series", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("example", 6),
        queries=[("sum by (origin) (cs_active_decisions)", "{{origin}}")]),
    "edge.detections": dict(
        title="Scenario overflows (detections)", kind="bars", unit="count", source="prom",
        window=DEFAULT_WINDOW, limit=12, grafana=("example", 5),
        queries=[("sum by (name) (increase(cs_bucket_overflowed_total[$__step]))",
                  "{{name}}")]),
    "hosts.net": dict(
        title="Network traffic by host", kind="series", unit="bps", source="prom",
        window=DEFAULT_WINDOW, grafana=("example", 74),
        queries=[('sum by (instance) (rate(node_network_receive_bytes_total{'
                  + _NET_DEV + '}[$__ri]) + rate(node_network_transmit_bytes_total{'
                  + _NET_DEV + '}[$__ri])) * 8', "{{instance}}")]),
    "edge.status": dict(
        title="Public requests by status class", kind="series", unit="count",
        source="loki", window=DEFAULT_WINDOW, grafana=("example", 7),
        queries=[('sum(count_over_time(' + _TRAEFIK_LINE +
                  ' | status=~"2..|3.." [$__step]))', "2xx/3xx"),
                 ('sum(count_over_time(' + _TRAEFIK_LINE +
                  ' | status=~"4.." [$__step]))', "4xx"),
                 ('sum(count_over_time(' + _TRAEFIK_LINE +
                  ' | status=~"5.." [$__step]))', "5xx")]),
    "edge.routers": dict(
        title="Public requests by router", kind="series", unit="count",
        source="loki", window=DEFAULT_WINDOW, grafana=("example", 8),
        queries=[('sum by (router) (count_over_time(' + _TRAEFIK_LINE +
                  ' [$__step]))', "{{router}}")]),
    "edge.top_clients": dict(
        title="Top client IPs", kind="table", unit="count", source="loki",
        window=DEFAULT_WINDOW, limit=10, grafana=("example", 9),
        queries=[('topk(10, sum by (ip) (count_over_time({job="traefik"} '
                  '| pattern `<ip> - <rest>` [$__range])))', "{{ip}}")]),
    "edge.top_probes": dict(
        title="Top 403/404 paths (probes)", kind="table", unit="count", source="loki",
        window="24h", max_window="24h", limit=10, grafana=("example", 10),
        queries=[('topk(10, sum by (path, status) (count_over_time(' + _TRAEFIK_LINE +
                  ' | status=~"40[34]" [$__range])))', "{{status}} {{path}}")]),
    "edge.ssh_denied": dict(
        title="Failed SSH auth by host", kind="bars", unit="count", source="loki",
        window=DEFAULT_WINDOW, grafana=("example", 11),
        queries=[('sum by (host) (count_over_time({job="auth"} |~ "Failed password|'
                  'Invalid user|authentication failure" [$__step]))', "{{host}}")]),
    "edge.ssh_granted": dict(
        title="Accepted SSH logins by host", kind="bars", unit="count", source="loki",
        window=DEFAULT_WINDOW, grafana=("example", 12),
        queries=[('sum by (host) (count_over_time({job="auth"} |= "Accepted" [$__step]))',
                  "{{host}}")]),
    "edge.scenarios": dict(
        title="Decisions by scenario", kind="series", unit="count", source="prom",
        window=DEFAULT_WINDOW, limit=10, grafana=("example", 32),
        queries=[("sum by (reason) (cs_active_decisions)", "{{reason}}")]),
    "edge.active_bans": dict(
        title="Active bans", kind="stat", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("example", 1),
        queries=[("sum(cs_active_decisions) or vector(0)", "bans")]),
    "edge.alerts": dict(
        title="Alerts by LAPI host", kind="stat", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("example", 2),
        queries=[("sum by (host) (cs_alerts)", "{{host}}")]),
    "edge.bouncer": dict(
        title="Bouncer queries / min", kind="stat", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("example", 3),
        queries=[("sum(rate(cs_lapi_bouncer_requests_total[$__ri])) * 60", "req/min")]),
    "edge.parsed": dict(
        title="Log lines parsed / s", kind="stat", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("example", 4),
        queries=[("sum(rate(cs_parser_hits_total[$__ri]))", "lines/s")]),
}
