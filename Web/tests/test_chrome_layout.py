"""The shape of the top chrome — pinned, because two of these are traps.

Layout cannot be asserted from a test client: nothing here renders, measures or
paints. What CAN be asserted is the STRUCTURE the layout depends on, and two of
the rules below were each a bug in the writing of them.
"""

import os
import pathlib
import re
import sys

import pytest

WEB = pathlib.Path(__file__).resolve().parent.parent
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "standalone"}

INDEX = WEB / "templates" / "index.html"
CSS = WEB / "static" / "atlas.css"
UI = WEB / "static" / "js" / "ui.js"
DESK = WEB / "static" / "desk.css"
BOOT = WEB / "static" / "js" / "atlas.js"


def _read(p):
    return p.read_text(encoding="utf-8")


def _band(html):
    """The markup between <nav id="scenes-list"> and its </nav>."""
    m = re.search(r'<nav id="scenes-list".*?</nav>', html, re.S)
    assert m, "the scene band is gone"
    return m.group(0)


# ── The trap ─────────────────────────────────────────────────────────────────

def test_the_map_tool_cluster_is_not_inside_the_band():
    """`#atlas-tools` must be a SIBLING of `#scenes-list`, never a descendant.

    The obvious markup — nest the cluster under THE ATLAS — silently renders
    nothing, and it fails in a way no unit test would otherwise catch:
    `#scenes-list` carries `backdrop-filter`, which makes it the containing
    block for `position: fixed` descendants (so the cluster is positioned
    against the band rather than the viewport), and its labels carry `overflow-x:
    auto` for the one-row scroll, which would clip the cluster away entirely.
    Neither `fixed` nor `absolute` escapes that combination.

    This test exists because the first version of this feature did exactly
    that. It would look like "the hover does nothing" and send someone hunting
    through the JS.
    """
    html = _read(INDEX)
    assert 'id="atlas-tools"' in html, "the map-tool cluster is gone"
    assert 'id="atlas-tools"' not in _band(html), (
        "#atlas-tools is nested inside #scenes-list — backdrop-filter + "
        "overflow on the band will position it wrongly and then clip it away")


def test_the_gear_is_in_the_band_and_in_flow():
    """The OPPOSITE of the rule above, on purpose (2026-09-04: "make the
    setting button expand to the left now in the command bar"). `#menu-tools`
    used to be a fixed cluster hanging BELOW ☰, kept outside the nav for the
    same reason `#atlas-tools` is. It sits INSIDE the band now, immediately
    before ☰, and the trap does not bite because the trap is about POSITIONED
    descendants: an in-flow flex item is positioned against nothing and is
    clipped only if it overflows, which a 30px item in a 30px row does not.

    So the belt here is the other way round: it must be in the band, it must
    come right before ☰ (a widening item before a right-pinned ☰ can only grow
    LEFTWARD, which is the whole gesture), and its rule must not position it —
    the day someone adds `position: fixed` back, the first test's trap is live
    again and the cluster vanishes."""
    html = _read(INDEX)
    band = _band(html)
    assert 'id="menu-tools"' in band, "the gear cluster left the band"
    assert band.index('id="menu-tools"') < band.index('id="btn-menu"'), (
        "⚙ must come BEFORE ☰ in the band, or it cannot expand to ☰'s left")
    assert 'id="btn-menu-settings"' in band
    assert 'data-scene="settings"' in band, "⚙ is not the SETTINGS scene's button"
    css = _read(CSS)
    rule = re.search(r"#scenes-list \.menu-tools \{.*?\}", css, re.S)
    assert rule, "the in-band gear rule is gone"
    assert "position:" not in rule.group(0), (
        "the in-band cluster is positioned — inside #scenes-list that is the "
        "backdrop-filter/overflow trap the first test in this file describes")
    tail = re.search(r"^#scenes-list \.band-tail \{.*?\}", css, re.S | re.M)   # the base rule, not a scheme override
    assert tail, "the band's tail is gone"
    assert "margin-left: auto" in tail.group(0), (
        "the auto margin that pins the band's tail must sit on the tail, "
        "not on ☰ — two auto margins split the slack and park ⚙ mid-band")
    # the labels scroll in their own strip, so the gear and ☰ are never in it
    assert 'id="band-tail"' not in re.search(
        r'id="band-labels".*?</div>', band, re.S).group(0), (
        "the tail must sit beside the labels' strip, or a narrow window scrolls it away")
    assert band.index('id="band-tail"') < band.index('id="menu-tools"') < band.index('id="btn-menu"')
    menu = re.search(r"#scenes-list \.ci-menu \{.*?\}", css, re.S)
    assert menu and "margin-left: auto" not in menu.group(0)
    # PINNED since 2026-10-31: a hover-revealed control is no control on a touch
    # screen, and on a desktop it is one you forget exists. So the cluster is
    # out at every width, with no hover wiring left behind.
    # 68px since v1.52.0: two buttons, the colour scheme and the gear
    assert "width: 68px" in rule.group(0), "the gear is not pinned beside the menu"
    assert "opacity: 0" not in rule.group(0) and "width: 0" not in rule.group(0)
    assert "hoverReveal($('btn-menu')" not in _read(UI), "the pinned cluster is still wired to hover"
    assert 'id="btn-scheme"' in band and band.index('id="btn-scheme"') < band.index('id="btn-menu-settings"'), (
        "☀/☾ must sit in the cluster, before ⚙")


