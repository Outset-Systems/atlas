"""THE CALENDAR — the realm's day, charted (v1.45.0).

The 2026-09-04 the GPU box Calendar was a hand-built page: every LLM-backed job in
the realm on one UTC day, so the meetings between them could be seen. A
hand-built page drifts the day after it is built, so the day became dataset
(v1.40.0, THE FORGE'S DAY) and then a scene of its own (v1.42.0) — while THE
RITES, since 2026-07-11, listed the same rows a second time and said whether
each one actually turned. Two pages of one fact drift too. v1.45.0 folds them
into THE CALENDAR: one row per rite, one clock down the middle, the verdict in
the gutter.

The model that lays the day out is pure JS (`calendar-model.js`) and is pinned
by `tests/test_calendar_model.mjs` under node. This file pins what Python owns
— the schema, validation, the bundled rows — and the wiring pytest can see.
"""

import copy
import json
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
CARD_JS = WEB / "static" / "js" / "card.js"
SCENE_JS = WEB / "static" / "js" / "calendar.js"
MODEL_JS = WEB / "static" / "js" / "calendar-model.js"
BUNDLED = WEB / "default-lab-data.json"
LIVE_COPY = WEB.parent / "Data" / "lab-data.json"

FORGE_FIELDS = {"asks", "model", "at", "days", "between", "hold"}


def _read(p):
    return p.read_text(encoding="utf-8")


def _bundled():
    return json.loads(_read(BUNDLED))


# ── the schema ───────────────────────────────────────────────────────────────

def test_a_rite_can_name_the_place_it_asks():
    import schema
    fields = {f["name"]: f for f in schema.SECTIONS["rites"]["fields"]}
    assert FORGE_FIELDS <= set(fields), FORGE_FIELDS - set(fields)
    assert fields["asks"]["type"] == "ref" and fields["asks"]["ref"] == "nodes", (
        "`asks` must be a node reference, or a typo would chart a rite onto nowhere")
    assert fields["hold"]["type"] == "int"
    for name in FORGE_FIELDS:
        assert not fields[name]["required"], f"{name} must stay optional — a rite with none of these is the rite it was"


def test_the_bundled_forge_rites_validate_clean():
    import validation
    data = _bundled()
    problems = validation.validate(data)
    assert not problems, problems


def test_asking_an_uncharted_place_is_refused():
    import validation
    data = _bundled()
    rite = copy.deepcopy(next(r for r in data["rites"] if r.get("asks")))
    rite["name"] = "A rite that asks nowhere"
    rite["asks"] = "no-such-forge"
    data["rites"].append(rite)
    problems = validation.validate(data)
    assert any("no-such-forge" in str(p) for p in problems), problems


# ── the rows ─────────────────────────────────────────────────────────────────

@pytest.mark.private_only   # the real map's own rites
def test_gpu_box_is_asked_by_the_llm_rites():
    """The six lanes of the 09-04 calendar, as charted intent: five with a
    clock, one (the benchmarks) deliberately without."""
    rites = [r for r in _bundled()["rites"] if r.get("asks") == "gpu-box"]
    names = {r["name"] for r in rites}
    assert {"The Feed's Morning Brief", "The Feed's Hourly Scoring", "The Week in Review",
            "The Ledger's Scout", "The Ledger's Chain", "The Feed's Benchmarks"} <= names, names
    clocked = [r for r in rites if r.get("at")]
    assert len(clocked) == 5
    assert all(r.get("model") for r in rites), "every forge rite says what it asks for"
    hourly = next(r for r in rites if r["name"] == "The Feed's Hourly Scoring")
    assert hourly["at"] == ":35" and hourly["between"], "the hourly pass keeps the worker's daytime window"
    chain = next(r for r in rites if r["name"] == "The Ledger's Chain")
    assert chain["days"] == "Mon–Fri", "the market does not open on Sunday"


def test_every_clock_is_a_clock():
    """`at` is UTC `HH:MM` or `:MM`; `between` is `HH:MM–HH:MM`. Anything else
    silently drops the rite off the strip, which is why it is pinned here."""
    for r in _bundled()["rites"]:
        if r.get("at"):
            assert re.fullmatch(r"(\d{1,2}:\d{2}|:\d{1,2})", r["at"]), (r["name"], r["at"])
        if r.get("between"):
            assert re.fullmatch(r"\d{1,2}:\d{2}\s*[-–—]\s*\d{1,2}:\d{2}", r["between"]), (r["name"], r["between"])
        if r.get("hold") is not None:
            assert isinstance(r["hold"], int) and 1 <= r["hold"] <= 1440, (r["name"], r["hold"])


