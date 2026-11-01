"""The Atlas reports on itself — `GET /metrics` for Prometheus (v1.38.0).

Every other place in the realm has a watchfire; the Atlas, which draws them
all, had none. This module is a Prometheus exposition of the app's own
health: request counts and latency by route and status, the chart layer's
fetches by source and outcome, the signals hub's last answer per source, and
a build-info line carrying the version.

Three decisions:

* **Bearer-gated, never anonymous.** `/metrics` is exempt from the session
  gate (Prometheus has no session) but answers only to
  `Authorization: Bearer <ATLAS_METRICS_TOKEN>` (`_FILE` variant for a docker
  secret). No token configured → 404, the house rule for absent features —
  so an Atlas that has not been told about a scraper exposes nothing, not
  even the fact that it could.
* **Correct across workers.** gunicorn runs two workers; a plain in-process
  registry would answer with whichever worker took the scrape. The
  prometheus_client multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`, set in the
  Dockerfile) keeps per-process files and sums them at scrape time. Without
  the env (tests, `python app.py`) it degrades to the single-process registry.
* **Routes, not URLs.** The label is the Flask rule (`/api/v2/charts/<key>`),
  never the raw path — a node id or a chart key in a label is a cardinality
  leak and, for the dataset's ids, a topology leak into a metrics store.
"""

import hmac
import logging
import os
import time

from flask import Blueprint, Response, g, request

log = logging.getLogger("atlas.web.metrics")

bp = Blueprint("metrics", __name__)
METRICS_PATH = "/metrics"

_enabled = False
_registry = None
_REQUESTS = _LATENCY = _CHART_FETCHES = _CHART_SECONDS = _SOURCE_STATE = _BUILD = None


def _token():
    import envnames
    return envnames.secret("ATLAS_METRICS_TOKEN")


def _setup():
    """Build the collectors once. prometheus_client is an optional dependency
    in the sense that its absence turns this module into a no-op that logs
    why, rather than an import error that stops the map."""
    global _enabled, _registry, _REQUESTS, _LATENCY, _CHART_FETCHES, _CHART_SECONDS, _SOURCE_STATE, _BUILD
    if _enabled:
        return True
    try:
        from prometheus_client import (CollectorRegistry, Counter, Gauge, Histogram,
                                       REGISTRY, multiprocess)
    except ImportError:
        log.warning("prometheus_client is not installed — /metrics is off")
        return False
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        os.makedirs(os.environ["PROMETHEUS_MULTIPROC_DIR"], exist_ok=True)
        _registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(_registry)
    else:
        _registry = REGISTRY
    _REQUESTS = Counter("atlas_http_requests_total", "HTTP requests served",
                        ["method", "route", "status"])
    _LATENCY = Histogram("atlas_http_request_seconds", "HTTP request latency by route",
                         ["route"], buckets=(0.005, 0.025, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))
    _CHART_FETCHES = Counter("atlas_chart_fetches_total", "Native watching answers, by outcome",
                             ["source", "outcome"])
    _CHART_SECONDS = Histogram("atlas_chart_fetch_seconds", "Time to answer one native watching",
                               ["source"], buckets=(0.05, 0.25, 0.5, 1, 2.5, 5, 10, 25))
    # Gauges that every worker sets to the SAME truth use `livemostrecent`:
    # the newest write from a process that is still alive (review, 2026-09-03
    # — `max` let a dead worker's file pin source_ok at 1 forever, so
    # AtlasSourceSilent could never fire until the container was recreated).
    # `live*` modes need dead workers unregistered: gunicorn.conf.py's
    # child_exit calls mark_process_dead().
    _SOURCE_STATE = Gauge("atlas_signals_source_ok", "1 when the source answered on the last poll",
                          ["source"], multiprocess_mode="livemostrecent")
    _BUILD = Gauge("atlas_build_info", "Version of the running Atlas", ["version"],
                   multiprocess_mode="livemax")
    global _DRIFT, _DATASET_AGE
    _DRIFT = Gauge("atlas_dataset_drift",
                   "1 when the live dataset differs from the copy baked into this image (git HEAD at build)",
                   multiprocess_mode="livemostrecent")
    _DATASET_AGE = Gauge("atlas_dataset_age_seconds", "Seconds since the live dataset was last written",
                         multiprocess_mode="livemostrecent")
    import settings
    _BUILD.labels(version=settings.APP_VERSION).set(1)
    _enabled = True
    return True


