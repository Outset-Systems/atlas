"""COLLECTIONS: a named list of places, in a dataset section of its own.

Born 2026-11-13 as SETS and renamed 2026-11-14 (the owner's word). What the
places table and the alerts lean on: the catalogue knows the section, a member
that does not exist is a problem, the Desk's one write path adds and removes
collections, and a viewer is never told about a place they may not see,
through a collection's members or through its words. A collection is not
access. A map, a rule or an import that still says `sets` keeps working.
"""

import json

import pytest

import viewers

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts"}

COLLECTION = {"id": "core-set", "name": "Core boxes", "places": ["alpha", "secret-place"],
              "note": "what the middle runs on"}


@pytest.fixture
def realm(tmp_path, monkeypatch):
    handle = viewers.build(tmp_path, monkeypatch, viewers.dataset(collections=[COLLECTION]))
    yield handle
    monkeypatch.undo()


def _ops(client, ops):
    stamp = client.get("/api/v2/admin/context").get_json()["stamp"]
    return client.post("/api/v2/admin/ops", headers=viewers.W,
                       json={"ops": ops, "expect": stamp, "note": "collections"})


def _on_disk(client):
    return client.get("/api/v2/admin/dataset").get_json()["data"]


# ── the catalogue ────────────────────────────────────────────────────────────

def test_the_section_is_catalogued():
    import schema
    s = schema.get("collections")
    assert (s["singular"], s["plural"], s["store"], s["id_field"]) == (
        "collection", "collections", "dataset", "id")
    assert "Not access" in s["subtitle"]
    fields = {f["name"]: f for f in s["fields"]}
    assert fields["id"]["type"] == "slug" and fields["id"]["required"]
    assert fields["name"]["required"]
    assert fields["places"]["type"] == "strings" and fields["places"]["ref"] == "nodes"
    assert fields["places"]["label"] == "Places" and not fields["places"]["required"]
    assert fields["note"]["type"] == "longtext"
    # the Desk and validation walk the order; the file and the reference walk the other
    assert "collections" in schema.SECTION_ORDER and "collections" in schema.FILE_ORDER
    assert "collections" in schema.catalogue()["sections"]
    # the old name is no section of its own any more
    assert schema.get("sets") is None and "sets" not in schema.SECTION_ORDER


def test_a_dangling_member_is_a_problem():
    import validation
    data = viewers.dataset(collections=[{"id": "s", "name": "S", "places": ["alpha", "ghost"]}])
    assert validation.validate(data) == ["collection 's': unknown places 'ghost'"]


def test_a_map_with_no_collections_is_unchanged():
    import validation
    assert validation.validate(viewers.dataset()) == []


# ── the old name, `sets` ─────────────────────────────────────────────────────

def test_upgrade_moves_the_old_section_to_the_new_name():
    import schema
    data = {"nodes": [], "sets": [COLLECTION]}
    assert schema.upgrade(data) is data
    assert data == {"nodes": [], "collections": [COLLECTION]}


def test_upgrade_with_both_names_keeps_the_new_and_adds_what_only_the_old_had():
    import schema
    data = {"collections": [{"id": "a", "name": "A"}],
            "sets": [{"id": "a", "name": "old A"}, {"id": "b", "name": "B"}]}
    schema.upgrade(data)
    assert data == {"collections": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]}


def test_upgrade_keeps_the_section_where_it_stood_in_the_file():
    """A hand-edited map must not see a whole block move on its first save."""
    import schema
    data = {"meta": {}, "nodes": [], "sets": [COLLECTION], "certs": [], "stones": []}
    assert list(schema.upgrade(data)) == ["meta", "nodes", "collections", "certs", "stones"]
    both = {"collections": [{"id": "a", "name": "A"}], "nodes": [], "sets": [{"id": "b", "name": "B"}]}
    assert list(schema.upgrade(both)) == ["collections", "nodes"]


def test_upgrade_of_a_shallow_copy_never_changes_the_callers_lists():
    """`validate` and the db import pass `dict(data)`: the caller's own
    `collections` list must not grow (the 2026-11-14 review)."""
    import schema
    mine = [{"id": "a", "name": "A"}]
    data = {"collections": mine, "sets": [{"id": "b", "name": "B"}]}
    out = schema.upgrade(dict(data))
    assert [c["id"] for c in out["collections"]] == ["a", "b"]
    assert mine == [{"id": "a", "name": "A"}] and data["sets"] == [{"id": "b", "name": "B"}]


def test_upgrade_prefers_a_good_old_list_over_a_broken_new_value():
    import schema
    assert schema.upgrade({"collections": "junk", "sets": [COLLECTION]}) == {"collections": [COLLECTION]}
    assert schema.upgrade({"collections": [COLLECTION], "sets": "junk"}) == {"collections": [COLLECTION]}


