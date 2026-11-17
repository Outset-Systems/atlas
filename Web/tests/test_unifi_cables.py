"""CABLES FROM UNIFI (2026-11-17): the UniFi review offers the wires it can see.

An uplink, an LLDP neighbour and a wired client's switch port each become a
cable, port to port, offered only between two places already on the map, and
never written until a person ticks it. A cable a person drew is never changed:
where UniFi reads it otherwise, the row says so in words and cannot be ticked.

The payloads are the ones tests/test_unifi.py already keeps (the recorded
shapes and the one real console's, under invented names), and small synthetic
ones in the same shape for what neither holds: a wireless uplink, an SFP port,
a PoE draw, two clients on one port. MACs are made up; addresses are in the
documentation ranges or the ones test_unifi.py already uses.
"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_connection_review import W, admin, dataset, import_, realm, review, rows  # noqa: E402,F401
from test_unifi import (AP, CLIENTS, DEVICES, GW, NAS, NETWORKS, R_GW, R_HOST, R_NAS, R_PDU,  # noqa: E402,F401
                        R_VM1, REAL, REAL_MAP, SW, UNIFI_KEY, net, save)

from importers import review as rv  # noqa: E402
from importers import unifi  # noqa: E402


def _snapshot():
    return {"devices": copy.deepcopy(DEVICES.body["data"]), "clients": copy.deepcopy(CLIENTS.body["data"]),
            "networks": copy.deepcopy(NETWORKS.body["data"])}


#: The fake controller's three devices and its wired NAS, already charted.
CHARTED = {
    "zones": [{"id": "core", "name": "Core", "vlan": 1, "subnet": "10.0.10.0/24"}],
    "nodes": [{"id": "edge", "name": "EDGE", "ip": "10.0.10.1", "kind": "network"},
              {"id": "core-sw", "name": "CORE SW", "ip": "10.0.10.2", "kind": "network"},
              {"id": "hall-ap", "name": "HALL AP", "ip": "10.0.10.3", "kind": "network"},
              {"id": "nas", "name": "NAS", "ip": "10.0.10.40", "kind": "physical"}],
    "routes": [],
}

#: The real console's shape, every end charted.
REAL_CHARTED = copy.deepcopy(REAL_MAP)
REAL_CHARTED["nodes"] += [{"id": "strip", "name": "STRIP", "ip": "10.50.66.41", "kind": "network"},
                          {"id": "vault", "name": "VAULT", "ip": "10.50.40.15", "kind": "physical"}]


def _cables(snapshot, data, ignored=()):
    cands, _ = unifi.candidates(snapshot)
    out = rv.annotate(cands, data, ignored)
    return out, {r["key"]: r for r in out if r["type"] == "cable"}


def _by_ends(cables):
    return {frozenset(tuple(e) for e in r["ends"]): r for r in cables.values()}


def _apply(data, ops):
    import dataset as ds
    return ds.apply_ops(data, ops)[0]


# ── what is offered, and from which fields ───────────────────────────────────

def test_an_uplink_and_the_lldp_that_hears_it_are_one_cable_with_both_ports():
    _, cables = _cables(_snapshot(), CHARTED)
    ends = _by_ends(cables)
    trunk = ends[frozenset({("core-sw", "24"), ("edge", "9")})]
    assert trunk["status"] == "new" and not trunk["blocked"]
    assert trunk["cable"] == {"kind": "copper", "state": "confirmed", "id": "core-sw.24--edge.9"}
    assert trunk["source"] == "unifi" and trunk["name"] == "CORE SW port 24 ↔ EDGE port 9"
    assert len([r for r in cables.values() if {"core-sw", "edge"} == {e[0] for e in r["ends"]}]) == 1


def test_a_port_table_gives_the_speed_and_the_untagged_vlan_and_nothing_more():
    _, cables = _cables(_snapshot(), CHARTED)
    ap = _by_ends(cables)[frozenset({("core-sw", "1"), ("hall-ap", "1")})]
    # port 1 says `port_poe`: it can power something, not what it draws, so no watts
    assert ap["cable"] == {"kind": "copper", "state": "confirmed", "speed": "1G", "vlan": 1,
                           "id": "core-sw.1--hall-ap.1"}
    assert ap["detail"] == "copper · 1G · U1"


def test_a_client_behind_a_devices_port_gets_no_cable_of_its_own():
    """The sample puts the NAS on port 1, where the access point's uplink is."""
    _, cables = _cables(_snapshot(), CHARTED)
    assert not [r for r in cables.values() if "nas" in {e[0] for e in r["ends"]}]


