"""THE DEMO'S FIGURES: invented charts and card vitals, for the hosted demo only.

The promise is in the refusals. Without ATLAS_DEMO_FIGURES=1 nothing changes; with
it, an Atlas holding a dataset of its own still shows nothing invented; and while
it is on, Prometheus is never asked, even when one is configured.
"""
import json
import os
import re
import time

import pytest

from appfixture import fresh_app

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "..", "..", "demo-lab", "seed")
FIGURES = os.path.join(SEED, "figures.demo.json")
DEMO_LAB = os.path.join(SEED, "lab-data.demo.json")

pytestmark = pytest.mark.skipif(not os.path.isfile(FIGURES),
                                reason="the demo seed is not in the image (Dockerfile copies Web/ only)")


@pytest.fixture(autouse=True)
def _these_settings_stay_here(monkeypatch):
    import demofigures
    monkeypatch.setattr(demofigures, "PATH", FIGURES)
    yield
    for key in ("ATLAS_DEMO_FIGURES", "ATLAS_PROM_URL", "ATLAS_FALLBACK"):
        os.environ.pop(key, None)


def _demo(tmp_path, monkeypatch, **env):
    """A look-only Atlas showing the bundled demo lab, as hosted/compose.demo.yaml runs one."""
    handle = fresh_app(ATLAS_AUTH_MODE="standalone", ATLAS_READONLY="1", ATLAS_DATA_BACKEND="file",
                       ATLAS_FALLBACK="bundled", ATLAS_DATA=str(tmp_path / "none" / "lab-data.json"),
                       ATLAS_SIGNALS_SOURCES="", ATLAS_INTEGRATIONS=str(tmp_path / "i.json"), **env)
    ctx = handle.app.extensions["atlas"]
    for part in (ctx.reader, ctx.store):          # the image's bundled dataset is the demo lab
        monkeypatch.setattr(part, "default_path", DEMO_LAB, raising=False)
    return handle.app.test_client()


@pytest.fixture
def no_prometheus(monkeypatch):
    import requests
    asked = []

    def refuse(url, **kw):
        asked.append(url)
        raise AssertionError(f"asked {url}")
    monkeypatch.setattr(requests, "get", refuse)
    return asked


def test_without_the_flag_nothing_is_invented(tmp_path, monkeypatch, no_prometheus):
    c = _demo(tmp_path, monkeypatch)
    assert not [e for e in c.get("/api/v2/charts").get_json()["charts"] if e["available"]]
    assert c.get("/api/v2/charts/containers.cpu").status_code == 404
    assert c.get("/api/v2/vitals/hypervisor").status_code == 404


def test_the_sky_and_the_depths_draw_from_the_seed(tmp_path, monkeypatch, no_prometheus):
    c = _demo(tmp_path, monkeypatch, ATLAS_DEMO_FIGURES="1", ATLAS_PROM_URL="http://prometheus.example:9090")
    index = {e["key"]: e for e in c.get("/api/v2/charts").get_json()["charts"]}
    lab = json.load(open(DEMO_LAB, encoding="utf-8"))
    watched = {w["chart"] for part in ("chronicle", "abyss") for w in lab[part] if w.get("chart")}
    assert watched and all(index[k]["available"] for k in watched), "every watching in the demo draws"
    now = time.time()
    j = c.get("/api/v2/charts/containers.cpu").get_json()
    assert j["demo"] and j["window"] == "21d" and len(j["series"]) == 8
    pts = j["series"][0]["points"]
    assert now - 3 * 3600 <= pts[-1][0] <= now, "the newest point is now, whatever day it is"
    assert pts[-1][0] - pts[0][0] >= 20 * 86400
    assert all(p[1] >= 0 for s in j["series"] for p in s["points"])
    table = c.get("/api/v2/charts/edge.top_clients").get_json()
    assert len(table["rows"]) == 10
    assert no_prometheus == []


def test_a_finer_window_counts_less_per_step(tmp_path, monkeypatch, no_prometheus):
    c = _demo(tmp_path, monkeypatch, ATLAS_DEMO_FIGURES="1")
    wide = c.get("/api/v2/charts/edge.status?range=21d").get_json()["series"][0]["points"]
    near = c.get("/api/v2/charts/edge.status?range=24h").get_json()["series"][0]["points"]
    assert len(near) > 80 and max(v for _, v in near) < max(v for _, v in wide)


def test_the_cards_draw_a_pulse(tmp_path, monkeypatch, no_prometheus):
    c = _demo(tmp_path, monkeypatch, ATLAS_DEMO_FIGURES="1", ATLAS_PROM_URL="http://prometheus.example:9090")
    lab = json.load(open(DEMO_LAB, encoding="utf-8"))
    for node in (n for n in lab["nodes"] if n.get("spark")):
        j = c.get(f"/api/v2/vitals/{node['id']}").get_json()
        assert len(j["cpu"]) == len(j["ram"]) == 169, node["id"]
        assert 0 <= j["now"]["cpu"] <= 100 and 0 < j["now"]["ram"] <= 100
    assert c.get("/api/v2/vitals/core-switch").status_code == 404
    assert c.get("/api/v2/vitals/nobody").get_json() == {"error": "no such place"}
    assert no_prometheus == []


def test_a_map_of_its_own_turns_the_figures_off(tmp_path, monkeypatch, no_prometheus):
    (tmp_path / "none").mkdir()
    (tmp_path / "none" / "lab-data.json").write_text(open(DEMO_LAB, encoding="utf-8").read(), encoding="utf-8")
    c = _demo(tmp_path, monkeypatch, ATLAS_DEMO_FIGURES="1")
    assert c.get("/api/v2/charts/containers.cpu").status_code == 404
    assert c.get("/api/v2/vitals/hypervisor").status_code == 404


def test_the_seed_lies_over_this_week():
    import demofigures
    first = demofigures._first(280, 3 * 3600, time.time())
    assert time.gmtime(first).tm_wday == 0 and time.gmtime(first).tm_hour == 0
    assert first + 280 * 3 * 3600 > time.time()


def test_every_figure_is_invented():
    text = open(FIGURES, encoding="utf-8").read()
    for ip in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
        assert ip.startswith(("203.0.113.", "198.51.100.", "192.0.2.")), ip
    lab = json.load(open(DEMO_LAB, encoding="utf-8"))
    figures = json.loads(text)
    assert set(figures["vitals"]) <= {n["id"] for n in lab["nodes"]}
    names = {n["name"] for n in lab["nodes"]}
    assert {s["name"] for s in figures["charts"]["hosts.net"]["series"]} <= names
