import hashlib
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
_DRIFT = _DATASET_AGE = None


def _token():
    import envnames
    return envnames.secret("ATLAS_METRICS_TOKEN")


def _setup():
    global _enabled, _registry, _REQUESTS, _LATENCY, _CHART_FETCHES, _CHART_SECONDS, _SOURCE_STATE, _BUILD
    global _DRIFT, _DATASET_AGE
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
    _SOURCE_STATE = Gauge("atlas_signals_source_ok", "1 when the source answered on the last poll",
                          ["source"], multiprocess_mode="livemostrecent")
    _BUILD = Gauge("atlas_build_info", "Version of the running Atlas", ["version"],
                   multiprocess_mode="livemax")
    _DRIFT = Gauge("atlas_dataset_drift",
                   "1 when the live dataset differs from the copy baked into this image (git HEAD at build)",
                   multiprocess_mode="livemostrecent")
    _DATASET_AGE = Gauge("atlas_dataset_age_seconds", "Seconds since the live dataset was last written",
                         multiprocess_mode="livemostrecent")
    import settings
    _BUILD.labels(version=settings.APP_VERSION).set(1)
    _enabled = True
    return True


_drift_cache = {"at": 0.0, "value": None}


def _observe_dataset():
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
    except Exception as e:
        log.warning("metrics: dataset drift check failed: %s", e)
    return Response(generate_latest(_registry), mimetype=CONTENT_TYPE_LATEST,
                    headers={"Cache-Control": "no-store"})


def init_app(app):
    try:
        ok = _setup()
    except Exception as e:
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
