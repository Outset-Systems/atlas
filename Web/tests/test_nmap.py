"""nmap importer tests — run directly, no pytest needed:

    python Web/tests/test_nmap.py

Covers parsing a recorded `nmap -oX` scan, matching observations to documented
nodes, the drift signal (undocumented devices), promotion into real nodes, and
the doctrine that a scan never deletes or retires anything.
"""

import copy
import json
import os
import sys
import tempfile

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

TMP = tempfile.mkdtemp(prefix="atlas-nmap-test-")
DB_URL = "sqlite:///" + os.path.join(TMP, "nmap.db").replace("\\", "/")
# Declared once so conftest can re-apply it before every test in this
# module. pytest imports all test modules before running any of them, so
# without this the last module imported owns os.environ for the whole run.
ATLAS_TEST_ENV = {
    "ATLAS_DB_URL": DB_URL,
}
os.environ.update(ATLAS_TEST_ENV)

from store import init_db, load_labdata, dump_labdata, session_scope  # noqa: E402
from store.labdata import get_site  # noqa: E402
from store.models import Node, ObservedNode  # noqa: E402
from importers.nmap import (  # noqa: E402
    NmapError, import_observations, parse_nmap_xml, undocumented,
)
from validation import validate  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "nmap")
with open(os.path.join(FIX, "scan.xml"), encoding="utf-8") as f:
    SCAN = f.read()
with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as f:
    GOLDEN = json.load(f)

init_db()


def _scope():
    os.environ["ATLAS_DB_URL"] = DB_URL
    return session_scope()


def _seed(session, slug):
    load_labdata(session, copy.deepcopy(GOLDEN), site_slug=slug)


def _nodes(session, slug):
    site = get_site(session, slug)
    return {n.slug: n for n in session.query(Node).filter(Node.site_id == site.id)}


def test_parse_skips_down_hosts_and_reads_details():
    hosts = parse_nmap_xml(SCAN)
    assert len(hosts) == 3, "down host should be skipped"
    first = hosts[0]
    assert first["ip"] == "10.77.33.5"
    assert first["mac"] == "AA:BB:CC:00:00:06" and "Micro-Star" in first["vendor"]
    assert first["hostname"] == "hypervisor.home.example"
    assert [p["port"] for p in first["ports"]] == [22], "only open ports are recorded"
    assert hosts[1]["ports"] == []


def test_doctype_is_refused():
    evil = '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY a "b">]><nmaprun/>'
    try:
        parse_nmap_xml(evil)
        assert False, "expected NmapError for DOCTYPE"
    except NmapError:
        pass


def test_bad_xml_is_an_error_not_a_crash():
    try:
        parse_nmap_xml("not xml at all")
        assert False, "expected NmapError"
    except NmapError:
        pass


def test_matches_documented_nodes_and_flags_the_stranger():
    with _scope() as s:
        _seed(s, "drift")
        stats = import_observations(s, parse_nmap_xml(SCAN), site_slug="drift")
        strangers = undocumented(s, "drift")
        after = dump_labdata(s, "drift")
    assert stats["matched"] == 2, stats           # hypervisor + nas are on the map
    assert stats["undocumented"] == 1, stats      # the ESP board is not
    assert stats["observed_new"] == 3 and stats["promoted"] == 0, stats
    assert [o.ip for o in strangers] == ["10.77.33.99"]
    assert strangers[0].hostname == "esp-9f2a.home.example"
    assert strangers[0].raw_json.get("vendor") == "Espressif Inc."
    assert len(after["nodes"]) == len(GOLDEN["nodes"]), "a scan must not add nodes without --promote"


def test_rescan_updates_rather_than_duplicating():
    with _scope() as s:
        _seed(s, "rescan")
        import_observations(s, parse_nmap_xml(SCAN), site_slug="rescan")
        first_seen = {o.ip: o.first_seen for o in s.query(ObservedNode)
                      .filter(ObservedNode.site_id == get_site(s, "rescan").id)}
        stats = import_observations(s, parse_nmap_xml(SCAN), site_slug="rescan")
        rows = list(s.query(ObservedNode)
                    .filter(ObservedNode.site_id == get_site(s, "rescan").id))
    assert stats["observed_new"] == 0 and stats["observed_seen"] == 3, stats
    assert len(rows) == 3, "rescan duplicated observation rows"
    for o in rows:
        assert o.first_seen == first_seen[o.ip], "first_seen must not move"
        assert o.last_seen >= o.first_seen