def test_redaction_reads_an_old_section_name_rather_than_passing_it_through():
    """The belt behind every loader: a `sets` section reaching `redact` must
    not carry a hidden member or a name that gives one away (the review's
    first finding, through the multi-site db route)."""
    import redaction
    data = viewers.dataset(sets=[COLLECTION, {"id": "x", "name": "secret-place and co", "places": ["alpha"]}])
    out, _ = redaction.redact(data, set())
    assert "sets" not in out
    assert out["collections"] == [{**COLLECTION, "places": ["alpha"]}]
    assert "secret-place" not in json.dumps(out)


def test_upgrade_leaves_what_it_cannot_read_for_the_validator():
    import schema
    assert schema.upgrade(None) is None
    assert schema.upgrade(["not", "a", "map"]) == ["not", "a", "map"]
    data = {"sets": "a string"}
    assert schema.upgrade(data) == {"collections": "a string"}
    assert schema.upgrade({"nodes": []}) == {"nodes": []}


def test_validation_reads_the_old_name_without_touching_the_callers_map():
    import validation
    data = viewers.dataset(sets=[{"id": "s", "name": "S", "places": ["alpha", "ghost"]}])
    assert validation.validate(data) == ["collection 's': unknown places 'ghost'"]
    assert "sets" in data and "collections" not in data


def test_a_map_file_that_says_sets_is_served_as_collections_and_saved_back_renamed(tmp_path, monkeypatch):
    handle = viewers.build(tmp_path, monkeypatch, viewers.dataset(sets=[COLLECTION]))
    try:
        admin = viewers.signed_in(handle, "ops")
        body = admin.get("/api/v2/lab-data").get_json()
        assert body["collections"] == [COLLECTION] and "sets" not in body
        roster = admin.get("/api/v2/places/roster").get_json()
        assert roster["collections"][0]["id"] == "core-set"
        assert {r["id"]: r["collections"] for r in roster["rows"]}["alpha"] == ["core-set"]
        # the next save writes today's name, and only today's
        r = _ops(admin, [{"op": "upsert", "section": "collections", "id": "core-set",
                          "body": {"name": "Core"}}])
        assert r.status_code == 200, r.get_json()
        on_file = json.loads((tmp_path / "lab-data.json").read_text(encoding="utf-8"))
        assert "sets" not in on_file
        assert on_file["collections"] == [{**COLLECTION, "name": "Core"}]
    finally:
        monkeypatch.undo()


def test_a_db_site_stored_before_the_rename_dumps_under_the_new_name(tmp_path, monkeypatch):
    """A site whose settings were written while the section was `sets`: every
    reader goes through `dump_labdata`, the multi-site routes included."""
    monkeypatch.setenv("ATLAS_DB_URL", f"sqlite:///{(tmp_path / 'a.db').as_posix()}")
    import store
    from store.labdata import get_site
    store.reset_engine_for_tests()
    try:
        store.init_db()
        with store.session_scope() as session:
            store.load_labdata(session, viewers.dataset(collections=[COLLECTION]), site_slug="old")
        with store.session_scope() as session:
            site = get_site(session, "old")
            settings = dict(site.settings_json)
            settings["sets"] = settings.pop("collections")
            settings["_top_keys"] = ["sets" if k == "collections" else k for k in settings["_top_keys"]]
            site.settings_json = settings
        with store.session_scope() as session:
            raw = dict(get_site(session, "old").settings_json)
            assert "sets" in raw and "collections" not in raw, "the old shape is really stored"
            out = store.dump_labdata(session, "old")
        assert out["collections"] == [COLLECTION] and "sets" not in out
    finally:
        store.reset_engine_for_tests()


