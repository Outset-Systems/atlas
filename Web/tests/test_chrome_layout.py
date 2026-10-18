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
    against the band rather than the viewport), and it carries `overflow-x:
    auto` for the one-row scroll, which then clips the cluster away entirely.
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
    assert "margin-left: auto" in rule.group(0), (
        "the auto margin that pins the band's tail must sit on the cluster, "
        "not on ☰ — two auto margins split the slack and park ⚙ mid-band")
    menu = re.search(r"#scenes-list \.ci-menu \{.*?\}", css, re.S)
    assert menu and "margin-left: auto" not in menu.group(0)
    assert re.search(r"#scenes-list \.menu-tools:has\(\.active\)", css), (
        "the cluster does not stay out while the SETTINGS scene is up")
    assert "overflow: hidden" in rule.group(0), "the reveal is a clip; without it the button overflows onto ☰"
    # a hover-revealed control is no control on a touch screen: at the narrow
    # width the cluster stands out permanently
    narrow = re.findall(r"@media \(max-width: 720px\) \{(.*?)\n\}", css, re.S)
    assert narrow, "no ≤720px block at all"
    assert any(re.search(r"#scenes-list \.menu-tools \{[^}]*width: 34px[^}]*opacity: 1", b) for b in narrow), (
        "no ≤720px block stands the gear out permanently")


def test_the_band_still_has_the_properties_that_make_that_trap_real():
    """Belt for the test above: if the band ever loses backdrop-filter AND its
    overflow, the rule stops being load-bearing and this file should be re-read
    rather than silently guarding nothing."""
    css = _read(CSS)
    band = re.search(r"#scenes-list \{.*?\}", css, re.S)
    assert band, "#scenes-list rule is gone"
    assert "backdrop-filter" in band.group(0)
    assert "overflow-x: auto" in band.group(0)


# ── What lives where ─────────────────────────────────────────────────────────

def test_the_index_button_lives_in_the_band():
    """☰ moved out of the top-right corner and into the band's far end."""
    assert 'id="btn-menu"' in _band(_read(INDEX))


def test_the_column_is_zoom_plus_the_network_glyph():
    """The column is + − and, since 2026-09-02, the network glyph
    PERMANENTLY under −. Anything else coming back here means `#card.card-left`'s
    clearance is wrong — see MUST TRACK in atlas.css (374px for three)."""
    html = _read(INDEX)
    m = re.search(r'<div class="zoom-stack">.*?</div>', html, re.S)
    assert m, "the zoom stack is gone"
    ids = re.findall(r'id="(btn-[\w-]+)"', m.group(0))
    assert ids == ["btn-zoom-in", "btn-zoom-out", "btn-net"], ids
    css = _read(CSS)
    assert re.search(r"#card\.card-left \{[^}]*--card-clear: 374px", css), (
        "three buttons in the column ⇒ the left-hand card clears 374px")


@pytest.mark.parametrize("button", ["btn-sky", "btn-depths", "btn-decoys"])
def test_every_map_tool_is_in_the_cluster(button):
    html = _read(INDEX)
    cluster = re.search(r'<span class="atlas-tools".*?</span>\s*$', html, re.S | re.M)
    assert cluster, "the cluster's markup could not be found"
    assert f'id="{button}"' in cluster.group(0), button


def test_the_cluster_is_two_rows_of_two():
    """Ops's ask, and the ORDER is the grouping: the top row is what you lay
    over the surface (☁ sky, ◈ roads), the bottom row is where you go and who
    is watching while you are there (☾ descent, 👁 the decoy watch).

    Reading order in the markup IS the reading order on screen — the cluster is
    a 2-column grid, so nothing else decides which button lands where.
    """
    html = _read(INDEX)
    cluster = re.search(r'<span class="atlas-tools".*?</span>\s*$', html, re.S | re.M)
    assert cluster, "the cluster's markup could not be found"
    order = re.findall(r'id="(btn-[\w-]+)"', cluster.group(0))
    # ◈ left the cluster for the zoom column 2026-09-02; the grid
    # stays two columns, so it now reads ☁ ☾ over 👁
    assert order == ["btn-sky", "btn-depths", "btn-decoys"], order

    css = _read(CSS)
    rule = re.search(r"^\.atlas-tools \{.*?\}", css, re.S | re.M)
    assert rule, ".atlas-tools rule is gone"
    assert "grid-template-columns: repeat(2, auto)" in rule.group(0), (
        "the cluster is not a 2-column grid — a flex row reflows the moment a "
        "button is added or removed, and the two rows quietly become one")


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

def test_the_atlas_button_only_pins_the_tools_when_no_scene_is_open():
    """THE ATLAS does the job that is AVAILABLE: leave the scene if one is up,
    otherwise pin the map tools it reveals on hover (2026-08-15 — it used to
    take the Index, which is ☰'s job at the other end of the band). Losing the
    guard would strand you in a scene with no way back except click-again."""
    js = _read(UI)
    assert "A.sceneOpen" in js
    assert re.search(r"scene === 'atlas' && !A\.sceneOpen", js), (
        "THE ATLAS's click no longer checks whether a scene is open")
    assert re.search(r"!A\.sceneOpen\) \{ A\.toggleToolsPin\(\)", js), (
        "THE ATLAS's spare gesture is not the tools pin any more")


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


def test_the_pin_state_survives_a_reload():
    """A pin that forgets is a pin you set every visit. The storage KEY is
    asserted, not just the mechanism: the gesture moved from a button to THE
    ATLAS's click, and reusing `atlas.toolsPinned` is what carries an existing
    preference across that change instead of silently resetting it."""
    js = _read(UI)
    assert "atlas.toolsPinned" in js
    assert "localStorage" in js


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
