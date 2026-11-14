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

def test_the_map_tools_are_not_inside_the_band():
    """The map's tools live in `#view-menu`, which must be a SIBLING of
    `#scenes-list`, never a descendant.

    The obvious markup — nest them under THE ATLAS — silently renders nothing:
    `#scenes-list` carries `backdrop-filter`, which makes it the containing
    block for `position: fixed` descendants (so they are positioned against the
    band rather than the viewport), and its labels carry `overflow-x: auto` for
    the one-row scroll, which would clip them away entirely. The first version
    of the hover did exactly that.
    """
    html = _read(INDEX)
    for button in ("btn-sky", "btn-depths", "btn-decoys"):
        assert f'id="{button}"' in html, f"{button} is gone"
        assert f'id="{button}"' not in _band(html), (
            f"#{button} is nested inside #scenes-list — backdrop-filter + "
            "overflow on the band will position it wrongly and then clip it away")
    assert 'id="atlas-tools"' not in html, "the standing column came back"


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


def _view_menu(html):
    start = html.index('<div class="view-menu" id="view-menu"')
    end = html.index("<!-- The one drawer: THE INDEX")
    return html[start:end]


@pytest.mark.parametrize("button", ["btn-sky", "btn-depths", "btn-decoys"])
def test_every_map_tool_is_in_the_views_menu(button):
    """The owner (2026-11-13): the three map tools drop with the views menu."""
    tools = re.search(r'<div class="view-tools".*?</div>', _view_menu(_read(INDEX)), re.S)
    assert tools, "the menu's tools group is gone"
    assert f'id="{button}"' in tools.group(0), button


def test_the_map_tools_are_the_menu_s_lower_part_in_order():
    """Top to bottom, sky, depths, tripwires, after the views; each a menu item
    the arrows reach, with a lamp and a name from the theme."""
    tools = re.search(r'<div class="view-tools".*?</div>', _view_menu(_read(INDEX)), re.S).group(0)
    assert re.findall(r'id="(btn-[\w-]+)"', tools) == ["btn-sky", "btn-depths", "btn-decoys"]
    assert tools.count('role="menuitem"') == 3 and tools.count('class="vt-lamp"') == 3
    for word in ("theme.text.sky|upper", "theme.text.depths|upper", "theme.text.stones_watch|upper"):
        assert word in tools, word
    js = _read(UI)
    assert "querySelectorAll('[role=\"menuitem\"]')" in js, "the arrows must reach the tools too"


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


@pytest.mark.parametrize("rule", [".zoom-stack", "#index-drawer"])
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


def test_the_atlas_button_is_always_home_and_never_puts_the_map_away():
    """2026-11-13 (stage 2 of the views): a click on ATLAS is always home. It
    closes whatever is up, leaves any view for the map, and centres. v1.67.0
    and v1.68.0's second press that put the map away is retired: one button,
    one meaning, and the views are one step off it, in the menu. A phone has
    no map, so ATLAS there is the top of its column (and hidden)."""
    js = _read(UI)
    click = re.search(r"if \(btn\.dataset\.scene === 'atlas'\) \{.*?return;\n    \}", js, re.S).group(0)
    for gone in ("sceneWasUp", "wasHome", "A.atHome", "setDeck", "A.DECK"):
        assert gone not in click, f"ATLAS still carries the put-away branch ({gone})"
    assert "A.setView('map', { remember: true })" in click, "ATLAS does not leave a view for the map"
    assert "if (A.PHONE) { A.deckTop?.(); return; }" in click
    assert "A.leaveToMap()" in click, "inside a region, home is the whole map"
    assert click.index("A.setView('map'") < click.index("A.home(true)")
    assert 'body.phone .scene[data-scene="atlas"] { display: none; }' in _read(CSS)


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


def test_the_map_tools_show_only_while_the_map_is_the_view():
    """The owner (2026-11-13): in the views menu, but only when MAP is selected.
    A view (`body.deck`) or a scene over the map has nothing for them to act on."""
    css = _read(CSS)
    assert "body:is(.deck, .scene-open) .view-tools { display: none; }" in css
    assert ".atlas-tools" not in re.sub(r"/\*.*?\*/", "", css, flags=re.S), "the standing column's rules came back"


# ── THE VIEWS (2026-11-13) ───────────────────────────────────────────────────