def test_the_db_import_stores_the_old_name_as_the_new(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DB_URL", f"sqlite:///{(tmp_path / 'a.db').as_posix()}")
    import store
    store.reset_engine_for_tests()
    try:
        store.init_db()
        with store.session_scope() as session:
            store.load_labdata(session, viewers.dataset(sets=[COLLECTION]), site_slug="default")
        with store.session_scope() as session:
            out = store.dump_labdata(session, "default")
        assert out["collections"] == [COLLECTION] and "sets" not in out
    finally:
        store.reset_engine_for_tests()


# ── the Desk's one write path ────────────────────────────────────────────────

def test_the_desk_adds_changes_and_removes_a_collection(realm):
    admin = viewers.signed_in(realm, "ops")
    new = {"id": "edge", "name": "Edge", "places": ["beta"]}
    assert _ops(admin, [{"op": "insert", "section": "collections", "body": new}]).status_code == 200
    found = {s["id"]: s for s in _on_disk(admin)["collections"]}
    assert found["edge"]["places"] == ["beta"]

    r = _ops(admin, [{"op": "upsert", "section": "collections", "id": "edge",
                      "body": {"places": ["alpha", "beta"]}}])
    assert r.status_code == 200, r.get_json()
    found = {s["id"]: s for s in _on_disk(admin)["collections"]}
    assert found["edge"]["places"] == ["alpha", "beta"] and found["edge"]["name"] == "Edge"

    assert _ops(admin, [{"op": "delete", "section": "collections", "id": "edge"}]).status_code == 200
    assert [s["id"] for s in _on_disk(admin)["collections"]] == ["core-set"]


def test_an_empty_collection_can_be_made_and_renamed(realm):
    """The rail's New collection sends a name and no places."""
    admin = viewers.signed_in(realm, "ops")
    r = _ops(admin, [{"op": "insert", "section": "collections", "body": {"id": "later", "name": "Later"}}])
    assert r.status_code == 200, r.get_json()
    r = _ops(admin, [{"op": "upsert", "section": "collections", "id": "later", "body": {"name": "Soon"}}])
    assert r.status_code == 200, r.get_json()
    later = {s["id"]: s for s in _on_disk(admin)["collections"]}["later"]
    assert later == {"id": "later", "name": "Soon"}
    roster = admin.get("/api/v2/places/roster").get_json()
    assert {"id": "later", "name": "Soon", "note": None, "unmanaged": False, "places": [], "services": []} in roster["collections"]


def test_a_revert_to_a_snapshot_from_before_the_rename_saves_the_new_name(realm):
    """The snapshot on disk says `sets` (written before the rename): the
    revert saves `collections`, and the stamp it answers is the one the next
    read gives (the review's fourth finding)."""
    admin = viewers.signed_in(realm, "ops")
    r = _ops(admin, [{"op": "upsert", "section": "collections", "id": "core-set", "body": {"name": "Core"}}])
    assert r.status_code == 200, r.get_json()
    store = realm.app.extensions["atlas"].store
    rev = store.revisions(limit=1)[0]["id"]
    path = store._snapshot_path(rev)
    with open(path, encoding="utf-8") as fh:
        snap = json.load(fh)
    snap["sets"] = snap.pop("collections")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snap, fh)
    stamp = admin.get("/api/v2/admin/context").get_json()["stamp"]
    r = admin.post(f"/api/v2/admin/revisions/{rev}/revert", headers=viewers.W, json={"expect": stamp})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["stamp"] == admin.get("/api/v2/admin/context").get_json()["stamp"]
    on_disk = _on_disk(admin)
    assert "sets" not in on_disk and on_disk["collections"] == [COLLECTION]


def test_a_write_naming_a_place_that_does_not_exist_is_refused(realm):
    admin = viewers.signed_in(realm, "ops")
    r = _ops(admin, [{"op": "upsert", "section": "collections", "id": "core-set",
                      "body": {"places": ["alpha", "ghost"]}}])
    assert r.status_code == 422
    assert any("ghost" in p for p in r.get_json()["problems"])


def test_deleting_a_place_takes_it_out_of_its_collections_and_keeps_the_collection(realm):
    admin = viewers.signed_in(realm, "ops")
    r = _ops(admin, [{"op": "delete", "section": "nodes", "id": "alpha", "cascade": True}])
    assert r.status_code == 200, r.get_json()
    assert _on_disk(admin)["collections"] == [{**COLLECTION, "places": ["secret-place"]}]


def test_a_token_cannot_write_a_collection(realm):
    token = viewers.issue(realm)
    c = realm.app.test_client()
    r = c.post("/api/v2/admin/ops", headers={**token, **viewers.W},
               json={"ops": [{"op": "delete", "section": "collections", "id": "core-set"}]})
    assert r.status_code != 200
    admin = viewers.signed_in(realm, "ops")
    assert [s["id"] for s in _on_disk(admin)["collections"]] == ["core-set"]


# ── who sees what ────────────────────────────────────────────────────────────

def test_a_hidden_member_is_dropped_and_the_collection_kept(realm):
    body = viewers.signed_in(realm, "alice").get("/api/v2/lab-data").get_json()
    assert body["collections"] == [{**COLLECTION, "places": ["alpha"]}]
    assert "secret-place" not in json.dumps(body)


def test_a_token_reads_the_same_cut(realm):
    body = realm.app.test_client().get("/api/v2/lab-data", headers=viewers.issue(realm)).get_json()
    assert body["collections"] == [{**COLLECTION, "places": ["alpha"]}]
    assert "secret-place" not in json.dumps(body)


def test_an_admin_sees_every_member(realm):
    body = viewers.signed_in(realm, "ops").get("/api/v2/lab-data").get_json()
    assert body["collections"] == [COLLECTION]


@pytest.mark.parametrize("words", [{"name": "Secret and friends"},
                                   {"note": "backs up secret-place nightly"},
                                   {"note": "reached at 192.0.2.99"}])
