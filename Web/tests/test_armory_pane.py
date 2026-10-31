"""The Armory's detail pane — what a selected vessel says about itself.

Pytest cannot run the scene, so this pins the STRUCTURE the pane's text depends
on: the fields it reads and the promise the Desk makes about them.

2026-09-04: "the description of the selected item is not displaying".
A rack slot's Description reached the pane only when the slot was NOT a
charted place — it stood in for the role and the hardware line — and the
schema's help text said exactly that. On a charted rack every Description
typed into the Desk therefore went nowhere. The pane shows it for every vessel
now, and the help text says what the field does.
"""

import os
import pathlib
import re
import sys

WEB = pathlib.Path(__file__).resolve().parent.parent
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "standalone"}

JS = WEB / "static" / "js" / "reliquary.js"
CSS = WEB / "static" / "atlas.css"


def _read(p):
    return p.read_text(encoding="utf-8")


def _show_detail():
    js = _read(JS)
    m = re.search(r"function showDetail\(d\) \{.*?\n\}", js, re.S)
    assert m, "showDetail is gone"
    return m.group(0)


def test_a_charted_vessel_shows_the_slot_description():
    """The slot's own words reach the pane when the slot IS a charted place —
    the case that covered three of four front slots and showed nothing."""
    body = _show_detail()
    assert re.search(r"const desc = n \? \(d\.desc \|\| ''\) : ''", body), (
        "the pane no longer takes the slot Description for a charted vessel")
    assert 'rel-detail-desc' in body, "the Description has no line of its own in the data block"
    # and the hardware line is the NODE's, never the slot's Description in disguise
    assert "const hw = n ? (n.hw || '') : ''" in body, (
        "the hardware line falls back to d.desc again — an uncharted slot will print it twice")


def test_an_uncharted_vessel_does_not_say_it_twice():
    """Uncharted slots wear the Description as the epigraph (their only
    role-like fact). Repeating it in the data block was the old double print."""
    body = _show_detail()
    assert "const role = n ? n.role : (d.desc || 'reserved')" in body
    assert "if (desc && desc !== hw)" in body, (
        "a Description identical to the hardware line would print twice")


def test_the_desk_no_longer_promises_the_old_behaviour():
    import schema
    rack = schema.SECTIONS["rack"]["fields"]
    desc = [f for f in rack if f["name"] == "desc"][0]
    assert "isn't a charted place" not in desc["help"], (
        "the help text still says the Description shows only for uncharted vessels")
    assert "every vessel" in desc["help"]


def test_the_description_line_is_dressed():
    css = _read(CSS)
    assert re.search(r"^\.rel-detail-desc \{", css, re.M), "no rule for the Description line"


def _rule(css, selector):
    m = re.search(r"^" + re.escape(selector) + r" \{([^}]*)\}", css, re.M)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_the_rack_column_has_a_width_of_its_own():
    """2026-09-07: the Armory was not "properly displaying" — the detail
    pane sat OFF the right edge of the panel behind a horizontal scrollbar.

    `.rel-rack` was `flex-shrink: 0` with no width, so it took the width of
    its widest child, and since v1.39.1 that child is the rear-of-rack strip:
    three buttons in one row, the third as long as the second switch's Description
    (~511px), 916px all told. The column must be the niche width plus its
    power-rail padding — the sheet is border-box — and a rear button must be
    allowed to wrap inside it, or the same sentence widens it again."""
    css = _read(CSS)
    rack = _rule(css, ".rel-rack")
    assert "flex: none" in rack, "the rack column shrinks/grows with its children again"
    assert re.search(r"width:\s*calc\(26px \+ 460px\)", rack), (
        "the rack column has no width of its own — its widest child decides it")
    assert re.search(r"padding-left:\s*26px", rack), (
        "the padding changed; the width above adds 26px for it and must move with it")
    item = _rule(css, ".rel-rear-item")
    assert "min-width: 0" in item and "max-width: 100%" in item, (
        "a rear vessel's button can refuse to be narrower than its Description again")
    elev = _rule(css, "#rel-elevation")
    assert re.search(r"width:\s*460px", elev), "the niche width moved; .rel-rack's calc must follow it"


