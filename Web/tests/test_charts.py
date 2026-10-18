"""G17 · Native watchings — the catalogue, asked right, absent right, cached right.

`/api/v2/charts` replaces the Chronicle's and the Abyss's Grafana iframes, so
its contract is pinned the way G16's was:

* LISTED RIGHT — the index names every catalogue key with the Grafana panel
  it replaces, and `available` follows the SOURCE's configuration: with only
  `ATLAS_PROM_URL` set the Loki-backed panels are listed but unavailable.
* ASKED RIGHT — exactly the catalogue's queries are issued, Grafana's
  `$__ri`/`$__step`/`$__range` tokens substituted for the window's own
  bucket (a 7-day window steps by the hour); legends template from labels;
  an `instance` of `ip:port` is named by the DATASET's node for that ip;
  a table kind asks an instant query and answers sorted rows; a limited
  chart keeps the strongest series and drops the silent ones.
* ABSENT RIGHT — unknown key → 404; a chart whose source is unset → 404
  (absent features answer as absent); a window off the allow-list → 400,
  never rounded; an unreachable scribe → 502, never a crash; NaN → null.
* CACHED RIGHT — a second ask inside the TTL answers from memory.
* GATED RIGHT — not in EXEMPT_PATHS: exactly as hard to reach as the map.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}


def _dataset(tmp_path):
    data = json.load(open(BUNDLED, encoding="utf-8"))
    node = data["nodes"][0]
    node["id"], node["name"], node["ip"] = "probe-me", "THE PROBE", "10.9.9.9"
    p = tmp_path / "lab-data.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def app(tmp_path, monkeypatch):
    handle = fresh_app(
        ATLAS_AUTH_MODE="standalone",
        ATLAS_DATA_BACKEND="file",
        ATLAS_DATA=str(_dataset(tmp_path)),
    )
    monkeypatch.setenv("ATLAS_PROM_URL", "http://prom.test:9090")
    monkeypatch.delenv("ATLAS_LOKI_URL", raising=False)
    from api.v2 import charts as ch
    ch._cache.clear()
    return handle.app


def _matrix(*items):
    return [{"metric": m, "values": v} for m, v in items]


# ── the catalogue itself ────────────────────────────────────────────────────
def test_catalogue_is_well_formed():
    from api.v2 import charts as ch
    assert ch.CATALOGUE, "an empty catalogue draws nothing"
    for key, spec in ch.CATALOGUE.items():
        assert spec["kind"] in ("series", "bars", "stat", "table"), key
        assert spec["source"] in ("prom", "loki"), key
        assert spec["window"] in ch.WINDOWS, key
        uid, panel = spec["grafana"]
        assert uid and isinstance(panel, int), key
        assert spec["queries"], key
        for q, legend in spec["queries"]:
            # only Grafana's three tokens are ever substituted — a fourth
            # would reach Prometheus verbatim and fail there
            leftover = [t for t in ("$__rate_interval", "$__interval", "$__auto")
                        if t in q]
            assert not leftover, (key, leftover)
            if spec["kind"] == "table":
                assert "$__range" in q, f"{key}: a table aggregates the whole window"
            assert isinstance(legend, str), key


def test_listed_right(app, monkeypatch):
    client = app.test_client()
    r = client.get("/api/v2/charts")
    assert r.status_code == 200
    charts = {c["key"]: c for c in r.get_json()["charts"]}
    from api.v2 import charts as ch
    assert set(charts) == set(ch.CATALOGUE)
    entry = charts["edge.bans"]
    assert entry["grafana"] == {"uid": "lab-security", "panel": 6}
    assert entry["kind"] == "series" and entry["source"] == "prom"
    # prom set, loki unset → prom panels available, loki ones listed but not
    assert entry["available"] is True
    assert charts["edge.status"]["available"] is False
    assert "queries" not in entry and "expr" not in json.dumps(entry)

    monkeypatch.setenv("ATLAS_LOKI_URL", "http://loki.test:3100")
    charts = {c["key"]: c for c in client.get("/api/v2/charts").get_json()["charts"]}
    assert charts["edge.status"]["available"] is True


# ── asking ──────────────────────────────────────────────────────────────────
def test_asked_right_series(app, monkeypatch):
    from api.v2 import charts as ch
    seen = []

    def fake(source, base, query, start, end, step):
        seen.append((source, base, query, start, end, step))
        return _matrix(
            ({"instance": "10.9.9.9:9100"}, [[1700000000, "1000"], [1700003600, "NaN"], [1700007200, "3000.4"]]),
            ({"instance": "10.8.8.8:9100"}, [[1700000000, "5"], [1700003600, "6"]]),
        )

    monkeypatch.setattr(ch, "_range_query", fake)
    r = app.test_client().get("/api/v2/charts/hosts.net")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["kind"] == "series" and body["unit"] == "bps"
    assert body["window"] == "21d" and body["step"] == 3 * 3600, "three weeks by default (2026-09-03)"
    assert body["end"] - body["start"] == 21 * 24 * 3600
    assert len(seen) == 1
    source, base, query, start, end, step = seen[0]
    assert source == "prom" and base == "http://prom.test:9090" and step == 3 * 3600
    assert "$__" not in query
    assert "[10800s]" in query, "the rate interval is the window's own bucket"
    assert start == body["start"] and end == body["end"]
    names = [s["name"] for s in body["series"]]
    assert names == ["THE PROBE", "10.8.8.8:9100"], "an address the map knows is named by the map"
    assert body["series"][0]["points"] == [[1700000000, 1000.0], [1700003600, None], [1700007200, 3000.4]]


def test_window_arg(app, monkeypatch):
    from api.v2 import charts as ch
    seen = []
    monkeypatch.setattr(ch, "_range_query",
                        lambda source, base, query, start, end, step: seen.append((query, step, end - start)) or [])
    client = app.test_client()
    r = client.get("/api/v2/charts/edge.bans?range=now-24h")
    assert r.status_code == 200
    assert r.get_json()["window"] == "24h" and r.get_json()["step"] == 900
    assert seen[-1][1] == 900 and seen[-1][2] == 86400
    # Loki's `[$__step]` becomes one bucket, so counts tile the window
    monkeypatch.setenv("ATLAS_LOKI_URL", "http://loki.test:3100")
    r = client.get("/api/v2/charts/edge.status?range=6h")
    assert r.status_code == 200
    assert all("[300s]" in q for q, _, _ in seen[-3:]), seen[-3:]
    assert client.get("/api/v2/charts/edge.bans?range=2h").status_code == 400
    assert client.get("/api/v2/charts/edge.bans?range=forever").status_code == 400
    # "all time" is a year at day steps for Prometheus …
    r = client.get("/api/v2/charts/edge.bans?range=1y")
    assert r.status_code == 200 and r.get_json()["window"] == "1y" and r.get_json()["step"] == 86400
    # … and Loki's month, because Loki refuses a longer query outright
    r = client.get("/api/v2/charts/edge.status?range=1y")
    assert r.status_code == 200 and r.get_json()["window"] == "30d"
    charts = {c["key"]: c for c in client.get("/api/v2/charts").get_json()["charts"]}
    assert charts["edge.status"]["max_window"] == "30d" and charts["edge.bans"]["max_window"] is None


def test_window_is_clamped_where_the_source_cannot_answer(app, monkeypatch):
    """Loki caps one query at 500 series; a week of guessed paths is more
    than that (measured). The chart declares `max_window` and a wider ask is
    clamped to it — and says so — rather than answering 502 every time."""
    from api.v2 import charts as ch
    monkeypatch.setenv("ATLAS_LOKI_URL", "http://loki.test:3100")
    seen = []
    monkeypatch.setattr(ch, "_instant_query",
                        lambda source, base, query, at: seen.append(query) or [])
    client = app.test_client()
    assert ch.CATALOGUE["edge.top_probes"]["max_window"] == "24h"
    r = client.get("/api/v2/charts/edge.top_probes?range=now-7d")
    assert r.status_code == 200 and r.get_json()["window"] == "24h"
    assert "[86400s]" in seen[-1]
    r = client.get("/api/v2/charts/edge.top_probes?range=6h")
    assert r.get_json()["window"] == "6h", "a narrower ask is honoured"
    charts = {c["key"]: c for c in client.get("/api/v2/charts").get_json()["charts"]}
    assert charts["edge.top_probes"]["max_window"] == "24h"
    assert charts["edge.bans"]["max_window"] is None


def test_asked_right_table(app, monkeypatch):
    from api.v2 import charts as ch
    monkeypatch.setenv("ATLAS_LOKI_URL", "http://loki.test:3100")
    seen = []

    def fake_instant(source, base, query, at):
        seen.append((source, base, query, at))
        return [
            {"metric": {"ip": "203.0.113.7"}, "value": [at, "12"]},
            {"metric": {"ip": "198.51.100.2"}, "value": [at, "340"]},
            {"metric": {"ip": "192.0.2.1"}, "value": [at, "junk"]},
        ]

    monkeypatch.setattr(ch, "_instant_query", fake_instant)
    monkeypatch.setattr(ch, "_range_query",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("a table never asks for a range")))
    r = app.test_client().get("/api/v2/charts/edge.top_clients")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["kind"] == "table"
    assert [row["name"] for row in body["rows"]] == ["198.51.100.2", "203.0.113.7"]
    assert body["rows"][0] == {"name": "198.51.100.2", "labels": {"ip": "198.51.100.2"}, "value": 340.0}
    source, base, query, at = seen[0]
    assert source == "loki" and base == "http://loki.test:3100"
    assert "[1814400s]" in query and "$__" not in query   # the whole 21-day window
    assert at == body["end"]


def test_limit_keeps_the_strongest(app, monkeypatch):
    from api.v2 import charts as ch
    spec = ch.CATALOGUE["containers.cpu"]
    assert spec["limit"] == 12
    rows = [({"name": f"c{i}"}, [[1700000000, str(i)], [1700003600, str(i)]]) for i in range(20)]
    rows.append(({"name": "silent"}, [[1700000000, "0"], [1700003600, "0"]]))
    rows.append(({"name": "absent"}, [[1700000000, "NaN"]]))
    monkeypatch.setattr(ch, "_range_query", lambda *a, **k: _matrix(*rows))
    body = app.test_client().get("/api/v2/charts/containers.cpu").get_json()
    names = [s["name"] for s in body["series"]]
    assert len(names) == 12
    assert names[0] == "c19" and "c7" not in names, "kept by area, strongest first"
    # a one-hour wonder with a towering MEAN (25 > c19's 19) does not outrank
    # the week-long series it would have under a mean ranking
    rows.append(({"name": "flash"}, [[1700000000, "25"]]))
    body = app.test_client().get("/api/v2/charts/containers.cpu?range=24h").get_json()
    names = [s["name"] for s in body["series"]]
    assert names[0] == "c19" and names.index("flash") > names.index("c13")
    assert "silent" not in names and "absent" not in names, "a flat zero says nothing"


def test_legend_without_labels(app, monkeypatch):
    from api.v2 import charts as ch
    monkeypatch.setattr(ch, "_range_query",
                        lambda *a, **k: _matrix(({}, [[1700000000, "7"]])))
    body = app.test_client().get("/api/v2/charts/edge.active_bans").get_json()
    assert body["kind"] == "stat"
    assert body["series"] == [{"name": "bans", "points": [[1700000000, 7.0]]}]


# ── absence ─────────────────────────────────────────────────────────────────
def test_absent_right(app, monkeypatch):
    from api.v2 import charts as ch
    client = app.test_client()
    assert client.get("/api/v2/charts/no.such").status_code == 404
    # a Loki chart with no Loki configured
    r = client.get("/api/v2/charts/edge.status")
    assert r.status_code == 404 and "ATLAS_LOKI_URL" in r.get_json()["error"]

    monkeypatch.setattr(ch, "_range_query",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no route")))
    assert client.get("/api/v2/charts/edge.bans").status_code == 502

    monkeypatch.setattr(ch, "_range_query", lambda *a, **k: [])
    r = client.get("/api/v2/charts/edge.bans")
    assert r.status_code == 200 and r.get_json()["series"] == []

    monkeypatch.delenv("ATLAS_PROM_URL")
    assert client.get("/api/v2/charts/edge.bans").status_code == 404
    charts = {c["key"]: c for c in client.get("/api/v2/charts").get_json()["charts"]}
    assert not any(c["available"] for c in charts.values())


def test_cached_right(app, monkeypatch):
    from api.v2 import charts as ch
    calls = []

    def fake(*a, **k):
        calls.append(1)
        return _matrix(({"origin": "CAPI"}, [[1700000000, "50"]]))

    monkeypatch.setattr(ch, "_range_query", fake)
    client = app.test_client()
    assert client.get("/api/v2/charts/edge.bans").status_code == 200
    assert client.get("/api/v2/charts/edge.bans").status_code == 200
    assert len(calls) == 1, "second ask inside the TTL must come from the cache"
    # a different window is a different answer
    assert client.get("/api/v2/charts/edge.bans?range=24h").status_code == 200
    assert len(calls) == 2


def test_gated_right():
    from api import v2 as api_v2
    assert "/api/v2/charts" not in "".join(api_v2.EXEMPT_PATHS)