def test_lldp_alone_names_the_port_it_heard_on_and_a_clients_port_is_its_switchs():
    _, cables = _cables(REAL, REAL_CHARTED)
    ends = _by_ends(cables)
    # the strip's uplink names no port; the gateway heard it by LLDP on 7
    assert frozenset({("front-door", "7"), ("strip", "")}) in ends
    host = ends[frozenset({("front-door", "6"), ("big-iron", "")})]
    assert host["cable"]["speed"] == "1G"
    vault = ends[frozenset({("front-door", "8"), ("vault", "")})]
    assert vault["name"] == "VAULT ↔ FRONT-DOOR port 8" and vault["status"] == "new"
    # A hypervisor's guests ride on their host's cable
    assert not [r for r in cables.values() if R_VM1 in r["key"]]


def test_an_end_the_map_has_not_got_makes_no_cable_and_no_stub():
    data = copy.deepcopy(CHARTED)
    data["nodes"] = [n for n in data["nodes"] if n["id"] != "hall-ap"]
    _, cables = _cables(_snapshot(), data)
    assert not [r for r in cables.values() if AP in r["key"]]
    assert [r["ends"] for r in cables.values()] == [[["core-sw", "24"], ["edge", "9"]]]
    # nor on an empty map, where everything else is new
    out, cables = _cables(REAL, {"zones": [], "nodes": [], "routes": []})
    assert cables == {} and out


def test_both_ends_on_one_place_is_no_cable():
    data = copy.deepcopy(CHARTED)
    data["nodes"] = [n for n in data["nodes"] if n["id"] != "hall-ap"]
    data["nodes"][1]["mac"] = AP                    # the switch's card answers to the AP's MAC too
    out, cables = _cables(_snapshot(), data)
    assert next(r for r in out if r["key"] == f"unifi:device/{AP}")["matched"] == "core-sw"
    assert not [r for r in cables.values() if AP in r["key"]]
    assert all(r["ends"][0][0] != r["ends"][1][0] for r in cables.values())


def test_the_same_link_is_offered_under_the_same_key_and_id_every_time():
    _, once = _cables(_snapshot(), CHARTED)
    _, again = _cables(_snapshot(), CHARTED)
    assert list(once) == list(again)
    assert [r["cable"]["id"] for r in once.values()] == [r["cable"]["id"] for r in again.values()]
    # and the other side's records first changes nothing
    flipped = _snapshot()
    flipped["devices"].reverse()
    _, turned = _cables(flipped, CHARTED)
    assert set(turned) == set(once)
    assert {r["cable"]["id"] for r in turned.values()} == {r["cable"]["id"] for r in once.values()}


def test_an_id_taken_by_another_cable_gets_a_number():
    data = copy.deepcopy(CHARTED)
    data["cables"] = [{"id": "core-sw.24--edge.9", "a": "nas", "b": "hall-ap", "source": "hand"}]
    _, cables = _cables(_snapshot(), data)
    trunk = _by_ends(cables)[frozenset({("core-sw", "24"), ("edge", "9")})]
    assert trunk["cable"]["id"] == "core-sw.24--edge.9-2"


# ── what the payload says, read only where it says it (synthetic) ────────────

