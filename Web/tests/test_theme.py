"""THE THEME (v1.48.0): the words and emblems that name one lab live in
themes/*.json, and the default theme names none of them."""
import json
import os

import pytest

import theme

THEMES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "themes")


def _read(name):
    with open(os.path.join(THEMES, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_plain_is_the_default():
    name, t = theme.load("")
    assert name == "plain"
    assert t["app_name"] == "Atlas"
    assert t["map_art"] == "plain.webp"
    assert t["veil_sigil"] == ""


def test_plain_backdrop_is_bundled():
    web = os.path.dirname(THEMES)
    assert os.path.isfile(os.path.join(web, "static", "map", _read("plain")["map_art"]))


def test_every_theme_key_has_a_plain_fallback():
    """A key only another theme defines would leave the plain page blank there."""
    plain = _read("plain")
    for fname in os.listdir(THEMES):
        if not fname.endswith(".json") or fname == "plain.json":
            continue
        other = _read(fname[:-5])
        for key in other:
            if not key.startswith("_"):
                assert key in plain, f"{fname}: {key} has no plain fallback"
        for key in other.get("text", {}):
            assert key in plain["text"], f"{fname}: text.{key} has no plain fallback"


def test_partial_theme_falls_back_to_plain(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "THEMES_DIR", str(tmp_path))
    (tmp_path / "plain.json").write_text(json.dumps(_read("plain")), encoding="utf-8")
    (tmp_path / "tiny.json").write_text(json.dumps(
        {"app_name": "Tiny", "text": {"colophon": "— tiny —"}}), encoding="utf-8")
    name, t = theme.load("tiny")
    assert name == "tiny"
    assert t["app_name"] == "Tiny"
    assert t["text"]["colophon"] == "— tiny —"
    assert t["text"]["map_alt"] == _read("plain")["text"]["map_alt"]


@pytest.mark.parametrize("bad", ["../plain", "the lab!", "no_such_theme"])
def test_bad_or_missing_name_falls_back_to_plain(bad):
    name, t = theme.load(bad)
    assert name == "plain"
    assert t["app_name"] == "Atlas"


def test_client_drops_unsafe_logo_slugs(monkeypatch):
    monkeypatch.setattr(theme, "T", {**theme.T, "node_logos": {"a": "ubuntu", "b": "../../etc"}})
    logos = theme.client()["nodeLogos"]
    assert logos == {"a": "ubuntu"}


def test_another_themes_maps_are_kept_but_not_offered(tmp_path, monkeypatch):
    """A theme's map set shows only while that theme is active."""
    (tmp_path / "plain.json").write_text(json.dumps(_read("plain")), encoding="utf-8")
    (tmp_path / "isles.json").write_text(json.dumps(
        {"map_art": "isles-main.webp", "maps": ["isles-main.webp", "isles-north.webp"]}),
        encoding="utf-8")
    monkeypatch.setattr(theme, "THEMES_DIR", str(tmp_path))
    monkeypatch.setattr(theme, "NAME", "plain")
    monkeypatch.setattr(theme, "T", theme.load("plain")[1])
    assert theme.foreign_maps() == {"isles-main.webp", "isles-north.webp"}
    name, t = theme.load("isles")
    monkeypatch.setattr(theme, "NAME", name)
    monkeypatch.setattr(theme, "T", t)
    assert "isles-north.webp" not in theme.foreign_maps()
    assert "plain.webp" in theme.foreign_maps()


def test_a_theme_can_invite_another_themes_map(tmp_path, monkeypatch):
    """Only the one it names: the rest of that theme's set stays out."""
    (tmp_path / "plain.json").write_text(json.dumps(_read("plain")), encoding="utf-8")
    (tmp_path / "isles.json").write_text(json.dumps(
        {"map_art": "isles-main.webp", "maps": ["isles-main.webp", "isles-north.webp"]}),
        encoding="utf-8")
    monkeypatch.setattr(theme, "THEMES_DIR", str(tmp_path))
    monkeypatch.setattr(theme, "NAME", "plain")
    monkeypatch.setattr(theme, "T", {**theme.load("plain")[1], "guest_maps": ["isles-main.webp"]})
    assert theme.foreign_maps() == {"isles-north.webp"}


def test_a_theme_names_its_own_maps(monkeypatch):
    monkeypatch.setattr(theme, "T", {**theme.T, "map_labels": {"a.webp": "The A Map"}})
    assert theme.map_label("a.webp") == "The A Map"
    assert theme.map_label("b.webp") == ""


def _render_index(monkeypatch, name):
    from app import app
    _, t = theme.load(name)
    monkeypatch.setattr(theme, "T", t)
    with app.test_request_context("/"):
        from flask import render_template
        return render_template("index.html", editable=False, seeded=True,
                               client_config={}, map_image="static/map/plain.webp",
                               realm_title="Atlas", veil_title="ATLAS")


def test_the_plain_theme_has_no_floating_island(monkeypatch):
    """The floating islet was placed for one theme's own map art; on the plain
    map, the demo lab or an empty install it hovered over nothing. A theme opts
    in with "sky_island": true (v1.52.0)."""
    _, plain = theme.load("plain")
    assert plain.get("sky_island") is False
    html = _render_index(monkeypatch, "plain")
    assert 'id="sky-island"' not in html and 'id="sky-shadow"' not in html
