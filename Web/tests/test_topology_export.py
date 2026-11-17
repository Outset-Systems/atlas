"""TOPOLOGY's connections sheet: `GET /api/v2/topology/connections.csv` (2026-11-17).

What matters: the columns and rows are the view's own (`topology.connections`)
on the demo map; a viewer who may not see a place finds it in no column (not
as a row, not as what a row is connected to, not inside another row's path)
and the row behind it loses its cable; a cell a spreadsheet would run as a
formula is written with a `'` before it; the answer is a dated UTF-8 file with
a byte-order mark that nothing keeps; and it is the page's, so a token alone
is refused.
"""

import csv
import io
import json
import os
import re

import pytest

import topology
import viewers
from api.v2 import topology_sheet as sheet

URL = "/api/v2/topology/connections.csv"
HEADER = ["Device", "Connected to", "Port", "Far port", "VLAN", "PoE (W)", "Path to the head"]
ARROW = " " + chr(0x203A) + " "
DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "demo-lab", "seed", "lab-data.demo.json")


def cable(cid, a, b, **extra):
    return {"id": cid, "a": a, "b": b, "kind": "copper", "state": "confirmed", **extra}


def _wired():
    """Alpha is the head; the hidden Secret hangs from it; Beta hangs from
    Secret; Gamma hangs from Alpha straight."""
    data = viewers.dataset(
        cables=[cable("head-secret", "alpha", "secret-place", a_port="p1", b_port="up", vlan=10),
                cable("secret-beta", "secret-place", "beta", a_port="p7", b_port="eth0", vlan=10),
                cable("head-gamma", "alpha", "gamma", a_port="p2", b_port="eth0", vlan=10, poe_w=12.5)],
        stubs=[],
    )
    data["nodes"][0]["kind"] = "network"
    data["nodes"].append(viewers.place("gamma", "Gamma", ip="192.0.2.7"))
    return data


@pytest.fixture
def realm(tmp_path, monkeypatch):
    handle = viewers.build(tmp_path, monkeypatch, _wired())
    yield handle
    monkeypatch.undo()


def _table(resp):
    raw = resp.get_data()
    assert raw.startswith(b"\xef\xbb\xbf"), "a byte-order mark first"
    text = raw.decode("utf-8")[1:]
    assert "\r\n" in text and "\n" not in text.replace("\r\n", ""), "CRLF lines"
    return list(csv.reader(io.StringIO(text)))


def _by_device(table):
    return {row[0]: row for row in table[1:]}


# ── the columns and rows ─────────────────────────────────────────────────────

def test_the_demo_map_gives_the_views_own_rows(tmp_path, monkeypatch):
    if not os.path.exists(DEMO):
        pytest.skip("no demo-lab seed in this tree")
    with open(DEMO, encoding="utf-8") as fh:
        demo = json.load(fh)
    handle = viewers.build(tmp_path, monkeypatch, demo)
    try:
        r = viewers.signed_in(handle, "ops").get(URL)
        assert r.status_code == 200, r.get_data(as_text=True)
        table = _table(r)
        assert table[0] == HEADER
        want = topology.connections(topology.build_graph(demo))
        assert [row[0] for row in table[1:]] == [w["name"] for w in want]
        rows = _by_device(table)
        assert rows["CAMERA HUB"] == ["CAMERA HUB", "CORE SWITCH", "eth0", "8", "U66", "12",
                                      ARROW.join(["CAMERA HUB", "CORE SWITCH", "GATEWAY", "Fibre line in"])]
        assert rows["CORE SWITCH"][1:6] == ["GATEWAY", "24", "igc1", "U1 T10,30,33,66,90", ""]
        # the provider's line is a stub with a cable, so it has a row: the head, blank
        assert rows["Fibre line in"] == ["Fibre line in", "", "", "", "", "", ""]
        # a place that hangs by a route or nothing is blank, never a guess
        assert rows["APP HOST"] == ["APP HOST", "", "", "", "", "", ""]
    finally:
        monkeypatch.undo()