A1, A2, S1 = "aa:bb:cc:20:00:01", "aa:bb:cc:20:00:02", "aa:bb:cc:20:00:03"
C1, C2, C3 = "de:ad:be:ef:20:01", "de:ad:be:ef:20:02", "de:ad:be:ef:20:03"
SYN = {
    "devices": [
        {"mac": S1, "type": "usw", "name": "Agg", "ip": "192.0.2.2", "port_table": [
            {"port_idx": 3, "up": True, "speed": 1000, "media": "GE", "port_poe": True, "poe_power": "4.52",
             "native_networkconf_id": "net-core"},
            {"port_idx": 4, "up": True, "speed": 1000, "media": "GE"},
            {"port_idx": 25, "up": True, "speed": 10000, "media": "SFP+"},
            {"port_idx": 26, "up": True, "speed": 1000, "media": "GE", "native_networkconf_id": "net-core"}]},
        {"mac": A1, "type": "uap", "name": "Mesh", "ip": "192.0.2.3",
         "uplink": {"uplink_mac": S1, "type": "wireless"}},
        {"mac": A2, "type": "usw", "name": "Leaf", "ip": "192.0.2.4",
         "uplink": {"uplink_mac": S1, "port_idx": 1, "uplink_remote_port": 25, "type": "wire"},
         "port_table": [{"port_idx": 1, "up": True, "speed": 2500, "media": "SFP+",
                         "native_networkconf_id": "net-iot"}]},
    ],
    "clients": [
        {"mac": C1, "ip": "192.0.2.31", "name": "Cam", "is_wired": True, "sw_mac": S1, "sw_port": 3},
        {"mac": C2, "ip": "192.0.2.32", "name": "Desk A", "is_wired": True, "sw_mac": S1, "sw_port": 4},
        {"mac": C3, "ip": "192.0.2.33", "name": "Desk B", "is_wired": True, "sw_mac": S1, "sw_port": 4},
    ],
    "networks": NETWORKS.body["data"],
}
SYN_MAP = {"zones": [], "routes": [], "nodes": [
    {"id": "agg", "name": "AGG", "ip": "192.0.2.2"}, {"id": "mesh", "name": "MESH", "ip": "192.0.2.3"},
    {"id": "leaf", "name": "LEAF", "ip": "192.0.2.4"}, {"id": "cam", "name": "CAM", "ip": "192.0.2.31"},
    {"id": "desk-a", "name": "DESK A", "ip": "192.0.2.32"}, {"id": "desk-b", "name": "DESK B", "ip": "192.0.2.33"}]}


def test_a_wireless_uplink_is_a_radio_link_with_no_ports():
    _, cables = _cables(SYN, SYN_MAP)
    mesh = _by_ends(cables)[frozenset({("agg", ""), ("mesh", "")})]
    assert mesh["cable"]["kind"] == "wireless" and "vlan" not in mesh["cable"]


def test_an_sfp_port_is_fibre_and_two_speeds_that_differ_are_no_speed():
    _, cables = _cables(SYN, SYN_MAP)
    leaf = _by_ends(cables)[frozenset({("agg", "25"), ("leaf", "1")})]
    assert leaf["cable"]["kind"] == "fibre"
    assert "speed" not in leaf["cable"], "10G at one end, 2.5G at the other: not a fact"
    assert leaf["cable"]["vlan"] == 66, "only one end states a VLAN"


def test_a_ports_poe_draw_is_written_in_watts():
    _, cables = _cables(SYN, SYN_MAP)
    cam = _by_ends(cables)[frozenset({("agg", "3"), ("cam", "")})]
    assert cam["cable"]["poe_w"] == 4.5 and cam["cable"]["vlan"] == 1
    assert "PoE 4.5 W" in cam["detail"]


def test_two_clients_on_one_port_are_behind_something_nobody_charted():
    _, cables = _cables(SYN, SYN_MAP)
    assert not [r for r in cables.values() if {"desk-a", "desk-b"} & {e[0] for e in r["ends"]}]


def test_a_wan_port_gives_no_vlan():
    snap = {"devices": [
        {"mac": R_GW, "type": "udm", "name": "Edge", "ip": "10.50.1.1", "port_table": [
            {"port_idx": 9, "up": True, "speed": 1000, "media": "GE", "network_name": "wan",
             "native_networkconf_id": "n-home"}]}],
        "clients": [{"mac": R_HOST, "ip": "10.50.1.6", "is_wired": True, "sw_mac": R_GW, "sw_port": 9}],
        "networks": REAL["networks"]}
    data = {"zones": [], "routes": [], "nodes": [{"id": "gw", "name": "GW", "ip": "10.50.1.1"},
                                                 {"id": "box", "name": "BOX", "ip": "10.50.1.6"}]}
    _, cables = _cables(snap, data)
    (only,) = cables.values()
    assert "vlan" not in only["cable"] and only["cable"]["speed"] == "1G"


# ── what the map already has ─────────────────────────────────────────────────

def _with(cable):
    data = copy.deepcopy(CHARTED)
    data["cables"] = [cable]
    return data


