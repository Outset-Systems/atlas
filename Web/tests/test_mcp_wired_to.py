"""MCP's `wired_to` reads cables as well as routes (2026-11-17).

atlas_impact's `wired_to` lists, for a place, one entry per cable that has it
at an end (with the ports, the VLANs in switch notation and the medium), then
one per route as before. A stub at the far end is named as a stub. The tool
reads the asker's redacted map, so a cable to a place the token may not see is
never in the answer; this file asks it over the wire, as a model would.
"""
import json
import os
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import viewers  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts"}
MODERN = "2026-07-28"

WIRING = {
    "stubs": [{"id": "line-in", "name": "Line in", "kind": "internet"},
              {"id": "closet-qq", "name": "Closet box", "kind": "switch"}],
    "cables": [
        {"id": "trunk", "a": "alpha", "a_port": "24", "b": "beta", "b_port": "9", "kind": "fibre",
         "vlan": 1, "tagged": [20, 10], "speed": "10G", "state": "confirmed", "source": "unifi",
         "note": "NOTE-QQ"},
        {"id": "wan", "a_stub": "line-in", "a_port": "lan", "b": "alpha", "b_port": "wan"},
        {"id": "to-secret-qq", "a": "alpha", "a_port": "SECRET-PORT-QQ", "b": "secret-place", "b_port": "1"},
        {"id": "closet-run-qq", "a_stub": "closet-qq", "b": "secret-place"},
    ],
    "routes": [{"from": "alpha", "to": "beta", "kind": "vlan"},
               {"from": "alpha", "to": "secret-place", "kind": "edge"}],
}
SENTINELS = ("QQ", "qq", "secret", "Secret", "Closet")


@pytest.fixture
def realm(tmp_path, monkeypatch):
    handle = viewers.build(tmp_path, monkeypatch, viewers.dataset(**WIRING))
    yield handle
    monkeypatch.undo()


def _impact(realm, auth, place="alpha"):
    head = {**auth, "MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call", "Mcp-Name": "atlas_impact"}
    params = {"name": "atlas_impact", "arguments": {"place": place},
              "_meta": {"io.modelcontextprotocol/protocolVersion": MODERN,
                        "io.modelcontextprotocol/clientCapabilities": {}}}
    r = realm.app.test_client().post("/api/v2/mcp", headers=head, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["result"]


def test_a_cable_comes_first_with_its_ports_and_vlans_then_the_road(realm):
    told = _impact(realm, viewers.issue(realm))["structuredContent"]
    wired = told["wired_to"]
    trunk = wired[0]
    assert (trunk["id"], trunk["cable"], trunk["port"], trunk["far_port"], trunk["vlans"], trunk["medium"]) \
        == ("beta", "trunk", "24", "9", "U1 T10,20", "fibre")
    assert "road" not in trunk and "note" not in trunk
    assert (wired[-1]["id"], wired[-1]["road"]) == ("beta", "vlan") and "cable" not in wired[-1]
    assert told["wired_to_total"] == len(wired) == 3


def test_a_stub_at_the_far_end_is_named_as_a_stub(realm):
    wired = _impact(realm, viewers.issue(realm))["structuredContent"]["wired_to"]
    line = next(w for w in wired if w.get("cable") == "wan")
    assert line == {"id": "line-in", "name": "Line in", "stub": "internet", "cable": "wan",
                    "port": "wan", "far_port": "lan"}


def test_the_far_side_reads_the_same_cable_turned(realm):
    wired = _impact(realm, viewers.issue(realm), "beta")["structuredContent"]["wired_to"]
    assert (wired[0]["id"], wired[0]["port"], wired[0]["far_port"]) == ("alpha", "9", "24")


def test_a_cable_to_a_hidden_place_is_never_in_the_answer(realm):
    result = _impact(realm, viewers.issue(realm))
    told = result["structuredContent"]
    assert [w.get("cable") for w in told["wired_to"]] == ["trunk", "wan", None]
    text = json.dumps(result)
    assert not [s for s in SENTINELS if s in text], "no hidden place, port, stub or note"


def test_the_tool_reads_the_redacted_map_not_a_second_filter():
    """The dataset `_map` hands the tool has already lost the hidden cable: the
    filter in `_cabled_to` is a second lock, not the first."""
    import redaction
    seen, _ = redaction.redact(viewers.dataset(**WIRING), frozenset())
    assert [c["id"] for c in seen["cables"]] == ["trunk", "wan"]
    assert [s["id"] for s in seen["stubs"]] == ["line-in"]


def test_the_second_lock_holds_on_an_unredacted_map():
    import mcp_tools
    data = viewers.dataset(**WIRING)
    by_id = {n["id"]: n for n in data["nodes"] if n["id"] != "secret-place"}
    data["stubs"] = data["stubs"][:1]
    rows = mcp_tools._cabled_to(data, "alpha", by_id, {})
    assert [r["cable"] for r in rows] == ["trunk", "wan"]
    assert mcp_tools._cabled_to({"cables": "not a list", "stubs": 3}, "alpha", by_id, {}) == []
    assert mcp_tools._cabled_to({"cables": [{"id": "loop", "a": "alpha", "a_port": "1", "b": "alpha",
                                             "b_port": "2"}, 7, {"id": "half", "a": "alpha"}]},
                                "alpha", by_id, {}) == []


def test_a_cloud_token_is_given_no_cables_so_its_wired_to_is_roads_only():
    import cloud_view
    reduced = cloud_view.project(viewers.dataset(**WIRING))
    assert "cables" not in reduced and "stubs" not in reduced and reduced["routes"]


def test_at_the_cap_cables_come_first_and_the_total_counts_them_all(tmp_path, monkeypatch):
    import mcp_tools
    cables = [{"id": f"c{i}", "a": "alpha", "a_port": str(i), "b": "beta", "b_port": str(i)}
              for i in range(mcp_tools.MAX_ROWS + 5)]
    realm = viewers.build(tmp_path, monkeypatch, viewers.dataset(
        cables=cables, routes=[{"from": "alpha", "to": "beta", "kind": "vlan"}]))
    told = _impact(realm, viewers.issue(realm))["structuredContent"]
    assert len(told["wired_to"]) == mcp_tools.MAX_ROWS
    assert all("cable" in w for w in told["wired_to"])
    assert told["wired_to_total"] == mcp_tools.MAX_ROWS + 6


def test_the_tool_text_says_what_a_cable_entry_holds():
    import mcp_tools
    told = next(t for t in mcp_tools.TOOLS if t["name"] == "atlas_impact")["description"]
    assert "entry per cable" in told and "U1 T10,20" in told and "stub" in told
