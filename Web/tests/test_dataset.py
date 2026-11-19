"""The write path: operations, strictness, the change log, and the diff.

The Atlas could only ever write two small overlay files before this. Now a
button can rewrite the map, so the properties that matter are the ones that
stop that being frightening: a refused write changes nothing, a concurrent
write is refused rather than merged, every change is reversible, and a save
touches only the lines it meant to.

That last one is not cosmetic. The dataset is tracked in git and reviewed by
eye (DATA.md); a save that rewrote all 1285 lines would bury every real change
in noise, which is exactly what Python's newline translation did on Windows
before `jsonio` pinned it.
"""

import copy
import json
import os
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

import dataset as ds  # noqa: E402
from dataset import ConflictError, FileDatasetStore, RejectedError  # noqa: E402

BUNDLED = os.path.join(WEB, "default-lab-data.json")


@pytest.fixture
def store(tmp_path):
    """A store over a throwaway copy of the bundled dataset."""
    path = tmp_path / "lab-data.json"
    with open(BUNDLED, encoding="utf-8") as fh:
        path.write_text(fh.read(), encoding="utf-8", newline="")
    return FileDatasetStore(str(path), BUNDLED, str(tmp_path / "revisions"))


def a_node(nid="testhold", **over):
    out = {"id": nid, "name": nid.upper(), "kind": "physical", "zone": "sky",
           "x": 10.0, "y": 10.0, "role": "a test · nothing more",
           "lore": "It exists only to be deleted."}
    out.update(over)
    return out


# ── a save over problems already on the map (2026-11-15) ────────────────────
# An import or a hand edit of the file can leave the map with problems; the
# write path refused every later save until they were mended, though a save
# writes one entry. It refuses what a save introduces, and what is still wrong
# in an entry it wrote; what was already there is let through and logged.

def _dirty(store, *nodes):
    data, _ = store.read()
    data["nodes"].extend(nodes)
    with open(store.path, "w", encoding="utf-8", newline="") as fh:
        json.dump(data, fh, indent=2)
    return store.read()[1]


def test_an_unrelated_save_lands_over_problems_already_there(store):
    stamp = _dirty(store, a_node("old-one", role=""), a_node("old-two", role=""))
    store.apply([{"op": "upsert", "section": "nodes", "id": "old-one", "body": {"role": "mended"}}],
                expect=stamp)
    data, stamp = store.read()
    assert next(n for n in data["nodes"] if n["id"] == "old-one")["role"] == "mended"
    # the other is still broken, and an edit elsewhere still lands
    store.apply([{"op": "upsert", "section": "nodes", "id": "testless", "body": a_node("testless")}],
                expect=stamp)


def test_a_new_problem_is_refused_and_named_alone(store):
    stamp = _dirty(store, a_node("old-one", role=""))
    with pytest.raises(RejectedError) as e:
        store.apply([{"op": "upsert", "section": "nodes", "id": "fresh",
                      "body": a_node("fresh", role="")}], expect=stamp)
    assert e.value.problems and all("'fresh'" in p for p in e.value.problems)


def test_an_entry_the_save_wrote_must_be_right_though_it_was_wrong_before(store):
    stamp = _dirty(store, a_node("old-one", role=""))
    with pytest.raises(RejectedError) as e:
        store.apply([{"op": "upsert", "section": "nodes", "id": "old-one",
                      "body": {"name": "RENAMED"}}], expect=stamp)
    assert any("'old-one'" in p for p in e.value.problems)


def test_a_save_over_an_old_problem_can_be_undone(store):
    """Its snapshot carries the old problem; the undo was refused for it
    (review, 2026-11-15)."""
    stamp = _dirty(store, a_node("old-one", role=""))
    out = store.apply([{"op": "upsert", "section": "nodes", "id": "testhold3",
                        "body": a_node("testhold3")}], expect=stamp)
    store.revert(out["revision"], actor="test")
    assert not any(n["id"] == "testhold3" for n in store.read()[0]["nodes"])


def test_a_deleted_entry_cannot_hand_its_old_problem_to_a_new_one(store):
    """Entries named by position: deleting the broken `route #N` and adding a
    new broken route that lands on #N kept the count and saved (review,
    2026-11-15). The entry under the name changed, so its problem is new."""
    data, _ = store.read()
    first, second = data["nodes"][0]["id"], data["nodes"][1]["id"]
    data.setdefault("routes", []).append({"from": first, "to": "ghost"})
    with open(store.path, "w", encoding="utf-8", newline="") as fh:
        json.dump(data, fh, indent=2)
    _, stamp = store.read()
    last = len(data["routes"]) - 1
    with pytest.raises(RejectedError):
        # another broken route with the same problem text at the same name,
        # then a clean route after it (an identical one would be no change)
        store.apply([{"op": "delete", "section": "routes", "index": last},
                     {"op": "insert", "section": "routes", "body": {"from": second, "to": "ghost"}},
                     {"op": "insert", "section": "routes", "body": {"from": first, "to": second}}],
                    expect=stamp)