@pytest.mark.parametrize("cable", [
    {"id": "trunk", "a": "core-sw", "a_port": "24", "b": "edge", "b_port": "9", "source": "hand"},
    {"id": "trunk", "a": "edge", "a_port": "9", "b": "core-sw", "b_port": "24"},        # turned, no source
    {"id": "trunk", "a": "core-sw", "b": "edge", "source": "hand"},                     # no ports at all
    {"id": "trunk", "a": "edge", "a_port": "9", "b": "core-sw", "source": "hand", "vlan": 1},
])
def test_a_cable_the_map_already_has_is_not_offered_again(cable):
    _, cables = _cables(_snapshot(), _with(cable))
    trunk = next(r for r in cables.values() if {e[0] for e in r["ends"]} == {"core-sw", "edge"})
    assert (trunk["status"], trunk["blocked"], trunk["matched"]) == ("charted", False, "trunk")


def _differs(cable, against=None):
    out, cables = _cables(_snapshot(), _with(cable))
    trunk = next(r for r in cables.values() if {e[0] for e in r["ends"]} == {"core-sw", "edge"}
                 or r["key"].endswith(against or "\0"))
    return out, trunk


def test_a_hand_cable_on_another_port_is_listed_in_words_and_left_alone():
    out, trunk = _differs({"id": "trunk", "a": "core-sw", "a_port": "8", "b": "edge", "b_port": "9",
                           "source": "hand"})
    assert trunk["blocked"] and trunk["status"] == "new" and trunk["group"] == rv.DIFFERS_GROUP
    assert trunk["differs"] == ["the map says port 8 on CORE SW, UniFi says port 24"]
    assert "stays as it is" in trunk["note"]
    with pytest.raises(rv.PlanError):
        rv.plan(out, [trunk["key"]], _with({}), label="UniFi Network")


def test_a_hand_cable_that_gives_the_port_to_something_else_is_listed():
    out, cables = _cables(_snapshot(), _with({"id": "desk", "a": "core-sw", "a_port": "24", "b": "nas",
                                              "source": "hand"}))
    trunk = _by_ends(cables)[frozenset({("core-sw", "24"), ("edge", "9")})]
    assert trunk["blocked"]
    assert trunk["differs"] == ["the map says port 24 on CORE SW goes to NAS, UniFi says EDGE"]


def test_a_port_given_to_a_stub_names_the_stub():
    data = _with({"id": "desk", "a": "core-sw", "a_port": "24", "b_stub": "under-desk", "source": "hand"})
    data["stubs"] = [{"id": "under-desk", "name": "Desk switch", "kind": "switch"}]
    _, cables = _cables(_snapshot(), data)
    trunk = _by_ends(cables)[frozenset({("core-sw", "24"), ("edge", "9")})]
    assert trunk["differs"] == ["the map says port 24 on CORE SW goes to the stub Desk switch, UniFi says EDGE"]


def test_a_hand_cable_with_another_vlan_is_listed():
    _, cables = _cables(_snapshot(), _with({"id": "ap", "a": "hall-ap", "a_port": "1", "b": "core-sw",
                                            "b_port": "1", "vlan": 10, "tagged": [20], "source": "hand"}))
    ap = _by_ends(cables)[frozenset({("core-sw", "1"), ("hall-ap", "1")})]
    assert ap["blocked"] and ap["differs"] == ["the map says U10 T20, UniFi says U1"]


def test_a_cable_another_system_wrote_is_left_alone_like_a_persons():
    _, cables = _cables(_snapshot(), _with({"id": "trunk", "a": "core-sw", "a_port": "8", "b": "edge",
                                            "b_port": "9", "source": "netbox"}))
    trunk = next(r for r in cables.values() if {e[0] for e in r["ends"]} == {"core-sw", "edge"})
    assert trunk["blocked"] and not trunk.get("updates")


def test_a_disagreement_can_be_ignored_and_comes_back_charted_never():
    cable = {"id": "trunk", "a": "core-sw", "a_port": "8", "b": "edge", "b_port": "9", "source": "hand"}
    _, trunk = _differs(cable)
    _, cables = _cables(_snapshot(), _with(cable), {trunk["key"]})
    assert cables[trunk["key"]]["status"] == "ignored"


