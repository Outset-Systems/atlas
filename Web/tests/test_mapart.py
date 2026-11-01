"""The picture the map is drawn on, and the upload surface behind it.

What matters: a filename cannot escape its directory, the *bytes* decide the
format so a renamed script is refused, SVG never gets in, bundled art always
wins over an upload, and a swapped render doesn't need the markers moved.
"""

import json
import os
import shutil
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

BUNDLED = os.path.join(WEB, "default-lab-data.json")
WRITE = {"X-Atlas-Write": "1"}

ATLAS_TEST_ENV = {
    "ATLAS_AUTH_MODE": "standalone",
    "ATLAS_ALLOW_INSECURE": "1",
    "ATLAS_DATA_BACKEND": "file",
    "ATLAS_INGEST_ENABLED": "0",
    "ATLAS_READONLY": "0",
}
os.environ.update(ATLAS_TEST_ENV)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture
def art(tmp_path):
    """`mapart` pointed at a scratch uploads directory."""
    import importlib
    os.environ["ATLAS_MAPS"] = str(tmp_path / "maps")
    import settings
    importlib.reload(settings)
    import mapart
    importlib.reload(mapart)
    return mapart


@pytest.fixture
def arena(tmp_path):
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    return fresh_app(ATLAS_DATA=str(data), ATLAS_READONLY="0",
                     ATLAS_MAPS=str(tmp_path / "maps"),
                     ATLAS_BEATS=str(tmp_path / "hb.json"),
                     ATLAS_BEATS_DIR=str(tmp_path / "beats"),
                     ATLAS_MAINTENANCE=str(tmp_path / "m.json"),
                     ATLAS_EVENTS=str(tmp_path / "e.json"),
                     ATLAS_REVISIONS=str(tmp_path / "rev"))


# ── Names ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", [
    "../../etc/passwd", "../secret.png", "a/b.png", "a\\b.png", ".hidden",
    "", "   ", "x" * 80, "with space.png", "semi;colon.png",
])
def test_a_render_name_that_could_escape_is_refused_not_rewritten(art, name):
    assert art.safe_name(name) is None


@pytest.mark.parametrize("name", ["backdrop5.png", "floor-2.jpg", "rack_rear.webp", "a.gif"])
def test_ordinary_names_are_accepted(art, name):
    assert art.safe_name(name) == name


# ── Formats ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("blob,kind", [
    (PNG, "png"), (JPEG, "jpg"), (WEBP, "webp"), (GIF, "gif")])
def test_the_bytes_decide_the_format(art, blob, kind):
    assert art.sniff(blob[:16]) == kind


def test_svg_is_refused_however_it_is_named(art):
    """Same-origin SVG is a script delivery mechanism, not a picture."""
    with pytest.raises(ValueError, match="SVG is refused"):
        art.save("map.svg", SVG)
    with pytest.raises(ValueError, match="SVG is refused"):
        art.save("map.png", SVG)          # the lie in the extension changes nothing


def test_a_renamed_script_is_refused(art):
    with pytest.raises(ValueError):
        art.save("innocent.png", b"<html><script>alert(1)</script></html>")


def test_riff_alone_is_not_webp(art):
    """A WAV file is RIFF too — both ends of the header have to match."""
    assert art.sniff(b"RIFF\x00\x00\x00\x00WAVEfmt ") is None


# ── The bundled backdrop actually reaches the browser as a picture ───────────
def test_webp_has_a_registered_mimetype():
    """CPython's built-in table knows `.avif` and not `.webp` (3.12), and Debian
    slim ships no `/etc/mime.types` to cover for it. Unregistered, Flask's static
    route serves the backdrop as `application/octet-stream` and the browser
    offers to download the map instead of drawing it — `mapart` registers it,
    beside SIGNATURES, so the formats the Atlas serves stay one list in one file."""
    import mimetypes
    import mapart  # noqa: F401 — importing it is what registers the type
    assert mimetypes.guess_type("backdrop.webp")[0] == "image/webp"