def test_a_collection_whose_words_name_a_hidden_place_goes_whole(words):
    import redaction
    data = viewers.dataset(collections=[{**COLLECTION, **words},
                                        {"id": "plain", "name": "Plain", "places": ["beta"]}])
    out, _ = redaction.redact(data, set())
    assert [s["id"] for s in out["collections"]] == ["plain"]
    # an admin keeps it
    assert len(redaction.redact(data, None)[0]["collections"]) == 2


@pytest.mark.parametrize("cid", ["secret-place-backups", "vault-box-backups", "vault_box", "cafe-server-pool"])
def test_a_collection_whose_id_names_a_hidden_place_goes_whole(cid):
    """The id is made from the first name and a rename keeps it: "Vault box
    backups" renamed "Backups" still says vault-box in its id, though the
    hidden place is written "Vault Box" (rounds 3 and 4). The hidden places
    here have ids unrelated to their names, so only the slugged name can
    catch the last three."""
    import redaction
    data = viewers.dataset(collections=[{"id": cid, "name": "Backups", "places": ["alpha"]},
                                        {"id": "plain", "name": "Plain", "places": ["beta"]}])
    data["nodes"] += [viewers.place("nas01", "Vault Box", require_group=viewers.GROUP),
                      viewers.place("srv7", "Café Server", require_group=viewers.GROUP)]
    out, _ = redaction.redact(data, set())
    assert [s["id"] for s in out["collections"]] == ["plain"], cid
    # a viewer who may see them keeps it
    assert len(redaction.redact(data, None)[0]["collections"]) == 2


@pytest.mark.parametrize("hidden_name", ["Сервер 1", "C++", "AB"])
def test_a_hidden_name_whose_slug_loses_letters_withholds_nothing_extra(hidden_name):
    """"Сервер 1" slugs to "1": it must not withhold every "Tier 1" (round 5).
    The name as written is still matched exactly."""
    import redaction
    data = viewers.dataset(collections=[{"id": "tier-1", "name": "Tier 1", "places": ["alpha"]},
                                        {"id": "c-tools", "name": "C tools", "places": ["alpha"]},
                                        {"id": "ab-test", "name": "AB test", "places": ["alpha"]}])
    data["nodes"].append(viewers.place("srv9", hidden_name, require_group=viewers.GROUP))
    out, _ = redaction.redact(data, set())
    ids = [s["id"] for s in out["collections"]]
    assert "tier-1" in ids and "c-tools" in ids
    if hidden_name == "AB":
        assert "ab-test" not in ids, "the exact name still withholds"


@pytest.mark.parametrize("hidden_name,cid", [("Søren NAS", "s-ren-nas-backups"),
                                              ("Straße Vault", "stra-e-vault-copies")])
def test_a_name_with_letters_nfkd_cannot_spell_still_hides_its_slug(hidden_name, cid):
    """The rail slugs "Søren" to `s-ren` too; round 5 had stopped matching
    such names, which reopened round 4's leak (round 6)."""
    import redaction
    data = viewers.dataset(collections=[{"id": cid, "name": "Backups", "places": ["alpha"]}])
    data["nodes"].append(viewers.place("nas01", hidden_name, require_group=viewers.GROUP))
    out, _ = redaction.redact(data, set())
    assert out["collections"] == []


def test_an_address_slug_never_withholds_a_date():
    import redaction
    data = viewers.dataset(collections=[{"id": "night-run", "name": "Night run",
                                         "note": "last run 2026-10-12 13:45", "places": ["alpha"]}])
    data["nodes"].append(viewers.place("ip9", "Box", ip="10.12.13.45", require_group=viewers.GROUP))
    out, _ = redaction.redact(data, set())
    assert [c["id"] for c in out["collections"]] == ["night-run"]


