"""CABLES AND STUBS (2026-11-16): the wiring under TOPOLOGY, as data.

A cable is a physical connection, port to port; each end is a place or a stub.
A stub is gear on the wiring nobody charts as a place (the provider's line, a
desk switch): no marker, no row in NODES, never watched. Nothing is drawn yet;
these tests hold the data: the catalogue, the checks, both stores, renames
and removals, and what a viewer who may not see a place is never told.
"""

import copy
import json
import os
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dataset as ds  # noqa: E402
import redaction  # noqa: E402
import schema  # noqa: E402
import validation  # noqa: E402
import viewers  # noqa: E402
from dataset import FileDatasetStore, RejectedError  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts"}

MODERN = "2026-07-28"
DEMO = os.path.join(os.path.dirname(WEB), "demo-lab", "seed", "lab-data.demo.json")


def cable(cid, a=None, b=None, **extra):
    out = {"id": cid}
    if a is not None:
        out["a"] = a
    if b is not None:
        out["b"] = b
    out.update(extra)
    return out


def realm_data(**sections):
    """Three places (`secret-place` behind a group) plus what a test adds."""
    return viewers.dataset(**sections)


def problems(data, strict=False):
    return validation.validate(data, strict=strict)


def cable_problems(data, strict=False):
    return [p for p in problems(data, strict) if p.startswith(("cable ", "stub "))]


# ── the catalogue ────────────────────────────────────────────────────────────

def test_the_cables_section_has_its_fields_in_order():
    s = schema.get("cables")
    assert (s["singular"], s["plural"], s["noun"], s["store"], s["id_field"]) == (
        "cable", "cables", "cable", "dataset", "id")
    names = [f["name"] for f in s["fields"]]
    assert names == ["id", "a", "a_stub", "a_port", "b", "b_stub", "b_port", "kind", "vlan",
                     "tagged", "poe_w", "speed", "state", "source", "note"]
    fields = {f["name"]: f for f in s["fields"]}
    assert fields["id"]["type"] == "slug" and fields["id"]["required"]
    for end in ("a", "b"):
        assert (fields[end]["type"], fields[end]["ref"]) == ("ref", "nodes")
        assert (fields[end + "_stub"]["type"], fields[end + "_stub"]["ref"]) == ("ref", "stubs")
        assert fields[end]["follows"] and fields[end + "_stub"]["follows"]
        assert not fields[end]["required"] and not fields[end + "_stub"]["required"]
        assert fields[end + "_port"]["type"] == "text"
    assert fields["kind"]["options"] == ["copper", "fibre", "dac", "wireless", "virtual"]
    assert fields["state"]["options"] == ["confirmed", "assumed"]
    assert fields["vlan"]["type"] == "scalar" and fields["tagged"]["type"] == "json"
    assert fields["poe_w"]["type"] == "number" and fields["poe_w"]["min"] == 0
    assert schema.blank("cables") == {"id": "", "kind": "copper", "state": "confirmed",
                                      "source": "hand"}


def test_the_stubs_section_has_its_fields_in_order():
    s = schema.get("stubs")
    assert (s["singular"], s["plural"], s["store"], s["id_field"], s["title_field"]) == (
        "stub", "stubs", "dataset", "id", "name")
    assert [f["name"] for f in s["fields"]] == ["id", "name", "kind", "note"]
    kind = schema.field("stubs", "kind")
    assert kind["options"] == ["internet", "switch", "patch", "outlet", "other"]
    assert kind["default"] == "other"
    assert schema.blank("stubs") == {"id": "", "name": "", "kind": "other"}
    # the word for "not ours to watch" belongs to places and services
    assert "unmanaged" not in json.dumps(s).lower()