def test_the_shipped_default_render_exists_and_is_what_it_claims(art):
    """`mapart.DEFAULT` is what an unconfigured map draws, so a rename that
    misses it leaves every deployment with a broken <img> and no error."""
    path, bundled = art.resolve(art.DEFAULT)
    assert bundled and path, f"{art.DEFAULT} is not shipped in static/map/"
    with open(path, "rb") as fh:
        head = fh.read(16)
    assert art.sniff(head) == art.DEFAULT.rsplit(".", 1)[1].replace("jpg", "jpg")


def test_the_default_backdrop_is_served_as_an_image(arena):
    """End to end: the page's <img src> must come back with an image type."""
    import mapart
    r = arena.app.test_client().get(f"/static/map/{mapart.DEFAULT}")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("image/"), r.headers["Content-Type"]


def test_the_gallery_reports_which_render_is_the_default(arena):
    """The Desk highlights the chosen tile from this, rather than from a
    filename hard-coded in the browser (which went stale the moment the
    shipped render was renamed)."""
    r = arena.app.test_client().get("/api/v2/admin/map-art")
    assert r.status_code == 200
    body = r.get_json()
    import mapart
    assert body["default"] == mapart.DEFAULT
    assert any(i["name"] == mapart.DEFAULT and i["bundled"] for i in body["images"])


def test_an_oversized_render_is_refused_with_the_numbers(art):
    with pytest.raises(ValueError, match="the limit is"):
        art.save("huge.png", PNG + b"\x00" * art.MAX_BYTES)


def test_an_empty_file_is_refused(art):
    with pytest.raises(ValueError, match="empty"):
        art.save("nothing.png", b"")


# ── Resolution ───────────────────────────────────────────────────────────────
def test_bundled_art_wins_over_an_upload_of_the_same_name(art):
    """Otherwise uploading the bundled render's name silently shadows the shipped render
    and the deployment can never get back to it."""
    with pytest.raises(ValueError, match="built into the Atlas"):
        art.save(art.DEFAULT, PNG)

    path, bundled = art.resolve(art.DEFAULT)
    assert bundled is True
    assert path.endswith(art.DEFAULT)


def test_an_upload_resolves_and_an_unknown_name_falls_back(art):
    art.save("floor-2.png", PNG)
    path, bundled = art.resolve("floor-2.png")
    assert bundled is False and path.endswith("floor-2.png")

    # "nowhere" for a name that isn't there, and equally for a hostile one —
    # the page falls back to the default, the resolver doesn't pretend
    assert art.resolve("never-uploaded.png") == (None, False)
    assert art.resolve("../../etc/passwd") == (None, False)


def test_available_lists_bundled_and_uploaded_without_duplicates(art):
    art.save("floor-2.png", PNG)
    names = [entry["name"] for entry in art.available()]
    assert art.DEFAULT in names
    assert "floor-2.png" in names
    assert len(names) == len(set(names))


def test_bundled_art_cannot_be_deleted(art):
    with pytest.raises(ValueError, match="built into the Atlas"):
        art.remove(art.DEFAULT)
    art.save("floor-2.png", PNG)
    art.remove("floor-2.png")
    assert "floor-2.png" not in [e["name"] for e in art.available()]