def test_the_band_still_has_the_properties_that_make_that_trap_real():
    """Belt for the test above: if the band ever loses backdrop-filter AND its
    overflow, the rule stops being load-bearing and this file should be re-read
    rather than silently guarding nothing."""
    css = _read(CSS)
    band = re.search(r"^#scenes-list \{.*?\}", css, re.S | re.M)   # the base rule, not a scheme override
    assert band, "#scenes-list rule is gone"
    assert "backdrop-filter" in band.group(0)
    labels = re.search(r"^\.band-labels \{.*?\}", css, re.S | re.M)
    assert labels and "overflow-x: auto" in labels.group(0)


# ── What lives where ─────────────────────────────────────────────────────────

def test_the_index_button_lives_in_the_band():
    """☰ moved out of the top-right corner and into the band's far end."""
    assert 'id="btn-menu"' in _band(_read(INDEX))


def test_the_column_is_zoom_plus_the_network_glyph():
    """The column is + − and, since 2026-09-02, the network glyph
    PERMANENTLY under −. Anything else coming back here means `#card.card-left`'s
    clearance is wrong — see MUST TRACK in atlas.css (282px for three)."""
    html = _read(INDEX)
    m = re.search(r'<div class="zoom-stack">.*?</div>', html, re.S)
    assert m, "the zoom stack is gone"
    ids = re.findall(r'id="(btn-[\w-]+)"', m.group(0))
    assert ids == ["btn-zoom-in", "btn-zoom-out", "btn-net"], ids
    css = _read(CSS)
    assert re.search(r"#card\.card-left \{[^}]*--card-clear: 282px", css), (
        "three buttons in the column ⇒ the left-hand card clears 282px")


@pytest.mark.parametrize("button", ["btn-sky", "btn-depths", "btn-decoys"])
def test_every_map_tool_is_in_the_cluster(button):
    html = _read(INDEX)
    cluster = re.search(r'<span class="atlas-tools".*?</span>\s*$', html, re.S | re.M)
    assert cluster, "the cluster's markup could not be found"
    assert f'id="{button}"' in cluster.group(0), button


def test_the_cluster_is_one_column_beside_the_zoom_column():
    """The owner's ask: top to bottom, sky, depths, tripwires, just right of
    the zoom column. Markup order IS the order on screen."""
    html = _read(INDEX)
    cluster = re.search(r'<span class="atlas-tools".*?</span>\s*$', html, re.S | re.M)
    assert cluster, "the cluster's markup could not be found"
    order = re.findall(r'id="(btn-[\w-]+)"', cluster.group(0))
    assert order == ["btn-sky", "btn-depths", "btn-decoys"], order

    css = _read(CSS)
    rule = re.search(r"^\.atlas-tools \{.*?\}", css, re.S | re.M)
    assert rule, ".atlas-tools rule is gone"
    assert "flex-direction: column" in rule.group(0)
    # zoom column: left 24 + 42 wide + its 10px gap
    assert "left: 76px" in rule.group(0)


def test_the_cluster_no_longer_carries_a_pin_button():
    """The pin moved onto THE ATLAS's own click (Ops, 2026-08-15), so the
    tools are four tools rather than four tools and a button about them."""
    html = _read(INDEX)
    assert 'id="btn-tools-pin"' not in html
    assert "ci-pin" not in html


# ── The crown's one number ───────────────────────────────────────────────────