def test_the_views_menu_is_a_sibling_of_the_band():
    """The same trap as `#atlas-tools`: inside the band, its backdrop-filter and
    overflow would position the menu against the band and clip it away."""
    html = _read(INDEX)
    assert 'id="view-menu"' in html, "the views' menu is gone"
    assert 'id="view-menu"' not in _band(html), (
        "#view-menu is nested inside #scenes-list: the band's backdrop-filter + "
        "overflow will position it wrongly and then clip it away")
    menu = re.search(r'<div class="view-menu" id="view-menu" role="menu"[^>]*>(.*?)</div>', html, re.S)
    assert menu, "the menu's markup could not be found"
    assert re.findall(r'data-view="(\w+)"', menu.group(1)) == ["map", "overview", "nodes", "alerts"]
    assert menu.group(1).count('role="menuitem"') == 7, "four views and three map tools"
    css = _read(CSS)
    rule = re.search(r"^\.view-menu \{.*?^\}", css, re.S | re.M).group(0)
    assert "position: fixed" in rule and "var(--bar-glass-firm)" in rule
    assert "z-index: 989" in rule, "the menu must stand over a scene's lifted band (988)"


def test_the_views_menu_is_in_the_bar_block():
    """It wears the bar's tokens, so it follows Part A like the band."""
    css = _read(CSS)
    head = css[css.index(':root[data-scheme-pick="light"] :is('):]
    head = head[:head.index("{")]
    for name in ("#view-menu", ".view-strip", ".scene-more"):
        assert head.count(name) == 4, f"{name} is not in all four bar clauses"


def test_the_atlas_is_a_split_button_with_an_opener():
    """A tap on ATLAS is always home, so a touch screen and a keyboard need
    their own way to the views: ▾ beside ATLAS, inside `.scene-home`."""
    band = _band(_read(INDEX))
    home = re.search(r'<span class="scene-home" id="scene-home">.*?</span>', band, re.S).group(0)
    more = re.search(r'<button class="scene-more" id="view-more"[^>]*>', home, re.S)
    assert more, "ATLAS has no ▾ opener"
    for attr in ('aria-haspopup="menu"', 'aria-expanded="false"', 'aria-controls="view-menu"'):
        assert attr in more.group(0), attr
    assert home.index('data-scene="atlas"') < home.index('id="view-more"')
    css = _read(CSS)
    assert re.search(r"@media \(hover: none\) \{ \.scene-more \{ opacity: 1; \} \}", css), \
        "a screen that cannot hover must always see ▾"
    rule = re.search(r"^\.scene-more \{.*?^\}", css, re.S | re.M).group(0)
    assert "width: 18px" in rule and "opacity: 0" in rule and "display: none" not in rule, (
        "▾ keeps its width whether it shows or not, so the label strip never changes size")


def test_the_menu_opens_by_hover_and_by_keyboard():
    js = _read(UI)
    assert "hoverReveal(sceneHome, viewMenu," in js
    for key in ("'ArrowDown'", "'ArrowUp'", "'Escape'"):
        assert key in js
    assert "A.setView(item.dataset.view, { remember: true })" in js
    assert "viewMore.setAttribute('aria-expanded'" in js


def test_the_camera_takes_no_keys_while_the_map_is_away():
    """A view hides the map, and the hidden map must not move under it: the
    window keydown steps aside under `body.deck`, except for Escape."""
    js = _read(WEB / "static" / "js" / "camera.js")
    keys = js[js.index("addEventListener('keydown'"):]
    keys = keys[:keys.index("\n});")]
    assert "document.body.classList.contains('deck')" in keys
    guard = keys.index("document.body.classList.contains('deck')")
    assert guard < keys.index("case 'ArrowLeft'"), "the guard must come before the camera's keys"
    assert "if (away && e.key !== 'Escape'" in keys


def test_every_view_has_a_main_and_one_shows_at_a_time():
    html = _read(INDEX)
    mains = re.findall(r'<main class="atlas-view" id="([\w-]+)" data-view="(\w+)" hidden', html)
    assert ("view-overview", "overview") in mains and ("view-nodes", "nodes") in mains, mains
    assert "chart-deck" not in html and 'data-view="charts"' not in html, "CHARTS is OVERVIEW's lower half now"
    views = _read(WEB / "static" / "js" / "views.js")
    assert "el.hidden = el.dataset.view !== next" in views
    assert "new CustomEvent('atlas:view'" in views
    assert "document.body.classList.toggle('deck', A.DECK)" in views