#: Every slug case rounds 4 to 7 of the 2026-11-14 review found, both ways:
#: (hidden place's name, ip, the collection's id, name, note, withheld?)
SLUG_CASES = [
    # an id the rail made from a name that names a hidden place: withheld
    ("Vault Box", "", "vault-box-backups", "Backups", "", True),
    ("Vault Box", "", "vault_box", "Backups", "", True),
    ("Café Server", "", "cafe-server-pool", "Pool", "", True),
    ("Søren NAS", "", "s-ren-nas-backups", "Backups", "", True),
    ("Straße Vault", "", "stra-e-vault-copies", "Copies", "", True),
    # free text that names it, any spacing: withheld
    ("Vault Box", "", "spare", "Spare", "mirror of vault-box", True),
    ("Rack (A)", "", "spare", "Spare", "Rack(A) spare parts", True),
    ("Core Switch", "", "spare", "Spare", "mirror of core-switch", True),
    # a list of two visible names next to a hidden two-word name: shown
    ("Core Switch", "", "spare", "Spare", "kept for: Core, Switch", False),
    # a name whose slug would lose a word, be under 3 or have no letter: shown
    ("東京 Alpha", "", "alpha-team", "Alpha team", "", False),
    ("Сервер Lab", "", "lab-tools", "Lab tools", "", False),
    ("Сервер 1", "", "tier-1", "Tier 1", "", False),
    ("C++", "", "c-tools", "C tools", "", False),
    ("Box", "10.12.13.45", "night-run", "Night run", "last run 2026-10-12 13:45", False),
    # a name that only shares letters: shown
    ("Vault", "", "vaulted-ceilings", "Vaulted ceilings", "", False),
    # two fields never join: shown
    ("Lab core", "", "lab", "Core switches", "", False),
    # round 8: a hidden name with list marks, written with dashes or spaces: withheld
    ("NAS (Backup)", "", "spare", "Spare", "mirror of nas-backup", True),
    ("Pi-hole (DNS)", "", "spare", "Spare", "Pi-hole DNS copy", True),
    # an id the rail made from a name with list marks: only the id match catches it
    ("Rack (A)", "", "rack-a-spares", "Spares", "", True),
    # round 8: another script with no space before the Latin word: shown
    ("東京Alpha", "", "alpha-team", "Alpha team", "", False),
    ("客厅NAS", "", "nas", "NAS", "书房NAS spare", False),
    # round 9: the rail lowercases before NFKD (™ -> nothing there): withheld
    ("NAS™ Box", "", "nas-box-backups", "Backups", "", True),
    # round 9: an emoji or a digit of another script would shrink the name: shown
    ("🔒 Alpha", "", "alpha-team", "Alpha team", "", False),
    ("٣ Alpha", "", "alpha-team", "Alpha team", "", False),
    # round 10: a symbol with two or more words left still names the place: withheld
    ("📺 Living Room TV", "", "living-room-tv-backups", "Backups", "", True),
    ("📺 Living Room TV", "", "spare", "Living Room TV streaming", "", True),
    ("Acme® Router", "", "acme-router-backups", "Backups", "", True),
    # round 11: an apostrophe written or left out: withheld both ways
    ("Dad's PC", "", "spare", "Spare", "dads pc backups", True),
    ("Dad's PC", "", "dads-pc-backups", "Backups", "", True),
    ("Dads PC", "", "spare", "Spare", "Dad's PC backups", True),
    # round 12: the curly and the modifier apostrophe are the same mark
    ("Dad\u2019s PC", "", "spare", "Spare", "Dads PC backups", True),
    ("Dad\u02bcs PC", "", "dad-s-pc-backups", "Backups", "", True),
    # round 12: a symbol name whose stripped form is one word gives no slug
    ("🔒 Mom's", "", "moms-laptop", "Moms laptop", "", False),
]


@pytest.mark.parametrize("hidden_name,ip,cid,name,note,withheld", SLUG_CASES)
def test_the_slug_rules_hold_for_every_case_the_reviews_found(hidden_name, ip, cid, name, note, withheld):
    import redaction
    data = viewers.dataset(collections=[{"id": cid, "name": name, "note": note, "places": ["alpha"]}])
    data["nodes"].append(viewers.place("h1", hidden_name, ip=ip or None, require_group=viewers.GROUP))
    out, _ = redaction.redact(data, set())
    assert (out["collections"] == []) is withheld, (hidden_name, cid, name, note)


def test_a_hidden_place_with_a_number_for_an_id_stays_hidden():
    """A hand edit's `"id": 7` on a hidden place (round 11: round 10 had let
    it through routes and collection members)."""
    import redaction
    data = viewers.dataset(collections=[{"id": "c", "name": "C", "places": ["alpha", 7]}],
                           routes=[{"id": "r", "from": "alpha", "to": 7}])
    data["nodes"].append({**viewers.place("x", "Seven", require_group=viewers.GROUP), "id": 7})
    assert 7 in redaction.hidden_node_ids(data, set())
    out, _ = redaction.redact(data, set())
    assert out["collections"][0]["places"] == ["alpha"]
    assert all(r.get("to") != 7 for r in out.get("routes") or [])


def test_a_number_id_is_hidden_where_it_is_written_as_text():
    """JSON keys are text: a hidden place 7's region pin is "7" (round 12)."""
    import redaction
    data = viewers.dataset(collections=[{"id": "c", "name": "C", "places": ["alpha", "7"]}],
                           regions=[{"id": "r", "name": "R", "places": {"7": [1, 2], "alpha": [3, 4]}}])
    data["nodes"].append({**viewers.place("x", "Seven", require_group=viewers.GROUP), "id": 7})
    out, _ = redaction.redact(data, set())
    assert out["collections"][0]["places"] == ["alpha"]
    assert out["regions"][0]["places"] == {"alpha": [3, 4]}


@pytest.mark.parametrize("section", ["collections", "sets", "zones", "regions", "routes", "rites",
                                     "nodes", "links", "monitors"])