def test_the_band_s_height_is_one_token():
    """`--crown-b` / `--crown-clear` exist, and are re-measured for the narrow
    band rather than inherited from the desktop one."""
    css = _read(CSS)
    root = re.search(r"^:root \{.*?^\}", css, re.S | re.M)
    assert root, ":root block is gone"
    assert "--crown-b:" in root.group(0)
    assert "--crown-clear:" in root.group(0)
    assert re.search(r"max-width: 720px\)\s*\{.*?--crown-b:", css, re.S), (
        "the ≤720px band is 2px shorter and must re-state --crown-b")


@pytest.mark.parametrize("rule", [".atlas-tools", ".zoom-stack", "#index-drawer"])
def test_nothing_under_the_crown_hand_bakes_its_own_top(rule):
    """The whole point of the token: the band's bottom edge was hand-baked into
    `.atlas-tools` (62px) and `.zoom-stack` (70px) and nothing else knew it,
    which is why every scene opened UNDERNEATH the band. Anything seated below
    the crown reads its top from the token or the next band change misses it.
    """
    css = _read(CSS)
    m = re.search(re.escape(rule) + r" \{.*?\}", css, re.S)
    assert m, f"{rule} is gone"
    top = re.search(r"top: ([^;]+);", m.group(0))
    assert top, f"{rule} has no top"
    assert "--crown-" in top.group(1), (
        f"{rule} hand-bakes its top ({top.group(1).strip()}) instead of "
        "deriving it from --crown-b / --crown-clear")


def test_the_path_no_longer_buries_the_scene_band():
    """THE PATH sat at z-1200, over the band's own z-988 — so the switcher was
    unclickable in the one scene you most want to leave from it. It joins the
    other scenes at 985."""
    css = _read(CSS)
    m = re.search(r"^#path \{.*?\}", css, re.S | re.M)
    assert m, "#path rule is gone"
    assert "z-index: 985;" in m.group(0), (
        "#path is not at z-985 — check it against `body.scene-open "
        "#scenes-list`'s 988, or the band is buried again")


# ── The behaviour that has no other home ─────────────────────────────────────

def test_the_atlas_button_goes_home():
    """THE ATLAS closes whatever is up and centres the whole map, every time. Its
    old second job, pinning the map tools, is what made them hide until hovered."""
    js = _read(UI)
    click = re.search(r"if \(btn\.dataset\.scene === 'atlas'\) \{.*?return;\n    \}", js, re.S)
    assert click, "THE ATLAS's click has lost its own branch"
    assert "closeAllScenes()" in click.group(0), "a scene would strand you with no way back"
    assert "A.home(true)" in click.group(0), "THE ATLAS no longer centres the map"


def test_settings_left_the_drawer():
    """2026-09-04: "make settings a scene and take it out of the index
    window". Three releases of special rules existed only because settings was
    a tabless third section of THE INDEX — ☰ must not open onto it (v1.33), the
    title must rename itself over it (v1.19.2), the search must hide (v1.19.0)
    — and each is deleted rather than kept. If `#settings-panel` ever comes
    back inside `#index-drawer`, every one of them is a bug again."""
    html = _read(INDEX)
    drawer = re.search(r'<aside id="index-drawer".*?</aside>', html, re.S)
    assert drawer, "the drawer is gone"
    assert 'id="settings-panel"' not in drawer.group(0), "settings is back in the drawer"
    assert 'id="settings-panel"' in html, "the settings body is gone altogether"
    js = _read(UI)
    assert "'SETTINGS' : 'THE INDEX'" not in js, "the drawer still retitles itself for settings"
    assert re.search(r"DRAWER_SECTIONS = \{ places: 'index-list', services: 'services-list' \}", js), (
        "the drawer's section map still knows a settings section")
    assert "selectDrawerTab('settings')" not in js
    # the gear no longer needs a drawer-open rule: it is not the drawer's door
    assert not re.search(r"body\.drawer-open \.menu-tools", _read(CSS))


def test_the_index_head_carries_no_controls_of_its_own():
    """⚙ and » both left the drawer head (Ops, 2026-08-15): the panel hangs
    off ☰, so ☰ closes it, and settings is the ⚙ hanging off ☰ beside it. A
    dangling listener for either would throw on load and take the rest of
    ui.js's top-level wiring with it — which is why this is a test and not a
    comment."""
    html = _read(INDEX)
    assert 'id="btn-drawer-close"' not in html
    assert 'id="btn-drawer-settings"' not in html
    js = _read(UI)
    assert "btn-drawer-close" not in js
    assert "btn-drawer-settings" not in js