def test_a_viewer_sees_every_place_it_may_and_the_cables_between_them(realm):
    table = _table(viewers.signed_in(realm, "ops").get(URL))
    rows = _by_device(table)
    assert set(rows) == {"Alpha", "Beta", "Gamma", "Secret"}
    assert rows["Beta"] == ["Beta", "Secret", "eth0", "p7", "U10", "", ARROW.join(["Beta", "Secret", "Alpha"])]
    assert rows["Gamma"] == ["Gamma", "Alpha", "eth0", "p2", "U10", "12.5", ARROW.join(["Gamma", "Alpha"])]


def test_a_hidden_place_is_in_no_column_and_its_cables_went_with_it(realm):
    r = viewers.signed_in(realm, "alice").get(URL)
    assert r.status_code == 200
    table = _table(r)
    rows = _by_device(table)
    assert set(rows) == {"Alpha", "Beta", "Gamma"}
    # Beta hung from the hidden switch: its cable columns are blank, not re-routed
    assert rows["Beta"] == ["Beta", "", "", "", "", "", ""]
    assert rows["Gamma"][1] == "Alpha" and rows["Gamma"][6] == ARROW.join(["Gamma", "Alpha"])
    body = r.get_data(as_text=True)
    for word in ("Secret", "secret-place", "192.0.2.99", "p1", "p7", "up"):
        assert word not in body, word


# ── what a spreadsheet would run ─────────────────────────────────────────────

@pytest.mark.parametrize("value", ["=HYPERLINK(\"http://example.org\")", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])
def test_a_cell_a_spreadsheet_would_run_is_neutralised(value):
    assert sheet.safe_cell(value) == "'" + value
    assert sheet.safe_cell("ALPHA") == "ALPHA" and sheet.safe_cell(12) == "12" and sheet.safe_cell(None) == ""


def test_the_neutralising_reaches_every_column(tmp_path, monkeypatch):
    data = viewers.dataset(cables=[cable("c", "alpha", "beta", a_port="@up", b_port="-3")], stubs=[])
    data["nodes"][0]["name"] = "=cmd|' /C calc'!A0"
    data["nodes"][1]["name"] = "+Beta"
    handle = viewers.build(tmp_path, monkeypatch, data)
    try:
        rows = _by_device(_table(viewers.signed_in(handle, "ops").get(URL)))
        beta = rows["'+Beta"]
        assert beta[:4] == ["'+Beta", "'=cmd|' /C calc'!A0", "'-3", "'@up"]
        assert beta[6] == "'+Beta" + ARROW + "=cmd|' /C calc'!A0"
    finally:
        monkeypatch.undo()


# ── the answer ───────────────────────────────────────────────────────────────

def test_the_answer_is_a_dated_utf8_attachment_nothing_keeps(realm):
    r = viewers.signed_in(realm, "alice").get(URL)
    assert r.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert re.fullmatch(r'attachment; filename="test-realm-connections-\d{4}-\d{2}-\d{2}\.csv"',
                        r.headers["Content-Disposition"]), r.headers["Content-Disposition"]
    assert r.headers["Cache-Control"] == "no-store"
    assert "Vary" in r.headers
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_a_token_alone_and_a_stranger_are_refused(realm):
    for headers in (viewers.issue(realm), viewers.issue(realm, "cloud"), {}):
        r = realm.app.test_client().get(URL, headers=headers)
        assert r.status_code in (401, 403), r.status_code
        assert b"Alpha" not in r.get_data()


def test_the_file_name_is_plain_ascii_and_matches_the_clients_slug():
    assert sheet.file_name("Test Realm", "2026-11-17") == "test-realm-connections-2026-11-17.csv"
    assert sheet.slug("  Café  Ünïcode!! ") == "cafe-unicode"
    assert sheet.slug("日本") == sheet.slug(None) == "atlas"
    assert sheet.slug('../../etc/"passwd"') == "etc-passwd"
    long = sheet.slug("a" * 30 + " " + "b" * 30)
    assert len(long) <= 40 and not long.endswith("-")
