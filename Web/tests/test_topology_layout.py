"""TOPOLOGY's layout (2026-11-17): where an admin put each card, a door at a time.

`GET /api/v2/topology/layout` gives anyone who may see the map the cards of
the places and stubs on their own map; `POST` is an admin's, behind the same
gate as marker positions, with a stamp so two admins dragging at once cannot
lose each other's moves. Not map data: no revision is written.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import topology_layout as layout  # noqa: E402
import viewers  # noqa: E402
from viewers import W  # noqa: E402

URL = "/api/v2/topology/layout"

WIRING = {
    "stubs": [
        {"id": "line-in", "name": "Line in", "kind": "internet"},
        {"id": "closet-qq", "name": "Closet box", "kind": "switch"},
    ],
    "cables": [
        {"id": "c-line", "a_stub": "line-in", "b": "alpha"},
        {"id": "c-closet", "a_stub": "closet-qq", "b": "secret-place"},
    ],
}


@pytest.fixture
def realm(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_TOPOLOGY_LAYOUT", str(tmp_path / "topology-layout.json"))
    return viewers.build(tmp_path, monkeypatch, viewers.dataset(**WIRING))


@pytest.fixture
def admin(realm):
    return viewers.signed_in(realm, "ops")


@pytest.fixture
def alice(realm):
    return viewers.signed_in(realm, "alice")


def _file(tmp_path):
    return json.loads((tmp_path / "topology-layout.json").read_text(encoding="utf-8"))


def _everywhere(admin):
    body = admin.get(URL).get_json()
    cards = {k: {"x": 10.0 * i, "y": 5.0} for i, k in
             enumerate(["alpha", "beta", "secret-place", "line-in", "closet-qq"])}
    r = admin.post(URL, json={"cards": cards, "expect": body["stamp"]}, headers=W)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


# ── an admin writes ──────────────────────────────────────────────────────────

def test_an_admin_writes_and_reads_back(admin, tmp_path):
    first = admin.get(URL)
    assert first.status_code == 200
    body = first.get_json()
    assert body["v"] == 1 and body["cards"] == {} and isinstance(body["stamp"], str)
    r = admin.post(URL, json={"cards": {"alpha": {"x": 12.345, "y": -40}, "nowhere": {"x": 1, "y": 1}},
                              "expect": body["stamp"]}, headers=W)
    assert r.status_code == 200
    out = r.get_json()
    # an id that is no place or stub is not saved, and says so in the count
    assert (out["ok"], out["saved"], out["total"]) == (True, 1, 1)
    assert out["stamp"] != body["stamp"]
    assert _file(tmp_path) == {"v": 1, "cards": {"alpha": {"x": 12.3, "y": -40.0}}}
    again = admin.get(URL).get_json()
    assert again["cards"] == {"alpha": {"x": 12.3, "y": -40.0}} and again["stamp"] == out["stamp"]


def test_null_forgets_a_card_and_replace_throws_the_layout_away(admin, tmp_path):
    out = _everywhere(admin)
    assert out["total"] == 5
    r = admin.post(URL, json={"cards": {"beta": None}, "expect": out["stamp"]}, headers=W)
    assert r.get_json()["total"] == 4 and "beta" not in _file(tmp_path)["cards"]
    r = admin.post(URL, json={"cards": {}, "replace": True, "expect": r.get_json()["stamp"]}, headers=W)
    assert r.status_code == 200 and r.get_json()["total"] == 0
    assert _file(tmp_path) == {"v": 1, "cards": {}}


def test_a_layout_write_is_not_map_data(admin, realm, tmp_path):
    """No revision and no change in the dataset's stamp: it is not on the undo list."""
    before = admin.get("/api/v2/admin/dataset").get_json()["stamp"]
    revs = admin.get("/api/v2/admin/revisions").get_json()
    _everywhere(admin)
    assert admin.get("/api/v2/admin/dataset").get_json()["stamp"] == before
    assert admin.get("/api/v2/admin/revisions").get_json() == revs


# ── a viewer reads ───────────────────────────────────────────────────────────

def test_a_viewer_never_gets_a_hidden_place_or_a_withheld_stub(admin, alice):
    _everywhere(admin)
    r = alice.get(URL)
    assert r.status_code == 200
    body = r.get_json()
    # secret-place is behind a group; closet-qq's only cable goes to it, so
    # the redaction withholds the stub too (redaction._scrub_wiring)
    assert sorted(body["cards"]) == ["alpha", "beta", "line-in"]
    text = json.dumps(body)
    assert "secret" not in text and "closet" not in text
    assert "private" in r.headers.get("Cache-Control", "")
    assert "Cookie" in r.headers.get("Vary", "")
    # the admin sees every card
    assert len(admin.get(URL).get_json()["cards"]) == 5


def test_a_viewer_cannot_write(alice, admin):
    stamp = admin.get(URL).get_json()["stamp"]
    r = alice.post(URL, json={"cards": {"alpha": {"x": 1, "y": 1}}, "expect": stamp}, headers=W)
    assert r.status_code == 403
    assert admin.get(URL).get_json()["cards"] == {}