def test_settings_is_a_scene_wired_like_every_other():
    """Every hop, as `test_accounts_scene.py` pins for ACCOUNTS — a break in
    any one is invisible until a human clicks ⚙ and nothing happens. The
    scene shell (scene.js) is what gives it the scrim, the ×, and the Escape
    route; `closeAllScenes` is the ONE list the Escape chain reads."""
    html, ui, css = _read(INDEX), _read(UI), _read(CSS)
    assert 'id="settings"' in html, "no overlay"
    assert 'id="set-close"' in html, "no ×"
    assert "makeScene({\n  id: 'settings', closeId: 'set-close'" in ui, "not built on the shell"
    assert "settings: A.openSettings" in ui, "not in the band's opener map"
    assert "A.closeSettings?.();" in ui, "not in closeAllScenes — Escape would not reach it"
    assert "querySelectorAll('[data-scene]')" in ui, (
        "the scene click handler / active mark still select `.scene` only, "
        "which the ⚙ (a `.chrome`) is not")
    # the shared scene chrome, not a private copy
    own = [l for l in css.splitlines() if l.strip().startswith("#settings {")]
    assert not own, f"declared its own overlay instead of joining the list: {own}"
    # "is #settings in the list", not "who is its neighbour". Pinning the
    # literal `#accounts, #settings {` meant every NEW scene added ahead of it
    # broke this test — THE TRUST did, on 2026-09-09, by joining the same rule
    # this assertion exists to require.
    assert re.search(r"#ledger,[^{]*#settings[^{]*\{", css), (
        "not in the shared overlay rule")
    assert "#settings.open" in css and "#settings.open .ldg-panel" in css
    assert "body.drawer-open #settings" in css, "would cover the Index instead of ceding room"
    assert re.search(r"#settings \.ldg-panel \{[^}]*width: min\(600px", css), "the narrower seat is gone"
    desk = _read(DESK)
    blocks = desk.split("@media (prefers-reduced-motion: reduce)")[1:]
    assert any("#settings" in b.split("}")[0] for b in blocks), "no reduced-motion block names #settings"
    # THE WATCHERS' clock must start on open and stop on close — it used to be
    # started by the drawer tab and stopped by the drawer closing
    assert re.search(r"onClose: \(\) => clearInterval\(sourcesTimer\)", ui)


def test_the_in_band_gear_is_a_lamp_not_a_beacon():
    """The same reason as the ☰ lamp test below, and one more: the cluster
    reveals by `overflow: hidden`, so a hover glow drawn outside the button's
    box is clipped to a square edge. No shadow, in either state."""
    css = _read(CSS)
    rule = re.search(r"#scenes-list \.ci-gear:hover,\n#scenes-list \.ci-gear\.active \{([^}]*)\}", css)
    assert rule, "the in-band gear has no no-glow rule"
    assert "box-shadow: none" in rule.group(1)


def test_settings_sections_default_closed_except_account():
    """Ops, 2026-08-16: settings greeted you with every section standing
    open. Untouched sections start CLOSED; ACCOUNT alone defaults open (who
    you are is the panel's first answer); a fold the user has set — either
    way — outranks the default, so this can never fight a stored choice."""
    js = _read(UI)
    assert "FOLD_DEFAULT_OPEN" in js
    assert re.search(r"FOLD_DEFAULT_OPEN = new Set\(\['account'\]\)", js)
    assert "Object.hasOwn(folds, key)" in js, (
        "the stored-fold check must be key PRESENCE — a stored 'open' is "
        "falsy and a truthiness test would re-close it")


def test_hovering_the_atlas_drops_the_map_tools():
    """The owner's ask. Touch has no hover, and these buttons are the door to the
    sky, so the column stays out there."""
    js, css = _read(UI), _read(CSS)
    assert "hoverReveal($('scene-home'), $('atlas-tools'))" in js
    assert re.search(r"@media \(hover: hover\) \{\s*"
                     r"\.atlas-tools:not\(\.peek\) \.chrome:not\(\.ci-decoys\.lit\) \{\s*opacity: 0;", css)
    assert "atlas-tools.pinned" not in css and "toggleToolsPin" not in js


