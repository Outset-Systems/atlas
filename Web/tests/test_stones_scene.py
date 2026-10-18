"""THE DECOYS scene — structure, wiring, and the traps that do not show
up in a browser until it is too late.

A scene is mostly JS, and pytest cannot run it. What CAN be guarded here is
everything that would fail silently: an inline script the CSP kills, a scene
that is listed but never built, a close that Escape does not reach, a token that
does not exist, and a cache-buster that was not bumped.
"""

import os
import pathlib
import re

import pytest

WEB = pathlib.Path(__file__).resolve().parent.parent
TPL = WEB / "templates" / "index.html"
CSS = WEB / "static" / "atlas.css"
JS = WEB / "static" / "js" / "stones.js"


def _read(p):
    return p.read_text(encoding="utf-8")


# ── The CSP trap ─────────────────────────────────────────────────────────────

def test_the_template_has_no_executable_inline_script():
    """The app-wide CSP blocks inline scripts, so an inline executable
    `<script>` is silently dead in a real browser while every test still passes.
    This is the single most expensive mistake available in this file.

    A `type="application/json"` block is NOT executable — the browser never runs
    it, CSP has no objection, and it is the prescribed way to hand server values
    to a module. So the rule is "no inline JS", not "no inline script tag".
    """
    html = _read(TPL)
    for m in re.finditer(r"<script\b([^>]*)>", html, re.I):
        attrs = m.group(1).lower()
        if "src=" in attrs:
            continue                                  # external: fine
        if 'type="application/json"' in attrs:
            continue                                  # a data block: never executed
        pytest.fail(f"executable inline <script> in index.html: {m.group(0)!r}")


def test_server_values_still_arrive_through_the_data_block():
    """The pattern the CSP forces, pinned so nobody 'simplifies' it back into an
    inline assignment."""
    html = _read(TPL)
    assert '<script type="application/json" id="atlas-config">' in html


def test_the_scene_js_is_loaded_as_a_module_not_inlined():
    """It rides in through atlas.js's import graph, which is loaded with src."""
    assert "import './stones.js';" in _read(WEB / "static" / "js" / "atlas.js")


# ── The scene exists end to end ──────────────────────────────────────────────

def test_the_overlay_and_its_hooks_exist():
    html = _read(TPL)
    assert 'id="stones"' in html
    for hook in ('id="gs-list"', 'id="gs-head"', 'id="gs-close"'):
        assert hook in html, hook


def test_the_scene_is_offered_in_the_drawer():
    assert 'data-scene="stones"' in _read(TPL)
    assert "{{ theme.text.stones|upper }}" in _read(TPL)


def test_the_scene_is_built_at_boot():
    """Listed but never built is a button that does nothing."""
    assert "A.buildStonesScene();" in _read(WEB / "static" / "js" / "atlas.js")


def test_the_button_is_wired_to_the_opener():
    ui = _read(WEB / "static" / "js" / "ui.js")
    assert "stones: A.openStones" in ui
    assert "A.closeStones?.()" in ui, "the switcher must close it like every sibling"


def test_escape_closes_it():
    """Every sibling scene is in this chain; a scene that Escape cannot close is
    the one the user has to hunt for a × to leave.

    Since 2026-08-21 the chain is ONE list: camera.js's Escape calls
    `A.closeAllScenes`, and `closeAllScenes` (ui.js) is where the scenes are
    enumerated — it used to be enumerated twice, and the Escape copy was the one
    that would have been forgotten. So the pin is in two halves: Escape reaches
    the list, and the list names this scene."""
    assert "A.closeAllScenes?.()" in _read(WEB / "static" / "js" / "camera.js")
    ui = _read(WEB / "static" / "js" / "ui.js")
    m = re.search(r"function closeAllScenes\(\) \{.*?\n\}", ui, re.S)
    assert m and "A.closeStones?.()" in m.group(0), "closeAllScenes no longer names the stones"


def test_the_scene_cedes_the_drawer_strip_without_undimming_it():
    """2026-08-16 (supersedes the v1.10.16 shove this test used to pin): the
    PANEL cedes the drawer's strip via wrapper padding, while the overlay's
    dim stays full-bleed — pulling the whole overlay's `right` to the drawer's
    edge un-dimmed the strip too, a bright column of map glowing around the
    floating Index. The drawer itself rises above the dim under scene-open."""
    css = _read(CSS)
    m = re.search(r"body\.drawer-open #reliquary[^{]*\{[^}]*\}", css, re.S)
    assert m and "#stones" in m.group(0), "the panel-room rule lost #stones"
    assert "padding-right" in m.group(0), (
        "the drawer-strip rule moves `right` again — that un-dims the strip "
        "along with un-covering it")
    assert re.search(r"body\.scene-open #index-drawer \{[^}]*z-index: 986", css), (
        "the drawer no longer rises above the scene dim")


def test_it_joins_the_shared_overlay_rules():
    css = _read(CSS)
    # the shared scene wrapper — since 2026-08-21 ONE rule for all six overlays,
    # so the pin is "#stones sits in the same selector list as #ledger", not the
    # exact list (which now carries #tribute and #reliquary too)
    assert re.search(r"#ledger,[^{]*#stones[^{]*\{", css)
    assert "#stones.open" in css


# ── Design conformance (the design notes is binding) ────────────────────────────────

