"""HARDWARE and RESOURCES by location (2026-11-20).

Owner: "adjust 'Racks' to say 'Hardware' and include any kind of compute iOT
raspberry pi, etc. ... add an add button next to arrange that will let you pick
from a device, then you can drag it up and down in the rack. When you hover
over hardware, it should show a drop down of locations ... update resources in
the same way: selecting 'home office' will display just the resources there,
but selecting 'Resources' will display a summary/total of everything."

The rules are node-tested (test_locations_model.mjs, test_tribute_model.mjs,
test_rack_model.mjs). These pin the page: the words, the pieces each scene
needs, and the seams between the files, read from Web/ alone so they run in
the image too.
"""
import json
import pathlib
import re

import pytest

WEB = pathlib.Path(__file__).resolve().parent.parent
JS = WEB / "static" / "js"


def _read(path):
    return path.read_text(encoding="utf-8")


def _css():
    return re.sub(r"/\*.*?\*/", "", _read(WEB / "static" / "atlas.css"), flags=re.S)


def _html():
    return _read(WEB / "templates" / "index.html")


def _block(html, start, end):
    block = html[html.index(start):]
    return re.sub(r"<!--.*?-->", "", block[:block.index(end) + len(end)], flags=re.S)


# ── the words ────────────────────────────────────────────────────────────────

def test_racks_is_hardware_and_the_ids_kept_their_names():
    html = _html()
    assert '<button class="scene" data-scene="rack">HARDWARE</button>' in html
    assert ">RACKS<" not in html
    panel = _block(html, '<div id="reliquary"', '<aside id="rel-detail" class="rel-detail"></aside>')
    assert 'id="rel-title">HARDWARE</span>' in panel
    assert 'aria-label="Hardware' in panel
    # the scene's ids, the band's key and the opener are what they were: only words changed
    ui = _read(JS / "ui.js")
    assert "rack: A.openReliquary, tribute: A.openTribute" in ui
    for old in ('id="rel-elevation"', 'class="rel-tools"', 'id="rel-edit"', 'id="rel-save"', 'id="rel-reset"'):
        assert old in panel, old


# ── one notion of a location, read by both scenes ───────────────────────────

def test_both_scenes_ask_the_one_location_model():
    for scene in ("reliquary.js", "tribute.js"):
        js = _read(JS / scene)
        assert "from './locations-model.js';" in js, scene
        assert "from './scene-places.js';" in js, scene
        assert "whereNow()" in js and "locationByKey(where, place)" in js, scene
    places = _read(JS / "scene-places.js")
    assert "whereabouts(A.DATA, themeText('rack_location', ''))" in places
    # the model itself touches no page
    model = _read(JS / "locations-model.js")
    assert "document" not in model and "localStorage" not in model and "import { A" not in model
    assert _read(JS / "tribute-model.js").count("import ") == 0


def test_a_place_may_say_where_it_stands_and_what_compute_it_has():
    import schema
    fields = {f["name"]: f for f in schema.SECTIONS["nodes"]["fields"]}
    assert fields["location"]["type"] == "text"
    for key in ("ram_gb", "ram_reserve_gb", "cpu_cores", "cpu_threads"):
        assert fields[key]["type"] == "number" and fields[key].get("min") == 0, key
    # a location is words, as a rack's is: hidden with the names a viewer may not read
    assert schema.HIDING["nodes"]["location"] == "words"
    assert schema.HIDING["racks"]["location"] == "words"
    # and a cloud token is never told it
    import cloud_view
    assert "location" in cloud_view.SEALED


# ── the band: a press, and the menus ────────────────────────────────────────

def test_a_scene_showing_one_location_shows_everything_before_it_closes():
    ui = _read(JS / "ui.js")
    rule = ui[ui.index("if (deselect && btn.dataset.place) {"):]
    rule = rule[:rule.index("if (deselect) { setSceneActive('atlas'); return; }")]
    assert "dispatchEvent(new CustomEvent('atlas:scene-place', { detail: { scene: btn.dataset.scene, place: '' } }));" in rule
    assert "return;" in rule and "closeAllScenes();" in rule, "it must return before the scenes are closed"
    assert rule.index("return;") < rule.index("closeAllScenes();")
    for scene, name in (("reliquary.js", "rack"), ("tribute.js", "tribute")):
        js = _read(JS / scene)
        assert f"if (e.detail?.scene === '{name}') setPlace(e.detail.place);" in js, scene
        assert f"markPlace('{name}', place);" in js, scene
        # closed, a scene forgets its location: pressed afresh it is everything
        assert f"markPlace('{name}', '')" in js, scene


