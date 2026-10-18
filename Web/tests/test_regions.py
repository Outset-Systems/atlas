"""REGIONS (v1.49.0, PLAN-REGIONS.md): the dataset section, its checks, the
demo lab's example, what the API serves, and what redaction must hide.

The maths (where places land, when zooming opens a region) is in
test_region_model.mjs; the page wiring in test_scene_* style checks here."""
import copy
import json
import os
import pathlib

import pytest

import redaction
import schema
import validation

WEB = pathlib.Path(__file__).resolve().parent.parent
DEMO = WEB.parent / "demo-lab" / "seed" / "lab-data.demo.json"

BASE = {
    "zones": [{"id": "z", "name": "Z", "vlan": 1, "subnet": "10.77.1.0/24", "hue": "#888888",
               "lore": "z", "label_x": 10, "label_y": 10}],
    "nodes": [
        {"id": "a", "name": "A", "kind": "vm", "zone": "z", "x": 40, "y": 40, "role": "r", "lore": "l"},
        {"id": "secret", "name": "S", "kind": "vm", "zone": "z", "x": 45, "y": 45, "role": "r",
         "lore": "l", "require_group": "ops-only"},
    ],
    "regions": [
        {"id": "room", "name": "Room", "map": "room.webp", "x": 30, "y": 30, "w": 30, "h": 30,
         "places": {"a": {"x": 10, "y": 20}, "secret": {"x": 70, "y": 80}}},
    ],
}


def problems(data):
    return [p for p in validation.validate(data) if "region" in p]


# ── the section ──────────────────────────────────────────────────────────────

def test_regions_are_an_editable_section_after_zones():
    s = schema.get("regions")
    assert s and s["store"] == "dataset"
    names = [f["name"] for f in s["fields"]]
    assert names[:2] == ["id", "name"]
    assert {"map", "parent", "x", "y", "w", "h", "auto", "places"} <= set(names)
    order = schema.SECTION_ORDER
    assert order.index("regions") == order.index("zones") + 1


def test_a_good_region_is_clean():
    assert problems(copy.deepcopy(BASE)) == []


@pytest.mark.parametrize("patch, words", [
    ({"x": 80, "w": 40}, "runs off its map"),
    ({"w": 0}, "more than 0"),
    ({"places": {"ghost": {"x": 1, "y": 1}}}, "unknown place 'ghost'"),
    ({"places": {"a": {"x": "left", "y": 1}}}, "numeric x and y"),
    ({"places": ["a"]}, "must be an object"),
    ({"parent": "nowhere"}, "unknown parent"),
])
def test_bad_regions_say_what_is_wrong(patch, words):
    d = copy.deepcopy(BASE)
    d["regions"][0].update(patch)
    found = problems(d)
    assert any(words in p for p in found), found


def test_a_parent_loop_is_reported():
    d = copy.deepcopy(BASE)
    d["regions"] = [
        {"id": "p", "name": "P", "map": "p.webp", "parent": "q", "x": 1, "y": 1, "w": 5, "h": 5},
        {"id": "q", "name": "Q", "map": "q.webp", "parent": "p", "x": 1, "y": 1, "w": 5, "h": 5},
    ]
    assert any("loops back" in p for p in problems(d))


def test_a_dataset_without_regions_is_untouched():
    d = copy.deepcopy(BASE)
    del d["regions"]
    assert problems(d) == []


# ── the demo lab's example (what a stranger sees) ────────────────────────────

def test_the_demo_lab_ships_a_working_region():
    if not DEMO.exists():
        pytest.skip("no demo-lab seed in this tree")
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    assert validation.validate(data) == []
    regions = data.get("regions") or []
    assert regions, "the demo lab should show the feature"
    for r in regions:
        art = DEMO.parent / "maps" / r["map"]
        assert art.exists(), f"{r['map']} is not rendered (python demo-lab/build.py)"
        # a true enlargement: no pins needed, places map through the rectangle
        inside = [n for n in data["nodes"]
                  if not n.get("off_map") and r["x"] <= n["x"] <= r["x"] + r["w"]
                  and r["y"] <= n["y"] <= r["y"] + r["h"]]
        assert len(inside) >= 3, "the demo region should hold several places"


# ── redaction: a pin names its place ─────────────────────────────────────────

def test_pins_on_hidden_places_are_scrubbed(monkeypatch):
    monkeypatch.setattr(redaction, "viewer_groups", lambda: ["viewers"])
    d, _ = redaction.redact_for_groups(copy.deepcopy(BASE))
    pins = d["regions"][0]["places"]
    assert "a" in pins and "secret" not in pins
    assert all(n["id"] != "secret" for n in d["nodes"])


def test_admins_keep_every_pin(monkeypatch):
    monkeypatch.setattr(redaction, "viewer_groups", lambda: None)
    d, _ = redaction.redact_for_groups(copy.deepcopy(BASE))
    assert set(d["regions"][0]["places"]) == {"a", "secret"}


# ── the API and the page ─────────────────────────────────────────────────────

def test_lab_data_serves_regions(tmp_path):
    from appfixture import fresh_app
    data = json.loads((WEB / "default-lab-data.json").read_text(encoding="utf-8"))
    data["regions"] = [{"id": "room", "name": "Room", "map": "room.webp",
                        "x": 10, "y": 10, "w": 20, "h": 20}]
    path = tmp_path / "lab-data.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    handle = fresh_app(ATLAS_DATA=str(path), ATLAS_AUTH_MODE="standalone")
    r = handle.app.test_client().get("/api/v2/lab-data")
    assert r.status_code == 200
    assert r.get_json()["regions"][0]["id"] == "room"


def test_the_page_carries_the_region_layers():
    page = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="region-frames"' in page
    assert 'id="region-lens"' in page and "hidden" in page.split('id="region-lens"')[1][:80]
    assert 'aria-live="polite"' in page.split('id="region-announce"')[1][:60]
    boot = (WEB / "static" / "js" / "atlas.js").read_text(encoding="utf-8")
    assert boot.index("import './regions.js'") > boot.index("import './world.js'"), \
        "regions.js wraps world.js's buildWorld and onCameraMove, so it must load after it"
