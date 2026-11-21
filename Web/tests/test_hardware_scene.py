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
        assert f"markPlace('{name}', place" in js, scene
        # closed, a scene forgets its location: pressed afresh it is everything
        assert f"markPlace('{name}', '')" in js, scene
    path = _read(JS / "path.js")
    assert "if (e.detail?.scene === 'path') setScenePlace(e.detail.place);" in path
    assert "markPlace('path', scenePlace);" in path and "markPlace('path', '');" in path
    # the press that shows everything, and the close, both let the rack go with the location
    trb = _read(JS / "tribute.js")
    shown = trb[trb.index("function setPlace(key) {"):trb.index("function setRack(")]
    assert "rack = null;" in shown
    assert "onClose: () => { place = ''; rack = null; by = 'guests'; built = false; markPlace('tribute', ''); }" in trb
    drawn = path[path.index("function setScenePlace(key) {"):path.index("function setSceneRack(")]
    assert "sceneRack = null;" in drawn
    closed = path[path.index("function close() {"):path.index("A.openPath = open;")]
    assert "scenePlace = '';" in closed and "sceneRack = null;" in closed


def test_the_bands_menus_of_locations():
    html = _html()
    for menu in ("hardware-menu", "resources-menu", "topology-menu"):
        assert f'<div class="view-menu band-menu" id="{menu}" role="menu"' in html, menu
    # siblings of the band, after the drawers; never in the stretch read as the views' menu
    assert html.index('<aside id="map-drawer"') < html.index('id="hardware-menu"')
    assert html.index("</nav>") < html.index('id="hardware-menu"')
    js = _read(JS / "band-menus.js")
    assert "import { hoverReveal } from './ui.js';" in js
    assert "export { hoverReveal };" in _read(JS / "ui.js")
    # the fade and the roll-up are the Index's alone (owner, 2026-11-20)
    assert "idleRollup(" not in js and "ROLLUP_MS" not in js
    assert "bandMenu('rack', 'hardware-menu');" in js and "bandMenu('tribute', 'resources-menu');" in js
    assert "bandMenu('path', 'topology-menu');" in js
    # one location is nothing to choose between: no menu at all (owner, 2026-11-20),
    # and the count is of what the scene has something to draw at
    assert "const offer = A.DATA ? offerFor(scene, at) : [];" in js
    assert "if (offer.length < 2) { menu.innerHTML = ''; return; }" in js
    # locations and nothing else (owner, 2026-11-20: "don't put the machines in the drop
    # down, just the location"): v1.96.0's rack rows are gone, and so is their mark
    assert "data-rack" not in js and "band-rack" not in js
    assert "askPlace(scene, item.dataset.place);" in js
    assert "dataset.rack" not in _read(JS / "scene-places.js").split("export function drawRackPicker")[0]
    assert "refuse: (how) => A.PHONE || !menu.childElementCount || (how === 'focus' && hush)," in js
    # focus handed back to the button (Escape, a keyboard pick) must not open it again
    assert "const handBack = () => { hush = true; reveal.close(); button.focus(); };" in js
    assert js.count("handBack();") == 2
    # an item names a place, never a scene: the band binds every [data-scene]
    assert 'role="menuitem" data-place=' in js and "data-scene=" not in js.split("function bandMenu")[1].replace(
        '.scene[data-scene="${scene}"]', "")
    assert "if (!button.classList.contains('active')) button.click();" in js
    assert not re.search(r"^\s*A\.\w+ = ", js, re.M), "no new name on the shared context"
    atlas = _read(JS / "atlas.js")
    assert atlas.index("import './tribute.js';") < atlas.index("import './band-menus.js';")
    css = _css()
    block = css[css.index(':root[data-scheme-pick="light"] :is(#scenes-list'):]
    assert block[:block.index("{")].count(".band-menu") == 4, "one for each clause of the bar's condition"
    assert ".band-menu > button { text-transform: uppercase; }" in css
    assert ".band-rack" not in css


def test_each_scene_has_the_picker_a_touch_screen_needs():
    html = _html()
    assert 'id="rel-places" role="group" aria-label="Choose a location" hidden' in html
    assert 'id="trb-places" role="group" aria-label="Choose a location" hidden' in html
    places = _read(JS / "scene-places.js")
    assert "const offer = offerFor(scene, key);" in places
    # one location and everything on show: nothing to pick; a location on show: ALL is the way back
    assert "el.hidden = offer.length < 2 && !key;" in places
    assert "drawPlacePicker($('rel-places'), 'rack', place, (key) => setPlace(key));" in _read(JS / "reliquary.js")
    assert "drawPlacePicker(placesEl, 'tribute', place, (key) => setPlace(key));" in _read(JS / "tribute.js")


