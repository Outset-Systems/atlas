"""The Atlas's own watchfire — `/metrics` (v1.38.0): absent right, gated
right, counted right, and never a leak.

* ABSENT RIGHT — no `ATLAS_METRICS_TOKEN` → 404 (the house rule: an absent
  feature answers as absent), even to a caller holding some other bearer.
* GATED RIGHT — a token configured: no/wrong bearer → 401, the right one →
  the Prometheus text format. The path is exempt from the SESSION gate (a
  scraper has no session) and gates itself.
* COUNTED RIGHT — requests are counted by the Flask RULE (never the raw
  path, which would carry node ids into a metrics store), the chart layer
  records its fetches by source and outcome, and build_info carries the
  version.
* BUDGETED RIGHT — a chart whose queries outrun `_BUDGET_S` answers 504 and
  is counted as `budget`, not as a crash.
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    monkeypatch.delenv("ATLAS_METRICS_TOKEN", raising=False)
    monkeypatch.delenv("ATLAS_METRICS_TOKEN_FILE", raising=False)
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    monkeypatch.setenv("ATLAS_PROM_URL", "http://prom.test:9090")
    h = fresh_app(ATLAS_DATA=str(data), ATLAS_POSITIONS=str(tmp_path / "positions.json"),
                  ATLAS_RACK=str(tmp_path / "rack.json"))
    assert h.app.config["METRICS_ENABLED"] is True
    return h.app.test_client()


def test_absent_right(client, monkeypatch):
    r = client.get("/metrics")
    assert r.status_code == 404
    r = client.get("/metrics", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 404


def test_gated_right(client, monkeypatch, tmp_path):
    tok = tmp_path / "metrics.token"
    tok.write_text("scrape-me-7f3\n", encoding="utf-8")
    monkeypatch.setenv("ATLAS_METRICS_TOKEN_FILE", str(tok))
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/metrics", headers={"Authorization": "Bearer scrape-me-7f3"})
    assert r.status_code == 200
    assert r.mimetype.startswith("text/plain")
    assert "atlas_build_info" in r.get_data(as_text=True)
    assert r.headers["Cache-Control"] == "no-store"


def test_counted_right(client, monkeypatch):
    from api.v2 import charts as ch
    monkeypatch.setenv("ATLAS_METRICS_TOKEN", "t0k")
    monkeypatch.setattr(ch, "_range_query",
                        lambda *a, **k: [{"metric": {"origin": "CAPI"}, "values": [[1700000000, "5"]]}])
    ch._cache.clear()
    assert client.get("/api/v2/charts/edge.bans").status_code == 200
    assert client.get("/api/v2/health").status_code == 200
    assert client.get("/api/v2/vitals/no-such-node-xyz").status_code == 404
    body = client.get("/metrics", headers={"Authorization": "Bearer t0k"}).get_data(as_text=True)
    # by RULE, never by path — the node id must not appear
    assert 'route="/api/v2/vitals/<node_id>"' in body
    assert "no-such-node-xyz" not in body
    assert 'atlas_http_requests_total{method="GET",route="/api/v2/health",status="200"}' in body
    assert 'atlas_chart_fetches_total{outcome="ok",source="prom"}' in body
    assert "atlas_chart_fetch_seconds_bucket" in body
    import settings
    assert f'atlas_build_info{{version="{settings.APP_VERSION}"}} 1.0' in body
    # the scrape itself is not counted (it would count itself forever)
    assert 'route="/metrics"' not in body


def test_dataset_drift_is_measured(client, monkeypatch, tmp_path):
    """DATA.md's contract as a number: 0 while the live dataset equals the
    baked default (git HEAD), 1 the moment the Desk changes it, and the
    dataset's age beside it. Cached a minute — the second scrape must not
    re-hash — so the test clears the cache between edits."""
    import metrics
    import settings
    monkeypatch.setenv("ATLAS_METRICS_TOKEN", "t0k")
    hdr = {"Authorization": "Bearer t0k"}
    # the fixture copied the bundled default to the live path: no drift
    metrics._drift_cache["at"] = 0.0
    body = client.get("/metrics", headers=hdr).get_data(as_text=True)
    assert "atlas_dataset_drift 0.0" in body
    assert "atlas_dataset_age_seconds" in body
    # a Desk edit
    with open(settings.DATA_PATH, "a", encoding="utf-8") as fh:
        fh.write("\n")
    metrics._drift_cache["at"] = 0.0
    body = client.get("/metrics", headers=hdr).get_data(as_text=True)
    assert "atlas_dataset_drift 1.0" in body
    # a missing live file is drift too (the fallback map is not the map)
    monkeypatch.setattr(settings, "DATA_PATH", str(tmp_path / "nowhere.json"))
    metrics._drift_cache["at"] = 0.0
    body = client.get("/metrics", headers=hdr).get_data(as_text=True)
    assert "atlas_dataset_drift 1.0" in body and "atlas_dataset_age_seconds -1.0" in body


def test_budgeted_right(client, monkeypatch):
    from api.v2 import charts as ch
    monkeypatch.setenv("ATLAS_METRICS_TOKEN", "t0k")
    monkeypatch.setenv("ATLAS_LOKI_URL", "http://loki.test:3100")
    monkeypatch.setattr(ch, "_BUDGET_S", 0.0)     # the ceiling is already gone
    monkeypatch.setattr(ch, "_range_query", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be asked")))
    ch._cache.clear()
    r = client.get("/api/v2/charts/edge.status")
    assert r.status_code == 504 and "too long" in r.get_json()["error"]
    body = client.get("/metrics", headers={"Authorization": "Bearer t0k"}).get_data(as_text=True)
    assert 'atlas_chart_fetches_total{outcome="budget",source="loki"}' in body
    # the ceiling does not leak into the next request on this thread
    assert getattr(ch._deadline, "at", None) is None
    assert ch._timeout(8) == (ch._CONNECT_S, 8)


def test_drift_is_not_measured_on_the_db_backend(client, monkeypatch):
    """On the db backend `DATA_PATH` is not the dataset, so hashing it read as
    drift forever. No reading beats a false one: the gauge is left alone."""
    import metrics
    import settings
    touched = []
    monkeypatch.setattr(settings, "DATA_BACKEND", "db")
    monkeypatch.setattr(metrics, "_DRIFT", type("G", (), {"set": lambda self, v: touched.append(v)})())
    metrics._drift_cache["at"] = 0.0
    metrics._observe_dataset()
    assert touched == []
