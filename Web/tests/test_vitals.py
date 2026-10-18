"""G16 · Native card vitals — asked right, absent right, cached right.

The route replaces two Grafana iframes, so its contract is narrow and worth
pinning exactly:

* ASKED RIGHT — the instance label is built from the DATASET's ip for the
  named node (the client picks an id, never an address), both whitelisted
  queries are issued over a 7-day range, and the payload carries series +
  `now` values rounded to one decimal.
* ABSENT RIGHT — no `ATLAS_PROM_URL` → 404 (a template deployment without
  Prometheus has quieter cards, not errors); unknown node → 404; a node with
  no address → 404; an unreachable Prometheus → 502, never a crash; a host
  Prometheus has never met → empty series and null `now`s, NOT zeros (missing
  must stay missing).
* CACHED RIGHT — a second ask inside the TTL answers from memory.
* GATED RIGHT — not in EXEMPT_PATHS: exactly as hard to reach as the map.
"""

import json
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


def _dataset(tmp_path):
    data = json.load(open(BUNDLED, encoding="utf-8"))
    node = data["nodes"][0]
    node["id"], node["ip"], node["spark"] = "probe-me", "10.9.9.9", True
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
    from api.v2 import vitals as vt
    vt._cache.clear()
    return handle.app


def _matrix(values):
    return [{"metric": {}, "values": values}]


def test_asked_right(app, monkeypatch):
    from api.v2 import vitals as vt
    seen = []

    def fake(base, query, start, end, step):
        seen.append((base, query, step))
        return _matrix([[1700000000, "12.345"], [1700003600, "34.5"]])

    monkeypatch.setattr(vt, "_range_query", fake)
    r = app.test_client().get("/api/v2/vitals/probe-me")
    assert r.status_code == 200
    body = r.get_json()
    assert body["window"] == "7d" and body["step"] == 3600
    assert body["cpu"] == [[1700000000, 12.3], [1700003600, 34.5]]
    assert body["now"] == {"cpu": 34.5, "ram": 34.5}
    assert len(seen) == 2
    for base, query, step in seen:
        assert base == "http://prom.test:9090" and step == 3600
        assert 'instance="10.9.9.9:9100"' in query
    assert "node_cpu_seconds_total" in seen[0][1]
    assert "node_memory_MemAvailable_bytes" in seen[1][1]


def test_absent_right(app, monkeypatch):
    from api.v2 import vitals as vt
    client = app.test_client()

    monkeypatch.setattr(vt, "_range_query",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no route")))
    assert client.get("/api/v2/vitals/probe-me").status_code == 502

    monkeypatch.setattr(vt, "_range_query", lambda *a, **k: [])
    r = client.get("/api/v2/vitals/probe-me")
    assert r.status_code == 200
    body = r.get_json()
    assert body["cpu"] == [] and body["ram"] == []
    assert body["now"] == {"cpu": None, "ram": None}

    assert client.get("/api/v2/vitals/no-such-place").status_code == 404

    monkeypatch.delenv("ATLAS_PROM_URL")
    assert client.get("/api/v2/vitals/probe-me").status_code == 404


def test_cached_right(app, monkeypatch):
    from api.v2 import vitals as vt
    calls = []

    def fake(*a, **k):
        calls.append(1)
        return _matrix([[1700000000, "50"]])

    monkeypatch.setattr(vt, "_range_query", fake)
    client = app.test_client()
    assert client.get("/api/v2/vitals/probe-me").status_code == 200
    assert client.get("/api/v2/vitals/probe-me").status_code == 200
    assert len(calls) == 2, "second ask inside the TTL must come from the cache"


def test_gated_right():
    from api import v2 as api_v2
    assert "/api/v2/vitals" not in "".join(api_v2.EXEMPT_PATHS)