def test_a_scene_offers_only_what_it_has_something_to_draw_at():
    """Owner, 2026-11-20: "if there isn't any equipment/hardware at a location
    that location shouldn't be displayed in the drop down". Each scene answers
    for itself, and the menu and the picker read the one list."""
    places = _read(JS / "scene-places.js")
    assert "const holds = scene === 'tribute' ? holdsHosts(hostsNow())" in places
    assert ": scene === 'path' ? holdsPlaces(where) : holdsHardware(where);" in places
    assert "return offered(where, holds, keep);" in places
    model = _read(JS / "locations-model.js")
    for name in ("export function offered(", "export const holdsHardware", "export function holdsPlaces("):
        assert name in model, name
    # what is on show stays offered, so the thing that emptied it does not move the scene
    assert ".filter((l) => (keep && l.key === keep) || holds(l, null))" in model
    assert "export const holdsHosts" in _read(JS / "tribute-model.js")
    # HARDWARE's own rack picker still lists an empty rack: Add is how it gets its first thing
    rel = _read(JS / "reliquary.js")
    assert "racks = racksAt(where, loc);" in rel and "nav.hidden = racks.length < 2;" in rel


def test_one_rack_can_be_shown_alone_in_resources_and_topology():
    """Owner, 2026-11-20: "you should be able to see the resources of a
    specific device, (Rack a or rack B) that is associated with a specific
    location". Reachable inside the scene, since a phone has no hover menu."""
    html = _html()
    assert 'id="trb-racks" role="group" aria-label="Choose a rack" hidden' in html
    assert 'id="pth-racks" role="group" aria-label="Choose a rack" hidden' in html
    places = _read(JS / "scene-places.js")
    assert "export function drawRackPicker(el, scene, key, rackId, onPick, allLabel = 'All') {" in places
    # two racks are always a choice; one only where the location is more than it, and never on a map of one location
    assert "if (at.racks.length >= 2) return at.racks;" in places
    assert "return at.racks.length === 1 && where.list.length > 1 && more ? at.racks : [];" in places
    trb = _read(JS / "tribute.js")
    assert "const hosts = shownRack ? hostsIn(every, rack) : hostsAt(every, loc ? loc.key : null);" in trb
    assert "drawRackPicker(racksEl, 'tribute', place, rack, setRack," in trb
    assert "if (groups.length < 2) groups.splice(0, groups.length, { hosts, head: null });" in trb
    # a map of one location is divided by its racks without one being chosen
    assert "if (offer.length === 1) byRack(offer[0].loc); else groups.push({ hosts, head: null });" in trb
    path = _read(JS / "path.js")
    assert "drawRackPicker($('pth-racks'), 'path', scenePlace, sceneRack, setSceneRack," in path
    assert "const away = awayFrom(where, loc, nodes, rack);" in path
    # '' is a real rack id (the one rack of a map that charts none): asked for by null, never by truth
    model = _read(JS / "locations-model.js")
    assert "if (id === null || id === undefined) return null;" in model
    # HARDWARE switches racks with its own picker, as it always did
    rel = _read(JS / "reliquary.js")
    assert "if (b.dataset.rack !== rackId) pickRack(b.dataset.rack);" in rel


def test_resources_offers_a_location_only_where_a_machine_runs_guests():
    """Owner, 2026-11-20, asked whether RESOURCES should hide a location whose
    machines run no guests: "hide them, for example living room should be
    hidden". Hidden as a choice; its machines are still listed under
    everything, so the count of machines above the list stays true."""
    model = _read(JS / "tribute-model.js")
    assert "hosts.some((h) => h.guests.length > 0" in model
    trb = _read(JS / "tribute.js")
    assert "const idle = hosts.filter((h) => h.location !== null && !chosen.has(h.location));" in trb
    assert "Elsewhere, running no guests" in trb
    # a plain heading: a place that is not a choice is never a button
    assert '<span class="trb-place">Elsewhere, running no guests</span>' in trb


def test_one_menu_at_a_time():
    """Owner, 2026-11-20: "there's still a bit of delay when switching between
    mouse overs in the nav bar and the new menu that pops up is below the old
    one". The menu that opens cuts every other one off at once."""
    ui = _read(JS / "ui.js")
    reveal = ui[ui.index("const reveals = new Set();"):ui.index("function mapEditor(")]
    assert "for (const other of reveals) if (other !== cut && other()) took = true;" in reveal
    # and it stands there at once itself: the band is never bare between the two
    assert "if (took) atOnce(show); else show();" in reveal
    # after `refuse`: a button with no menu to show (one location) cuts nothing
    assert reveal.index("if (refuse(how)) return;") < reveal.index("for (const other of reveals)")
    # no wait and no fading out under the newcomer
    cut = reveal[reveal.index("const cut = () => {"):reveal.index("reveals.add(cut);")]
    assert "atOnce(() => { cluster.classList.remove('peek'); shut(); onChange(); });" in cut
    once = reveal[reveal.index("const atOnce = (change) => {"):reveal.index("const cut = () => {")]
    assert "cluster.style.transition = 'none';" in once and "cluster.style.transition = '';" in once


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
    assert "hostsAt(every, loc ? loc.key : null);" in js
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