def test_the_desk_offers_every_faceplate_the_model_draws():
    """`kind` is a select in the Desk and a key of KIND_HUE in rack-model.js. A
    kind added to one and not the other is either unreachable or undrawable."""
    import schema
    model = _read(WEB / "static" / "js" / "rack-model.js")
    hues = re.search(r"export const KIND_HUE =\s*\{(.*?)\}", model, re.S).group(1)
    kinds = set(re.findall(r"(\w+):", hues))
    assert set(schema.RACK_KINDS) - {"auto"} == kinds


def test_every_kind_has_a_dressed_panel():
    """A kind without a `.rel-<kind> .fp-panel` rule still draws, in the default
    fill; the ones below are meant to read as their own iron in both views."""
    css = _read(CSS)
    for kind in ("gateway", "switch", "forge", "patch", "storage", "power", "enclosure"):
        assert f".rel-{kind} .fp-panel" in css, kind


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))


def test_two_racks_keep_their_own_slots_and_heights():
    """The same name in two racks is two slots, and a rack's height is its own."""
    import overlays
    data = {
        "racks": [{"id": "a", "name": "Rack A"}, {"id": "b", "name": "Rack B"}],
        "rack": [
            {"rack": "a", "u": "U12", "size": 1, "name": "Patch Panel"},
            {"rack": "b", "u": "U4", "size": 1, "name": "Patch Panel"},
            {"u": "U1", "size": 1, "name": "No rack set"},
        ],
    }
    assert overlays.slot_key(data["rack"][0]) == "slot:a-patch-panel"
    assert overlays.slot_key(data["rack"][1]) == "slot:b-patch-panel"
    assert overlays.slot_key(data["rack"][2]) == "slot:no-rack-set"
    clean = overlays._rack_clean(data, {
        "slot:a-patch-panel": 10,
        "slot:b-patch-panel": 9,     # rack B is 4U: refused, though rack A has room
        "slot:no-rack-set": 11,      # unset means the first rack, which is 12U
    })
    assert clean == {"slot:a-patch-panel": 10, "slot:no-rack-set": 11}


def test_the_old_names_are_gone_from_the_scene_band():
    """Plain words on the band and the flyout (2026-10-31)."""
    html = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
    for word in ("RACKS", "RESOURCES", "ADDRESSES", "TOPOLOGY"):
        assert f">{word}</button>" in html
    for word in ("ARMORY", "TRIBUTE", "LEDGER", "PATH"):
        assert f">{word}</button>" not in html
    card = (WEB / "static" / "js" / "card.js").read_text(encoding="utf-8")
    assert "◈ ROUTE" in card and "◈ TOPOLOGY" in card
    assert "◈ ROAD" not in card and "◈ PATH" not in card


def test_settings_are_grouped_in_plain_words():
    """Settings reads by task, and no section's key moved (2026-10-31)."""
    html = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
    panel = html[html.index('id="settings-panel"'):html.index("Toast for unbuilt scenes")]
    panel = re.sub(r"<!--.*?-->", "", panel, flags=re.S)   # comments may keep history
    groups = re.findall(r'class="sp-group" data-group="(\w+)"', panel)
    assert groups == ["you", "map", "connections", "admin"]
    for key in ("account", "directory", "integrations", "realm", "deployment", "users",
                "signins", "survey", "seeking", "table", "watchers"):
        assert f'data-sec="{key}"' in panel, f"the stored fold for {key} would be lost"
    for old in ("THE SURVEY<", "THE SEEKING", "CARTOGRAPHER", "THE WATCHERS<"):
        assert old not in panel
    account = (WEB / "static" / "js" / "account.js").read_text(encoding="utf-8")
    for old in (">THE SOURCES<", ">THE DIRECTORY<", ">THE LAB<", ">THE DEPLOYMENT<", "SURVEYOR"):
        assert old not in account
