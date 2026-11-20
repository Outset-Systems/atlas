"""The demo's two invented reports (2026-11-20), and that they are the demo's alone.

Owner: "we also need to adjust the security report link and uptime board link
in the public demo". Both pointed at addresses that exist only in the demo
lab's story, so a press opened a tab that could not load. The demo answers
them itself now, behind the same switch as its invented charts.
"""
import json
import os
from datetime import datetime, timezone

import pytest

from appfixture import fresh_app

NOW = datetime(2026, 11, 20, 6, 30, tzinfo=timezone.utc)   # a Friday


@pytest.fixture(autouse=True)
def _these_settings_stay_here():
    yield
    for key in ("ATLAS_DEMO_FIGURES", "ATLAS_FALLBACK"):
        os.environ.pop(key, None)


def _look_only(tmp_path):
    (tmp_path / "lab-data.json").write_text(json.dumps({
        "meta": {"title": "T"}, "zones": [{"id": "z", "name": "Z"}],
        "nodes": [{"id": "box", "name": "BOX", "kind": "physical", "zone": "z", "x": 1, "y": 1},
                  {"id": "quiet", "name": "QUIET", "kind": "physical", "zone": "z", "x": 2, "y": 2}],
        "routes": [], "rack": [], "vms": []}), encoding="utf-8")
    return fresh_app(ATLAS_AUTH_MODE="standalone", ATLAS_READONLY="1", ATLAS_DATA_BACKEND="file",
                     ATLAS_DATA=str(tmp_path / "lab-data.json"), ATLAS_SIGNALS_SOURCES="",
                     ATLAS_MAPS=str(tmp_path)).app


def test_the_write_up_says_it_is_invented_and_is_dated_to_last_week():
    import demoreports
    text = demoreports.security(NOW)
    assert text.startswith("# WEEKLY SECURITY REPORT")
    assert "_An invented report for the demo lab. Nothing here describes a real network._" in text
    # 2026-11-20 is a Friday: the week that began on Monday the 16th reports the week before it
    assert "week of 2026-11-09 to 2026-11-15" in text
    assert "written 2026-11-16 06:00 UTC" in text
    # the same day a week on reads a week on: the demo never goes stale
    later = demoreports.security(datetime(2026, 11, 27, 6, 30, tzinfo=timezone.utc))
    assert "week of 2026-11-16 to 2026-11-22" in later


def test_the_board_is_read_from_the_feed_the_map_wears():
    import demoreports
    data = {"nodes": [{"id": "a", "name": "ALPHA"}, {"id": "b", "name": "BETA"},
                      {"id": "c", "name": "GAMMA"}, {"id": "d"}, "junk", {"name": "no id"}]}
    feed = {"nodes": {"a": {"state": "healthy", "uptime_30d": 99.9},
                      "b": {"state": "degraded", "uptime_30d": 98.4},
                      "c": {"state": "maintenance"}},
            "services": {"Zeta": {"state": "down"}, "alpha web": {"state": "healthy"}}}
    text = demoreports.uptime(data, feed, NOW)
    assert "_An invented status page for the demo lab, read from the same feed the map wears._" in text
    assert "- as of 2026-11-20 06:30 UTC" in text
    assert "- 4 places: 1 up · 1 degraded · 1 maintenance · 1 not watched" in text
    lines = text.splitlines()
    assert "  ALPHA              up            99.90%" in lines
    assert "  BETA               degraded      98.40%" in lines
    assert "  GAMMA              maintenance        —" in lines
    assert "  d                  not watched        —" in lines      # no name, no state: said, not hidden
    # services by name, whatever their case; a fault is not softened
    assert lines.index("  alpha web                    up") < lines.index("  Zeta                         DOWN")


def test_the_board_with_nothing_watched_says_so():
    import demoreports
    text = demoreports.uptime({}, {}, NOW)
    assert "- 0 places: nothing is watched" in text
    assert "## Services" not in text


def test_a_real_lab_never_gets_the_invented_pages(tmp_path):
    """Off the demo, `security` is the staged scroll (or says it has not been
    delivered) and `uptime` is no page at all."""
    client = _look_only(tmp_path).test_client()
    import demoreports
    assert demoreports.enabled() is False
    r = client.get("/report/uptime")
    assert r.status_code == 404 and "No such scroll" in r.get_data(as_text=True)
    page = client.get("/report/security").get_data(as_text=True)
    assert "invented" not in page.lower()
    assert "not yet delivered" in page


def test_the_demo_serves_both_and_they_may_be_framed(tmp_path, monkeypatch):
    client = _look_only(tmp_path).test_client()
    import demoreports
    monkeypatch.setattr(demoreports, "enabled", lambda: True)
    for name, head in (("security", "# WEEKLY SECURITY REPORT"), ("uptime", "# UPTIME BOARD")):
        r = client.get(f"/report/{name}")
        assert r.status_code == 200, name
        assert head in r.get_data(as_text=True), name
        # the Depths and the viewing glass draw it in a frame of the same origin
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN", name
    board = client.get("/report/uptime").get_data(as_text=True)
    assert "BOX" in board and "QUIET" in board and "- 2 places:" in board
    # no other name is invented
    assert client.get("/report/crowdsec").status_code == 200
    assert "invented" not in client.get("/report/crowdsec").get_data(as_text=True).lower()
    assert client.get("/report/anything").status_code == 404


def test_the_switch_is_the_demo_figures_own():
    import demofigures
    import demoreports
    assert demoreports.NAMES == ("security", "uptime")
    src = open(demoreports.__file__, encoding="utf-8").read()
    assert "return demofigures.enabled()" in src
    assert "os.environ" not in src, "one switch, read in one place"
    assert demoreports.enabled() == demofigures.enabled()


def test_the_demo_labs_two_buttons_open_them():
    seed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "demo-lab", "seed",
                        "lab-data.demo.json")
    if not os.path.isfile(seed):
        pytest.skip("the demo lab's seed is not in this tree")
    with open(seed, encoding="utf-8") as fh:
        data = json.load(fh)
    links = {w["title"]: w.get("url") for w in data["chronicle"] + data["abyss"]}
    assert links["Uptime board"] == "report/uptime"
    assert links["Security report"] == "report/security"
