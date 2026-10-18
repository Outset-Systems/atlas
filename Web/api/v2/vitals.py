"""G16 · Native card vitals — `GET /api/v2/vitals/<node_id>` (v1.34.0).

WHY. The card's "pulse of this place" used to be two Grafana `/d-solo/`
iframes — each booting the entire Grafana SPA to draw one gauge. Megabytes of
JavaScript for two numbers, a visible multi-second boot on every cold cache,
and the map's most-touched surface depended on Grafana being up and warm
(2026-08-30 made that cost obvious: four Grafana restarts in an evening and
every card felt broken). The Atlas already trusts `ATLAS_PROM_URL` for the
signals layer, so the server asks Prometheus itself and the card draws its own
sparkline — a few hundred bytes of JSON instead of two SPA boots, and the
core map works with no Grafana at all (the §20c AIO shape: Grafana is the
optional deep-dive, never the pulse).

SHAPE. `{window, step, cpu: [[ts, pct]…], ram: [[ts, pct]…], now: {cpu, ram}}`
— seven days at one-hour steps, percentages rounded to one decimal. A place
Prometheus has never met returns empty series and null `now`s; the card shows
nothing rather than a fake calm (the "missing must stay missing" rule).

RULES, same as every other outbound asker in this app:
* Never a free-form proxy — exactly two PromQL shapes are ever issued, and the
  instance label is built from the DATASET's own ip for the named node. The
  client chooses a node id, nothing else.
* Behind the app-wide gate (deliberately NOT in `EXEMPT_PATHS`).
* 404 when unconfigured — an absent feature answers as absent (the `ingest`
  precedent), so a template deployment without Prometheus just has quieter
  cards.
* A short per-node cache (120 s): opening the same card twice in a minute
  should not ask Prometheus twice for an hour-granular week.
"""

import logging
import re
import threading
import time

from flask import jsonify

from context import atlas

from . import bp

log = logging.getLogger("atlas.api.v2")

_WINDOW_S = 7 * 24 * 3600
_STEP_S = 3600
_CACHE_TTL_S = 120
_TIMEOUT = 6

# Exactly what node-exporter answers for a host, nothing configurable:
# CPU = share of non-idle time, RAM = share of memory not available.
_CPU_Q = ('100 * (1 - avg(rate(node_cpu_seconds_total'
          '{{mode="idle",instance="{inst}"}}[15m])))')
_RAM_Q = ('100 * (1 - node_memory_MemAvailable_bytes{{instance="{inst}"}}'
          ' / node_memory_MemTotal_bytes{{instance="{inst}"}})')

#: The instance label rides inside PromQL quotes; the dataset's ips are clean
#: by schema, but a label value is still never interpolated unvetted.
_INST_OK = re.compile(r"^[0-9A-Za-z.\-:]+$")

_cache_lock = threading.Lock()
_cache: dict = {}   # node_id -> (expires_at, payload)


def _prom_url() -> str:
    # THE SOURCES (v1.37.0): the settings file first, the environment second
    import integrations
    return integrations.get("ATLAS_PROM_URL").rstrip("/")


def _range_query(base, query, start, end, step):
    """One `query_range` call. Module-level on purpose — the tests inject a
    fake here, which is also why the route never calls `requests` directly."""
    import requests
    r = requests.get(base + "/api/v1/query_range",
                     params={"query": query, "start": start,
                             "end": end, "step": step},
                     timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json().get("data", {}).get("result", [])


def _series(result):
    """First matrix result → [[int ts, float pct]…], junk points dropped."""
    if not result:
        return []
    out = []
    for ts, val in result[0].get("values", []):
        try:
            out.append([int(float(ts)), round(float(val), 1)])
        except (TypeError, ValueError):
            continue
    return out


@bp.route("/vitals/<node_id>")
def vitals(node_id):
    base = _prom_url()
    if not base:
        return jsonify({"error": "vitals are not configured "
                                 "(ATLAS_PROM_URL unset)"}), 404

    now = time.time()
    with _cache_lock:
        hit = _cache.get(node_id)
        if hit and hit[0] > now:
            return jsonify(hit[1])

    ctx = atlas()
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError) as e:
        log.error("vitals: lab data unreadable: %s", e)
        return jsonify({"error": f"lab data unreadable: {e}"}), 500

    node = next((n for n in data.get("nodes", [])
                 if n.get("id") == node_id), None)
    if node is None:
        return jsonify({"error": "no such place"}), 404
    ip = str(node.get("ip") or "").split("/")[0].strip()
    if not ip or ip == "—":
        return jsonify({"error": "this place has no address to ask about"}), 404
    inst = f"{ip}:9100"
    if not _INST_OK.match(inst):
        return jsonify({"error": "this place's address is not askable"}), 404

    start, end = int(now) - _WINDOW_S, int(now)
    try:
        cpu = _series(_range_query(base, _CPU_Q.format(inst=inst),
                                   start, end, _STEP_S))
        ram = _series(_range_query(base, _RAM_Q.format(inst=inst),
                                   start, end, _STEP_S))
    except Exception as e:  # noqa: BLE001 — an unreachable scribe is a 502, not a crash
        log.warning("vitals: prometheus not answering for %s: %s", node_id, e)
        return jsonify({"error": "the scribe is not answering"}), 502

    payload = {
        "window": "7d", "step": _STEP_S, "cpu": cpu, "ram": ram,
        "now": {"cpu": cpu[-1][1] if cpu else None,
                "ram": ram[-1][1] if ram else None},
    }
    with _cache_lock:
        _cache[node_id] = (now + _CACHE_TTL_S, payload)
    return jsonify(payload)
