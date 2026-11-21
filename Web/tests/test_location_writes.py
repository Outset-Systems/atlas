"""Where a thing stands, as the server takes it (2026-11-20).

The page's Location box and the map editor's Draw a box send only ops the
editing API already had (static/js/location-set-model.js builds them, and
tests/test_location_set_model.mjs pins their shape). These apply those same
shapes to the map every new Atlas starts from, which charts no racks: the
first `racks` record, a place's own location set and cleared, and a region
made from a drawn rectangle.
"""
import json
from pathlib import Path

import dataset as ds
import validation

WEB = Path(__file__).resolve().parent.parent


def _default():
    """The shipped map with its racks taken out: the private tree ships the
    owner's map and the public one the demo's, and either may chart racks
    and regions of its own. What these tests need is a map that charts none."""
    data = json.loads((WEB / "default-lab-data.json").read_text(encoding="utf-8"))
    data.pop("racks", None)
    for section in ("rack", "rack_rear"):
        for slot in data.get(section) or []:
            slot.pop("rack", None)
    data["regions"] = []
    return data


def _clean(data):
    assert validation.validate(data) == [], validation.validate(data)


def test_the_first_rack_record_is_written_on_a_map_that_charts_none():
    data = _default()
    out, said = ds.apply_ops(data, [
        {"op": "insert", "section": "racks",
         "body": {"id": "rack-a", "name": "Rack A", "location": "Closet"}}])
    assert out["racks"] == [{"id": "rack-a", "name": "Rack A", "location": "Closet"}]
    assert "rack" in said[0]
    _clean(out)
    # the slots named no rack before and name none now: they are the first rack's
    assert out.get("rack") == data.get("rack")
    assert all("rack" not in slot or slot["rack"] == "rack-a" for slot in out.get("rack") or [])


def test_a_places_location_is_set_and_cleared():
    data = _default()
    place = next(n["id"] for n in data["nodes"] if n.get("kind") == "physical")
    out, _ = ds.apply_ops(data, [
        {"op": "upsert", "section": "nodes", "id": place, "body": {"location": "Attic"}}])
    node = next(n for n in out["nodes"] if n["id"] == place)
    assert node["location"] == "Attic"
    _clean(out)
    # an explicit null clears it: the place is back at the map's default location
    out, _ = ds.apply_ops(out, [
        {"op": "upsert", "section": "nodes", "id": place, "body": {"location": None}}])
    assert "location" not in next(n for n in out["nodes"] if n["id"] == place)
    _clean(out)


def test_a_drawn_box_becomes_a_region_alone_or_inside_another():
    data = _default()
    art = data.get("meta", {}).get("map_image") or "plain.webp"
    box = {"id": "server-room", "name": "Server room", "map": art,
           "x": 51.8, "y": 57.8, "w": 16.6, "h": 24.9, "auto": True}
    out, _ = ds.apply_ops(data, [{"op": "insert", "section": "regions", "body": box}])
    assert out["regions"][-1] == box
    _clean(out)
    inner = {**box, "id": "cage", "name": "Cage", "parent": "server-room", "x": 10.0, "y": 10.0, "w": 30.0, "h": 30.0}
    out, _ = ds.apply_ops(out, [{"op": "insert", "section": "regions", "body": inner}])
    assert out["regions"][-1]["parent"] == "server-room"
    _clean(out)