def test_the_phone_names_the_views_in_a_strip():
    """No ATLAS and no map on a phone: OVERVIEW · NODES · ALERTS at the top of
    the column (ALERTS for an admin only)."""
    html = _read(INDEX)
    strip = re.search(r'<nav class="view-strip" id="view-strip"[^>]*>(.*?)</nav>', html, re.S)
    assert strip, "the phone's strip is gone"
    assert re.findall(r'data-view="(\w+)"', strip.group(1)) == ["overview", "nodes", "alerts"]
    css = _read(CSS)
    assert "body.phone .view-strip { display: flex; }" in css
    assert "body.phone :is(.scene-more, .view-menu) { display: none; }" in css


def test_alerts_is_a_view_and_an_admin_s_only():
    """ALERTS (2026-11-13, stage 4): a view like the others, with its own main;
    its menu item and strip entry are marked admin-only and start hidden, and
    views.js draws them for an admin (NODES' bulk gate) and removes them for
    anyone else, so no door is offered that the routes would refuse."""
    html = _read(INDEX)
    assert '<main class="atlas-view" id="view-alerts" data-view="alerts" hidden' in html
    for where in (r'<div class="view-menu" id="view-menu"[^>]*>(.*?)</div>',
                  r'<nav class="view-strip" id="view-strip"[^>]*>(.*?)</nav>'):
        block = re.search(where, html, re.S).group(1)
        item = re.search(r'<button[^>]*data-view="alerts"[^>]*>', block).group(0)
        assert "data-admin" in item and " hidden" in item, item
        for other in re.findall(r'<button[^>]*data-view="(?:map|overview|nodes)"[^>]*>', block):
            assert "data-admin" not in other and "hidden" not in other, other
    assert "{{ theme.text.view_alerts }}" in html
    views = _read(WEB / "static" / "js" / "views.js")
    assert "const ADMIN = canAdminWrite() && document.body.dataset.editable === '1';" in views
    assert "if (ADMIN) el.removeAttribute('hidden'); else el.remove();" in views
    assert "allowedView(named, A.PHONE, ADMIN)" in views, "a press must not open ALERTS for anyone else"
    assert "import './alerts.js';" in _read(WEB / "static" / "js" / "atlas.js")
    css = _read(CSS)
    light = css[css.index(':root[data-scheme="light"] :is('):]
    assert "#view-alerts" in light[:light.index("{")], "the ALERTS sheet must follow the light scheme"


def test_a_place_link_waits_for_the_opening_shot():
    """`?place=<id>` (an alert's link) opens the map on the place's card, after
    the veil's glide home, the way `#region=` waits (regions.js)."""
    views = _read(WEB / "static" / "js" / "views.js")
    assert "parsePlace(query.get('place'))" in views
    at = views.index("function openPlace()")
    body = views[at:views.index("\n}", at)]
    assert "A.DATA?.nodes?.find((n) => n.id === place)" in body and "if (!node) return;" in body
    assert "A.focusNode?.(place)" in body
    assert "document.body.classList.contains('pre')" in views[at:]


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


def test_a_label_glows_on_hover_and_only_the_selected_one_is_outlined():
    """The owner's ask, 2026-11-01. The border is always there and transparent,
    so the outline fades in and the band does not shift when it lands."""
    css = _read(CSS)
    scene = re.search(r"^\.scene \{.*?^\}", css, re.S | re.M).group(0)
    assert "border: 1px solid transparent" in scene and "border-color 250ms" in scene
    hover = re.search(r"^\.scene:hover[^{]*\{(.*?)\}", css, re.S | re.M).group(1)
    assert "text-shadow" in hover and "border-color" not in hover
    assert "border-color: var(--gilt)" in re.search(r"^\.scene\.active \{.*$", css, re.M).group(0)


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


def test_a_lit_tool_lights_its_lamp_in_the_menu():
    """A tool that is on says so in the menu: its lamp fills, in the same tokens
    the round buttons used (the Sky and the Depths in reverse)."""
    css = _read(CSS)
    assert ".view-tool.lit .vt-lamp {" in css
    assert re.search(r"\.view-tool\.ci-sky\.lit \.vt-lamp \{[^}]*var\(--sky-lit-fill\)", css)
    assert re.search(r"\.view-tool\.ci-depths\.lit \.vt-lamp \{[^}]*var\(--depths-lit-fill\)", css)


def test_the_menu_and_the_index_fade_and_roll_up_when_the_mouse_leaves():
    """The owner (2026-11-13): partly transparent when not hovered, rolled up
    after a few seconds. Only a mouse makes them idle, and typing inside one
    keeps it up."""
    js, css = _read(UI), _read(CSS)
    assert re.search(r"const ROLLUP_MS = [3-6]000;", js), "roll up after 3 to 6 seconds"
    assert ".view-menu:is(.peek, .open).idle, #index-drawer.open.idle { opacity: 0.6; }" in css
    assert "const mouse = (e) => e.pointerType === 'mouse';" in js
    assert "idleRollup(drawer, [drawer, $('btn-menu')]" in js
    assert "idleRollup(viewMenu, [sceneHome, viewMenu]" in js
    assert "el.matches('input, textarea, select')" in js, "typing in the Index's search must keep it up"