# ── TOPOLOGY by location, and its seat in the band ───────────────────────────

def test_topology_draws_every_place_or_one_location():
    """Owner, 2026-11-20: "add a dropdown like hardware and resources for
    topology, if there are more than one site/location"."""
    js = _read(JS / "path.js")
    assert "from './locations-model.js';" in js and "from './scene-places.js';" in js
    # folded places are drawn (a diagram has the room); really-off-map ones are not
    assert "const nodes = placesFor(where, loc, A.DATA.nodes, A.DATA.routes, rack).filter((n) => !n.off_map || n._folded);" in js
    assert "const away = awayFrom(where, loc, nodes, rack);" in js and "' pth-away'" in js
    assert "drawPlacePicker($('pth-places'), 'path', scenePlace, (key) => setScenePlace(key));" in js
    # a service's reach, asked for from its card, is shown on the whole map
    opened = js[js.index("function open(focusId, reachIds, serviceLabel) {"):js.index("function close() {")]
    assert "if (focusId) { scenePlace = ''; sceneRack = null; }" in opened
    assert opened.index("if (focusId) { scenePlace = ''; sceneRack = null; }") < opened.index("build();")
    html = _html()
    panel = _block(html, '<div id="path"', '<div class="pth-legend" id="pth-legend"></div>')
    assert 'id="pth-where"' in panel
    assert 'id="pth-places" role="group" aria-label="Choose a location" hidden' in panel


def test_topology_stands_before_addresses_in_the_band():
    html = _html()
    band = html[html.index('<nav id="scenes-list"'):html.index("</nav>", html.index('<nav id="scenes-list"'))]
    order = re.findall(r'<button class="scene[^"]*" data-scene="(\w+)"', band)
    assert order[:5] == ["atlas", "rack", "tribute", "path", "ledger"], order



# ── 2026-11-21: Add says what the device is and where in the rack it goes ────
# Owner: "in the hardware when you click add, it should also have a drop down
# for device ... and a location front, back inside."

def test_add_asks_for_the_device_and_the_seat():
    html = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
    box = html[html.index('id="rel-addbox"'):html.index('id="rel-add-go"')]
    assert box.index('id="rel-add-what"') < box.index('id="rel-add-type"') < box.index('id="rel-add-seat"') < box.index('id="rel-add-size"')
    js = (WEB / "static" / "js" / "reliquary.js").read_text(encoding="utf-8")
    assert "import { DEVICE_GROUPS, SEATS, addBody, addName, typeById } from './hardware-catalog.js';" in js
    # behind the rack and inside it there is no U to say
    assert "$('rel-add-size').closest('.rel-add-field').hidden = $('rel-add-seat').value !== 'front';" in js
    assert "if (seat !== 'front') { addFitting({ seat, name, node, type, here, say }); return; }" in js
    # one strip, two halves, each item keeping its place in the map's list
    assert "half('rear of rack', false) + half('inside the rack', true)" in js
    import schema
    assert schema.HIDING["rack_rear"]["side"] == "safe"
    assert schema.REAR_SIDES == ["rear", "inside"]



# ── 2026-11-21: RESOURCES lists the available compute by location or by hardware ──
# Owner: "in resources, can we add buttons for like location and hardware so we
# can see the available compute by rack or site".

def test_resources_lists_what_is_free_by_site_and_by_rack():
    html = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
    pickers = html[html.index('class="trb-pickers"'):html.index('<div class="trb-cap">MEMORY</div>')]
    # always drawn: no `hidden`, and its three choices in this order
    switch = pickers[pickers.index('id="trb-by"'):]
    assert "hidden" not in switch.split(">", 1)[0]
    assert re.findall(r'data-by="(\w+)"', switch) == ["guests", "site", "rack"]
    js = (WEB / "static" / "js" / "tribute.js").read_text(encoding="utf-8")
    assert "if (by !== 'guests') { drawAvailable(where, every, loc); return; }" in js
    # by hardware keeps to the location on show; by location is every one
    assert "availableBy(every, where, by, by === 'rack' && loc ? loc.key : '')" in js
    # closed, the scene is the guests again
    assert "onClose: () => { place = ''; rack = null; by = 'guests'; built = false; markPlace('tribute', ''); }" in js
    model = (WEB / "static" / "js" / "tribute-model.js").read_text(encoding="utf-8")
    assert "export function availableOf(hosts)" in model and "export function availableBy(hosts, where, by, locKey = '')" in model
