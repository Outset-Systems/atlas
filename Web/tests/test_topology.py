"""The server's twin of TOPOLOGY's rules (topology.py, 2026-11-17).

Every case in tests/topology_cases.json is run here exactly as
tests/test_topology_model.mjs runs it through the client's
static/js/topology-model.js: the same heads, depths, what each thing hangs
from, paths to the head and connections rows, and the data left as it was
given. A few small checks of the twin's own reading follow.
"""

import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import topology as T  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "topology_cases.json"), encoding="utf-8") as fh:
    CASES = json.load(fh)["cases"]


def test_the_shared_cases_file_has_every_case_the_twin_needs():
    assert len(CASES) >= 10
    for c in CASES:
        for key in ("name", "data", "heads", "depth", "up", "paths", "connections"):
            assert key in c, f"{c.get('name')} lacks {key}"


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_a_shared_case(case):
    data = copy.deepcopy(case["data"])
    graph = T.build_graph(data)
    assert T.heads(graph) == case["heads"], "heads"
    info = T.layers(graph)
    assert list(info) == [t["id"] for t in graph["things"]], "layers are in thing order"
    for tid, depth in case["depth"].items():
        assert tid in info, f"{tid} is a thing"
        assert info[tid]["depth"] == depth, f"depth of {tid}"
        assert info[tid]["loose"] is (depth is None), f"loose of {tid}"
    for tid, up in case["up"].items():
        assert (info[tid]["up"]["id"] if info[tid]["up"] else None) == up, f"up of {tid}"
    for tid, path in case["paths"].items():
        p = T.path_to_head(graph, tid)
        assert p["things"] == path, f"path of {tid}"
        assert len(p["links"]) == max(0, len(path) - 1)
        assert all(lid in graph["link_by_id"] for lid in p["links"])
    keys = ("id", "to", "port", "farPort", "vlan", "poe", "path")
    rows = [{k: r[k] for k in keys} for r in T.connections(graph)]
    assert rows == case["connections"], "connections"
    assert data == case["data"], "the data is not changed"


def test_a_row_names_the_far_thing_by_id_too_and_poe_is_a_plain_number():
    case = next(c for c in CASES if c["name"] == "a single chain")
    rows = {r["id"]: r for r in T.connections(T.build_graph(case["data"]))}
    assert (rows["app"]["toId"], rows["app"]["name"]) == ("host", "APP")
    assert rows["app"]["poe"] == 4 and isinstance(rows["app"]["poe"], int)
    assert rows["gate"]["toId"] == ""


def test_values_are_read_as_the_client_reads_them():
    assert [T.vlan_number(v) for v in (10, 4.0, "20", " 30 ", 4096, -1, 4.5, True, "—", "x", None)] == \
        [10, 4, 20, 30, None, None, None, None, None, None, None]
    assert T.vlan_label({"vlan": "1", "tagged": ["99", 20, 10, 20, "x"]}) == "U1 T10,20,99"
    assert T.vlan_label({"tagged": [30, 20]}) == "T20,30"
    assert T.vlan_label({}) == "" and T.vlan_label(None) == ""
    g = T.build_graph({"nodes": [{"id": "a", "ip": "—", "kind": 7}, {"id": "b", "name": True}],
                       "cables": [{"a": "a", "b": "b", "poe_w": "7.5"}, {"a": "a", "b": "b", "poe_w": True}]})
    assert (g["by_id"]["a"]["ip"], g["by_id"]["a"]["kind"], g["by_id"]["b"]["name"]) == ("", "7", "b")
    assert [link["poe"] for link in g["links"]] == [7.5, None]
    assert [link["id"] for link in g["links"]] == ["cable:0", "cable:1"]
    assert [(link["lane"], link["lanes"]) for link in g["links"]] == [(0, 2), (1, 2)]


def test_a_route_beside_a_cable_is_shadowed_and_a_parent_tie_it_covers_is_not_added():
    g = T.build_graph({"nodes": [{"id": "host"}, {"id": "vm", "parent": "host"}, {"id": "vm2", "parent": "host"}],
                       "cables": [{"id": "c", "a": "host", "b": "vm"}],
                       "routes": [{"from": "host", "to": "vm"}, {"from": "host", "to": "vm"}]})
    assert [(link["id"], link["layer"], link["shadowed"]) for link in g["links"]] == [
        ("c", "cable", False), ("route:host:vm", "route", True), ("route:host:vm:2", "route", True),
        ("parent:vm2", "parent", False)]


def test_nothing_and_junk_give_an_empty_graph():
    for data in (None, [], "x", {}, {"nodes": "x", "cables": {}}):
        g = T.build_graph(data)
        assert (g["things"], g["links"], T.heads(g), T.connections(g)) == ([], [], [], [])
        assert T.path_to_head(g, "x") == {"things": [], "links": []}
