"""THE DECOYS — the `stones[]` section of the catalogue.

The decoy feed charts its tripwires here so the map knows where to draw them. The
stone's *live* state (silent / stirred / speaking) deliberately does NOT live
in this section: it arrives through the signals layer, the same way a node's
health does. Writing it into the dataset would put a change-log entry and an
atomic file write on the path of every trip, and would fight the Surveyor's
Desk for the file — see the note in `sanitize.py` and PROGRESS task 10.
"""

import json
import os
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

import schema  # noqa: E402
from validation import validate  # noqa: E402


def _stone(**kw):
    base = {"id": "nas-restore-share", "name": "Restoration-Keys",
            "kind": "windows-folder", "zone": "internal", "severity": "critical"}
    base.update(kw)
    return base


def _data(*stones):
    return {"stones": list(stones)}


# ── The section is in the catalogue, and reachable by the browser ───────────

def test_the_section_exists():
    s = schema.get("stones")
    assert s is not None
    assert s["plural"] == "stones"
    assert s["id_field"] == "id"
    assert s["title_field"] == "name"


def test_it_is_in_the_editor_order_and_the_file_order():
    """Absent from SECTION_ORDER, the Desk has no page for it. Absent from
    FILE_ORDER, a first write lands in an arbitrary place in the dataset."""
    assert "stones" in schema.SECTION_ORDER
    assert "stones" in schema.FILE_ORDER


def test_the_catalogue_served_to_the_browser_includes_it():
    """`/api/admin/context` carries this as its `schema` key, and the editor
    builds every form from it. Missing here, the Desk silently cannot edit the
    section at all."""
    cat = schema.catalogue()
    assert "stones" in cat["sections"]
    assert "stones" in cat["order"]
    fields = {f["name"] for f in cat["sections"]["stones"]["fields"]}
    assert {"id", "name", "kind", "host", "zone", "severity",
            "placement", "mimics", "retired", "note"} <= fields


def test_the_catalogue_is_json_serializable():
    """It is sent to a browser. A field carrying a non-JSON value would 500
    the editor rather than fail here."""
    json.dumps(schema.catalogue())


# ── The live state is deliberately NOT a dataset field ──────────────────────

def test_state_and_last_spoke_are_not_dataset_fields():
    """They come from the signals layer, like node health. In the dataset they
    would mean a change-log entry and an atomic whole-file write per trip, and
    a writer racing the Desk for the same file."""
    fields = {f["name"] for f in schema.fields_of("stones")}
    assert "state" not in fields
    assert "last_spoke" not in fields


# ── A malformed stone is a problem, not a shrug ─────────────────────────────

def test_a_clean_stone_validates():
    assert validate(_data(_stone())) == []


def test_a_stone_missing_its_name_is_a_problem():
    bad = _stone()
    del bad["name"]
    assert validate(_data(bad)) != []


def test_a_stone_with_an_unknown_zone_is_a_problem():
    """Zone decides the escalation policy. A junk value would match neither the
    internal rule nor the wan one, so it must never validate."""
    problems = validate(_data(_stone(zone="lan")))
    assert problems and any("zone" in p for p in problems)


def test_a_stone_with_an_unknown_severity_is_a_problem():
    assert validate(_data(_stone(severity="apocalyptic"))) != []


def test_a_stone_with_an_unknown_kind_is_a_problem():
    assert validate(_data(_stone(kind="teleporter"))) != []


def test_two_stones_with_one_id_is_a_problem():
    """The live feed keys on `id`. Two stones sharing one means a trip cannot
    be attributed to a marker."""
    problems = validate(_data(_stone(), _stone(name="Other")))
    assert problems and any("duplicate" in p for p in problems)


def test_stones_must_be_a_list():
    assert validate({"stones": {"not": "a list"}}) != []


def test_a_dataset_with_no_stones_at_all_is_fine():
    """The section is optional. A realm that has planted nothing is not a
    realm with a broken dataset."""
    assert validate({}) == []


# ── The vocabularies match the engine's ─────────────────────────────────────

def test_zone_and_severity_vocabularies_match_the_decoy_feed():
    """These are duplicated across two repos by necessity — the Atlas cannot
    import from the decoy feed. Pinned here so a change on one side shows up as a test
    failure rather than as a stone the map refuses to draw."""
    assert schema.STONE_ZONES == ["internal", "wan"]
    assert schema.STONE_SEVERITIES == ["info", "low", "medium", "high", "critical"]


# ── The public demo must not carry the deception layout ────────────────────

def test_the_sanitizer_drops_stones_entirely():
    """Not redacts — drops. A scrubbed stone still discloses that deception
    exists here, how much of it there is, and roughly where. There is no
    version of this section that belongs on the internet."""
    src = os.path.join(os.path.dirname(WEB), "demo", "sanitize.py")
    if not os.path.exists(src):
        pytest.skip("demo/sanitize.py not in this checkout")
    body = open(src, encoding="utf-8").read()
    assert 'data.pop("stones", None)' in body


def test_the_shipped_demo_dataset_carries_no_stones():
    demo = os.path.join(os.path.dirname(WEB), "demo", "lab-data.demo.json")
    if not os.path.exists(demo):
        pytest.skip("demo dataset not in this checkout")
    assert "stones" not in json.load(open(demo, encoding="utf-8"))
