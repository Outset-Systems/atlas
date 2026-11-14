"""SETS (2026-11-13): a named list of places, in a dataset section of its own.

What the places table, and later the alerts, lean on: the catalogue knows the
section, a member that does not exist is a problem, the Desk's one write path
adds and removes sets, and a viewer is never told about a place they may not
see, through a set's members or through its words. A set is not access.
"""

import json

import pytest

import viewers

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts"}

SET = {"id": "core-set", "name": "Core boxes", "places": ["alpha", "secret-place"],
       "note": "what the middle runs on"}


@pytest.fixture
def realm(tmp_path, monkeypatch):
    handle = viewers.build(tmp_path, monkeypatch, viewers.dataset(sets=[SET]))
    yield handle
    monkeypatch.undo()


def _ops(client, ops):
    stamp = client.get("/api/v2/admin/context").get_json()["stamp"]
    return client.post("/api/v2/admin/ops", headers=viewers.W,
                       json={"ops": ops, "expect": stamp, "note": "sets"})


# ── the catalogue ────────────────────────────────────────────────────────────

def test_the_section_is_catalogued():
    import schema
    s = schema.get("sets")
    assert (s["singular"], s["plural"], s["store"], s["id_field"]) == ("set", "sets", "dataset", "id")
    assert "Not access" in s["subtitle"]
    fields = {f["name"]: f for f in s["fields"]}
    assert fields["id"]["type"] == "slug" and fields["id"]["required"]
    assert fields["name"]["required"]
    assert fields["places"]["type"] == "strings" and fields["places"]["ref"] == "nodes"
    assert fields["places"]["label"] == "Places" and not fields["places"]["required"]
    assert fields["note"]["type"] == "longtext"
    # the Desk and validation walk the order; the file and the reference walk the other
    assert "sets" in schema.SECTION_ORDER and "sets" in schema.FILE_ORDER
    assert "sets" in schema.catalogue()["sections"]


def test_a_dangling_member_is_a_problem():
    import validation
    data = viewers.dataset(sets=[{"id": "s", "name": "S", "places": ["alpha", "ghost"]}])
    assert validation.validate(data) == ["set 's': unknown places 'ghost'"]


def test_a_map_with_no_sets_is_unchanged():
    import validation
    assert validation.validate(viewers.dataset()) == []


# ── the Desk's one write path ────────────────────────────────────────────────

def test_the_desk_adds_changes_and_removes_a_set(realm):
    admin = viewers.signed_in(realm, "ops")
    new = {"id": "edge", "name": "Edge", "places": ["beta"]}
    assert _ops(admin, [{"op": "insert", "section": "sets", "body": new}]).status_code == 200
    sets = {s["id"]: s for s in admin.get("/api/v2/admin/dataset").get_json()["data"]["sets"]}
    assert sets["edge"]["places"] == ["beta"]

    r = _ops(admin, [{"op": "upsert", "section": "sets", "id": "edge",
                      "body": {"places": ["alpha", "beta"]}}])
    assert r.status_code == 200, r.get_json()
    sets = {s["id"]: s for s in admin.get("/api/v2/admin/dataset").get_json()["data"]["sets"]}
    assert sets["edge"]["places"] == ["alpha", "beta"] and sets["edge"]["name"] == "Edge"

    assert _ops(admin, [{"op": "delete", "section": "sets", "id": "edge"}]).status_code == 200
    sets = admin.get("/api/v2/admin/dataset").get_json()["data"]["sets"]
    assert [s["id"] for s in sets] == ["core-set"]


def test_a_write_naming_a_place_that_does_not_exist_is_refused(realm):
    admin = viewers.signed_in(realm, "ops")
    r = _ops(admin, [{"op": "upsert", "section": "sets", "id": "core-set",
                      "body": {"places": ["alpha", "ghost"]}}])
    assert r.status_code == 422
    assert any("ghost" in p for p in r.get_json()["problems"])


def test_deleting_a_place_takes_it_out_of_its_sets_and_keeps_the_set(realm):
    admin = viewers.signed_in(realm, "ops")
    r = _ops(admin, [{"op": "delete", "section": "nodes", "id": "alpha", "cascade": True}])
    assert r.status_code == 200, r.get_json()
    sets = admin.get("/api/v2/admin/dataset").get_json()["data"]["sets"]
    assert sets == [{**SET, "places": ["secret-place"]}]


def test_a_token_cannot_write_a_set(realm):
    token = viewers.issue(realm)
    c = realm.app.test_client()
    r = c.post("/api/v2/admin/ops", headers={**token, **viewers.W},
               json={"ops": [{"op": "delete", "section": "sets", "id": "core-set"}]})
    assert r.status_code != 200
    admin = viewers.signed_in(realm, "ops")
    assert [s["id"] for s in admin.get("/api/v2/admin/dataset").get_json()["data"]["sets"]] == ["core-set"]


# ── who sees what ────────────────────────────────────────────────────────────

def test_a_hidden_member_is_dropped_and_the_set_kept(realm):
    body = viewers.signed_in(realm, "alice").get("/api/v2/lab-data").get_json()
    assert body["sets"] == [{**SET, "places": ["alpha"]}]
    assert "secret-place" not in json.dumps(body)


def test_a_token_reads_the_same_cut(realm):
    body = realm.app.test_client().get("/api/v2/lab-data", headers=viewers.issue(realm)).get_json()
    assert body["sets"] == [{**SET, "places": ["alpha"]}]
    assert "secret-place" not in json.dumps(body)


def test_an_admin_sees_every_member(realm):
    body = viewers.signed_in(realm, "ops").get("/api/v2/lab-data").get_json()
    assert body["sets"] == [SET]


@pytest.mark.parametrize("words", [{"name": "Secret and friends"},
                                   {"note": "backs up secret-place nightly"},
                                   {"note": "reached at 192.0.2.99"}])
def test_a_set_whose_words_name_a_hidden_place_goes_whole(words):
    import redaction
    data = viewers.dataset(sets=[{**SET, **words}, {"id": "plain", "name": "Plain", "places": ["beta"]}])
    out, _ = redaction.redact(data, set())
    assert [s["id"] for s in out["sets"]] == ["plain"]
    # an admin keeps it
    assert len(redaction.redact(data, None)[0]["sets"]) == 2


def test_a_member_written_as_one_string_is_judged_like_a_list():
    """A hand edit can write one id where a list belongs; validation only
    warns, so the file is served and the hidden id must not go with it (the
    11-12 audit's first redaction item)."""
    import redaction
    data = viewers.dataset(sets=[{"id": "one", "name": "One", "places": "secret-place"},
                                 {"id": "two", "name": "Two", "places": "alpha"}])
    data["nodes"][0]["depends_on"] = "secret-place"
    out, _ = redaction.redact(data, set())
    assert "secret-place" not in json.dumps(out)
    assert out["sets"][1]["places"] == "alpha"
    assert "depends_on" not in out["nodes"][0]


def test_a_cloud_token_is_given_no_sets():
    """`withhold` passes the section through and `project` keeps only what it
    names, which does not include sets."""
    import cloud_view
    import redaction
    data = viewers.dataset(sets=[SET])
    marked = cloud_view.withhold(data)
    view = cloud_view.project(redaction.redact(marked, set(), True)[0],
                              redaction.hidden_words(marked, set()))
    assert "sets" not in view
