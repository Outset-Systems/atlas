"""The two settings only the hosted demo uses, and what stays shut without them."""

import json
import os
import re

import pytest

from appfixture import fresh_app

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
       b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99"
       b"=\x1d\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture(autouse=True)
def _these_settings_stay_here():
    """`fresh_app` writes to the environment, and a later suite must not inherit them."""
    yield
    for key in ("ATLAS_DEMO_TRUST", "ATLAS_DEFAULT_STYLE", "ATLAS_DEMO_LINK"):
        os.environ.pop(key, None)


def _look_only(tmp_path, **env):
    (tmp_path / "lab-data.json").write_text(json.dumps({
        "meta": {"title": "T"}, "zones": [{"id": "z", "name": "Z"}],
        "nodes": [{"id": "pub", "name": "PUB", "kind": "physical", "zone": "z", "x": 1, "y": 1}],
        "routes": [], "rack": [], "vms": []}), encoding="utf-8")
    return fresh_app(ATLAS_AUTH_MODE="standalone", ATLAS_READONLY="1", ATLAS_DATA_BACKEND="file",
                     ATLAS_DATA=str(tmp_path / "lab-data.json"), ATLAS_SIGNALS_SOURCES="",
                     ATLAS_MAPS=str(tmp_path), **env).app


def _config(page):
    block = re.search(r'id="atlas-config">(.*?)</script>', page, re.S).group(1)
    return json.loads(block)


def test_the_trust_map_stays_shut_on_a_look_only_atlas(tmp_path):
    client = _look_only(tmp_path).test_client()
    assert client.get("/api/v2/trust").status_code == 403
    assert not _config(client.get("/").get_data(as_text=True)).get("demoTrust")


def test_a_named_demo_trust_map_is_open_and_nothing_else_is(tmp_path):
    invented = tmp_path / "demo-trust.json"
    invented.write_text(json.dumps({"apps": [{"name": "invented"}]}), encoding="utf-8")
    client = _look_only(tmp_path, ATLAS_DEMO_TRUST=str(invented)).test_client()
    r = client.get("/api/v2/trust")
    assert r.status_code == 200 and r.get_json()["apps"] == [{"name": "invented"}]
    assert _config(client.get("/").get_data(as_text=True))["demoTrust"] is True
    assert client.get("/api/v2/admin/dataset").status_code == 403


def test_the_demo_link_takes_https_only(tmp_path):
    page = _look_only(tmp_path, ATLAS_DEMO_LINK="https://example.org/atlas/").test_client().get("/")
    assert _config(page.get_data(as_text=True))["demoLink"] == "https://example.org/atlas/"
    page = _look_only(tmp_path, ATLAS_DEMO_LINK="javascript:alert(1)").test_client().get("/")
    assert _config(page.get_data(as_text=True))["demoLink"] == ""


def test_a_missing_demo_trust_map_says_so(tmp_path):
    client = _look_only(tmp_path, ATLAS_DEMO_TRUST=str(tmp_path / "gone.json")).test_client()
    assert client.get("/api/v2/trust").status_code == 503


def test_a_default_style_is_drawn_first_and_carries_its_words(tmp_path):
    (tmp_path / "isle.png").write_bytes(PNG)
    (tmp_path / "isle.style.json").write_text(json.dumps({
        "label": "The Isle", "words": {"realm": "kingdom"}, "places": {"pub": {"x": 5, "y": 6}, "gone": {"x": 1, "y": 1}}}),
        encoding="utf-8")
    page = _look_only(tmp_path, ATLAS_DEFAULT_STYLE="isle.png").test_client().get("/").get_data(as_text=True)
    assert 'src="map-art/isle.png"' in page
    style = _config(page)["defaultStyle"]
    assert style["label"] == "The Isle" and style["words"] == {"realm": "kingdom"}
    assert style["places"] == {"pub": {"x": 5, "y": 6}}


def test_a_default_style_with_no_art_falls_back_to_the_realms_map(tmp_path):
    page = _look_only(tmp_path, ATLAS_DEFAULT_STYLE="gone.png").test_client().get("/").get_data(as_text=True)
    assert "map-art/gone.png" not in page
    assert "defaultStyle" not in _config(page)


def test_a_look_only_atlas_keeps_the_admin_s_tiles_to_itself(tmp_path):
    """Every visitor of a look-only standalone Atlas sees every place (no one
    signs in), but none of them is its admin: OVERVIEW names no change, drift
    or source, and NODES names no reviewer (the 2026-11-13 front-end review)."""
    client = _look_only(tmp_path).test_client()
    assert client.get("/api/v2/admin/dataset").status_code == 403
    body = client.get("/api/v2/overview").get_json()
    assert body["admin"] is False
    assert "drift" not in body
    assert body["sources"]["items"] == []
    rows = client.get("/api/v2/places/roster").get_json()["rows"]
    assert rows and all("reviewed_by" not in r for r in rows)