def test_two_cables_between_one_pair_each_find_their_own():
    """An aggregate: the map has one by hand; the second is new, not a disagreement."""
    snap = _snapshot()
    sw = next(d for d in snap["devices"] if d["mac"] == SW)
    sw["lldp_table"] = [{"chassis_id": GW, "local_port_idx": 24}, {"chassis_id": GW, "local_port_idx": 23}]
    out, cables = _cables(snap, _with({"id": "trunk", "a": "core-sw", "a_port": "24", "b": "edge",
                                       "b_port": "9", "source": "hand"}))
    pair = [r for r in cables.values() if {e[0] for e in r["ends"]} == {"core-sw", "edge"}]
    assert sorted((r["status"], r["blocked"]) for r in pair) == [("charted", False), ("new", False)]


# ── a cable UniFi wrote, read differently now ────────────────────────────────

def test_a_unifi_cable_on_another_port_is_offered_as_an_update():
    data = _with({"id": "core-sw.8--edge.9", "a": "core-sw", "a_port": "8", "b": "edge", "b_port": "9",
                  "kind": "copper", "state": "confirmed", "source": "unifi", "note": "kept"})
    out, cables = _cables(_snapshot(), data)
    trunk = next(r for r in cables.values() if {e[0] for e in r["ends"]} == {"core-sw", "edge"})
    assert trunk["status"] == "new" and not trunk["blocked"] and trunk["updates"] == "core-sw.8--edge.9"
    assert "the map says port 8 on CORE SW, UniFi says port 24" in trunk["note"]
    ops = rv.plan(out, [trunk["key"]], data, label="UniFi Network")
    assert ops == [{"op": "upsert", "section": "cables", "id": "core-sw.8--edge.9",
                    "body": {"a": "core-sw", "b": "edge", "a_port": "24", "b_port": "9"}}]
    after = _apply(data, ops)
    assert after["cables"][0]["note"] == "kept", "an update carries only what changed"
    _, again = _cables(_snapshot(), after)
    assert again[trunk["key"]]["status"] == "charted"


def test_a_unifi_cable_with_a_stale_field_is_offered_only_that_field():
    data = _with({"id": "ap", "a": "core-sw", "a_port": "1", "b": "hall-ap", "kind": "copper",
                  "state": "confirmed", "speed": "100M", "vlan": 10, "source": "unifi"})
    out, cables = _cables(_snapshot(), data)
    ap = _by_ends(cables)[frozenset({("core-sw", "1"), ("hall-ap", "1")})]
    # the speed is a reading: kept as the map has it, not offered as a change
    assert ap["updates"] == "ap" and ap["changes"] == {"b_port": "1", "vlan": 1}
    assert ap["note"] == "updates the cable UniFi gave before: port 1; U1, was U10"
    after = _apply(data, rv.plan(out, [ap["key"]], data, label="UniFi Network"))
    assert _cables(_snapshot(), after)[1][ap["key"]]["status"] == "charted"


def test_a_reading_fills_a_blank_and_a_drifting_one_is_not_offered_again():
    data = copy.deepcopy(SYN_MAP)
    out, cables = _cables(SYN, data)
    cam = _by_ends(cables)[frozenset({("agg", "3"), ("cam", "")})]
    after = _apply(data, rv.plan(out, [cam["key"]], data, label="UniFi Network"))
    drifted = copy.deepcopy(SYN)
    drifted["devices"][0]["port_table"][0].update(poe_power="4.71", speed=100)
    assert _cables(drifted, after)[1][cam["key"]]["status"] == "charted"
    after["cables"][0].pop("poe_w")
    again = _cables(drifted, after)[1][cam["key"]]
    assert again["updates"] == cam["cable"]["id"] and again["changes"] == {"poe_w": 4.7}


