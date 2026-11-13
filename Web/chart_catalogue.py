"""The chart catalogue: every chart `/api/v2/charts` can draw, the windows a
client may ask for, and the query text behind each key.

Data only. The routes, the two askers, the cache and the budget are in
`api/v2/charts.py`, which imports `CATALOGUE` and `WINDOWS` from here, so both
names still resolve on that module. It is a top-level module, beside
`settings.py`, because the Deployment view lists environment names by reading
the source of the modules there, and two of them are read below.
"""

import envnames

#: The windows a client may ask for, each with the bucket that keeps a chart
#: at a readable ~100–170 points. Anything else is refused, not rounded.
WINDOWS = {
    "1h": (3600, 60),
    "6h": (6 * 3600, 300),
    "24h": (24 * 3600, 900),
    "7d": (7 * 24 * 3600, 3600),
    "21d": (21 * 24 * 3600, 3 * 3600),        # the default (2026-09-03)
    "30d": (30 * 24 * 3600, 6 * 3600),
    "1y": (365 * 24 * 3600, 24 * 3600),       # "all time" — the source's retention decides how far back it truly reaches
}
DEFAULT_WINDOW = "21d"

#: Loki refuses a range wider than its `max_query_length` (30d1h by default)
#: outright, and its retention is 30 days anyway — so every Loki-backed chart
#: is capped there unless it says something tighter. Prometheus answers any
#: window; its retention simply ends the series where the data ends.
_LOKI_MAX_WINDOW = "30d"

# Log lines every LLM caller in the suite writes (framework llm_core):
#   "llm ok model=…"  /  "llm FALLBACK model=… reason=…"
# The container list is the callers as of v1.35.0 — the Grafana original still
# named score-worker, retired 2026-08-26, and missed the Feed v2 worker that
# now makes almost every call.
# Which containers and which log tag are one deployment's facts (v1.48.0):
# ATLAS_LLM_CONTAINERS is a Loki regex over container names (default: any),
# ATLAS_LLM_LOG_TAG the prefix of the "<tag> ok" / "<tag> FALLBACK" lines.

_LLM_CONTAINERS = envnames.env("ATLAS_LLM_CONTAINERS")
_LLM_TAG = envnames.env("ATLAS_LLM_LOG_TAG")
_LLM_STREAM = '{container=~"' + _LLM_CONTAINERS + '"}'

# Traefik's access line, as Loki's `pattern` parser reads it.
_TRAEFIK_LINE = ('{job="traefik"} | pattern `<ip> - <_> [<_>] "<method> <path> <_>" '
                 '<status> <size> <_> <_> <_> "<router>" <rest>`')
_NET_DEV = 'device!~"lo|veth.*|br.*|docker.*|virbr.*|tap.*"'