def test_both_sections_are_ordered_for_the_desk_and_the_file():
    order, file_order = schema.SECTION_ORDER, schema.FILE_ORDER
    assert order.index("cables") == order.index("interfaces") + 1
    assert order.index("stubs") == order.index("cables") + 1
    assert file_order.index("cables") == file_order.index("interfaces") + 1
    assert file_order.index("stubs") == file_order.index("cables") + 1
    assert {"cables", "stubs"} <= set(schema.catalogue()["sections"])
    # the house voice, and no em dash in the new words
    for key in ("cables", "stubs"):
        s = schema.get(key)
        assert s["lore"] and s["subtitle"]
        assert "—" not in json.dumps(s, ensure_ascii=False)


def test_the_followers_of_a_place_and_a_stub_are_the_cable_ends():
    assert schema.followers("nodes") == [("cables", "a"), ("cables", "b")]
    assert schema.followers("stubs") == [("cables", "a_stub"), ("cables", "b_stub")]


@pytest.mark.parametrize("value, number", [
    (10, 10), ("10", 10), (" 20 ", 20), (1, 1), (4094, 4094), (10.0, 10),
    (0, None), (4095, None), ("ten", None), (True, None), ("²", None), (None, None),
])
def test_a_vlan_number(value, number):
    assert schema.vlan_number(value) == number


# ── upgrade: a map without the sections ───────────────────────────────────────

def test_a_map_without_the_sections_loads_as_it_was():
    data = realm_data()
    before = copy.deepcopy(data)
    stamp = ds.content_stamp(data)
    schema.upgrade(data)
    schema.servable(data)
    assert data == before and ds.content_stamp(data) == stamp
    assert "cables" not in data and "stubs" not in data
    assert problems(data) == []


# ── validation ───────────────────────────────────────────────────────────────

def wired(cables=(), stubs=()):
    return realm_data(cables=list(cables), stubs=list(stubs))


def test_a_good_wiring_is_clean():
    data = wired([cable("ab", "alpha", "beta", a_port="1", b_port="2", vlan=1, tagged=[10, 20]),
                  cable("line", b="alpha", a_stub="isp", a_port="lan", b_port="wan")],
                 [{"id": "isp", "name": "Line in", "kind": "internet"}])
    assert problems(data) == [] and problems(data, strict=True) == []


@pytest.mark.parametrize("entry, words", [
    (cable("x", b="beta"), "end A names no place and no stub"),
    (cable("x", "alpha"), "end B names no place and no stub"),
    (cable("x", "alpha", "beta", a_stub="isp"), "end A names both a place and a stub"),
    (cable("x", "ghost", "beta"), "unknown a 'ghost'"),
    (cable("x", "alpha", b_stub="nowhere"), "unknown b_stub 'nowhere'"),
    (cable("x", "alpha", "alpha"), "runs from place 'alpha' to itself"),
    (cable("x", "alpha", "alpha", a_port="3", b_port=" 3 "), "runs from place 'alpha' to itself"),
    (cable("x", a_stub="isp", b_stub="isp"), "runs from stub 'isp' to itself"),
    (cable("x", "alpha", "beta", vlan=0), "vlan 0 is not a VLAN number"),
    (cable("x", "alpha", "beta", vlan=5000), "vlan 5000 is not a VLAN number"),
    (cable("x", "alpha", "beta", vlan="trunk"), "vlan 'trunk' is not a VLAN number"),
    (cable("x", "alpha", "beta", tagged=10), "tagged must be a list of VLAN numbers"),
    (cable("x", "alpha", "beta", tagged=[10, 4095]), "tagged VLAN 4095 is not a VLAN number"),
    (cable("x", "alpha", "beta", tagged=[10, "10"]), "tagged lists VLAN 10 twice"),
    (cable("x", "alpha", "beta", vlan=10, tagged=[10, 20]), "tagged repeats the untagged VLAN 10"),
    (cable("x", "alpha", "beta", kind="ethernet"), "unknown kind 'ethernet'"),
    (cable("x", "alpha", "beta", state="maybe"), "unknown state 'maybe'"),
    (cable("x", "alpha", "beta", poe_w=-1), "poe_w must be at least 0"),
    (cable("Bad Id", "alpha", "beta"), "is not a valid id"),
])
def test_each_cable_rule_is_an_error(entry, words):
    data = wired([entry], [{"id": "isp", "name": "Line in"}])
    for strict in (False, True):
        found = cable_problems(data, strict)
        assert any(words in p for p in found), (strict, found)