def test_a_list_section_written_as_a_number_never_takes_the_atlas_down(tmp_path, monkeypatch, section):
    """Validation only warns, so the map is served: every read, a restricted
    viewer's included, and the annals' poll that carries the alerts must
    answer (round 13: these raised before the alert tick was reached; round
    14: `nodes`, a place's `links` and `monitors`)."""
    import annalist
    data = viewers.dataset()
    if section in ("links", "monitors"):
        data["nodes"][0][section] = 5
    else:
        data[section] = 5
    handle = viewers.build(tmp_path, monkeypatch, data)
    try:
        for who in ("ops", "alice"):
            client = viewers.signed_in(handle, who)
            for path in ("/api/v2/lab-data", "/api/v2/signals", "/api/v2/places/roster"):
                assert client.get(path).status_code == 200, (section, who, path)
        assert annalist.poll_once(handle.app) is True
    finally:
        monkeypatch.undo()


def _odd_list_id(data):
    data["collections"] = [{"id": ["a"], "name": "Odd"}]


def _odd_node_id(data):
    data["nodes"].append({"id": {}, "name": "Odd", "zone": "core", "x": 1, "y": 1})


def _odd_kuma(data):
    data["nodes"][0]["links"] = [{"label": "UI", "url": "https://a.example", "kuma": ["a"]}]


def _odd_drift(data):
    data["signals"] = {"drift_ignore": 5}


@pytest.mark.parametrize("edit", [_odd_list_id, _odd_node_id, _odd_kuma, _odd_drift])
def test_odd_ids_and_monitor_keys_never_take_the_atlas_down(tmp_path, monkeypatch, edit):
    """Round 15: a list or object id raised in validation's duplicate check,
    a link's list `kuma` in the monitor keys, a number `drift_ignore` in the
    drift; each through every read and the annals' poll."""
    import annalist
    data = viewers.dataset()
    edit(data)
    handle = viewers.build(tmp_path, monkeypatch, data)
    try:
        for who in ("ops", "alice"):
            client = viewers.signed_in(handle, who)
            for path in ("/api/v2/lab-data", "/api/v2/signals", "/api/v2/places/roster"):
                assert client.get(path).status_code == 200, (edit.__name__, who, path)
        assert annalist.poll_once(handle.app) is True
    finally:
        monkeypatch.undo()


def test_a_monitor_on_a_hidden_place_written_another_way_is_withheld():
    import redaction
    data = viewers.dataset()
    data["signals"] = {"kuma": {"Secret": "SECRET-PLACE", "Alpha": "alpha"}, "drift_ignore": ["Secret"]}
    seen = redaction.visible_monitors(data, set())
    assert "Alpha" in seen and "Secret" not in seen
    out, _ = redaction.redact(data, set())
    assert "drift_ignore" not in out["signals"] and "Secret" not in json.dumps(out)
    # an admin keeps the operator's list
    assert redaction.redact(data, None)[0]["signals"]["drift_ignore"] == ["Secret"]


def test_the_drift_reads_only_text_names():
    from types import SimpleNamespace
    from api.v2 import feeds
    for odd in (5, [["x"]], [{"a": 1}], "x"):
        ctx = SimpleNamespace(dataset=lambda odd=odd: ({"nodes": [], "signals": {"drift_ignore": odd}}, 0, []))
        assert feeds._drift(ctx, {"services": {"m1": {}}})["uncharted"] == ["m1"]
    ctx = SimpleNamespace(dataset=lambda: ({"nodes": [], "signals": 5}, 0, []))
    assert feeds._drift(ctx, {"services": {"m1": {}}})["uncharted"] == ["m1"]


def test_an_upsert_cannot_move_a_collection_onto_an_id_a_rule_still_names(realm):
    """Round 15: the guard checked only inserts; the Desk can edit an id."""
    import json as _json
    import settings
    with open(settings.ALERTS_PATH, "w", encoding="utf-8") as fh:
        _json.dump({"rules": [{"id": "r-c", "name": "R", "note": "", "enabled": True,
                               "target": {"kind": "collection", "id": "gone"}, "to": ["down"],
                               "for_minutes": 0, "destination": "d"}],
                    "digest": {}, "destinations": []}, fh)
    admin = viewers.signed_in(realm, "ops")
    r = _ops(admin, [{"op": "upsert", "section": "collections", "id": "core-set", "body": {"id": "gone"}}])
    assert r.status_code == 422
    r = _ops(admin, [{"op": "upsert", "section": "collections", "id": "gone", "body": {"name": "Gone"}}])
    assert r.status_code == 422