def test_a_rename_onto_a_broken_names_problem_is_new(store):
    stamp = _dirty(store, a_node("c-old", role=""), a_node("a-new"))
    with pytest.raises(RejectedError):
        store.apply([{"op": "delete", "section": "nodes", "id": "c-old"},
                     {"op": "upsert", "section": "nodes", "id": "a-new",
                      "body": {"id": "c-old", "role": ""}}], expect=stamp)


def test_an_address_two_places_claim_does_not_block_an_edit_elsewhere(store):
    """The review's case (2026-11-15): an importer brought back a place at an
    address a hand-charted place had taken meanwhile."""
    # neutral ids: the public tree's demo lab has a place called `nas`
    stamp = _dirty(store, a_node("claim-x1", ip="10.250.0.5"), a_node("claim-x2", ip="10.250.0.5"))
    store.apply([{"op": "upsert", "section": "nodes", "id": "testhold2", "body": a_node("testhold2")}],
                expect=stamp)
    with pytest.raises(RejectedError):   # but a third claim is new
        store.apply([{"op": "upsert", "section": "nodes", "id": "claim-x3",
                      "body": a_node("claim-x3", ip="10.250.0.5")}], expect=store.read()[1])


# ── operations ──────────────────────────────────────────────────────────────

def test_insert_then_edit_then_remove(store):
    data, stamp = store.read()
    before = len(data["nodes"])

    result = store.apply([{"op": "insert", "section": "nodes", "body": a_node()}],
                         actor="tester", expect=stamp)
    assert result["changed"] == ["added node testhold"]
    assert len(store.read()[0]["nodes"]) == before + 1

    result = store.apply([{"op": "upsert", "section": "nodes", "id": "testhold",
                           "body": {"role": "edited · still a test"}}], actor="tester")
    assert result["changed"] == ["changed node testhold"]
    node = next(n for n in store.read()[0]["nodes"] if n["id"] == "testhold")
    assert node["role"] == "edited · still a test"
    assert node["name"] == "TESTHOLD", "an edit must not drop the fields it didn't mention"

    store.apply([{"op": "delete", "section": "nodes", "id": "testhold"}], actor="tester")
    assert len(store.read()[0]["nodes"]) == before


def test_an_explicit_null_clears_an_optional_field(store):
    store.apply([{"op": "insert", "section": "nodes",
                  "body": a_node(hue="#ff0000")}], actor="t")
    store.apply([{"op": "upsert", "section": "nodes", "id": "testhold",
                  "body": {"hue": None}}], actor="t")
    node = next(n for n in store.read()[0]["nodes"] if n["id"] == "testhold")
    assert "hue" not in node


def test_unknown_keys_survive_an_edit(store):
    """The dataset is allowed to be richer than the catalogue."""
    store.apply([{"op": "insert", "section": "nodes",
                  "body": {**a_node(), "some_future_key": {"deep": True}}}], actor="t")
    store.apply([{"op": "upsert", "section": "nodes", "id": "testhold",
                  "body": {"name": "RENAMED"}}], actor="t")
    node = next(n for n in store.read()[0]["nodes"] if n["id"] == "testhold")
    assert node["some_future_key"] == {"deep": True}


def test_index_addressed_sections(store):
    """Roads have no id, so they are addressed by position."""
    data, stamp = store.read()
    n = len(data["routes"])
    store.apply([{"op": "insert", "section": "routes",
                  "body": {"from": "app-host", "to": "gateway", "kind": "vlan"}}],
                actor="t", expect=stamp)
    store.apply([{"op": "upsert", "section": "routes", "index": n,
                  "body": {"kind": "mesh"}}], actor="t")
    assert store.read()[0]["routes"][n]["kind"] == "mesh"
    store.apply([{"op": "delete", "section": "routes", "index": n}], actor="t")
    assert len(store.read()[0]["routes"]) == n


def test_a_new_section_lands_where_the_catalogue_says(store):
    """A dataset is read by people; order is part of how it reads."""
    store.apply([{"op": "insert", "section": "prefixes",
                  "body": {"id": "p", "cidr": "10.0.0.0/24"}}], actor="t")
    keys = list(store.read()[0].keys())
    assert keys.index("zones") < keys.index("prefixes") < keys.index("rack")


# ── refusals ────────────────────────────────────────────────────────────────

