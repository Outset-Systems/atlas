"""THE REAL-WORLD SURVEY — the half that must work without any network.

Nothing in this file touches Nominatim or Overpass: the parse and paint are
pure functions fed fixtures, and the route tests monkeypatch the whole
journey. The two fixed upstream hosts are asserted AS constants — the
/api/whois lesson says the day a request can name the host is the day this
route becomes a proxy.
"""

import io
import json
import os
import shutil
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

BUNDLED = os.path.join(WEB, "default-lab-data.json")

# Declared for conftest so this module owns its environment (see conftest.py).
ATLAS_TEST_ENV = {
    "ATLAS_DATA_BACKEND": "file",
    "ATLAS_ALLOW_INSECURE": "1",
    "ATLAS_AUTH_MODE": "standalone",
}
os.environ.update(ATLAS_TEST_ENV)

import worldsurvey  # noqa: E402

WRITE = {"X-Atlas-Write": "1"}

# a tiny neighbourhood: two buildings (one tagged height, one levels) + a road
OVERPASS_FIXTURE = {
    "elements": [
        {"type": "way", "tags": {"building": "yes", "height": "21 m"},
         "geometry": [{"lat": 30.2670, "lon": -97.7430},
                      {"lat": 30.2672, "lon": -97.7430},
                      {"lat": 30.2672, "lon": -97.7427},
                      {"lat": 30.2670, "lon": -97.7427}]},
        {"type": "way", "tags": {"building": "house", "building:levels": "2"},
         "geometry": [{"lat": 30.2665, "lon": -97.7435},
                      {"lat": 30.2666, "lon": -97.7435},
                      {"lat": 30.2666, "lon": -97.7434}]},
        {"type": "way", "tags": {"highway": "residential"},
         "geometry": [{"lat": 30.2660, "lon": -97.7440},
                      {"lat": 30.2675, "lon": -97.7420}]},
        {"type": "way", "tags": {"building": "yes"},
         "geometry": [{"lat": 30.2668, "lon": -97.7432}]},   # degenerate: 1 pt
    ],
}


# ── The fixed upstreams ──────────────────────────────────────────────────────

def test_the_fetch_refuses_redirects():
    """the 2026-08-16 security review: the default opener follows 3xx, so a hostile upstream
    could 302 the survey at an internal host — the whois referral-SSRF class
    through a redirect. `_fetch` uses a build_opener(_NoRedirect); a 3xx must
    turn into a refusal, never an internal fetch."""
    assert worldsurvey._NoRedirect().redirect_request(
        None, None, 302, "moved", {}, "http://10.77.33.30:5013/") is None
    # the module-level opener is the redirect-refusing one, not the default
    handlers = [type(h).__name__ for h in worldsurvey._OPENER.handlers]
    assert "_NoRedirect" in handlers


def test_the_upstream_hosts_are_constants_not_parameters():
    import inspect
    sig_geo = inspect.signature(worldsurvey.geocode)
    sig_osm = inspect.signature(worldsurvey.fetch_osm)
    assert "url" not in sig_geo.parameters and "host" not in sig_geo.parameters
    assert "url" not in sig_osm.parameters and "host" not in sig_osm.parameters
    assert worldsurvey.NOMINATIM.startswith("https://nominatim.openstreetmap.org/")
    assert worldsurvey.OVERPASS.startswith("https://overpass-api.de/")


@pytest.mark.parametrize("bad", ["", "  ", "a", "x" * 121, "☠<script>", "a\nb"])
def test_a_malformed_query_is_refused_before_any_network(bad, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the network was reached for a refused query")
    monkeypatch.setattr(worldsurvey, "_fetch", boom)
    with pytest.raises(worldsurvey.SurveyError):
        worldsurvey.geocode(bad)


# ── Parsing ──────────────────────────────────────────────────────────────────

def test_parse_reads_buildings_roads_and_heights():
    buildings, roads = worldsurvey.parse_elements(
        OVERPASS_FIXTURE, 30.2668, -97.7430)
    assert len(buildings) == 2          # the 1-point way is dropped
    assert len(roads) == 1
    heights = sorted(h for _pts, h in buildings)
    assert heights[0] == pytest.approx(2 * worldsurvey.LEVEL_M)   # levels
    assert heights[1] == pytest.approx(21.0)                      # "21 m"
    # local metres: the survey point itself is the origin
    for pts, _h in buildings:
        assert all(abs(x) < 200 and abs(y) < 200 for x, y in pts)


def test_a_building_with_no_height_hint_gets_the_default():
    data = {"elements": [{"type": "way", "tags": {"building": "yes"},
                          "geometry": OVERPASS_FIXTURE["elements"][0]["geometry"]}]}
    buildings, _ = worldsurvey.parse_elements(data, 30.2668, -97.7430)
    assert buildings[0][1] == worldsurvey.DEFAULT_HEIGHT_M


# ── The painter ──────────────────────────────────────────────────────────────

def test_render_paints_a_png_of_the_canvas_size():
    buildings, roads = worldsurvey.parse_elements(
        OVERPASS_FIXTURE, 30.2668, -97.7430)
    png = worldsurvey.render_iso(buildings, roads, canvas=256)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(png))
    assert img.size == (256, 256)
    # something was painted: the canvas is not a flat sheet of ground
    assert len(set(img.getdata())) > 1