@pytest.mark.private_only   # the real map's own rites
def test_the_realms_day_is_mostly_drawable():
    """v1.45.0's whole point: THE FORGE could time five of twenty-eight rites,
    because only the LLM rites carry the Desk's `at`. THE CALENDAR reads the
    hour out of each rite's own `when` as well — the same best-effort read
    `api/v2/manifest` already publishes to the Hub — so the page draws the
    realm's day instead of a corner of it. Pinned as a floor, not a target: a
    rite whose prose names no hour must still be listed, never invented.

    The Python mirror of `calendar-model.js`'s `clockOf`, kept deliberately
    dumb — if this and the JS ever disagree, the number below moves and says so.
    """
    rites = _bundled()["rites"]
    clock = re.compile(r"\b(\d{1,2}):(\d{2})\b")

    def timed(r):
        if r.get("at"):
            return True
        m = clock.search(r.get("when") or "")
        return bool(m) and int(m.group(1)) < 24 and int(m.group(2)) < 60

    drawable = [r for r in rites if timed(r)]
    assert len(drawable) >= 20, f"only {len(drawable)} of {len(rites)} rites carry an hour"
    listed = [r["name"] for r in rites if not timed(r)]
    parked = [r["name"] for r in rites if r.get("cadence") == "parked"]
    assert parked, "the dataset keeps at least one parked rite as the floor case"
    for name in parked:
        assert name in listed, f"{name!r} names no hour and must stay listed"


def test_the_live_copy_matches_the_bundled_default():
    """DATA.md: keep the two identical. The forge rites were added to both."""
    if not LIVE_COPY.exists():
        return
    assert _read(LIVE_COPY) == _read(BUNDLED), "Data/lab-data.json and Web/default-lab-data.json have drifted"


# ── the wiring ───────────────────────────────────────────────────────────────

def test_the_rites_and_the_forge_are_one_scene():
    """v1.45.0 (the owner: "combine the rites and the forge into a calendar"):
    CALENDAR in the band, built by calendar.js through the shared scene shell.
    The two scenes it replaces must be gone — a stale `#rites` panel nothing
    opens is exactly the kind of second drawing of one fact this merge exists
    to delete."""
    scene_js, card_js, html = _read(SCENE_JS), _read(CARD_JS), _read(INDEX)
    ui_js, atlas_js, css = _read(WEB / "static" / "js" / "ui.js"), _read(WEB / "static" / "js" / "atlas.js"), _read(CSS)
    js_dir = WEB / "static" / "js"
    # the scene
    assert 'data-scene="calendar"' in html, "CALENDAR has no button in the band"
    assert '<div id="calendar" aria-hidden="true">' in html and 'id="cal-close"' in html
    assert "makeScene({ id: 'calendar', closeId: 'cal-close'" in scene_js
    assert "A.openCalendar = scene.open" in scene_js and "A.closeCalendar = scene.close" in scene_js
    assert "calendar: A.openCalendar" in ui_js, "the band's click handler cannot open it"
    assert "A.closeCalendar?.()" in ui_js, "closeAllScenes would leave it up"
    assert "A.buildCalendarScene();" in atlas_js
    for sel in ("#calendar,", "#calendar.open,", "#calendar.open .ldg-panel,", "body.drawer-open #calendar,"):
        assert sel in css, f"{sel} missing — the scene chrome does not dress #calendar"
    # the two it replaces are gone, not merely unwired
    for dead in ("rites.js", "forge.js", "forge-model.js"):
        assert not (js_dir / dead).exists(), f"{dead} survived the merge"
    for dead in ('data-scene="rites"', 'data-scene="forge"', 'id="rt-close"', 'id="fg-close"'):
        assert dead not in html, f"{dead} is still in the page"
    for dead in ("openRites", "openForge", "closeRites", "closeForge"):
        assert dead not in ui_js and dead not in atlas_js, f"{dead} still wired"
    # the card points, never draws
    assert "import { calendarPointerHTML } from './calendar.js';" in card_js
    assert "forgeCalendarHTML" not in card_js and "cal-track" not in card_js, "the card still draws the strip"
    assert "A.openCalendar?.()" in card_js
    assert 'id="card-forge"' in html, "the card has no seat for the pointer"
    assert MODEL_JS.exists()