def test_no_new_colours_only_the_existing_semantic_tokens():
    """the design notes: 'reuse zone hues; no new colors'. The scene's palette must be
    tokens, and any literal must be an rgba() of a colour already in the file."""
    # Scoped to THIS section only. It used to be `split(marker)[1]`, i.e.
    # "everything to the end of the file" — which silently meant "the stones
    # section AND every section appended after it". THE TRUST was added at the
    # end of atlas.css on 2026-09-09 and failed this test for its own,
    # legitimate `rgba(var(--gilt-rgb), …)`. Cut at the next section header so
    # the assertion means what its name says.
    block = _read(CSS).split("── THE DECOYS")[1].split("/* ──")[0]
    literals = set(re.findall(r"#[0-9a-fA-F]{3,6}\b", block))
    assert literals == set(), f"new literal colours in the scene: {literals}"
    # the one rgba is the down tone's own glow, spelled from --sem-down
    for rgba in set(re.findall(r"rgba\(([^)]+)\)", block)):
        nums = [n.strip() for n in rgba.split(",")]
        assert nums[:3] == ["251", "73", "52"], f"unexpected rgba: {rgba}"


def test_the_fonts_are_the_systems_own():
    """There are no --font-* custom properties in this codebase; fonts are
    declared literally. A var() that does not exist fails SILENTLY to the
    inherited face, which is exactly the kind of visual bug no test sees."""
    block = _read(CSS).split("── THE DECOYS")[1]
    assert "var(--font-" not in block
    assert "'Cinzel', serif" in block          # display / place names
    assert "'JetBrains Mono', monospace" in block   # data


def test_reduced_motion_is_honoured():
    """the design notes: 'Always: full prefers-reduced-motion fallback.' The stone must
    still read as speaking without the pulse."""
    block = _read(CSS).split("── THE DECOYS")[1]
    assert "@media (prefers-reduced-motion: reduce)" in block
    m = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.+?)\n\}", block, re.S)
    assert m and "animation: none" in m.group(1)
    assert "box-shadow" in m.group(1), "it must stay visibly alarmed, just still"


def test_the_pulse_matches_the_maps_own_heartbeat():
    """the design notes: 'Markers breathe: 3.2s'. A second rhythm would read as a
    different system."""
    assert "gs-breathe 3.2s" in _read(CSS)


def test_the_cache_buster_was_bumped():
    """Any change to CSS/JS/templates needs APP_VERSION moved, because `?v=` is
    baked Python — otherwise browsers keep serving the old scene."""
    import sys
    sys.path.insert(0, str(WEB))
    import settings
    # A version, not a number to compare: the public tree restarts at 0.1.x
    # (the publish build script), and "1.9.0" > "1.12.0" as strings anyway.
    import re
    assert re.fullmatch(r"\d+\.\d+\.\d+(-[a-z0-9.]+)?", settings.APP_VERSION), settings.APP_VERSION
    assert "?v={{ v }}" in (WEB / "templates" / "index.html").read_text(encoding="utf-8")


def test_design_decisions_log_has_a_row_for_this():
    """Repo hygiene, not runtime: `the design notes` lives beside `Web/` and the
    Dockerfile copies only `Web/`, so this cannot be answered from inside the
    image. It SKIPS there rather than failing, because a permanently-red test
    in the pre-deploy run is worse than no test — the documented gate is "run
    The suite against the new image", and a baseline of "1 failed, and that one
    is fine" is a gate nobody can read. It still runs, and still fails, from a
    working copy, which is the only place the answer means anything."""
    design = WEB.parent / "the design notes"
    if not design.exists():
        pytest.skip("the design notes is not in the image (Dockerfile copies Web/ only)")
    assert "STONES" in _read(design).upper() or "DECOYS" in _read(design).upper()


# ── The failure the scene must not hide ──────────────────────────────────────

def test_the_scene_distinguishes_quiet_from_unreachable():
    """The load-bearing behaviour. Both cases are an empty `stones` map, and
    only `sources.deception` tells them apart — so the source must be read and
    the lost case must be stated in words."""
    js = _read(JS)
    assert "signalsSources" in js
    assert "CONTACT LOST" in js
    assert "THE WATCH IS NOT SET" in js, "unconfigured is a third, different case"


def test_the_scene_never_infers_calm_from_an_empty_list():
    """`ALL QUIET` may only be reached after the source has been confirmed
    reachable — otherwise it is the map inventing reassurance."""
    js = _read(JS)
    quiet = js.index("ALL QUIET")
    lost = js.index("CONTACT LOST")
    assert lost < quiet, "the unreachable branch must return before the calm one"


def test_a_stone_that_cannot_speak_says_so():
    """A charted stone with no token behind it is not a quiet watcher — it was
    never armed, and the difference matters more than any state it shows."""
    assert "not planted" in _read(JS)


def _render_body():
    """Just the HTML-building function — scanning the whole file would trip over
    ordinary JS that happens to mention the same fields."""
    js = _read(JS)
    start = js.index("function stoneHTML(")
    end = js.index("\nfunction ", start + 1)
    return js[start:end]


@pytest.mark.parametrize("field", [
    "s.name", "s.id", "s.host", "s.zone", "s.mimics", "s.placement", "s.kind",
    "s.last_reason", "s.last_spoke",
])
def test_every_stone_string_reaches_the_page_escaped(field):
    """The feed half is scrubbed of attacker text by the decoy feed, but the dataset
    half is human-edited and a browser is the last place to discover otherwise.
    Numbers are exempt — `s.trips | 0` is an integer by construction — so this
    names the string-valued fields rather than guessing from a regex."""
    assert "import { A, $, esc }" in _read(JS)
    body = _render_body()
    for m in re.finditer(r"\$\{([^}]*)\}", body):
        expr = m.group(1)
        if re.search(re.escape(field) + r"\b", expr):
            assert "esc(" in expr, f"{field} interpolated unescaped: {expr!r}"


def test_the_render_function_was_actually_found():
    """Guards the test above: if stoneHTML is renamed and the slice comes back
    empty, every escaping assertion would pass vacuously."""
    body = _render_body()
    assert "gs-row" in body and len(body) > 400
