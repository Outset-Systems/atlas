"""G17 · Native watchings — `GET /api/v2/charts` + `/charts/<key>` (v1.35.0).

WHY. The Chronicle and the Abyss were twenty Grafana `/d-solo/` iframes, each
booting the whole Grafana SPA to draw one panel, each needing the §20c embed
token, and all of them dark the moment Grafana was cold or restarting. The
card vitals (G16) proved the alternative: the Atlas asks Prometheus itself and
paints its own ink. This module is that idea for the carousels — a CATALOGUE
of named panels, each a fixed PromQL or LogQL shape, answered as a few
kilobytes of JSON that `static/js/charts.js` draws with Chart.js. Grafana
itself was decommissioned on 2026-09-03 (v1.36.0): the `grafana` tag on each
entry now only records which panel a key grew out of, and it still matches
any dataset that has not yet been told `chart: <key>` outright.

SHAPE.
  GET /api/v2/charts
      {"charts": [{key, title, kind, unit, source, window, grafana:{uid,panel},
                   max_window, available}…]}
      The index the front-end matches watchings against: a watching whose
      `embed` URL names a Grafana (uid, panelId) this catalogue knows — or
      whose `chart` field names a key outright — is drawn natively.
  GET /api/v2/charts/<key>?range=7d
      {key, kind, unit, title, window, step, start, end,
       series: [{name, points: [[ts, value|null]…]}…]}         (series/bars/stat)
      {key, kind, unit, title, window, step, start, end,
       rows: [{name, labels:{…}, value}…]}                     (table)
      and `demo: true` when the answer is the demo's invented figures.

RULES, the same as every outbound asker in this app:
* Never a free-form proxy. Exactly the queries written in CATALOGUE are ever
  issued; the client chooses a key and a window from an allow-list, nothing
  else. Query text never leaves the server.
* Two sources, each only when configured: `ATLAS_PROM_URL` (Prometheus, the
  trust the signals layer already holds) and `ATLAS_LOKI_URL` (Loki, new here,
  for the edge's log-derived panels). A chart whose source is unset is listed
  `available: false` and answers 404 — an absent feature answers as absent,
  and the front-end keeps the Grafana iframe for that one watching.
* Behind the app-wide gate (deliberately NOT in `EXEMPT_PATHS`).
* Short cache per (key, window): paging back to a slide inside a minute must
  not ask Loki for a week of Traefik lines twice.
* A series is named by the dataset when it can be: an `instance` label of
  `10.0.20.5:9100` is shown as the place the map calls it, so the legend
  reads like the Atlas rather than like a scrape config.
"""

import logging
import math
import re
import threading
import time

from flask import jsonify, request

from chart_catalogue import CATALOGUE, WINDOWS, _LOKI_MAX_WINDOW
from context import atlas
from redaction import hidden_words, sees_everything, viewer_groups

from . import bp
from .vitals import _prom_url

log = logging.getLogger("atlas.api.v2")

_CACHE_TTL_S = 60
_PROM_TIMEOUT = 8
_LOKI_TIMEOUT = 25

_LEGEND_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_INSTANCE_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?$")

_cache_lock = threading.Lock()
_cache: dict = {}   # (key, window) -> (expires_at, payload)


# ── configuration ───────────────────────────────────────────────────────────
# `_prom_url` is the card vitals' own, imported above: one reading of the setting.
def _loki_url() -> str:
    import integrations
    return integrations.get("ATLAS_LOKI_URL").rstrip("/")


def _base_for(source: str) -> str:
    return _prom_url() if source == "prom" else _loki_url()


def _index_entry(key, spec, demo=None):
    """One catalogue line. `demo` is the demo's chart keys while its invented
    figures are on (demofigures.py): then they, not a source, say what is drawn."""
    uid, panel = spec["grafana"]
    return {
        "key": key, "title": spec["title"], "kind": spec["kind"],
        "unit": spec["unit"], "source": spec["source"], "window": spec["window"],
        "grafana": {"uid": uid, "panel": panel},
        "max_window": _cap_for(spec),
        "available": key in demo if demo is not None else bool(_base_for(spec["source"])),
    }