# ── Through the app ──────────────────────────────────────────────────────────
def test_upload_list_serve_and_delete(arena):
    client = arena.app.test_client()

    resp = client.post("/api/v2/admin/map-art", headers=WRITE,
                       data={"image": (__import__("io").BytesIO(PNG), "floor-2.png")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_json()
    assert "floor-2.png" in [e["name"] for e in resp.get_json()["images"]]

    served = client.get("/map-art/floor-2.png")
    assert served.status_code == 200
    assert served.headers["Content-Type"] == "image/png"
    assert served.headers["X-Content-Type-Options"] == "nosniff"

    assert client.delete("/api/v2/admin/map-art/floor-2.png", headers=WRITE).status_code == 200
    assert client.get("/map-art/floor-2.png").status_code == 404


def test_serving_refuses_a_traversal_and_an_unknown_render(arena):
    client = arena.app.test_client()
    assert client.get("/map-art/..%2F..%2Fetc%2Fpasswd").status_code in (307, 404)
    assert client.get("/map-art/nothing-here.png").status_code == 404


def test_uploading_needs_the_write_header(arena):
    """The editor's CSRF gate covers this route like every other write."""
    resp = arena.app.test_client().post(
        "/api/v2/admin/map-art",
        data={"image": (__import__("io").BytesIO(PNG), "x.png")},
        content_type="multipart/form-data")
    assert resp.status_code == 403


def test_the_page_renders_the_configured_render(arena, tmp_path):
    """The whole point: point `meta.map_image` at something else and the map
    is drawn on it, with no marker moved."""
    client = arena.app.test_client()
    client.post("/api/v2/admin/map-art", headers=WRITE,
                data={"image": (__import__("io").BytesIO(PNG), "floor-2.png")},
                content_type="multipart/form-data")

    path = os.environ["ATLAS_DATA"]
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    before = json.dumps(payload.get("nodes"))
    payload["meta"]["map_image"] = "floor-2.png"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    page = client.get("/").get_data(as_text=True)
    assert 'src="map-art/floor-2.png"' in page

    with open(path, encoding="utf-8") as handle:
        assert json.dumps(json.load(handle).get("nodes")) == before   # markers untouched


def test_an_unconfigured_map_still_draws_the_default(arena):
    page = arena.app.test_client().get("/").get_data(as_text=True)
    assert "static/map/" in page


# ── THE CARTOGRAPHER'S TABLE — the viewer-side gallery ──────────────────────
def test_the_viewer_gallery_lists_every_render_with_a_fetchable_url(arena):
    """`/api/maps` is the read-only half of the gallery a settings panel needs:
    every render, where to fetch it (bundled art from static/, uploads from
    /map-art/), which one is the default, and its theme if charted. It was the
    one map route with no test."""
    import io
    import mapart
    client = arena.app.test_client()

    r = client.get("/api/v2/maps")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "private, no-cache"
    assert "Cookie" in r.headers.get("Vary", "")
    maps = r.get_json()["maps"]
    assert set(maps[0]) == {"name", "label", "url", "default", "theme", "regions", "zoom"}
    bundled = next(m for m in maps if m["name"] == mapart.DEFAULT)
    # the default is whichever render the dataset names, else the bundled one
    import json
    with open(BUNDLED, encoding="utf-8") as fh:
        in_use = (json.load(fh).get("meta") or {}).get("map_image") or mapart.DEFAULT
    assert next(m for m in maps if m["default"])["name"] == in_use
    assert bundled["url"] == f"static/map/{mapart.DEFAULT}"
    import theme
    assert bundled["label"] == (theme.map_label(mapart.DEFAULT) or mapart.DEFAULT.rsplit(".", 1)[0])
    assert bundled["theme"] is None
    assert sum(1 for m in maps if m["default"]) == 1
    # nothing the Desk's gallery knows (sizes, bundled flag) leaks to viewers
    assert "bundled" not in maps[0] and "bytes" not in maps[0]

    resp = client.post("/api/v2/admin/map-art", headers=WRITE,
                       data={"image": (io.BytesIO(PNG), "floor-3.png")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_json()
    maps = client.get("/api/v2/maps").get_json()["maps"]
    uploaded = next(m for m in maps if m["name"] == "floor-3.png")
    assert uploaded["url"] == "map-art/floor-3.png"
    assert uploaded["default"] is False
    assert client.get("/" + uploaded["url"]).status_code == 200


def test_the_viewer_gallery_carries_the_charted_theme_and_default(arena):
    """`meta.map_art` lets a render bring its palette; `meta.map_image` picks
    the default. Both ride the dataset, so the gallery must read them live."""
    import io
    import mapart
    client = arena.app.test_client()
    client.post("/api/v2/admin/map-art", headers=WRITE,
                data={"image": (io.BytesIO(PNG), "night.png")},
                content_type="multipart/form-data")

    path = os.environ["ATLAS_DATA"]
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("meta", {})["map_image"] = "night.png"
    data["meta"]["map_art"] = [
        {"name": "night.png", "label": "The Night Chart",
         "theme": {"--parchment": "#111"}},
        {"name": mapart.DEFAULT, "theme": "not-a-theme"},
    ]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    arena._lab.invalidate()

    maps = {m["name"]: m for m in client.get("/api/v2/maps").get_json()["maps"]}
    assert maps["night.png"]["default"] is True
    assert maps["night.png"]["label"] == "The Night Chart"
    assert maps["night.png"]["theme"] == {"--parchment": "#111"}
    assert maps[mapart.DEFAULT]["default"] is False
    assert maps[mapart.DEFAULT]["theme"] is None        # a non-object theme degrades to none


# ── Styles that bring their own zoom ─────────────────────────────────────────
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _style_files(art, tmp_path, sidecar):
    maps = tmp_path / "maps"
    maps.mkdir(exist_ok=True)
    for name in ("isle.png", "cove.png"):
        (maps / name).write_bytes(PNG)
    (maps / "isle.style.json").write_text(sidecar, encoding="utf-8")


COVE = ('{"label": "The Isle", "regions": [{"id": "cove", "name": "The Cove", "map": "cove.png",'
        ' "x": 10, "y": 20, "w": 30, "h": 40, "auto": true, "places": {"x": {"x": 1, "y": 2}}}]}')


def test_a_style_names_itself_and_brings_its_regions(art, tmp_path):
    _style_files(art, tmp_path, COVE)
    style = art.style("isle.png")
    assert style["label"] == "The Isle"
    assert style["regions"] == [{"id": "cove", "name": "The Cove", "map": "cove.png",
                                 "url": "map-art/cove.png", "x": 10, "y": 20, "w": 30, "h": 40,
                                 "auto": True}]


def test_region_art_and_sidecars_are_not_offered_as_backdrops(art, tmp_path):
    _style_files(art, tmp_path, COVE)
    names = {image["name"] for image in art.available()}
    assert "isle.png" in names
    assert not names & {"cove.png", "isle.style.json"}
    assert art.resolve("cove.png")[0], "the zoom still has to reach it"


@pytest.mark.parametrize("sidecar", ["{not json", "[]"])
def test_a_broken_sidecar_costs_the_zoom_never_the_map(art, tmp_path, sidecar):
    _style_files(art, tmp_path, sidecar)
    assert art.style("isle.png") == {}
    assert "isle.png" in {image["name"] for image in art.available()}


@pytest.mark.parametrize("region", [
    {"id": "x", "name": "X", "map": "../secret.png", "x": 1, "y": 1, "w": 1, "h": 1},
    {"id": "x", "name": "X", "map": "gone.png", "x": 1, "y": 1, "w": 1, "h": 1},
    {"id": "x", "name": "X", "map": "cove.png", "x": "1", "y": 1, "w": 1, "h": 1},
    {"id": "../x", "name": "X", "map": "cove.png", "x": 1, "y": 1, "w": 1, "h": 1},
    {"id": "x", "name": "", "map": "cove.png", "x": 1, "y": 1, "w": 1, "h": 1},
    "not a region",
])
def test_a_bad_region_is_dropped_alone(art, tmp_path, region):
    import json
    _style_files(art, tmp_path, json.dumps({"regions": [region]}))
    assert art.style("isle.png")["regions"] == []


def test_the_maps_list_carries_a_styles_regions(arena, tmp_path):
    (tmp_path / "maps").mkdir(exist_ok=True)
    _style_files(None, tmp_path, COVE)
    maps = arena.app.test_client().get("/api/v2/maps").get_json()["maps"]
    isle = next(m for m in maps if m["name"] == "isle.png")
    assert isle["label"] == "The Isle"
    assert [r["id"] for r in isle["regions"]] == ["cove"]
    assert next(m for m in maps if m["name"] == "cove.png" or m["default"])["regions"] == []


def test_the_datasets_own_region_art_is_marked_as_zoom(arena, tmp_path):
    """The map needs its address, the style list must not offer it."""
    _style_files(None, tmp_path, COVE)
    client = arena.app.test_client()
    data = client.get("/api/v2/lab-data").get_json()
    region_art = {r["map"] for r in data.get("regions") or []}
    maps = client.get("/api/v2/maps").get_json()["maps"]
    assert {m["name"] for m in maps if m["zoom"]} == region_art & {m["name"] for m in maps}
    assert not next(m for m in maps if m["name"] == "isle.png")["zoom"]