def test_promote_charts_the_stranger_and_keeps_the_map_valid():
    with _scope() as s:
        _seed(s, "promote")
        stats = import_observations(s, parse_nmap_xml(SCAN), site_slug="promote", promote=True)
        nodes = _nodes(s, "promote")
        out = dump_labdata(s, "promote")
        strangers = undocumented(s, "promote")
    assert stats["promoted"] == 1 and stats["undocumented"] == 0, stats
    assert stats["placed"] >= 1, "promoted node must be laid out"
    assert strangers == [], "a promoted device is no longer undocumented"
    n = nodes["esp-9f2a"]
    assert n.kind == "unknown" and n.ip == "10.77.33.99"
    assert n.external_source == "nmap" and n.external_ref == "ip:10.77.33.99"
    assert n.zone_slug == "sky", "10.77.33.99 belongs to the 10.77.33.0/24 realm"
    assert n.x is not None and n.y is not None
    assert validate(out) == [], f"promoted map must still validate: {validate(out)}"
    assert len(out["nodes"]) == len(GOLDEN["nodes"]) + 1


def test_absent_host_is_never_retired():
    """A powered-off machine must not erase its marker (scan != inventory)."""
    with _scope() as s:
        _seed(s, "absent")
        import_observations(s, parse_nmap_xml(SCAN), site_slug="absent")
        smaller = [h for h in parse_nmap_xml(SCAN) if h["ip"] != "10.77.33.10"]
        import_observations(s, smaller, site_slug="absent")
        out = dump_labdata(s, "absent")
        nodes = _nodes(s, "absent")
    assert "nas" in {x["id"] for x in out["nodes"]}
    assert nodes["nas"].status == "documented"


def test_promoted_node_survives_rescan_without_duplicating():
    with _scope() as s:
        _seed(s, "twice")
        import_observations(s, parse_nmap_xml(SCAN), site_slug="twice", promote=True)
        before = _nodes(s, "twice")["esp-9f2a"]
        before_id, before_pos = before.id, (before.x, before.y)
        stats = import_observations(s, parse_nmap_xml(SCAN), site_slug="twice", promote=True)
        after = _nodes(s, "twice")["esp-9f2a"]
        count = len(_nodes(s, "twice"))
    assert stats["promoted"] == 0, "already-charted device must not be promoted again"
    assert after.id == before_id and (after.x, after.y) == before_pos
    assert count == len(GOLDEN["nodes"]) + 1


if __name__ == "__main__":
    failures = 0
    for name in sorted(n for n in globals() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"  ok   {name}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {name}: {e}")
    print("PASS" if not failures else f"{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)


def test_a_promoted_stranger_is_stamped_unreviewed_and_the_rest_are_left_alone():
    """The importers write rows, not a dataset, so they pass the store's stamp:
    `restamp` gives what they added the same standing a Desk survey gets."""
    from store import restamp
    with _scope() as s:
        _seed(s, "stamped")
        before = dump_labdata(s, "stamped")
        import_observations(s, parse_nmap_xml(SCAN), site_slug="stamped", promote=True)
        moved = restamp(s, "stamped", before, "cli", "nmap")
        after = dump_labdata(s, "stamped")
        again = restamp(s, "stamped", after, "cli", "nmap")
    was = {n["id"] for n in before["nodes"]}
    new = [n for n in after["nodes"] if n["id"] not in was]
    assert new and moved >= len(new)
    for n in new:
        mark = n["provenance"]
        assert mark["reviewed"] is False and mark["source"] == "nmap" and mark["charted_by"] == "cli"
    # a place the scan did not change says nothing new, and a second pass is a no-op
    untouched = [n for n in after["nodes"] if n["id"] in was and "provenance" not in n]
    assert untouched
    assert again == 0