def test_a_member_written_another_way_never_reaches_a_restricted_viewer(realm):
    """"SECRET-PLACE" is no place's id, so the reference walker kept it; a
    collection now lists only visible places for such a viewer (round 13)."""
    import redaction
    data = viewers.dataset(collections=[{"id": "c", "name": "C",
                                         "places": ["alpha", "SECRET-PLACE", " secret-place", "beta"]}])
    out, _ = redaction.redact(data, set())
    assert out["collections"][0]["places"] == ["alpha", "beta"]
    # an admin keeps the entry exactly as stored
    assert redaction.redact(data, None)[0]["collections"][0]["places"][1] == "SECRET-PLACE"


@pytest.mark.parametrize("spelling", ["SECRET-PLACE", " secret-place", "Secret-Place"])
def test_a_hidden_id_written_another_way_is_withheld_in_every_reference(spelling):
    """Round 13 fixed collections; round 14 found depends_on, a route's ends,
    a region pin and a certificate's place. While anything is hidden, a
    reference names a visible place or nothing."""
    import redaction
    data = viewers.dataset(
        routes=[{"from": "alpha", "to": spelling}, {"from": "alpha", "to": "beta"}],
        regions=[{"id": "g", "name": "G", "places": {spelling: [1, 2], "alpha": [3, 4]}}],
        certs=[{"name": "x.example", "kind": "tls", "issuer": "I", "expires": "2027-01-01", "place": spelling},
               {"name": "y.example", "kind": "tls", "issuer": "I", "expires": "2027-01-01", "place": "beta"}])
    data["nodes"][0]["depends_on"] = ["beta", spelling]
    out, _ = redaction.redact(data, set())
    text = json.dumps(out)
    assert spelling not in text, spelling
    assert out["nodes"][0]["depends_on"] == ["beta"]
    assert [r["to"] for r in out["routes"]] == ["beta"]
    assert out["regions"][0]["places"] == {"alpha": [3, 4]}
    assert [c["name"] for c in out["certs"]] == ["y.example"]
    # an admin sees it all, as stored
    assert spelling in json.dumps(redaction.redact(data, None)[0])


def test_a_new_collection_cannot_take_an_id_an_alert_rule_still_names(realm):
    """Removing a collection suspends its rules; inserting the same id from
    anywhere would quietly revive them (round 14: the server refuses)."""
    import json as _json
    import settings
    with open(settings.ALERTS_PATH, "w", encoding="utf-8") as fh:
        _json.dump({"rules": [{"id": "r-c", "name": "R", "note": "", "enabled": True,
                               "target": {"kind": "collection", "id": "gone"}, "to": ["down"],
                               "for_minutes": 0, "destination": "d"}],
                    "digest": {}, "destinations": []}, fh)
    admin = viewers.signed_in(realm, "ops")
    r = _ops(admin, [{"op": "insert", "section": "collections", "body": {"id": "gone", "name": "Gone"}}])
    assert r.status_code == 422 and "alert rule" in r.get_json()["problems"][0]
    r = _ops(admin, [{"op": "insert", "section": "collections", "body": {"id": "gone-2", "name": "Gone"}}])
    assert r.status_code == 200, r.get_json()
    # an existing collection the rule watches is edited freely
    r = _ops(admin, [{"op": "upsert", "section": "collections", "id": "core-set", "body": {"name": "Core"}}])
    assert r.status_code == 200, r.get_json()


def test_the_annals_sequence_is_a_whole_number():
    import events
    assert events._shape({"seq": 3.5, "events": [{"id": 2}, {"id": 4}]})["seq"] == 4
    assert events._shape({"seq": "x", "events": []})["seq"] == 0
    assert events._shape({"seq": True, "events": [{"id": 9}]})["seq"] == 9
    assert events._shape({"seq": 12, "events": []})["seq"] == 12


def test_the_monitor_map_reads_only_text_pairs():
    import signals
    data = {"nodes": [{"id": "alpha", "monitors": ["a"]}],
            "signals": {"kuma": {"m": ["vault"], "n": "alpha", "o": 5}}}
    assert signals.monitor_map(data) == {"a": "alpha", "n": "alpha"}
    assert signals.monitor_map({"nodes": [], "signals": 5}) == {}
    assert signals.monitor_map({"nodes": [], "signals": {"kuma": ["x"]}}) == {}


def test_the_roster_reads_a_collections_section_that_is_not_a_list_as_none():
    from api.v2 import roster
    assert roster._collections({"collections": 5}) == []


def test_a_stray_node_never_breaks_the_other_restricted_reads():
    """`cleared` on a non-object is hidden, never a raise: monitors, feeds."""
    import redaction
    data = viewers.dataset()
    data["nodes"].append(["not", "a", "place"])
    assert redaction.cleared(["not a place"], set()) is False
    assert isinstance(redaction.visible_monitors(data, set()), set)
    data["nodes"].append({"id": ["a list"], "name": "Odd", "require_group": viewers.GROUP})
    assert "secret-place" in redaction.hidden_node_ids(data, set())