def test_the_bands_menus_of_locations():
    html = _html()
    for menu in ("hardware-menu", "resources-menu"):
        assert f'<div class="view-menu band-menu" id="{menu}" role="menu"' in html, menu
    # siblings of the band, after the drawers; never in the stretch read as the views' menu
    assert html.index('<aside id="map-drawer"') < html.index('id="hardware-menu"')
    assert html.index("</nav>") < html.index('id="hardware-menu"')
    js = _read(JS / "band-menus.js")
    assert "import { hoverReveal, idleRollup } from './ui.js';" in js
    assert "export { hoverReveal, idleRollup };" in _read(JS / "ui.js")
    assert "bandMenu('rack', 'hardware-menu');" in js and "bandMenu('tribute', 'resources-menu');" in js
    assert "refuse: (how) => A.PHONE || !menu.childElementCount || (how === 'focus' && hush)," in js
    # focus handed back to the button (Escape, a keyboard pick) must not open it again
    assert "const handBack = () => { hush = true; reveal.close(); button.focus(); };" in js
    assert js.count("handBack();") == 2
    # an item names a place, never a scene: the band binds every [data-scene]
    assert 'role="menuitem" data-place=' in js and "data-scene=" not in js.split("function bandMenu")[1].replace(
        '.scene[data-scene="${scene}"]', "")
    assert "askPlace(scene, item.dataset.place);" in js
    assert "if (!button.classList.contains('active')) button.click();" in js
    assert not re.search(r"^\s*A\.\w+ = ", js, re.M), "no new name on the shared context"
    atlas = _read(JS / "atlas.js")
    assert atlas.index("import './tribute.js';") < atlas.index("import './band-menus.js';")
    css = _css()
    block = css[css.index(':root[data-scheme-pick="light"] :is(#scenes-list'):]
    assert block[:block.index("{")].count(".band-menu") == 4, "one for each clause of the bar's condition"
    assert ".band-menu > button { text-transform: uppercase; }" in css


def test_each_scene_has_the_picker_a_touch_screen_needs():
    html = _html()
    assert 'id="rel-places" role="group" aria-label="Choose a location" hidden' in html
    assert 'id="trb-places" role="group" aria-label="Choose a location" hidden' in html
    places = _read(JS / "scene-places.js")
    assert "el.hidden = list.length < 2;" in places, "one location: nothing to pick"
    assert "drawPlacePicker($('rel-places'), place, setPlace);" in _read(JS / "reliquary.js")
    assert "drawPlacePicker(placesEl, place, setPlace);" in _read(JS / "tribute.js")


# ── HARDWARE: what stands outside a rack, and add and remove ────────────────

def test_the_shelf_lists_what_stands_outside_a_rack():
    js = _read(JS / "reliquary.js")
    shelf = js[js.index("function renderShelf() {"):js.index("/** Show one location")]
    assert "looseAt(where, loc)" in shelf and "el.className = 'rel-rear rel-shelf';" in shelf
    assert "not in a rack" in shelf
    # the shelf wears the rear strip's class, so the rear strip is named alone where it is replaced
    assert js.count(".rel-rear:not(.rel-shelf)") == 2
    # a location with no rack shows the shelf and none of the rack's furniture
    assert "root.classList.toggle('no-rack', rackId === null);" in js
    assert "#reliquary.no-rack :is(.rel-power, #rel-elevation, #rel-3d, #rel-3d-legend) { display: none; }" in _css()
    assert "const seat = d.loose ? `not in a rack · ${d.where}`" in js