def test_the_card_arrives_from_the_edge_it_lands_on():
    """The owner's bug: the first card of a visit started hidden on the right and
    `right` animated while it was hidden, so it crossed the screen as it arrived.
    The card starts on its default side, and only a card that is up may slide."""
    css = _read(CSS)
    hidden = re.search(r"^#card \{.*?^\}", css, re.S | re.M).group(0)
    assert not re.search(r"transition:[^;]*\bright\b", hidden)
    shown = re.search(r"^#card\.visible \{.*?^\}", css, re.S | re.M).group(0)
    assert re.search(r"transition:[^;]*\bright 380ms", shown)
    assert '<article id="card" class="card-left"' in _read(INDEX)
    # a place that splits frames its ring after the card opens: side first
    js = _read(WEB / "static" / "js" / "world.js")
    assert js.index("if (willSplit) A.setCardSide") < js.index("A.openCard(n);", js.index("function focusNode"))


def test_the_band_s_right_hand_buttons_sit_bare_on_it():
    """The owner's ask: no background of their own."""
    css = _read(CSS)
    tail = re.search(r"^#scenes-list \.band-tail \{.*?^\}", css, re.S | re.M).group(0)
    assert "background" not in tail.replace("backdrop", "")
    assert "#scenes-list .chrome { background: transparent; border-color: transparent; backdrop-filter: none; }" in css


def test_every_label_wears_the_buttons_hover_ring():
    """The owner's ask. The border is always there and transparent, so the ring
    fades in on the buttons' 250ms and the band does not shift when it lands."""
    css = _read(CSS)
    scene = re.search(r"^\.scene \{.*?^\}", css, re.S | re.M).group(0)
    assert "border: 1px solid transparent" in scene and "border-color 250ms" in scene
    assert ".scene:hover { color: var(--text); border-color: var(--gilt); }" in css


def test_the_band_says_when_there_is_more_and_cannot_overlap():
    """The owner's ask: at a narrow window the labels ran under the buttons, and
    nothing said how to reach the rest."""
    html, css, js = _read(INDEX), _read(CSS), _read(UI)
    band = _band(html)
    assert band.index('id="band-prev"') < band.index('id="band-labels"') < band.index('id="band-next"')
    assert "#scenes-list.over .band-arrow { display: block; }" in css
    assert "$('scenes-list').classList.toggle('over', room > 1)" in js
    assert "labels.addEventListener('wheel'" in js
    assert re.search(r"scrollIntoView\(\{ block: 'nearest', inline: 'nearest' \}\)", js)


def test_every_section_sits_on_the_dark_dim_in_the_light_scheme():
    """The owner's ask: Topology was the only one, and every section should match."""
    css = _read(CSS)
    dim = re.search(r'#accounts, #trust, #settings\) \{\s*background: rgba\(13, 11, 7, 0\.82\)', css)
    assert dim, "the light scheme's sections are not on Topology's dim"
    assert "background: rgba(13,11,7,0.82); backdrop-filter: blur(6px);" in css


def test_the_addresses_grid_reads_in_the_light_scheme():
    """The owner's ask: a charted cell was a pale ring on a pale grid."""
    css = _read(CSS)
    assert ':root[data-scheme="light"] .ldg-cell.lit {' in css
    # the navy is the light scheme's --text (#0f172a), not a literal of its own
    assert "color-mix(in srgb, var(--c-hue) 45%, var(--text))" in css


def test_a_journey_lands_on_its_section():
    """The section fits the window below the band, and the camera frames it there,
    or a tall chart hides its own heading under the band."""
    css = _read(CSS)
    assert "calc(100vh - 330px)" in css
    assert css.count("width: min(1560px, calc(100vw - 168px))") == 2, "the zoom column would sit on the charts"
    assert css.index(".scene {") < css.index("@media (max-width: 1100px) {"), (
        "the tightening must follow the base rule, or the base rule wins")
    world = _read(WEB / "static" / "js" / "world.js")
    assert "A.cam.y = A.landOn('abyss');" in world and "A.cam.y = A.landOn('chronicle');" in world


def test_sky_and_depths_undo_the_camera_s_fit():
    """The owner's ask: inside the stage they shrank with the map, half size at
    1024px. The floor and the ceiling have to measure the same scaled height."""
    css = _read(CSS)
    assert css.count("scale(calc(1 / var(--fit, 1)))") == 2
    js = _read(WEB / "static" / "js" / "camera.js")
    assert "abyss.offsetHeight + CFG.VOID_FOOT_PX) / fit" in js
    assert "skyNorth = Math.max(CFG.SKY_NORTH" in js


