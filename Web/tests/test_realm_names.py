"""A map image's own name, the sky and the depths renamed, a null that clears
a setting, and a deleted map taking its sidecar with it (2026-11-20)."""
import json
import os
from pathlib import Path

import dataset as ds
import mapart
import schema
import settings
import validation

WEB = Path(__file__).resolve().parent.parent


def test_a_maps_name_is_declared_and_a_null_clears_a_setting():
    assert schema.HIDING["meta"]["map_art"] == "safe"
    data = json.loads((WEB / "default-lab-data.json").read_text(encoding="utf-8"))
    out, _ = ds.apply_ops(data, [{"op": "upsert", "section": "meta", "body": {
        "map_art": [{"name": "plain.webp", "label": "Flat"}]}}])
    assert validation.validate(out) == []
    assert out["meta"]["map_art"] == [{"name": "plain.webp", "label": "Flat"}]
    # an explicit null clears it, as it does on a list section's entry: it
    # used to be stored as a null
    out, _ = ds.apply_ops(out, [{"op": "upsert", "section": "meta", "body": {"map_art": None}}])
    assert "map_art" not in out["meta"]
    assert validation.validate(out) == []


def test_the_sky_and_the_depths_are_renamed_as_the_networks_they_are():
    """The page heads the two places by the networks `sky` and `depths`
    (ui.js nameRegionHeads); the map editor's two boxes send this."""
    data = json.loads((WEB / "default-lab-data.json").read_text(encoding="utf-8"))
    # whatever map this tree ships, it has these two after this
    have = {z["id"] for z in data["zones"]}
    spare = dict(data["zones"][0])
    for zone in ("sky", "depths"):
        if zone not in have:
            data["zones"].append({**spare, "id": zone, "name": zone.title()})
    out, _ = ds.apply_ops(data, [
        {"op": "upsert", "section": "zones", "id": "sky", "body": {"name": "Cloud Tops"}},
        {"op": "upsert", "section": "zones", "id": "depths", "body": {"name": "Undercroft"}}])
    names = {z["id"]: z["name"] for z in out["zones"]}
    assert names["sky"] == "Cloud Tops" and names["depths"] == "Undercroft"


def test_a_deleted_map_takes_its_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAPS_DIR", str(tmp_path))
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    name = mapart.save("floor-two.png", png)
    sidecar = tmp_path / "floor-two.style.json"
    sidecar.write_text(json.dumps({"label": "Second floor"}), encoding="utf-8")
    mapart.remove(name)
    assert not os.path.exists(tmp_path / name)
    assert not sidecar.exists(), "a later upload under this name would wear the old style"