def test_the_sky_lights_as_the_depths_do_in_reverse():
    """The owner's ask: scrolling into the sky lights its button, from the camera
    so S and the button do too, in the theme's colours: biolume in the Depths,
    dark ink with the accent in the sky."""
    world = _read(WEB / "static" / "js" / "world.js")
    shades = re.search(r"function updateShades.*?^}", world, re.S | re.M).group(0)
    assert "$('btn-sky').classList.toggle('lit', inSky)" in shades
    assert "CFG.SKY_RELEASE" in shades and "CFG.SKY_ENGAGE" in shades
    css = _read(CSS)
    # being lit follows the BAR's colour (stage 1, 2026-11-13): the rules read
    # tokens, the night values sit on :root and the bar block restates them
    depths = re.search(r":root \.chrome\.ci-depths\.lit \{.*?\}", css, re.S).group(0)
    sky = re.search(r":root \.chrome\.ci-sky\.lit \{.*?\}", css, re.S).group(0)
    for part in ("fill", "ink", "border"):
        assert f"var(--depths-lit-{part})" in depths and f"var(--sky-lit-{part})" in sky
    root = re.search(r"^:root \{.*?^\}", css, re.S | re.M).group(0)
    bar = re.search(r'^:root\[data-scheme-pick="light"\] :is\(.*?^\}', css, re.S | re.M).group(0)
    # a dark bar: the Depths in biolume with dark ink, the Sky in gilt with its own ink
    assert "--depths-lit-fill: var(--depth);" in root and "--depths-lit-ink: var(--card-ink);" in root
    assert "--sky-lit-fill: var(--gilt);" in root and "--sky-lit-ink: var(--on-gilt);" in root
    # a light bar: the Sky in navy (the bar's gilt), the Depths in deep teal with pale ink
    assert "--sky-lit-fill: var(--gilt);" in bar and "--sky-lit-ink: var(--on-gilt);" in bar
    assert "--depths-lit-fill: #0f766e;" in bar and "--depths-lit-ink: #f0fdfa;" in bar
    assert "#btn-depths.lit" not in css, "an id rule would outrank the fill"
    # nothing lit is keyed on the OS any more; `:root` lifts both over `.chrome.lit`
    assert 'data-scheme="light"] .chrome' not in css
    assert css.index(".chrome.lit {") < css.index(":root .chrome.ci-sky.lit")


def test_the_scheme_button_shows_the_bar_s_own_glyph():
    """Both icons ride in the button; the bar block flips which one shows, so
    the glyph follows the camera with no write (stage 1, 2026-11-13)."""
    css = _read(CSS)
    assert ".sch-sun { display: var(--bar-sun, none); }" in css
    assert ".sch-moon { display: var(--bar-moon, block); }" in css
    # after `.ci-glyph`, which says `display: block` at the same weight
    assert css.index(".ci-glyph { width: 20px") < css.index(".sch-sun {")
    root = re.search(r"^:root \{.*?^\}", css, re.S | re.M).group(0)
    bar = re.search(r'^:root\[data-scheme-pick="light"\] :is\(.*?^\}', css, re.S | re.M).group(0)
    assert "--bar-sun: none;" in root and "--bar-moon: block;" in root
    assert "--bar-sun: block;" in bar and "--bar-moon: none;" in bar
    m = re.search(r'<button class="chrome ci-scheme" id="btn-scheme".*?</button>', _read(INDEX), re.S)
    assert m and "sch-sun" in m.group(0) and "sch-moon" in m.group(0), "the button carries both icons"
    tools = re.search(r'<span class="menu-tools" id="menu-tools">(.*?)</span>', _read(INDEX), re.S).group(1)
    assert tools.index('id="btn-scheme"') < tools.index('id="btn-menu-settings"'), "the button sits before ⚙"


def test_the_colours_row_offers_light_dark_and_light_dark():
    html = _read(INDEX)
    row = re.search(r'<div class="sp-scheme" role="radiogroup".*?</div>', html, re.S)
    assert row, "Settings › YOU has no COLOURS row"
    assert re.findall(r'name="sp-scheme" value="(\w+)"', row.group(0)) == ["light", "dark", "auto"]
    css = _read(CSS)
    assert ".sp-scheme-opt:has(input:checked)" in css
    assert ".sp-scheme-opt:has(input:focus-visible) { outline: 2px solid var(--gilt); outline-offset: 2px;" in css