def test_a_stranger_reads_nothing(realm):
    r = realm.app.test_client().get(URL)
    assert r.status_code in (401, 403)


def test_an_api_token_is_not_let_in(admin, realm):
    """The layout is not one of a token's doors (api_tokens.READ_PATHS), as
    marker positions are not."""
    r = admin.post("/api/v2/admin/tokens", json={"name": "reader", "days": 90}, headers=W)
    assert r.status_code == 200, r.get_json()
    bearer = {"Authorization": f"Bearer {r.get_json()['secret']}"}
    c = realm.app.test_client()
    assert c.get(URL, headers=bearer).status_code in (401, 403)
    assert c.post(URL, json={"cards": {}}, headers={**bearer, **W}).status_code in (401, 403)


# ── refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    None, [1, 2], "nope", {}, {"cards": []}, {"cards": {"alpha": {"x": "1", "y": 2}}},
    {"cards": {"alpha": {"x": True, "y": 2}}}, {"cards": {"alpha": {"x": 1}}},
    {"cards": {"alpha": {"x": 1, "y": 1}}, "replace": "yes"},
    {"cards": {"alpha": {"x": 1, "y": 1}}, "expect": 7},
    {"cards": {"alpha": {"x": 1e9, "y": 1}}},
])
def test_a_bad_body_is_one_sentence(admin, body):
    r = admin.post(URL, json=body, headers=W)
    assert r.status_code == 400, body
    assert isinstance(r.get_json()["error"], str) and set(r.get_json()) == {"error"}


@pytest.mark.parametrize("raw", ['{"cards": {"alpha": {"x": NaN, "y": 1}}}',
                                 '{"cards": {"alpha": {"x": Infinity, "y": 1}}}'])
def test_not_a_number_is_refused(admin, raw):
    r = admin.post(URL, data=raw, headers={**W, "Content-Type": "application/json"})
    assert r.status_code == 400


def test_a_stale_stamp_is_refused_with_the_stamp_on_file(admin, tmp_path):
    old = admin.get(URL).get_json()["stamp"]
    now = admin.post(URL, json={"cards": {"alpha": {"x": 1, "y": 1}}, "expect": old}, headers=W).get_json()
    r = admin.post(URL, json={"cards": {"beta": {"x": 2, "y": 2}}, "expect": old}, headers=W)
    assert r.status_code == 409
    assert r.get_json()["stamp"] == now["stamp"] and "read again" in r.get_json()["error"]
    assert _file(tmp_path)["cards"] == {"alpha": {"x": 1.0, "y": 1.0}}


def test_the_write_header_is_required(admin):
    r = admin.post(URL, json={"cards": {}}, headers={"Origin": "http://localhost"})
    assert r.status_code == 403


def test_read_only_refuses_the_write_and_still_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_TOPOLOGY_LAYOUT", str(tmp_path / "topology-layout.json"))
    handle = viewers.build(tmp_path, monkeypatch, viewers.dataset(**WIRING))
    monkeypatch.setenv("ATLAS_READONLY", "1")
    from appfixture import fresh_app
    handle = fresh_app()
    admin = viewers.signed_in(handle, "ops")
    r = admin.post(URL, json={"cards": {"alpha": {"x": 1, "y": 1}}}, headers=W)
    assert r.status_code == 403 and "read-only" in r.get_json()["error"]
    assert admin.get(URL).status_code == 200
    assert not (tmp_path / "topology-layout.json").exists()


# ── the file, read leniently ─────────────────────────────────────────────────

def test_a_hand_edited_file_is_read_leniently(tmp_path):
    path = tmp_path / "layout.json"
    path.write_text(json.dumps({"v": 1, "cards": {"a": {"x": 1, "y": 2}, "b": {"x": "1", "y": 2},
                                                  "c": [1, 2], "": {"x": 1, "y": 1}}}), encoding="utf-8")
    assert layout.read(str(path)) == {"v": 1, "cards": {"a": {"x": 1.0, "y": 2.0}}}
    path.write_text("not json", encoding="utf-8")
    assert layout.read(str(path)) == {"v": 1, "cards": {}}
    assert layout.read(str(tmp_path / "missing.json")) == {"v": 1, "cards": {}}


def test_a_card_of_a_thing_gone_from_the_map_is_dropped_on_the_next_write(tmp_path):
    path = str(tmp_path / "layout.json")
    layout.save(path, {"a", "b"}, {"a": {"x": 1, "y": 1}, "b": {"x": 2, "y": 2}})
    out = layout.save(path, {"a"}, {"a": {"x": 3, "y": 3}})
    assert out["total"] == 1 and layout.read(path)["cards"] == {"a": {"x": 3, "y": 3}}


def test_a_viewer_stamp_never_moves_for_a_card_they_cannot_see(admin, alice):
    _everywhere(admin)
    before = alice.get(URL).get_json()["stamp"]
    stamp = admin.get(URL).get_json()["stamp"]
    admin.post(URL, json={"cards": {"secret-place": {"x": 999, "y": 999}}, "expect": stamp}, headers=W)
    assert alice.get(URL).get_json()["stamp"] == before