# ── the budget (v1.38.0) ──────────────────────────────────────────────────────
#: Wall-clock ceiling for ONE chart answer, all of its queries together. A
#: source's own timeout is trimmed to what is left of this, and connecting
#: gets 3 s of it — a scribe that will not even pick up should fail fast.
_BUDGET_S = 25
_CONNECT_S = 3
_deadline = threading.local()


class BudgetExhausted(Exception):
    pass


def _check_budget(deadline, key):
    _deadline.at = deadline
    if time.monotonic() >= deadline - 1:
        raise BudgetExhausted(f"{key}: out of time after {_BUDGET_S}s across its queries")


def _timeout(default):
    """(connect, read) for one request: the source's read timeout, trimmed to
    the budget's remainder. Outside a chart answer (the tests, a probe) the
    default stands."""
    at = getattr(_deadline, "at", None)
    if at is None:
        return (_CONNECT_S, default)
    return (_CONNECT_S, max(1, min(default, at - time.monotonic())))


# ── the two askers — module-level so the tests can inject fakes ────────────
def _range_query(source, base, query, start, end, step):
    """One range query against Prometheus or Loki. Both answer the same
    `{data: {resultType: "matrix", result: [{metric, values}]}}` shape."""
    import requests
    if source == "prom":
        url, timeout = base + "/api/v1/query_range", _PROM_TIMEOUT
    else:
        url, timeout = base + "/loki/api/v1/query_range", _LOKI_TIMEOUT
    r = requests.get(url, params={"query": query, "start": start, "end": end,
                                  "step": step}, timeout=_timeout(timeout))
    r.raise_for_status()
    return r.json().get("data", {}).get("result", [])


def _instant_query(source, base, query, at):
    """One instant query (a `vector` answer) — the table kind's `$__range`
    aggregations are a single number per label set, not a series."""
    import requests
    if source == "prom":
        url, timeout = base + "/api/v1/query", _PROM_TIMEOUT
    else:
        url, timeout = base + "/loki/api/v1/query", _LOKI_TIMEOUT
    r = requests.get(url, params={"query": query, "time": at}, timeout=_timeout(timeout))
    r.raise_for_status()
    return r.json().get("data", {}).get("result", [])


# ── shaping ─────────────────────────────────────────────────────────────────
def _substitute(query, window_s, step_s):
    ri = max(300, step_s)
    return (query.replace("$__range", f"{window_s}s")
                 .replace("$__step", f"{step_s}s")
                 .replace("$__ri", f"{ri}s"))


def _float(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(x) or math.isinf(x)) else x


def _name_for(legend, labels, ip_names):
    """Grafana's `{{label}}` legend, with `instance` translated to the place
    the dataset calls it when the address is one the map knows."""
    def label(m):
        v = labels.get(m.group(1), "")
        if m.group(1) == "instance":
            im = _INSTANCE_RE.match(v)
            if im and im.group(1) in ip_names:
                return ip_names[im.group(1)]
        return v
    if legend:
        return _LEGEND_RE.sub(label, legend).strip() or legend
    return ", ".join(f"{k}={v}" for k, v in sorted(labels.items())) or "value"


def _series_from(result, legend, ip_names):
    out = []
    for item in result:
        pts = []
        for ts, val in item.get("values", []):
            try:
                pts.append([int(float(ts)), _float(val)])
            except (TypeError, ValueError):
                continue
        out.append({"name": _name_for(legend, item.get("metric", {}), ip_names),
                    "points": pts})
    return out