def test_the_same_place_on_two_different_ports_is_a_cable():
    """A patch between two ports of one switch is a real cable."""
    assert cable_problems(wired([cable("loop", "alpha", "alpha", a_port="1", b_port="2")])) == []


def test_a_vlan_may_be_written_as_text_or_left_blank():
    data = wired([cable("a1", "alpha", "beta", vlan="10", tagged=["20", 30]),
                  cable("a2", "alpha", "beta", vlan="—"),
                  cable("a3", "alpha", "beta", vlan="")])
    assert cable_problems(data) == []


def test_ids_are_unique_and_a_stub_is_not_a_place():
    data = wired([cable("dup", "alpha", "beta"), cable("dup", "beta", "alpha")],
                 [{"id": "alpha", "name": "Shadow"}, {"id": "s", "name": "S"},
                  {"id": "s", "name": "S again"}])
    found = cable_problems(data)
    assert "cable 'dup': duplicate id" in found
    assert "stub 's': duplicate id" in found
    assert any(p.startswith("stub 'alpha': id 'alpha' is also a place's id") for p in found)


def test_a_port_two_cables_use_is_a_warning_on_read_and_no_refusal_on_save():
    data = wired([cable("first", "alpha", "beta", a_port="7"),
                  cable("second", "alpha", "beta", a_port=" 7")])
    read = cable_problems(data)
    assert len(read) == 1 and "port ' 7' of place 'alpha' is also used by cable 'first'" in read[0]
    assert "a warning" in read[0]
    assert cable_problems(data, strict=True) == []


def test_a_port_with_no_interface_is_allowed_silently():
    data = wired([cable("c", "alpha", "beta", a_port="eth9", b_port="sfp+1")])
    data["interfaces"] = [{"device": "alpha", "name": "eth0"}]
    assert problems(data) == [] and problems(data, strict=True) == []


def test_a_malformed_cable_is_named_and_never_raises():
    data = wired([cable("c1", ["alpha"], "beta"), "not a cable", cable("c2", {"x": 1}, "beta",
                                                                         a_port=["1"])])
    found = problems(data)
    assert any("must be one id" in p for p in found)
    assert any("entry must be an object" in p for p in found)


# ── the two stores ───────────────────────────────────────────────────────────

def _file_store(tmp_path, data):
    path = tmp_path / "lab-data.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return FileDatasetStore(str(path), str(path), str(tmp_path / "rev"))