def test_an_invalid_write_is_refused_whole_and_changes_nothing(store):
    _, stamp = store.read()
    with pytest.raises(RejectedError) as caught:
        store.apply([
            {"op": "insert", "section": "nodes", "body": a_node("good")},
            {"op": "insert", "section": "nodes", "body": a_node("bad", zone="nowhere")},
        ], actor="t", expect=stamp)
    assert any("unknown zone" in p for p in caught.value.problems)
    assert store.read()[1] == stamp, "a refused batch must not have written anything"
    assert not any(n["id"] == "good" for n in store.read()[0]["nodes"])


def test_a_stale_stamp_is_a_conflict(store):
    _, stamp = store.read()
    store.apply([{"op": "insert", "section": "nodes", "body": a_node()}], actor="a")
    with pytest.raises(ConflictError):
        store.apply([{"op": "insert", "section": "nodes", "body": a_node("other")}],
                    actor="b", expect=stamp)


def test_an_empty_or_oversized_batch_is_refused(store):
    with pytest.raises(RejectedError):
        store.apply([], actor="t")
    with pytest.raises(RejectedError):
        store.apply([{"op": "insert", "section": "rites", "body": {}}] * 501, actor="t")


def test_an_unknown_section_or_operation_is_refused(store):
    with pytest.raises(RejectedError):
        store.apply([{"op": "insert", "section": "nope", "body": {}}], actor="t")
    with pytest.raises(RejectedError):
        store.apply([{"op": "obliterate", "section": "nodes", "id": "x"}], actor="t")


# ── referential integrity ───────────────────────────────────────────────────

def test_dependents_are_reported_before_a_delete(store):
    data, _ = store.read()
    deps = ds.dependents(data, "nodes", "gateway")
    assert deps, "the gateway is on plenty of roads"
    assert all(d["section"] and d["field"] for d in deps)


def test_deleting_something_depended_on_is_refused_without_cascade(store):
    with pytest.raises(RejectedError) as caught:
        store.apply([{"op": "delete", "section": "nodes", "id": "gateway"}], actor="t")
    assert any("unknown" in p for p in caught.value.problems)


def test_cascade_removes_roads_and_unhooks_optional_references(store):
    store.apply([{"op": "insert", "section": "nodes", "body": a_node()},
                 {"op": "insert", "section": "routes",
                  "body": {"from": "testhold", "to": "gateway", "kind": "vlan"}},
                 {"op": "insert", "section": "rack",
                  "body": {"u": "U1", "name": "Test", "node": "testhold"}}], actor="t")
    store.apply([{"op": "delete", "section": "nodes", "id": "testhold", "cascade": True}],
                actor="t")
    data = store.read()[0]
    assert not any(r["to"] == "testhold" for r in data["routes"]), "the road should be gone"
    slot = next(s for s in data["rack"] if s["name"] == "Test")
    assert "node" not in slot, "the rack slot is still a slot; it just lost its marker"


# ── the change log ──────────────────────────────────────────────────────────

def test_every_write_is_journalled_and_revertable(store):
    original = store.read()[1]
    store.apply([{"op": "insert", "section": "nodes", "body": a_node()}],
                actor="ops", note="a note")
    revisions = store.revisions()
    assert len(revisions) == 1
    assert revisions[0]["actor"] == "ops" and revisions[0]["note"] == "a note"
    assert revisions[0]["revertable"]

    store.revert(revisions[0]["id"], actor="ops")
    assert store.read()[1] == original, "revert must restore the exact document"
    assert len(store.revisions()) == 2, "a revert is itself a revision"


def test_reverting_to_a_pruned_snapshot_says_so(store):
    store.apply([{"op": "insert", "section": "nodes", "body": a_node()}], actor="t")
    os.remove(store._snapshot_path(1))
    assert store.revisions()[0]["revertable"] is False
    with pytest.raises(RejectedError) as caught:
        store.revert(1, actor="t")
    assert "pruned" in str(caught.value)


# ── what lands on disk ──────────────────────────────────────────────────────

def test_a_save_touches_only_the_lines_it_changed(store, tmp_path):
    original = (tmp_path / "lab-data.json").read_text(encoding="utf-8")
    # A place with no stamp yet, so the stamp arrives whole: the bundled
    # dataset is the live map, and places there gain stamps as they are edited.
    unstamped = [n["id"] for n in json.loads(original)["nodes"] if "provenance" not in n]
    assert unstamped, "every place in the bundled dataset is stamped; this test needs one that isn't"
    store.apply([{"op": "upsert", "section": "nodes", "id": unstamped[0],
                  "body": {"role": "changed · for the test"}}], actor="t")
    after = (tmp_path / "lab-data.json").read_text(encoding="utf-8")

    # The diff is the edited line and the place's own stamp (provenance.py), and
    # nothing else: no reformatting, no reordering, no other place touched.
    import difflib
    diff = [d for d in difflib.unified_diff(original.split("\n"), after.split("\n"), lineterm="", n=0)
            if d[:1] in "+-" and d[:3] not in ("+++", "---")]
    removed = [d[1:].strip() for d in diff if d[0] == "-"]
    added = [d[1:].strip() for d in diff if d[0] == "+"]
    stamp = [a for a in added if not a.startswith('"role"') and not a.startswith('"links"')
             and a not in ("],", "]")]
    assert len([r for r in removed if r.startswith('"role"')]) == 1
    assert len([a for a in added if a.startswith('"role"')]) == 1
    assert stamp[0] == '"provenance": {' and stamp[-1] in ("}", "},"), stamp
    assert all(s.startswith(('"changed_', '"reviewed', '"provenance"', "}")) for s in stamp), stamp
    assert len(removed) <= 2 and len(added) <= len(stamp) + 2, diff