def test_the_model_is_pure_and_the_renderer_is_the_only_dom():
    """calendar-model.js must stay importable under node: no `A`, no `$`, no
    document — that is what makes test_calendar_model.mjs possible."""
    model = _read(MODEL_JS)
    assert "import" not in model.split("export const DAY_MIN")[0].replace("\n", " ").split("*/")[-1], (
        "calendar-model.js imports something — it must depend on nothing")
    assert "document." not in model and "from './config.js'" not in model
    assert "from './calendar-model.js'" in _read(SCENE_JS)


def test_every_desk_pencil_still_has_a_header_to_sit_in():
    """The one place a scene's markup is named from OUTSIDE its own module.

    `editor/index.js` hangs a ✎ in each editable scene's header by selector, and
    `addHeaderButtons` skips a selector that matches nothing — silently. So
    renaming THE RITES to THE CALENDAR left `#rites .ldg-head` pointing at
    markup that no longer existed and quietly took the "Add or remove rites"
    pencil off the map: no error, no console line, just a scene that could no
    longer be edited from itself. Pinned by resolving every `at` against the
    template rather than by remembering."""
    html, editor = _read(INDEX), _read(WEB / "static" / "js" / "editor" / "index.js")
    ats = re.findall(r"\{ at: '#([a-z-]+) \.([a-z-]+)'", editor)
    assert len(ats) >= 6, f"the scene-editor table stopped parsing: {ats}"
    for panel, cls in ats:
        assert f'id="{panel}"' in html, f"the ✎ for #{panel} points at a panel that is not in the page"
        assert f'class="{cls}"' in html, f"#{panel}'s ✎ wants .{cls}, which the page does not draw"
    assert ("calendar", "ldg-head") in ats, "the rites can no longer be edited from their own scene"


def test_one_page_reads_the_rites_once():
    """The merge's real prize: THE RITES' verdicts and THE FORGE's day come
    off the SAME fetch, so a rite re-timed in the Desk cannot move on one and
    not the other. Two fetches of `api/v2/rites` in this file would be the old
    bug wearing a new name."""
    scene_js = _read(SCENE_JS)
    assert scene_js.count("api/v2/rites") == 1, "the scene reads the rites more than once"
    assert "api/v2/calendar" in scene_js, "the fleet's day is not fetched"
    assert "A.DATA.rites" in scene_js, "no fallback when the truth cannot be fetched"


def test_the_day_spends_colour_once():
    """the design notes, "if everything glows, nothing does". The ladder was re-cut for
    twenty-eight rows: an ordinary rite is ink, the GILT is kept for the rites
    that ask a forge for a model, the heavy model takes the warning tone, a
    meeting is the only alarm on the page, and now is one info hairline."""
    css = _read(CSS)
    assert re.search(r"\.cal-blk \{[^}]*var\(--text-dim\)", css), "the ordinary block is not ink"
    assert re.search(r"\.cal-row\.tone-warm \.cal-blk \{[^}]*var\(--gilt\)", css)
    assert re.search(r"\.cal-row\.tone-heavy \.cal-blk \{[^}]*var\(--sem-warn\)", css)
    assert re.search(r"\.cal-blk\.hit \{[^}]*var\(--sem-down\)", css)
    assert re.search(r"\.cal-now \{[^}]*var\(--sem-info\)", css)
    # the gilt is spent once: no other block rule may claim it
    gilt_blocks = re.findall(r"^\.cal-[^{\n]*\.cal-blk[^{\n]*\{[^}]*var\(--gilt\)", css, re.M)
    assert len(gilt_blocks) <= 2, f"the gold is being spread across {len(gilt_blocks)} block rules"
    # the four columns are declared once, and everything hangs off them
    assert css.count("grid-template-columns: var(--cal-gut) var(--cal-name) 1fr var(--cal-meta);") == 1, (
        "the ruler and the rows must share ONE grid, or an hour drifts off its own axis")
    assert ".card-forge[hidden] { display: none; }" in css
    assert ".card-forge .card-forge-link" in css, "the card's door has no dress"
    # `.rt-head` was on this list until v1.47.1 — it was NOT dead: SEALS, GOSSIP
    # STONES, ACCOUNTS and THE TRUST still write their verdict into one, so
    # deleting it with THE RITES left four scene heads unstyled. Its rule is
    # back and test_scene_heads.py pins every .rt-* class a scene writes.
    for dead in (".rite-when", ".fc-block", ".forge-cal"):
        assert dead not in css, f"{dead} is dead dress from a scene that no longer exists"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