def _trim(series, limit):
    """Keep the `limit` series with the most AREA under them over the window;
    drop those that are nothing but nulls or zeros. Area, not mean: a build
    container that lived one hot hour has a towering mean and no story, and
    would elbow out a service that ran all week. Server-side rather than a
    PromQL `topk`, which picks per-timestamp and leaves broken lines behind."""
    def area(s):
        vals = [p[1] for p in s["points"] if p[1] is not None]
        return sum(vals) if vals else None
    kept = [(area(s), s) for s in series]
    kept = [(m, s) for m, s in kept if m is not None and m != 0]
    kept.sort(key=lambda ms: ms[0], reverse=True)
    return [s for _, s in kept[:limit]]


def _ip_names():
    """ip → node name, from the dataset; empty when the map is unreadable
    (a chart still draws, its legend just reads like a scrape config)."""
    try:
        data, _, _ = atlas().dataset()
    except Exception:  # noqa: BLE001 — never fail a chart over the legend
        return {}
    out = {}
    for n in data.get("nodes", []):
        ip = str(n.get("ip") or "").split("/")[0].strip()
        if ip and n.get("name"):
            out[ip] = n["name"]
    return out


def _for_viewer(payload):
    """The answer without the series and rows that name a hidden place. Filled
    after the cache: an answer is cached once, for everyone, so its legend holds
    every name and each viewer takes away what they may not read."""
    groups = viewer_groups()
    if sees_everything(groups):
        return payload
    try:
        data, _, _ = atlas().dataset()
    except Exception:  # noqa: BLE001 — without the map no legend can be vouched for
        return {**payload, "series": [], "rows": []}
    words = hidden_words(data, groups)
    if words is None:
        return payload
    clean = lambda row: not words.search(  # noqa: E731
        " ".join([str(row.get("name") or ""), *map(str, (row.get("labels") or {}).values())]))
    out = dict(payload)
    for part in ("series", "rows"):
        if part in out:
            out[part] = [row for row in out[part] if clean(row)]
    return out


def _window_arg(spec):
    raw = (request.args.get("range") or "").strip().lower()
    if raw.startswith("now-"):
        raw = raw[4:]
    if not raw:
        return spec["window"], None
    if raw not in WINDOWS:
        return None, f"unknown range {raw!r} — one of {', '.join(WINDOWS)}"
    # a chart that cannot answer a wide window (a source-side series ceiling,
    # or Loki's query-length limit) is clamped to the widest it can, and the
    # payload says which it drew
    cap = _cap_for(spec)
    if cap and WINDOWS[raw][0] > WINDOWS[cap][0]:
        return cap, None
    return raw, None


def _cap_for(spec):
    """The widest window this chart may be asked for: its own `max_window`,
    else Loki's ceiling for a Loki-backed chart, else none."""
    own = spec.get("max_window")
    if spec["source"] == "loki":
        if not own or WINDOWS[own][0] > WINDOWS[_LOKI_MAX_WINDOW][0]:
            return _LOKI_MAX_WINDOW
    return own


# ── routes ──────────────────────────────────────────────────────────────────
@bp.route("/charts")
def charts_index():
    import demofigures
    demo = demofigures.chart_keys() if demofigures.enabled() else None
    return jsonify({"charts": [_index_entry(k, s, demo) for k, s in CATALOGUE.items()]})


def _head(key, spec, window, step_s, start, end):
    """The part of an answer every kind shares."""
    return {"key": key, "kind": spec["kind"], "unit": spec["unit"],
            "title": spec["title"], "window": window, "step": step_s,
            "start": start, "end": end}


def _table_rows(key, spec, base, deadline, window_s, step_s, end, ip_names):
    """A table's rows: one instant query each, largest first, cut to the limit."""
    rows = []
    for query, legend in spec["queries"]:
        q = _substitute(query, window_s, step_s)
        _check_budget(deadline, key)
        for item in _instant_query(spec["source"], base, q, end):
            val = _float((item.get("value") or [None, None])[1])
            if val is None:
                continue
            labels = item.get("metric", {})
            rows.append({"name": _name_for(legend, labels, ip_names),
                         "labels": labels, "value": val})
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows[:spec.get("limit", 10)]