def test_add_and_remove_write_through_the_editors_store():
    js = _read(JS / "reliquary.js")
    html = _html()
    tools = _block(html, '<span class="rel-tools">', '<button class="rel-close"')
    assert tools.index('id="rel-add"') < tools.index('id="rel-edit"'), "Add stands next to Rearrange"
    for control in ("rel-addbox", "rel-add-what", "rel-add-name", "rel-add-size", "rel-add-go", "rel-why"):
        assert f'id="{control}"' in html, control
    add = js[js.index("async function addVessel() {"):js.index("/** Take a vessel out of the rack")]
    assert "const top = freeTop(devices, rackU, size);" in add
    assert "store.apply([{ op: 'insert', section: 'rack', body }]," in add
    # two vessels of one key would be moved, and removed, as one
    assert "if ((A.DATA.rack || []).some((s) => slotKey(s) === key)) {" in add
    assert "setEditing(true);" in add, "added, it can be dragged at once"
    remove = js[js.index("async function removeVessel(d) {"):js.index("/** The ✕ a vessel wears")]
    # the index comes from the map on disk, never from the overlaid view on screen
    assert "(store.data[section] || []).map((slot, index) => ({ slot, index }))" in remove
    assert "if (!hit || hit.slot.name !== d.name) throw new Error(" in remove
    # `id` clears the saved layout's entry for the slot (the server keys its overlay on it)
    assert "{ op: 'delete', section, index: hit.index, ...(d.rear ? {} : { id: d.key }) }" in remove
    # the place stays on the map, on this location's shelf; the default
    # location (the theme's word) is never written into the map
    assert "ops.push({ op: 'upsert', section: 'nodes', id: node.id, body: { location: written } });" in remove
    assert "(store.data.racks || []).find((r) => r && r.id === rackId)?.location" in remove
    assert "here.location } }" not in remove
    # with moves waiting, the seat on screen is a draft: Add asks for Save or Reset first
    assert "if (Object.keys(readOvr()).length) { say('Save or Reset the moves you have made first, then add.'); return; }" in add
    assert "await Editor.load();" in js, "read fresh, so a write refuses a map that changed"
    # the first press of ✕ only asks
    assert "b.textContent = 'Take out?';" in js
    assert "#reliquary.editing .rel-remove { display: block; }" in _css()
    assert not re.search(r"\bfetch\(", js), "writes go through the editor's store and postJSON"


def test_a_viewer_who_may_not_write_is_told_so():
    js = _read(JS / "reliquary.js")
    assert "const mayWrite = () => canAdminWrite() && document.body.dataset.editable === '1';" in js
    paint = js[js.index("function paintWrites() {"):js.index("function openAddBox(on) {")]
    assert "add.disabled = !can;" in paint and "save.disabled = !can;" in paint
    assert "why.hidden = can || !editing;" in paint
    # no ✕ is drawn for a viewer who could not use it
    assert js.count("if (mayWrite()) ") == 2
    assert ".rel-tool:disabled { opacity: 0.45; cursor: not-allowed; }" in _css()


def test_add_is_not_offered_in_3d_or_where_there_is_no_rack():
    js = _read(JS / "reliquary.js")
    assert "for (const id of ['rel-edit', 'rel-add']) $(id)?.setAttribute('hidden', '');" in js
    assert "for (const id of ['rel-view', 'rel-edit', 'rel-add']) $(id)?.toggleAttribute('hidden', !here || (id !== 'rel-view' && view3d));" in js


# ── RESOURCES ────────────────────────────────────────────────────────────────

def test_resources_shows_everything_or_one_location():
    js = _read(JS / "tribute.js")
    assert "from './tribute-model.js';" in js
    assert "const hosts = hostsAt(every, loc ? loc.key : null);" in js
    assert "const t = totalsOf(hosts);" in js
    # one host and nothing else is the scene as it always was: no headings
    assert "const single = hosts.length === 1 && hosts[0].guests.length > 0;" in js
    # a host that says nothing is said, never drawn as empty or full
    assert "'capacity not charted'" in js and "no capacity charted" in js
    html = _html()
    panel = _block(html, '<div id="tribute"', '<div class="trb-list" id="trb-list"></div>')
    for piece in ('id="trb-where"', 'id="trb-places"', 'id="trb-note"', 'id="trb-vessel"', 'id="trb-vessel-cpu"'):
        assert piece in panel, piece


def test_the_demo_lab_has_three_locations_and_compute_outside_its_racks():
    """The public demo is where the feature is shown; skipped where the demo
    lab is not in the tree (the image carries Web/ alone)."""
    seed = WEB.parent / "demo-lab" / "seed" / "lab-data.demo.json"
    if not seed.is_file():
        pytest.skip("the demo lab's seed is not in this tree")
    data = json.loads(seed.read_text(encoding="utf-8"))
    assert [r["location"] for r in data["racks"]] == ["Home office", "Garage"]
    nodes = {n["id"]: n for n in data["nodes"]}
    assert nodes["camera-hub"]["location"] == "Living room"
    assert nodes["workstation"]["location"] == "Home office"
    host = nodes["hypervisor"]
    assert (host["ram_gb"], host["ram_reserve_gb"], host["cpu_cores"], host["cpu_threads"]) == (128, 8, 16, 32)
    # the old single figure still says the same, for a reader of the old key
    assert data["meta"]["tribute"] == {"total_gb": 128, "host_reserve_gb": 8, "cpu_cores": 16, "cpu_threads": 32}
