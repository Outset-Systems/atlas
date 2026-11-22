import logging
import re
import threading
import time

from flask import jsonify

from context import atlas
from redaction import cleared, no_store, viewer_groups

from . import bp

log = logging.getLogger("atlas.api.v2")

_WINDOW_S = 7 * 24 * 3600
_STEP_S = 3600
_CACHE_TTL_S = 120
_TIMEOUT = 6

_CPU_Q = ('100 * (1 - avg(rate(node_cpu_seconds_total'
          '{{mode="idle",instance="{inst}"}}[15m])))')
_RAM_Q = ('100 * (1 - node_memory_MemAvailable_bytes{{instance="{inst}"}}'
          ' / node_memory_MemTotal_bytes{{instance="{inst}"}})')

_INST_OK = re.compile(r"^[0-9A-Za-z.\-:]+$")

_cache_lock = threading.Lock()
_cache: dict = {}


def _prom_url() -> str:
    import integrations
    return integrations.get("ATLAS_PROM_URL").rstrip("/")


def _range_query(base, query, start, end, step):
    import requests
    r = requests.get(base + "/api/v1/query_range",
                     params={"query": query, "start": start,
                             "end": end, "step": step},
                     timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json().get("data", {}).get("result", [])


def _series(result):
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
    import demofigures
    demo = demofigures.enabled()
    base = _prom_url()
    if not base and not demo:
        return jsonify({"error": "vitals are not configured "
                                 "(ATLAS_PROM_URL unset)"}), 404

    ctx = atlas()
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError) as e:
        log.error("vitals: lab data unreadable: %s", e)
        return jsonify({"error": f"lab data unreadable: {e}"}), 500

    node = next((n for n in data.get("nodes", [])
                 if n.get("id") == node_id), None)
    if node is None or not cleared(node, viewer_groups()):
        return jsonify({"error": "no such place"}), 404

    now = time.time()
    if demo:
        week = demofigures.vitals(node_id, int(now))
        if not week:
            return jsonify({"error": "the demo has no vitals for this place"}), 404
        return no_store(jsonify({"window": "7d", "step": _STEP_S, **week, "demo": True,
                                 "now": {"cpu": week["cpu"][-1][1] if week["cpu"] else None,
                                         "ram": week["ram"][-1][1] if week["ram"] else None}}))
    with _cache_lock:
        hit = _cache.get(node_id)
        if hit and hit[0] > now:
            return no_store(jsonify(hit[1]))
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
    except Exception as e:
        log.warning("vitals: prometheus not answering for %s: %s", node_id, e)
        return jsonify({"error": "the scribe is not answering"}), 502

    payload = {
        "window": "7d", "step": _STEP_S, "cpu": cpu, "ram": ram,
        "now": {"cpu": cpu[-1][1] if cpu else None,
                "ram": ram[-1][1] if ram else None},
    }
    with _cache_lock:
        _cache[node_id] = (now + _CACHE_TTL_S, payload)
    return no_store(jsonify(payload))