def test_a_unifi_cable_another_row_already_holds_is_never_moved():
    """A wire that would collide with a cable another row has matched is
    listed, never offered as a move of that cable."""
    data = _with({"id": "t", "a": "core-sw", "a_port": "24", "b": "edge", "b_port": "9", "source": "unifi"})
    data["nodes"].append({"id": "odd", "name": "ODD", "ip": "192.0.2.9", "kind": "physical"})
    chart = rv._Map(data)
    row = {"key": "k", "ends": [["odd", ""], ["edge", "9"]], "cable": {"kind": "copper"},
           "source": "unifi", "by": "UniFi"}
    rv._against_the_rest(row, chart, [rv._map_ends(c) for c in chart.cables], {0}, set(), {"t"})
    assert row["blocked"] and not row.get("updates")
    assert row["differs"] == ["the map says port 9 on EDGE goes to CORE SW, UniFi says ODD"]
    # the same row with the cable not held is a move of UniFi's own cable
    row = {"key": "k", "ends": [["odd", ""], ["edge", "9"]], "cable": {"kind": "copper"},
           "source": "unifi", "by": "UniFi"}
    rv._against_the_rest(row, chart, [rv._map_ends(c) for c in chart.cables], set(), set(), {"t"})
    assert row["updates"] == "t" and row["changes"]["a"] == "odd" and row["changes"]["a_port"] is None


def test_a_hand_cable_in_the_way_beats_a_unifi_one():
    data = copy.deepcopy(CHARTED)
    data["cables"] = [
        {"id": "u", "a": "core-sw", "a_port": "8", "b": "edge", "b_port": "9", "source": "unifi"},
        {"id": "h", "a": "core-sw", "a_port": "24", "b": "nas", "source": "hand"}]
    _, cables = _cables(_snapshot(), data)
    trunk = next(r for r in cables.values() if {e[0] for e in r["ends"]} == {"core-sw", "edge"})
    assert trunk["blocked"] and not trunk.get("updates") and len(trunk["differs"]) == 2


# ── landing ──────────────────────────────────────────────────────────────────

def test_ticked_cables_land_as_valid_cables_and_a_second_review_offers_nothing():
    import validation
    data = copy.deepcopy(CHARTED)
    out, cables = _cables(_snapshot(), data)
    picks = [k for k, r in cables.items() if r["status"] == "new" and not r["blocked"]]
    assert len(picks) == 2
    ops = rv.plan(out, picks, data, label="UniFi Network")
    assert {"op": "insert", "section": "cables", "body": {
        "id": "core-sw.1--hall-ap.1", "a": "core-sw", "a_port": "1", "b": "hall-ap", "b_port": "1",
        "kind": "copper", "vlan": 1, "speed": "1G", "state": "confirmed", "source": "unifi"}} in ops
    after = _apply(data, ops)
    assert not [p for p in validation.validate(after, strict=True) if p.startswith("cable")]
    again, cables = _cables(_snapshot(), after)
    assert {r["status"] for r in cables.values()} == {"charted"}
    assert not [r for r in again if r["type"] == "cable" and rv.NEW == r["status"]]


def test_accept_over_the_wire_then_review_again_offers_nothing_new(realm, admin, net):
    save(admin, UNIFI_KEY)
    body = review(admin, "unifi")
    first = [f"unifi:device/{m}" for m in (SW, GW, AP)]
    assert import_(admin, "unifi", first, body).status_code == 200
    body = review(admin, "unifi")
    offered = [r for r in body["rows"] if r["type"] == "cable"]
    assert {r["status"] for r in offered} == {"new"} and len(offered) == 2
    before = dataset(realm)
    r = import_(admin, "unifi", [r["key"] for r in offered], body)
    assert r.status_code == 200, r.get_json()
    laid = [c for c in dataset(realm)["cables"]]
    assert len(laid) == 2 and {c["source"] for c in laid} == {"unifi"}
    assert dataset(realm)["nodes"] == before["nodes"], "a cable changes no place"
    again = [r for r in review(admin, "unifi")["rows"] if r["type"] == "cable"]
    assert {r["status"] for r in again} == {"charted"}
    # and a disagreement posted anyway is refused, with nothing written
    data = dataset(realm)
    data["cables"][0].update(source="hand", a_port="8")
    realm.data_path.write_text(json.dumps(data), encoding="utf-8")
    told = review(admin, "unifi")
    differ = [r for r in told["rows"] if r["type"] == "cable" and r["blocked"]]
    assert len(differ) == 1 and "UniFi says port" in differ[0]["note"]
    held = realm.data_path.read_text(encoding="utf-8")
    r = import_(admin, "unifi", [differ[0]["key"]], told)
    assert r.status_code == 422
    assert realm.data_path.read_text(encoding="utf-8") == held