@pytest.fixture
def db_store(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DB_URL", f"sqlite:///{(tmp_path / 'atlas.db').as_posix()}")
    import store
    store.reset_engine_for_tests()
    store.init_db()

    def make(data):
        with store.session_scope() as session:
            store.load_labdata(session, copy.deepcopy(data), site_slug="default")
        return ds.DbDatasetStore("default", str(tmp_path / "rev"))
    yield make
    store.reset_engine_for_tests()


@pytest.fixture(params=["file", "db"])
def make_store(request, tmp_path, db_store):
    if request.param == "file":
        return lambda data: _file_store(tmp_path, data)
    return db_store


STUB = {"id": "isp", "name": "Line in", "kind": "internet", "note": "the box on the wall"}
CABLE = {"id": "line", "a_stub": "isp", "a_port": "lan", "b": "alpha", "b_port": "eth0",
         "kind": "copper", "vlan": 1, "tagged": [10, 20], "poe_w": 4.5, "speed": "1G",
         "state": "assumed", "source": "hand", "note": "under the stairs"}


def test_a_stub_and_a_cable_save_and_read_back(make_store):
    st = make_store(realm_data())
    _, stamp = st.read()
    out = st.apply([{"op": "insert", "section": "stubs", "body": STUB},
                    {"op": "insert", "section": "cables", "body": CABLE}], expect=stamp)
    assert out["changed"] == ["added stub isp", "added cable line"]
    data, _ = st.read()
    assert data["stubs"] == [STUB] and data["cables"] == [CABLE]
    # the file's order: the new sections sit where FILE_ORDER puts them
    keys = list(data)
    assert keys.index("routes") < keys.index("cables") < keys.index("stubs")
    # nothing else moved
    assert data["nodes"] == realm_data()["nodes"]


def test_a_second_cable_on_a_used_port_saves(make_store):
    st = make_store(realm_data(cables=[cable("one", "alpha", "beta", a_port="7")]))
    _, stamp = st.read()
    st.apply([{"op": "insert", "section": "cables",
               "body": cable("two", "alpha", "beta", a_port="7")}], expect=stamp)
    data, _ = st.read()
    assert [c["id"] for c in data["cables"]] == ["one", "two"]
    assert any("is also used by" in p for p in problems(data))


def test_a_save_refuses_a_cable_it_breaks(make_store):
    st = make_store(realm_data())
    _, stamp = st.read()
    with pytest.raises(RejectedError) as err:
        st.apply([{"op": "insert", "section": "cables", "body": cable("x", "alpha", "ghost")}],
                 expect=stamp)
    assert any("unknown b 'ghost'" in p for p in err.value.problems)


def test_an_undo_takes_a_cable_back_out(tmp_path):
    st = _file_store(tmp_path, realm_data())
    _, stamp = st.read()
    out = st.apply([{"op": "insert", "section": "cables", "body": cable("c", "alpha", "beta")}],
                   expect=stamp)
    st.revert(out["revision"], actor="test")
    assert "cables" not in st.read()[0]           # the map exactly as it was before


# ── a place or a stub renamed ────────────────────────────────────────────────

def test_a_renamed_place_takes_its_cables_along(make_store):
    st = make_store(realm_data(cables=[cable("ab", "alpha", "beta"),
                                       cable("aa", "alpha", "alpha", a_port="1", b_port="2"),
                                       cable("bb", "beta", b_stub="isp")],
                               stubs=[{"id": "isp", "name": "Line in"}]))
    _, stamp = st.read()
    out = st.apply([{"op": "upsert", "section": "nodes", "id": "alpha", "body": {"id": "gamma"}}],
                   expect=stamp)
    assert out["changed"] == ["changed node alpha (and 2 things that pointed at it, "
                              "carried to the new id)"]
    data, _ = st.read()
    ends = {c["id"]: (c.get("a"), c.get("b")) for c in data["cables"]}
    assert ends == {"ab": ("gamma", "beta"), "aa": ("gamma", "gamma"), "bb": ("beta", None)}


def test_a_renamed_stub_takes_its_cables_along(make_store):
    st = make_store(realm_data(cables=[cable("bb", "beta", b_stub="isp")],
                               stubs=[{"id": "isp", "name": "Line in"}]))
    _, stamp = st.read()
    out = st.apply([{"op": "upsert", "section": "stubs", "id": "isp", "body": {"id": "fibre"}}],
                   expect=stamp)
    assert "(and 1 thing that pointed at it, carried to the new id)" in out["changed"][0]
    assert st.read()[0]["cables"][0]["b_stub"] == "fibre"


def test_a_place_with_a_route_is_still_refused_a_rename_as_before(tmp_path):
    """Only a cable's ends follow a rename. A route is not carried today, and
    this stage leaves that as it was: the rename is refused for the route."""
    st = _file_store(tmp_path, realm_data(routes=[{"from": "alpha", "to": "beta"}],
                                          cables=[cable("ab", "alpha", "beta")]))
    _, stamp = st.read()
    with pytest.raises(RejectedError) as err:
        st.apply([{"op": "upsert", "section": "nodes", "id": "alpha", "body": {"id": "gamma"}}],
                 expect=stamp)
    assert err.value.problems == ["route #1: unknown from 'alpha'"]


# ── a place or a stub removed ────────────────────────────────────────────────

def test_removing_a_place_removes_its_cables_in_the_same_save(make_store):
    st = make_store(realm_data(routes=[{"from": "alpha", "to": "beta"}],
                               cables=[cable("ab", "alpha", "beta"),
                                       cable("bx", "beta", b_stub="isp"),
                                       cable("ax", "alpha", b_stub="isp")],
                               stubs=[{"id": "isp", "name": "Line in"}]))
    _, stamp = st.read()
    out = st.apply([{"op": "delete", "section": "nodes", "id": "alpha", "cascade": True}],
                   expect=stamp)
    # two cables and the route: the count the Desk shows today for routes
    assert out["changed"] == ["removed node alpha (and 3 things that pointed at it)"]
    data, _ = st.read()
    assert [c["id"] for c in data["cables"]] == ["bx"]
    assert data["routes"] == []


def test_removing_a_place_without_cascade_is_refused_as_for_routes(tmp_path):
    st = _file_store(tmp_path, realm_data(cables=[cable("ab", "alpha", "beta")]))
    _, stamp = st.read()
    with pytest.raises(RejectedError) as err:
        st.apply([{"op": "delete", "section": "nodes", "id": "alpha"}], expect=stamp)
    assert any("unknown a 'alpha'" in p for p in err.value.problems)
    deps = ds.dependents(st.read()[0], "nodes", "alpha")
    assert deps == [{"section": "cables", "index": 0, "field": "a", "label": "ab"}]


def test_removing_a_stub_removes_its_cables(make_store):
    st = make_store(realm_data(cables=[cable("bx", "beta", b_stub="isp"),
                                       cable("ab", "alpha", "beta")],
                               stubs=[{"id": "isp", "name": "Line in"}]))
    _, stamp = st.read()
    out = st.apply([{"op": "delete", "section": "stubs", "id": "isp", "cascade": True}],
                   expect=stamp)
    assert out["changed"] == ["removed stub isp (and 1 thing that pointed at it)"]
    data, _ = st.read()
    assert data["stubs"] == [] and [c["id"] for c in data["cables"]] == ["ab"]


# ── a viewer who may not see a place ─────────────────────────────────────────

#: Words that must never reach a viewer who may not see `secret-place`.
SENTINELS = ("hidden-cable-qq", "HIDDEN-PORT-QQ", "HIDDEN-NOTE-QQ", "closet-qq", "CLOSET-NOTE-QQ",
             "word-stub-qq", "secret")

WIRING = {
    "stubs": [
        {"id": "line-in", "name": "Line in", "kind": "internet"},
        {"id": "closet-qq", "name": "Closet box", "kind": "switch", "note": "CLOSET-NOTE-QQ"},
        {"id": "spare-jack", "name": "Spare jack", "kind": "outlet"},
        {"id": "word-stub-qq", "name": "Secret patch", "kind": "patch"},
    ],
    "cables": [
        cable("c-visible", "alpha", "beta", a_port="1", b_port="2", note="VISIBLE-NOTE"),
        cable("hidden-cable-qq", "alpha", "secret-place", a_port="HIDDEN-PORT-QQ", b_port="9",
              note="HIDDEN-NOTE-QQ"),
        cable("c-line", b="alpha", a_stub="line-in", a_port="lan", b_port="wan"),
        cable("c-closet", b="secret-place", a_stub="closet-qq", a_port="4"),
        cable("alpha-to-secret", "alpha", "beta", a_port="5", b_port="6"),
    ],
}


def _seen_wiring(body):
    return ([c["id"] for c in body.get("cables") or []],
            [s["id"] for s in body.get("stubs") or []])


def _clean(body):
    text = json.dumps(body)
    return [s for s in SENTINELS if s in text]


def test_the_rule_on_the_dataset_itself():
    seen, _ = redaction.redact(realm_data(**WIRING), frozenset())
    assert _seen_wiring(seen) == (["c-visible", "c-line"], ["line-in", "spare-jack"])
    assert all("note" not in c for c in seen["cables"])
    assert _clean(seen) == []
    # an admin sees it all, notes included
    whole, _ = redaction.redact(realm_data(**WIRING), None)
    assert len(whole["cables"]) == 5 and whole["cables"][0]["note"] == "VISIBLE-NOTE"


def test_a_viewer_with_nothing_hidden_sees_every_cable_and_note():
    data = realm_data(**WIRING)
    data["nodes"] = [n for n in data["nodes"] if n["id"] != "secret-place"]
    data["cables"] = [c for c in data["cables"] if "secret-place" not in (c.get("a"), c.get("b"))]
    seen, _ = redaction.redact(data, frozenset())
    assert len(seen["cables"]) == 3 and seen["cables"][0]["note"] == "VISIBLE-NOTE"
    assert len(seen["stubs"]) == 4


def test_a_stub_wired_only_to_hidden_places_is_not_passed_off_as_unwired():
    """Counted on the whole map: the closet's only cable goes, and so does it."""
    data = realm_data(stubs=[{"id": "closet", "name": "Closet"}],
                      cables=[cable("c", b="secret-place", a_stub="closet")])
    seen, _ = redaction.redact(data, frozenset())
    assert seen["stubs"] == [] and seen["cables"] == []


def test_a_chain_of_stubs_stops_where_the_hidden_place_starts():
    data = realm_data(stubs=[{"id": "s1", "name": "Wall jack"}, {"id": "s2", "name": "Patch"}],
                      cables=[cable("c1", "alpha", b_stub="s1"),
                              cable("c2", a_stub="s1", b_stub="s2"),
                              cable("c3", b="secret-place", a_stub="s2")])
    seen, _ = redaction.redact(data, frozenset())
    assert _seen_wiring(seen) == (["c1", "c2"], ["s1", "s2"])


def test_a_cable_never_points_at_a_withheld_stub():
    data = realm_data(stubs=[{"id": "s1", "name": "Secret box"}],
                      cables=[cable("c1", "alpha", b_stub="s1")])
    seen, _ = redaction.redact(data, frozenset())
    assert seen["stubs"] == [] and seen["cables"] == []


@pytest.mark.parametrize("cables, stubs, kept", [
    # no cable list at all: the stub is wired to nothing, so it is shown
    ("not a list", [{"id": "s", "name": "S"}], ["s"]),
    # a stub end that is no id cannot be matched, so every stub counts as wired
    ([cable("c", "alpha", b_stub=["s"]), 7], [{"id": "s", "name": "S"}], []),
    ([cable("c", "alpha", b_stub="s")], "not a list", []),
    ([cable("c", "alpha", b_stub="s")], [{"id": ["s"], "name": "S"}, 5], []),
])
def test_a_malformed_wiring_is_withheld_and_never_raises(cables, stubs, kept):
    data = realm_data(cables=cables, stubs=stubs)
    seen, _ = redaction.redact(data, frozenset())
    assert seen.get("cables") in (None, [])
    assert [s["id"] for s in seen.get("stubs") or []] == kept


@pytest.fixture
def realm(tmp_path, monkeypatch):
    handle = viewers.build(tmp_path, monkeypatch, realm_data(**WIRING))
    yield handle
    monkeypatch.undo()


def _tool(realm, auth, name, args=None):
    """The whole answer of one tool call, words and structure alike."""
    head = {**auth, "MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call", "Mcp-Name": name}
    params = {"name": name, "arguments": args or {},
              "_meta": {"io.modelcontextprotocol/protocolVersion": MODERN,
                        "io.modelcontextprotocol/clientCapabilities": {}}}
    r = realm.app.test_client().post("/api/v2/mcp", headers=head, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["result"]


def test_door_the_lab_data_read(realm):
    body = viewers.signed_in(realm, "alice").get("/api/v2/lab-data").get_json()
    assert _seen_wiring(body) == (["c-visible", "c-line"], ["line-in", "spare-jack"])
    assert _clean(body) == []
    whole = viewers.signed_in(realm, "ops").get("/api/v2/lab-data").get_json()
    assert len(whole["cables"]) == 5 and len(whole["stubs"]) == 4


def test_door_the_lab_data_read_by_a_token(realm):
    body = realm.app.test_client().get("/api/v2/lab-data", headers=viewers.issue(realm)).get_json()
    assert _seen_wiring(body) == (["c-visible", "c-line"], ["line-in", "spare-jack"])
    assert _clean(body) == []


@pytest.mark.parametrize("profile", ["full", "cloud"])
def test_door_every_mcp_tool(realm, profile):
    import mcp_tools
    auth = viewers.issue(realm, profile)
    args = {"atlas_search": {"query": "alpha"}, "atlas_place": {"place": "alpha"},
            "atlas_impact": {"place": "alpha"}}
    for name in mcp_tools._CALLS:
        told = _tool(realm, auth, name, args.get(name))
        # a cloud token is not shown `alpha` at all (nobody has checked it),
        # so its one-place tools answer "no such place"; every other answer
        # is a real one
        assert told["isError"] is (profile == "cloud" and name in ("atlas_place", "atlas_impact")), \
            (name, told)
        assert _clean(told) == [], name


def test_door_the_places_table(realm):
    body = viewers.signed_in(realm, "alice").get("/api/v2/places/roster").get_json()
    assert _clean(body) == []


def test_door_the_overview(realm):
    body = viewers.signed_in(realm, "alice").get("/api/v2/overview").get_json()
    assert _clean(body) == []


def test_door_the_db_backend_and_its_site_read(tmp_path, monkeypatch):
    for name, value in {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "db",
                        "ATLAS_DB_URL": f"sqlite:///{(tmp_path / 'atlas.db').as_posix()}",
                        "ATLAS_SITE": "default",
                        "ATLAS_DATA": str(tmp_path / "no-such.json"),
                        "ATLAS_ACCOUNTS_DB": str(tmp_path / "a.db"),
                        "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
                        "ATLAS_EVENTS": str(tmp_path / "events.json"),
                        "ATLAS_REVISIONS": str(tmp_path / "rev"),
                        "ATLAS_SECRET_KEY": "test-signing-key", "ATLAS_INSECURE_COOKIES": "1",
                        "ATLAS_SIGNALS_SOURCES": "", "ATLAS_AUTH_BACKENDS": "local",
                        "ATLAS_MFA_REQUIRED": "", "ATLAS_ALLOW_INSECURE": "1"}.items():
        monkeypatch.setenv(name, value)
    import store
    store.reset_engine_for_tests()
    try:
        store.init_db()
        with store.session_scope() as session:
            store.load_labdata(session, realm_data(**WIRING), site_slug="default")
        handle = viewers.fresh_app()
        assert handle.DATA_BACKEND == "db"
        import accounts
        accounts.create_local_user("alice", viewers.PW, display_name="Alice", is_admin=False)
        accounts.create_local_user("ops", viewers.PW, display_name="Ops", is_admin=True)
        alice = viewers.signed_in(handle, "alice")
        for path in ("/api/v2/lab-data", "/api/v2/sites/default/lab-data"):
            body = alice.get(path).get_json()
            assert _seen_wiring(body) == (["c-visible", "c-line"], ["line-in", "spare-jack"]), path
            assert _clean(body) == [], path
        whole = viewers.signed_in(handle, "ops").get("/api/v2/lab-data").get_json()
        assert whole["cables"] == WIRING["cables"] and whole["stubs"] == WIRING["stubs"]
    finally:
        monkeypatch.undo()
        store.reset_engine_for_tests()


# ── the published contract ───────────────────────────────────────────────────

def test_the_openapi_document_knows_both_sections():
    import openapi
    props = openapi.dataset_schema()["properties"]
    cables = props["cables"]["items"]["properties"]
    assert {"id", "a", "a_stub", "a_port", "b", "b_stub", "b_port", "kind", "vlan", "tagged",
            "poe_w", "speed", "state", "source", "note"} == set(cables)
    assert "Names an entry in `stubs`." in cables["a_stub"]["description"]
    assert set(props["stubs"]["items"]["properties"]) == {"id", "name", "kind", "note"}
    docs = os.path.join(os.path.dirname(WEB), "docs", "openapi.json")
    if not os.path.exists(docs):
        pytest.skip("docs/ is not beside Web/ here (the image carries Web/ only)")
    with open(docs, encoding="utf-8") as fh:
        published = json.load(fh)
    text = json.dumps(published)
    assert '"cables"' in text and '"stubs"' in text


# ── the demo lab ─────────────────────────────────────────────────────────────

def test_the_demo_wiring_validates_clean_and_has_something_to_draw():
    if not os.path.exists(DEMO):
        pytest.skip("no demo-lab seed in this tree")
    with open(DEMO, encoding="utf-8") as fh:
        data = json.load(fh)
    assert problems(data) == [] and problems(data, strict=True) == []
    cables, stubs = data["cables"], data["stubs"]
    assert 5 <= len(cables) <= 8 and len(stubs) == 2
    assert {s["kind"] for s in stubs} == {"internet", "switch"}
    assert any(c.get("tagged") for c in cables)                       # a trunk
    assert any(c.get("poe_w") for c in cables)                        # PoE
    assert any(c.get("state") == "assumed" for c in cables)
    assert any(c.get("kind") == "fibre" for c in cables)
    places = {n["id"] for n in data["nodes"]}
    for c in cables:
        for side in ("a", "b"):
            assert c.get(side) in places or c.get(side + "_stub") in {s["id"] for s in stubs}
            assert c.get(side + "_port")


def test_two_stubs_wired_only_towards_a_hidden_place_go_together():
    """2026-11-17: each had a cable left (the one between them), so both
    stayed: gear that reaches nothing the viewer can see."""
    data = realm_data(stubs=[{"id": "s3", "name": "Desk switch"}, {"id": "s4", "name": "Wall jack"}],
                      cables=[cable("c4", a_stub="s3", b_stub="s4", a_port="1", b_port="2"),
                              cable("c5", b="secret-place", a_stub="s4")])
    seen, _ = redaction.redact(data, frozenset())
    assert _seen_wiring(seen) == ([], [])
    # a token is cut the same way
    seen, _ = redaction.redact(data, frozenset(), token=True)
    assert _seen_wiring(seen) == ([], [])


def test_stubs_wired_to_each_other_and_to_nothing_hidden_stay():
    data = realm_data(stubs=[{"id": "s1", "name": "Patch A"}, {"id": "s2", "name": "Patch B"},
                             {"id": "s3", "name": "Closet"}],
                      cables=[cable("c1", a_stub="s1", b_stub="s2"),
                              cable("c2", b="secret-place", a_stub="s3")])
    seen, _ = redaction.redact(data, frozenset())
    assert _seen_wiring(seen) == (["c1"], ["s1", "s2"])


def test_a_piece_that_touches_a_hidden_place_keeps_only_what_a_seen_place_reaches():
    """alpha - s1 - s2 - secret, and s3 hanging off s2 through the hidden
    side only: s1 and s2 are reached from alpha; s3 - s4 are not."""
    data = realm_data(stubs=[{"id": f"s{i}", "name": f"Jack {i}"} for i in (1, 2, 3, 4)],
                      cables=[cable("c1", "alpha", b_stub="s1"),
                              cable("c2", a_stub="s1", b_stub="s2"),
                              cable("c3", b="secret-place", a_stub="s2"),
                              cable("c4", b="secret-place", a_stub="s3"),
                              cable("c5", a_stub="s3", b_stub="s4")])
    seen, _ = redaction.redact(data, frozenset())
    assert _seen_wiring(seen) == (["c1", "c2"], ["s1", "s2"])