def test_render_is_deterministic():
    buildings, roads = worldsurvey.parse_elements(
        OVERPASS_FIXTURE, 30.2668, -97.7430)
    a = worldsurvey.render_iso(buildings, roads, canvas=128)
    b = worldsurvey.render_iso(buildings, roads, canvas=128)
    assert a == b


# ── The route ────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    atlas_app = fresh_app(
        ATLAS_DATA=str(data),
        ATLAS_MAPS=str(tmp_path / "maps"),
        ATLAS_POSITIONS=str(tmp_path / "positions.json"),
        ATLAS_RACK=str(tmp_path / "rack.json"),
        ATLAS_REVISIONS=str(tmp_path / "revisions"),
        ATLAS_OBSERVED=str(tmp_path / "observed.json"),
        ATLAS_READONLY="0",
    )
    return atlas_app.app.test_client()


def test_the_route_runs_the_whole_journey(client, monkeypatch):
    monkeypatch.setattr(worldsurvey, "geocode",
                        lambda q: (30.2668, -97.7430, "Somewhere, TX"))
    monkeypatch.setattr(worldsurvey, "fetch_osm",
                        lambda lat, lon, radius=380: OVERPASS_FIXTURE)
    r = client.post("/api/v2/admin/map-art/survey",
                    json={"query": "78701"}, headers=WRITE)
    body = r.get_json()
    assert r.status_code == 200, body
    assert body["ok"] is True
    assert body["name"].startswith("survey-78701")
    assert body["surveyed"] == "Somewhere, TX"
    assert any(m["name"] == body["name"] for m in body["images"])


def test_a_survey_error_is_a_sentence_not_a_500(client, monkeypatch):
    def refuse(q):
        raise worldsurvey.SurveyError("nowhere called that could be found")
    monkeypatch.setattr(worldsurvey, "geocode", refuse)
    r = client.post("/api/v2/admin/map-art/survey",
                    json={"query": "zzzz"}, headers=WRITE)
    assert r.status_code == 422
    assert "nowhere" in r.get_json()["error"]


def test_no_write_header_no_survey(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("survey ran without the write header")
    monkeypatch.setattr(worldsurvey, "survey", boom)
    r = client.post("/api/v2/admin/map-art/survey", json={"query": "78701"})
    assert r.status_code in (400, 403)


def test_only_one_survey_at_a_time(monkeypatch):
    worldsurvey._survey_lock.acquire()
    try:
        with pytest.raises(worldsurvey.SurveyError, match="already underway"):
            worldsurvey.survey("78701")
    finally:
        worldsurvey._survey_lock.release()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))



def test_the_projection_is_not_a_mirror_image():
    """The 11-12 audit's Foundations 9: east to north turned clockwise on the
    screen. Canvas y grows down, so in y-up terms the turn from east to north
    must be anticlockwise, and north must be up."""
    ex, ey = worldsurvey._iso(1, 0)
    nx, ny = worldsurvey._iso(0, 1)
    assert ex * -ny - (-ey) * nx > 0, "east to north turns clockwise: a mirror image"
    assert ny < 0 and ey < 0, "north and east are both away from the camera, so up the canvas"
    assert nx < 0 < ex, "north is up-left, east up-right"
    _x, up = worldsurvey._iso(0, 0, 10)
    assert up < 0, "height is up"


def _counts(png):
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("RGB")
    colours = img.getcolors(maxcolors=1 << 16)
    return {c: n for n, c in colours}


def test_a_building_is_lit_the_same_whichever_way_its_outline_runs():
    """Foundations 10: the lit and shaded walls followed the edge's direction,
    so the same block lit opposite walls when OpenStreetMap drew its outline
    the other way round. One square, both windings: the same picture."""
    square = [(-20.0, -20.0), (20.0, -20.0), (20.0, 20.0), (-20.0, 20.0)]   # anticlockwise
    one = worldsurvey.render_iso([(square, 30.0)], [], canvas=256)
    other = worldsurvey.render_iso([(list(reversed(square)), 30.0)], [], canvas=256)
    a, b = _counts(one), _counts(other)
    assert a.get(worldsurvey.WALL_LIT) and a.get(worldsurvey.WALL_SHADE), "both faces show"
    assert a.get(worldsurvey.WALL_LIT) == b.get(worldsurvey.WALL_LIT)
    assert a.get(worldsurvey.WALL_SHADE) == b.get(worldsurvey.WALL_SHADE)


def test_the_near_building_is_painted_over_the_far_one():
    """With far now at large x + y, a tower to the north-east must not be
    painted over a low block south-west of it, in front of the camera."""
    near = ([(-30.0, -30.0), (-10.0, -30.0), (-10.0, -10.0), (-30.0, -10.0)], 6.0)
    far = ([(10.0, 10.0), (30.0, 10.0), (30.0, 30.0), (10.0, 30.0)], 80.0)
    a = worldsurvey.render_iso([near, far], [], canvas=256)
    b = worldsurvey.render_iso([far, near], [], canvas=256)
    assert a == b, "the order in the list must not change the picture"