def test_the_drift_note_fades_and_returns_to_the_middle_of_the_map():
    """The owner's ask: fully clear by six seconds, back on returning to the middle.
    `paintDrift` runs on every poll, so only an arrival may wake it, or it would
    never stay gone."""
    signals = _read(WEB / "static" / "js" / "signals.js")
    paint = re.search(r"function paintDrift.*?^}", signals, re.S | re.M).group(0)
    assert "if (arriving) wakeDrift();" in paint
    assert "DRIFT_REST_MS: 5000" in _read(WEB / "static" / "js" / "config.js")
    css = _read(CSS)
    assert "transition: border-radius 200ms, opacity 1s ease;" in css
    assert "#drift-note.resting { opacity: 0; pointer-events: none; }" in css
    world = _read(WEB / "static" / "js" / "world.js")
    shades = re.search(r"function updateShades.*?^}", world, re.S | re.M).group(0)
    assert "if (onCentre) A.wakeDrift?.();" in shades


def test_a_lit_layer_stays_out_of_the_closed_column():
    """Hidden per button and never by the column, so the tripwires can say they
    are on. Sky and Depths are places, not layers, and go with the rest."""
    rule = re.search(r"^\.atlas-tools \{.*?\}", _read(CSS), re.S | re.M).group(0)
    assert "opacity" not in rule


def test_the_sky_lights_as_the_depths_do_in_reverse():
    """The owner's ask: scrolling into the sky lights its button, from the camera
    so S and the button do too, in the theme's colours: biolume in the Depths,
    dark ink with the accent in the sky."""
    world = _read(WEB / "static" / "js" / "world.js")
    shades = re.search(r"function updateShades.*?^}", world, re.S | re.M).group(0)
    assert "$('btn-sky').classList.toggle('lit', inSky)" in shades
    assert "CFG.SKY_RELEASE" in shades and "CFG.SKY_ENGAGE" in shades
    css = _read(CSS)
    depths = re.search(r":root \.chrome\.ci-depths\.lit \{.*?\}", css, re.S).group(0)
    sky = re.search(r":root \.chrome\.ci-sky\.lit \{.*?\}", css, re.S).group(0)
    assert "background: var(--depth);" in depths and "color: var(--card-ink);" in depths
    assert "background: var(--card-ink);" in sky and "color: var(--gilt-bright);" in sky
    assert ':root[data-scheme="light"] .chrome.ci-sky.lit { background: var(--gilt); color: var(--on-gilt); }' in css
    assert "#btn-depths.lit" not in css, "an id rule would outrank the fill"
    # the light scheme's `.chrome.lit` carries the same weight: order decides
    assert css.index(':root[data-scheme="light"] .chrome.lit') < css.index(":root .chrome.ci-sky.lit")


def test_the_depths_do_not_announce_themselves():
    """The owner's ask: nothing pops up on the way down or back up."""
    js = _read(WEB / "static" / "js" / "world.js")
    body = re.search(r"function toggleDepths.*?^}", js, re.S | re.M)
    assert body and "showToast" not in body.group(0)


def test_the_world_ends_at_the_abyss_s_foot():
    """A fixed depth left a black spacer under a short section. The floor is
    measured, so it cannot drift from the section again."""
    js = _read(WEB / "static" / "js" / "camera.js")
    assert "sectionWatch.observe($('abyss'))" in js
    assert "voidDepth: CFG.VOID_DEPTH" not in js


def test_the_depths_zone_draws_no_name_on_the_black():
    js = _read(WEB / "static" / "js" / "world.js")
    assert "z.hide_label || z.id === 'depths'" in js
    assert "zone-label.depths-kin" not in _read(CSS)


def test_the_menu_lamp_cannot_overflow_the_band_it_sits_in():
    """`.chrome.lit` grows 16% and paints a 22px glow — fine for a button
    floating over the map, wrong for the ☰ INSIDE the band, which sets
    `overflow-x: auto` (and CSS computes the other axis to `auto` with it). The
    growth clipped at the band's edges and the glow, which lives entirely
    outside the button's box, was clipped away to a bright square edge. The
    in-band lamp must not scale, pulse or cast."""
    css = _read(CSS)
    rule = re.search(r"#scenes-list \.ci-menu\.lit \{.*?\}", css, re.S)
    assert rule, "the in-band lamp has no rule of its own — .chrome.lit will win"
    body = rule.group(0)
    assert "transform: none" in body
    assert "animation: none" in body
    assert "box-shadow: none" in body


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