def test_a_node_that_is_not_an_object_never_breaks_redaction():
    """Validation only warns, so a stray entry is served (round 9)."""
    import redaction
    data = viewers.dataset(collections=[{"id": "c", "name": "C", "places": ["alpha"]}])
    data["nodes"].append("not a place")
    out, _ = redaction.redact(data, set())
    assert "secret-place" not in json.dumps(out)


def test_two_fields_joined_do_not_make_a_hidden_slug():
    """id `lab`, name "Core switches", and a hidden place `lab-core`: the
    gap between the two fields is no dash (round 5)."""
    import redaction
    data = viewers.dataset(collections=[{"id": "lab", "name": "Core switches", "places": ["alpha"]}])
    data["nodes"].append(viewers.place("lab-core", "Lab core", require_group=viewers.GROUP))
    out, _ = redaction.redact(data, set())
    assert [s["id"] for s in out["collections"]] == ["lab"]


def test_an_id_cut_at_48_characters_is_still_matched():
    import redaction
    long_name = "Primary storage array vault box secondary replica"
    cid = redaction.slug(long_name)[:48].strip("-")
    data = viewers.dataset(collections=[{"id": cid, "name": "Backups", "places": ["alpha"]}])
    data["nodes"].append(viewers.place("nas01", long_name, require_group=viewers.GROUP))
    out, _ = redaction.redact(data, set())
    assert out["collections"] == []


@pytest.mark.parametrize("regions", [{"id": "r", "places": {"secret-place": [1, 2]}},
                                     [{"id": "r", "name": "R", "places": ["secret-place", "alpha"]}]])
def test_regions_in_the_wrong_shape_reach_no_restricted_viewer(regions):
    import redaction
    data = viewers.dataset(regions=regions)
    out, _ = redaction.redact(data, set())
    assert "secret-place" not in json.dumps(out)


def test_an_access_group_that_is_not_text_hides_and_never_raises():
    import redaction
    data = viewers.dataset()
    data["nodes"][0]["require_group"] = ["ops"]
    data["nodes"][1]["links"] = "not a list"
    out, _ = redaction.redact(data, set())
    assert [n["id"] for n in out["nodes"]] == ["beta"]
    assert out["nodes"][0]["links"] == []
    assert redaction.cleared({"require_group": {"a": 1}}, {"a"}) is False


def test_a_name_that_only_shares_letters_with_a_hidden_place_stays():
    import redaction
    data = viewers.dataset(collections=[{"id": "vaulted-ceilings", "name": "Vaulted ceilings", "places": ["alpha"]}])
    data["nodes"].append(viewers.place("nas01", "Vault", require_group=viewers.GROUP))
    out, _ = redaction.redact(data, set())
    assert [s["id"] for s in out["collections"]] == ["vaulted-ceilings"]


@pytest.mark.parametrize("shape", [{"id": "misc", "places": ["secret-place", "alpha"]},
                                   ["secret-place", "alpha"], "secret-place"])
def test_a_collections_section_in_the_wrong_shape_reaches_no_restricted_viewer(shape):
    """Validation only warns, so a hand edit is served: a section that is not
    a list of objects must not pass redaction whole (round 4)."""
    import redaction
    data = viewers.dataset(collections=shape)
    out, _ = redaction.redact(data, set())
    assert "secret-place" not in json.dumps(out)


def test_upgrade_with_both_names_and_an_id_that_is_not_text_does_not_raise():
    import schema
    data = {"collections": [{"id": ["x"], "name": "A"}], "sets": [{"id": {"y": 1}, "name": "B"}, {"id": "c", "name": "C"}]}
    out = schema.upgrade(data)
    assert [c.get("name") for c in out["collections"]] == ["A", "B", "C"]


def test_a_member_written_as_one_string_is_judged_like_a_list():
    """A hand edit can write one id where a list belongs; validation only
    warns, so the file is served and the hidden id must not go with it (the
    11-12 audit's first redaction item)."""
    import redaction
    data = viewers.dataset(collections=[{"id": "one", "name": "One", "places": "secret-place"},
                                        {"id": "two", "name": "Two", "places": "alpha"}])
    data["nodes"][0]["depends_on"] = "secret-place"
    out, _ = redaction.redact(data, set())
    assert "secret-place" not in json.dumps(out)
    # read as one id, served as a list of visible members (round 13)
    assert out["collections"][1]["places"] == ["alpha"]
    assert "depends_on" not in out["nodes"][0]


def test_a_cloud_token_is_given_no_collections():
    """`withhold` passes the section through and `project` keeps only what it
    names, which does not include collections."""
    import cloud_view
    import redaction
    data = viewers.dataset(collections=[COLLECTION])
    marked = cloud_view.withhold(data)
    view = cloud_view.project(redaction.redact(marked, set(), True)[0],
                              redaction.hidden_words(marked, set()))
    assert "collections" not in view and "sets" not in view