#: The catalogue. `grafana` names the panel each one replaces, so a watching
#: whose `embed` URL points there is matched without a dataset edit.
#: Tokens inside a query: `$__ri` (rate interval), `$__step` (one bucket),
#: `$__range` (the whole window) — Grafana's names, substituted here.
CATALOGUE = {
    # ── THE UPPER DECK ──────────────────────────────────────────────────
    "containers.cpu": dict(
        title="CPU by container", kind="series", unit="pct", source="prom",
        window=DEFAULT_WINDOW, limit=12, grafana=("pMEd7m0Mz", 15),
        queries=[('sum by (name) (rate(container_cpu_usage_seconds_total'
                  '{name!=""}[$__ri])) * 100', "{{name}}")]),
    "containers.mem": dict(
        title="Memory by container", kind="series", unit="bytes", source="prom",
        window=DEFAULT_WINDOW, limit=12, grafana=("pMEd7m0Mz", 9),
        queries=[('sum by (name) (container_memory_rss{name!=""})', "{{name}}")]),
    "llm.calls": dict(
        title="LLM calls — ok vs fallback", kind="bars", unit="count", source="loki",
        window=DEFAULT_WINDOW, grafana=("lab-llm-health", 4),
        queries=[('sum(count_over_time(' + _LLM_STREAM +
                  ' |~ "' + _LLM_TAG + ' ok" [$__step]))', "ok"),
                 ('sum(count_over_time(' + _LLM_STREAM +
                  ' |= "' + _LLM_TAG + ' FALLBACK" [$__step]))', "fallback")]),
    "llm.apps": dict(
        title="LLM calls per app", kind="series", unit="count", source="loki",
        window=DEFAULT_WINDOW, grafana=("lab-llm-health", 5),
        queries=[('sum by (container) (count_over_time(' + _LLM_STREAM +
                  ' |~ "' + _LLM_TAG + ' (ok|FALLBACK)" [$__step]))', "{{container}}")]),
    "patch.pending": dict(
        title="Pending upgrades by host", kind="series", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("lab-patch-survey", 4),
        queries=[("apt_upgrades_pending", "{{host}}")]),
    # ── THE DEPTHS ───────────────────────────────────────────────────────
    "edge.bans": dict(
        title="Active decisions, by origin", kind="series", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("lab-security", 6),
        queries=[("sum by (origin) (cs_active_decisions)", "{{origin}}")]),
    "edge.detections": dict(
        title="Scenario overflows (detections)", kind="bars", unit="count", source="prom",
        window=DEFAULT_WINDOW, limit=12, grafana=("lab-security", 5),
        queries=[("sum by (name) (increase(cs_bucket_overflowed_total[$__step]))",
                  "{{name}}")]),
    "hosts.net": dict(
        title="Network traffic by host", kind="series", unit="bps", source="prom",
        window=DEFAULT_WINDOW, grafana=("rYdddlPWk", 74),
        queries=[('sum by (instance) (rate(node_network_receive_bytes_total{'
                  + _NET_DEV + '}[$__ri]) + rate(node_network_transmit_bytes_total{'
                  + _NET_DEV + '}[$__ri])) * 8', "{{instance}}")]),
    "edge.status": dict(
        title="Public requests by status class", kind="series", unit="count",
        source="loki", window=DEFAULT_WINDOW, grafana=("lab-security", 7),
        queries=[('sum(count_over_time(' + _TRAEFIK_LINE +
                  ' | status=~"2..|3.." [$__step]))', "2xx/3xx"),
                 ('sum(count_over_time(' + _TRAEFIK_LINE +
                  ' | status=~"4.." [$__step]))', "4xx"),
                 ('sum(count_over_time(' + _TRAEFIK_LINE +
                  ' | status=~"5.." [$__step]))', "5xx")]),
    "edge.routers": dict(
        title="Public requests by router", kind="series", unit="count",
        source="loki", window=DEFAULT_WINDOW, grafana=("lab-security", 8),
        queries=[('sum by (router) (count_over_time(' + _TRAEFIK_LINE +
                  ' [$__step]))', "{{router}}")]),
    "edge.top_clients": dict(
        title="Top client IPs", kind="table", unit="count", source="loki",
        window=DEFAULT_WINDOW, limit=10, grafana=("lab-security", 9),
        queries=[('topk(10, sum by (ip) (count_over_time({job="traefik"} '
                  '| pattern `<ip> - <rest>` [$__range])))', "{{ip}}")]),
    # ⚠ max_window: a week of guessed paths is more than Loki's 500-series
    # ceiling for one query (measured 2026-09-02: 7d → "maximum of series
    # (500) reached", 24h fine). The Grafana panel this replaces had the same
    # limit and simply showed an error over its default week.
    "edge.top_probes": dict(
        title="Top 403/404 paths (probes)", kind="table", unit="count", source="loki",
        window="24h", max_window="24h", limit=10, grafana=("lab-security", 10),
        queries=[('topk(10, sum by (path, status) (count_over_time(' + _TRAEFIK_LINE +
                  ' | status=~"40[34]" [$__range])))', "{{status}} {{path}}")]),
    "edge.ssh_denied": dict(
        title="Failed SSH auth by host", kind="bars", unit="count", source="loki",
        window=DEFAULT_WINDOW, grafana=("lab-security", 11),
        queries=[('sum by (host) (count_over_time({job="auth"} |~ "Failed password|'
                  'Invalid user|authentication failure" [$__step]))', "{{host}}")]),
    "edge.ssh_granted": dict(
        title="Accepted SSH logins by host", kind="bars", unit="count", source="loki",
        window=DEFAULT_WINDOW, grafana=("lab-security", 12),
        queries=[('sum by (host) (count_over_time({job="auth"} |= "Accepted" [$__step]))',
                  "{{host}}")]),
    "edge.scenarios": dict(
        title="Decisions by scenario", kind="series", unit="count", source="prom",
        window=DEFAULT_WINDOW, limit=10, grafana=("hjmZdB4nk", 32),
        queries=[("sum by (reason) (cs_active_decisions)", "{{reason}}")]),
    "edge.active_bans": dict(
        title="Active bans", kind="stat", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("lab-security", 1),
        queries=[("sum(cs_active_decisions) or vector(0)", "bans")]),
    "edge.alerts": dict(
        title="Alerts by LAPI host", kind="stat", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("lab-security", 2),
        queries=[("sum by (host) (cs_alerts)", "{{host}}")]),
    "edge.bouncer": dict(
        title="Bouncer queries / min", kind="stat", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("lab-security", 3),
        queries=[("sum(rate(cs_lapi_bouncer_requests_total[$__ri])) * 60", "req/min")]),
    "edge.parsed": dict(
        title="Log lines parsed / s", kind="stat", unit="count", source="prom",
        window=DEFAULT_WINDOW, grafana=("lab-security", 4),
        queries=[("sum(rate(cs_parser_hits_total[$__ri]))", "lines/s")]),
}