# ── the drawing's map writes, as the page sends them ─────────────────────────
#
# topology-draw-model.js makes these batches (tests/test_topology_draw_model.mjs
# holds their shape); here they go through the real ops route, so the shapes
# the form sends are ones the server takes.

def _ops(admin, ops, note="drew on the topology"):
    stamp = admin.get("/api/v2/admin/dataset").get_json()["stamp"]
    return admin.post("/api/v2/admin/ops", json={"ops": ops, "expect": stamp, "note": note}, headers=W)


def _disk(admin):
    return admin.get("/api/v2/admin/dataset").get_json()["data"]


def test_a_cable_with_a_new_port_and_a_stub_end_is_one_save(admin):
    r = _ops(admin, [
        {"op": "insert", "section": "interfaces", "body": {"device": "beta", "name": "eth7"}},
        {"op": "insert", "section": "cables", "body": {
            "a_stub": "line-in", "b": "beta", "id": "line-in-to-beta", "a_port": "lan", "b_port": "eth7",
            "kind": "fibre", "state": "assumed", "vlan": 10, "tagged": [20, 30], "poe_w": 12.5,
            "source": "hand"}},
    ])
    assert r.status_code == 200, r.get_json()
    data = _disk(admin)
    assert {"device": "beta", "name": "eth7"} in data["interfaces"]
    cable = next(c for c in data["cables"] if c["id"] == "line-in-to-beta")
    assert (cable["a_stub"], cable["b"], cable["tagged"]) == ("line-in", "beta", [20, 30])
    assert len(admin.get("/api/v2/admin/revisions").get_json()["revisions"]) >= 1


def test_an_edit_clears_a_field_renames_and_a_removal_takes_it_out(admin):
    assert _ops(admin, [{"op": "insert", "section": "cables", "body": {
        "a": "alpha", "b": "beta", "id": "alpha-to-beta", "tagged": [20], "note": "n", "source": "hand"}}]).status_code == 200
    r = _ops(admin, [{"op": "upsert", "section": "cables", "id": "alpha-to-beta",
                      "body": {"tagged": None, "note": None, "id": "uplink", "b_port": "2"}}])
    assert r.status_code == 200, r.get_json()
    cable = next(c for c in _disk(admin)["cables"] if c["id"] == "uplink")
    assert "tagged" not in cable and "note" not in cable and cable["b_port"] == "2"
    assert _ops(admin, [{"op": "delete", "section": "cables", "id": "uplink"}]).status_code == 200
    assert not any(c["id"] == "uplink" for c in _disk(admin)["cables"])


def test_a_refused_value_comes_back_in_words_for_the_form(admin):
    r = _ops(admin, [{"op": "insert", "section": "cables", "body": {
        "a": "alpha", "b": "beta", "id": "bad", "vlan": "ten", "tagged": [10, "x"], "source": "hand"}}])
    assert r.status_code == 422
    words = " ".join(r.get_json()["problems"])
    assert "'ten' is not a VLAN number" in words and "'x' is not a VLAN number" in words


def test_a_stub_and_cables_from_routes_land(admin):
    assert _ops(admin, [{"op": "insert", "section": "stubs",
                         "body": {"id": "desk-switch", "name": "Desk switch", "kind": "switch"}}]).status_code == 200
    r = _ops(admin, [
        {"op": "insert", "section": "cables", "body": {"id": "alpha-to-beta", "a": "alpha", "b": "beta",
                                                       "state": "assumed", "source": "hand"}},
        {"op": "insert", "section": "cables", "body": {"id": "beta-to-alpha", "a": "beta", "b": "alpha",
                                                       "state": "assumed", "source": "hand"}},
    ], note="made cables from routes on the topology")
    assert r.status_code == 200, r.get_json()
    data = _disk(admin)
    assert any(s["id"] == "desk-switch" for s in data["stubs"])
    assert {c["id"] for c in data["cables"]} >= {"alpha-to-beta", "beta-to-alpha"}


def test_the_stamp_rule_comes_with_the_store(admin):
    old = admin.get("/api/v2/admin/dataset").get_json()["stamp"]
    assert _ops(admin, [{"op": "insert", "section": "stubs", "body": {"id": "s1", "name": "S1"}}]).status_code == 200
    r = admin.post("/api/v2/admin/ops", headers=W, json={"expect": old, "ops": [
        {"op": "insert", "section": "stubs", "body": {"id": "s2", "name": "S2"}}]})
    assert r.status_code == 409


def test_a_save_that_cannot_get_the_file_says_so_and_is_no_bare_500(admin, monkeypatch):
    """2026-11-17: `filelock.LockTimeout` is a RuntimeError; it went out as a 500."""
    import filelock
    import topology_layout

    def held(*args, **kwargs):
        raise filelock.LockTimeout("held")

    monkeypatch.setattr(topology_layout, "save", held)
    stamp = admin.get(URL).get_json()["stamp"]
    r = admin.post(URL, json={"cards": {"alpha": {"x": 1, "y": 1}}, "expect": stamp}, headers=W)
    assert r.status_code == 503 and r.headers.get("Retry-After") == "2"
    assert "try again" in r.get_json()["error"]