def _series_for(key, spec, base, deadline, window_s, step_s, start, end, ip_names):
    """Every other kind's series: one range query each, trimmed to the limit."""
    series = []
    for query, legend in spec["queries"]:
        q = _substitute(query, window_s, step_s)
        _check_budget(deadline, key)
        series.extend(_series_from(
            _range_query(spec["source"], base, q, start, end, step_s),
            legend, ip_names))
    if "limit" in spec:
        series = _trim(series, spec["limit"])
    return series


def _demo_chart(key, spec):
    """A watching answered from the demo's invented figures. Never a source."""
    import demofigures
    window, err = _window_arg(spec)
    if err:
        return jsonify({"error": err}), 400
    window_s, step_s = WINDOWS[window]
    end = int(time.time())
    part = demofigures.chart(key, end - window_s, end, step_s)
    if part is None:
        return jsonify({"error": "the demo has no figures for this watching"}), 404
    if spec["kind"] == "table" and "rows" in part:
        part["rows"] = part["rows"][:spec.get("limit", 10)]
    return jsonify(_for_viewer({**_head(key, spec, window, step_s, end - window_s, end),
                                "demo": True, **part}))


@bp.route("/charts/<key>")
def chart(key):
    spec = CATALOGUE.get(key)
    if spec is None:
        return jsonify({"error": "no such watching"}), 404
    import demofigures
    if demofigures.enabled():
        return _demo_chart(key, spec)
    base = _base_for(spec["source"])
    if not base:
        var = "ATLAS_PROM_URL" if spec["source"] == "prom" else "ATLAS_LOKI_URL"
        return jsonify({"error": f"this watching is not configured ({var} unset)"}), 404

    window, err = _window_arg(spec)
    if err:
        return jsonify({"error": err}), 400
    window_s, step_s = WINDOWS[window]

    now = time.time()
    with _cache_lock:
        hit = _cache.get((key, window))
        if hit and hit[0] > now:
            return jsonify(_for_viewer(hit[1]))

    end = int(now)
    start = end - window_s
    ip_names = _ip_names()
    payload = _head(key, spec, window, step_s, start, end)
    # One BUDGET per answer (v1.38.0): a chart with three Loki queries must not
    # hold a gunicorn thread for three full timeouts. Each query gets what is
    # left of the budget, and the answer is a 504 the moment it runs out —
    # the front-end's "the scribe is not answering", with the reason logged.
    deadline = time.monotonic() + _BUDGET_S
    t0 = time.monotonic()
    outcome = "ok"
    try:
        if spec["kind"] == "table":
            payload["rows"] = _table_rows(key, spec, base, deadline, window_s, step_s,
                                          end, ip_names)
        else:
            payload["series"] = _series_for(key, spec, base, deadline, window_s, step_s,
                                            start, end, ip_names)
    except BudgetExhausted as e:
        outcome = "budget"
        log.warning("charts: %s", e)
        return jsonify({"error": "the scribe is taking too long"}), 504
    except Exception as e:  # noqa: BLE001 — an unreachable scribe is a 502, not a crash
        outcome = "error"
        log.warning("charts: %s not answering for %s: %s", spec["source"], key, e)
        return jsonify({"error": "the scribe is not answering"}), 502
    finally:
        _deadline.at = None   # the thread serves other requests next; no stale ceiling
        try:
            import metrics
            metrics.record_chart(spec["source"], outcome, time.monotonic() - t0)
        except Exception:  # noqa: BLE001 — never fail a chart over its own bookkeeping
            pass

    with _cache_lock:
        _cache[(key, window)] = (now + _CACHE_TTL_S, payload)
    return jsonify(_for_viewer(payload))