def test_the_file_stays_lf_and_two_space_indented(store, tmp_path):
    store.apply([{"op": "insert", "section": "rites",
                  "body": {"name": "R", "cadence": "daily", "when": "03:00", "host": "h"}}],
                actor="t")
    raw = (tmp_path / "lab-data.json").read_bytes()
    assert b"\r\n" not in raw, "CRLF would rewrite every line against .gitattributes eol=lf"
    assert raw.startswith(b'{\n  "'), "indent must stay at two spaces"
    assert raw.endswith(b"}\n")


def test_a_no_op_save_is_byte_identical(store, tmp_path):
    original = (tmp_path / "lab-data.json").read_bytes()
    data, _ = store.read()
    store._save(copy.deepcopy(data))
    assert (tmp_path / "lab-data.json").read_bytes() == original


def test_utf8_survives_the_round_trip(store, tmp_path):
    store.apply([{"op": "insert", "section": "nodes",
                  "body": a_node(role="a test · with an em—dash", lore="→ and an arrow")}],
                actor="t")
    raw = (tmp_path / "lab-data.json").read_text(encoding="utf-8")
    assert "·" in raw and "—" in raw and "→" in raw
    assert "\\u" not in raw, "the dataset is UTF-8, not escaped ASCII"


# ── the unseeded case ───────────────────────────────────────────────────────

def test_a_fresh_install_does_not_fork_the_bundled_map(tmp_path, monkeypatch):
    """The whole point of ATLAS_FALLBACK=empty: your first save is *yours*."""
    import settings
    monkeypatch.setattr(settings, "FALLBACK", "empty")
    path = tmp_path / "nothing-here.json"
    store = FileDatasetStore(str(path), BUNDLED, str(tmp_path / "rev"))

    data, stamp = store.read()
    assert data["nodes"] == [] and data["zones"] == []

    store.apply([{"op": "insert", "section": "zones",
                  "body": {"id": "z", "name": "Z", "vlan": 1, "subnet": "10.0.0.0/24",
                           "hue": "#ffffff", "lore": "l", "label_x": 1, "label_y": 2}}],
                actor="t", expect=stamp)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert len(written["zones"]) == 1
    assert written["nodes"] == [], "a fresh install must not inherit 17 strangers"


def test_the_bundled_fallback_is_still_available_when_asked_for(tmp_path, monkeypatch):
    import settings
    monkeypatch.setattr(settings, "FALLBACK", "bundled")
    store = FileDatasetStore(str(tmp_path / "none.json"), BUNDLED, str(tmp_path / "rev"))
    assert len(store.read()[0]["nodes"]) > 10


def test_a_deleted_place_leaves_no_pin_and_no_monitor_behind(store):
    """A region's pins are keyed by place id and `signals.kuma` maps a monitor
    to one: neither is a reference the catalogue can walk. The leftover pin
    was a problem the save refused, so a place shown on a region could not be
    deleted at all (audit 2026-11-12, Data 9)."""
    store.apply([{"op": "insert", "section": "nodes", "body": a_node()},
                 {"op": "insert", "section": "regions",
                  "body": {"id": "test-region", "name": "Test region", "map": "plain.webp",
                           "x": 10, "y": 10, "w": 20, "h": 20,
                           "places": {"testhold": {"x": 10, "y": 20}, "gateway": {"x": 30, "y": 40}}}}],
                actor="t")
    with open(store.path, encoding="utf-8") as fh:
        raw = json.load(fh)
    raw.setdefault("signals", {}).setdefault("kuma", {})["Testhold web"] = "testhold"
    with open(store.path, "w", encoding="utf-8") as fh:
        json.dump(raw, fh)
    store.apply([{"op": "delete", "section": "nodes", "id": "testhold", "cascade": True}],
                actor="t")
    data = store.read()[0]
    region = next(r for r in data["regions"] if r["id"] == "test-region")
    assert region["places"] == {"gateway": {"x": 30, "y": 40}}
    assert "Testhold web" not in data["signals"]["kuma"]
    assert not any(n.get("id") == "testhold" for n in data["nodes"])