def test_the_v1584_depths_override_is_gone():
    """The band went nearly solid over the Depths' black in the light scheme.
    Under Light the Depths are no longer black, and under Light/Dark the bar is
    dark there, so the rule has no case left. The firmer band over a scene stays."""
    css = _read(CSS)
    assert "body.depths #scenes-list" not in css
    assert "body.depths .chrome:not(.lit)" not in css
    firm = re.search(r"^body\.scene-open #scenes-list \{.*?^\}", css, re.S | re.M).group(0)
    assert "var(--bar-glass-firm)" in firm and "var(--bar-shadow-firm)" in firm


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



# ── OVERVIEW (2026-11-13, stage 3) ───────────────────────────────────────────

def test_overview_is_the_deck_with_its_facts_on_top():
    """OVERVIEW is one main: the tiles' sheet, holding the `Charts ↓` jump and
    `#overview-body` (the only thing overview.js writes into), then the charts'
    seat that views.js lifts the Sky's and the Depths' sections into. CHARTS
    is an old name for it."""
    html = _read(INDEX)
    main = re.search(r'<main class="atlas-view" id="view-overview" data-view="overview" hidden[^>]*>(.*?)</main>',
                     html, re.S)
    assert main, "OVERVIEW's main is gone"
    body = main.group(1)
    for needle in ('id="charts-jump"', 'id="overview-tiles"', 'id="overview-body"', 'id="overview-charts"'):
        assert needle in body, needle
    assert (body.index('id="overview-tiles"') < body.index('id="charts-jump"')
            < body.index('id="overview-body"') < body.index('id="overview-charts"'))
    sheet = re.search(r'<section class="ov-sheet" id="overview-tiles"[^>]*>(.*?)</section>', body, re.S).group(1)
    assert 'id="charts-jump"' in sheet and 'id="overview-body"' in sheet, (
        "the jump sits in the sheet, so it wears the panel's tokens over the light sheet")
    assert 'href="#overview-charts"' in body
    views = _read(WEB / "static" / "js" / "views.js")
    # the lift seats: each section leaves a comment where it sat, and goes back to it
    assert "const MOVERS = ['chronicle', 'abyss', 'colophon'];" in views
    assert "document.createComment(` ${id} sits here on the map `)" in views
    assert "seat.replaceWith($(id))" in views
    assert "if (prev === 'overview') settle();" in views and "if (next === 'overview') lift();" in views
    assert "charts.append(el)" in views, "the sections must lift into #overview-charts, below the tiles"
    assert "A.setDeck = (on, opts) => A.setView(on ? 'overview' : 'map', opts);" in views
    assert "tracking = A.VIEW === 'overview'" in views, "a phone's swipe pages the charts under OVERVIEW"
    # the seats on the map still exist for the sections to go back to
    for sid in ('id="chronicle"', 'id="abyss"', 'id="colophon"'):
        assert sid in html, sid
    css = _read(CSS)
    assert 'body[data-view="charts"]' not in css
    assert css.count('body[data-view="overview"]') == 6
    over = _read(WEB / "static" / "js" / "overview.js")
    assert "$('overview-body')" in over, "overview.js draws into #overview-body"
    for whole in ("$('view-overview')", "$('overview-tiles')"):
        assert whole not in over, (
            "overview.js must write into #overview-body only: the view holds the lifted charts "
            "and the sheet holds the `Charts ↓` jump")
    assert "import './overview.js';" in _read(WEB / "static" / "js" / "atlas.js")


def test_cancel_never_acknowledges():
    """The 11-12 audit: `prompt(...) ?? ''` turned Cancel into an empty note and
    acknowledged anyway. Cancel (null) now stops; OK with nothing typed is
    still an acknowledgement with no note. The ANNALS and the TRIPWIRES both."""
    for name in ("annals.js", "stones.js"):
        js = _read(WEB / "static" / "js" / name)
        assert "prompt('What was it? (optional)') ?? ''" not in js, f"{name}: Cancel still acknowledges"
        block = js[js.index("prompt('What was it? (optional)')"):]
        block = block[:block.index("ackEvent(")]
        assert "if (note === null) return;" in block, f"{name}: Cancel must return before acknowledging"
        assert block.index("if (note === null) return;") < block.index("btn.disabled = true;")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