_DRIFT = _DATASET_AGE = None
_drift_cache = {"at": 0.0, "value": None}


def _observe_dataset():
    """THE DRIFT CHECK (v1.38.1). DATA.md's contract: `Web/default-lab-data.json`
    (baked into the image — git HEAD at build) must equal the live
    `Data/lab-data.json`. The Desk edits the live one; the dataset sync script
    pulls it back into git. Between those two the repo is behind the map, and
    nothing said so — the Z: copy drifted for a week before the 09-02 Grafana
    decom found it. Now the Atlas measures it on every scrape (cheap: two
    hashes of ~80 KB, cached a minute) and `AtlasDatasetDrift` pages after a
    day. Absent files count as drift too: a missing default is a build
    problem, a missing live file is the fallback map.

    File backend only: on the db backend `DATA_PATH` is not the dataset, so
    hashing it read as permanent drift. There is nothing to compare there
    yet, and no reading beats a false one."""
    import hashlib
    import settings
    if settings.DATA_BACKEND != "file":
        return
    now = time.monotonic()
    if now - _drift_cache["at"] < 60 and _drift_cache["value"] is not None:
        return
    def digest(path):
        try:
            with open(path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            return None
    live, baked = digest(settings.DATA_PATH), digest(settings.DEFAULT_DATA_PATH)
    drift = 0 if (live and baked and live == baked) else 1
    try:
        age = max(0.0, time.time() - os.path.getmtime(settings.DATA_PATH))
    except OSError:
        age = -1
    _DRIFT.set(drift)
    _DATASET_AGE.set(age)
    _drift_cache.update(at=now, value=drift)


def record_chart(source, outcome, seconds):
    if _enabled:
        _CHART_FETCHES.labels(source=source, outcome=outcome).inc()
        _CHART_SECONDS.labels(source=source).observe(seconds)


def record_sources(states):
    """`{name: 'ok' | 'silent'}` from the hub, after each poll."""
    if _enabled:
        for name, state in (states or {}).items():
            _SOURCE_STATE.labels(source=str(name)).set(1 if state == "ok" else 0)


def _route_label():
    rule = request.url_rule.rule if request.url_rule else "unmatched"
    if rule.startswith("/static/"):
        return "/static/<path>"
    return rule


@bp.route(METRICS_PATH)
def scrape():
    token = _token()
    if not token:
        return {"error": "metrics are not configured (ATLAS_METRICS_TOKEN unset)"}, 404
    import security
    given = security.bearer_token(request)
    if not given or not hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8")):
        return Response("unauthorized\n", status=401, mimetype="text/plain")
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    try:
        _observe_dataset()
    except Exception as e:  # noqa: BLE001 — a scrape must never fail over the drift check
        log.warning("metrics: dataset drift check failed: %s", e)
    return Response(generate_latest(_registry), mimetype=CONTENT_TYPE_LATEST,
                    headers={"Cache-Control": "no-store"})


def init_app(app):
    """Wire the hooks and the route. Returns True when the registry is live.

    A registry that cannot come up (the multiprocess dir unwritable — the
    2026-09-03 uid mismatch — or a broken install) is a warning and no
    watchfire, never a map that will not boot: the Atlas's own health must not
    depend on its ability to report it."""
    try:
        ok = _setup()
    except Exception as e:  # noqa: BLE001 — see above
        log.error("metrics disabled: the registry could not start: %s", e)
        ok = False
    if not ok:
        return False

    @app.before_request
    def _start():
        g._metrics_t0 = time.monotonic()

    @app.after_request
    def _observe(resp):
        t0 = getattr(g, "_metrics_t0", None)
        if t0 is not None and request.path != METRICS_PATH:
            route = _route_label()
            _REQUESTS.labels(method=request.method, route=route,
                             status=str(resp.status_code)).inc()
            _LATENCY.labels(route=route).observe(time.monotonic() - t0)
        return resp

    app.register_blueprint(bp)
    return True
