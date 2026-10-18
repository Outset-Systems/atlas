"""CSV importer tests — run directly, no pytest needed:

    python Web/tests/test_csv.py

Covers the spreadsheet-user contract: a device list becomes a valid map,
every problem is reported with its line number, and a single bad row imports
nothing at all.
"""

import copy
import json
import os
import sys
import tempfile

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

TMP = tempfile.mkdtemp(prefix="atlas-csv-test-")
DB_URL = "sqlite:///" + os.path.join(TMP, "csv.db").replace("\\", "/")
# Declared once so conftest can re-apply it before every test in this
# module. pytest imports all test modules before running any of them, so
# without this the last module imported owns os.environ for the whole run.
ATLAS_TEST_ENV = {
    "ATLAS_DB_URL": DB_URL,
}
os.environ.update(ATLAS_TEST_ENV)

from store import init_db, load_labdata, dump_labdata, session_scope  # noqa: E402
from store.labdata import get_site  # noqa: E402
from store.models import Node  # noqa: E402
from importers.csv_import import CsvError, import_text, parse_csv  # noqa: E402
from validation import validate  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "csv")
with open(os.path.join(FIX, "devices.csv"), encoding="utf-8") as f:
    DEVICES = f.read()

init_db()


def _scope():
    os.environ["ATLAS_DB_URL"] = DB_URL
    return session_scope()


def _nodes(session, slug):
    site = get_site(session, slug)
    return {n.slug: n for n in session.query(Node).filter(Node.site_id == site.id)}


def test_device_list_becomes_a_valid_map():
    with _scope() as s:
        stats = import_text(s, DEVICES, site_slug="office")
        out = dump_labdata(s, "office")
        nodes = _nodes(s, "office")
        # `links` is a lazy relationship: read it while the session is open.
        # Detached, it only loads if some earlier query happened to populate
        # it, which made this assertion pass or fail by test order.
        switch_links = [(l.label, l.url) for l in nodes["front-desk-switch"].links]
    assert stats["created"] == 4 and stats["zones_created"] == 2, stats
    assert stats["links_added"] == 3, stats  # the AP row has no url
    assert stats["placed"] == 4, stats
    assert validate(out) == [], f"csv-built map must validate clean: {validate(out)}"

    n = nodes["front-desk-switch"]
    assert n.kind == "network" and n.ip == "192.168.10.2"
    assert n.role == "48-port PoE switch" and n.lore == "Closet A"
    assert n.external_source == "csv" and n.external_ref == "front-desk-switch"
    assert switch_links == [("Switch UI", "https://192.168.10.2")]
    assert {z["id"] for z in out["zones"]} == {"main-office", "warehouse"}
    assert nodes["warehouse-ap"].zone_slug == "warehouse"
    for x in out["nodes"]:
        assert 0 <= x["x"] <= 100 and -40 <= x["y"] <= 140


def test_reimport_updates_without_duplicating_nodes_or_links():
    with _scope() as s:
        import_text(s, DEVICES, site_slug="again")
        before = {slug: n.id for slug, n in _nodes(s, "again").items()}
        stats = import_text(s, DEVICES, site_slug="again")
        nodes = _nodes(s, "again")
        switch_link_count = len(nodes["front-desk-switch"].links)  # lazy: read in-session
    assert stats["created"] == 0 and stats["updated"] == 4, stats
    assert stats["links_added"] == 0, "re-import duplicated service links"
    assert {slug: n.id for slug, n in nodes.items()} == before
    assert switch_link_count == 1


def test_hand_written_lore_and_position_survive():
    with _scope() as s:
        import_text(s, DEVICES, site_slug="hand")
        n = _nodes(s, "hand")["file-server"]
        n.lore = "Ask Dana before rebooting."
        n.x, n.y, n.layout_locked = 33.0, 44.0, True
        s.flush()
        import_text(s, DEVICES, site_slug="hand")
        n = _nodes(s, "hand")["file-server"]
    assert n.lore == "Ask Dana before rebooting.", "csv notes overwrote a human's words"
    assert (n.x, n.y) == (33.0, 44.0), "locked position moved"


def test_every_bad_row_is_reported_with_its_line_number():
    bad = (
        "name,ip,kind,zone,url\n"
        "Good Switch,10.0.0.1,network,Office,https://ok.example\n"
        ",10.0.0.2,vm,Office,\n"                       # line 3: no name
        "Bad IP,not-an-ip,vm,Office,\n"                 # line 4: bad ip
        "Bad Kind,10.0.0.4,toaster,Office,\n"           # line 5: bad kind
        "Bad Url,10.0.0.5,vm,Office,ftp://nope\n"       # line 6: bad url
        "Good Switch,10.0.0.6,vm,Office,\n"             # line 7: duplicate name
    )
    rows, errors = parse_csv(bad)
    joined = "\n".join(errors)
    assert len(errors) == 5, joined
    for line, needle in ((3, "name is required"), (4, "not an IP"),
                         (5, "unknown kind"), (6, "url must start"), (7, "duplicate name")):
        assert f"line {line}:" in joined and needle in joined, f"missing {needle}: {joined}"


def test_one_bad_row_imports_nothing():
    bad = "name,ip\nFine Device,10.0.0.1\nBroken,not-an-ip\n"
    try:
        with _scope() as s:
            import_text(s, bad, site_slug="atomic")
        assert False, "expected CsvError"
    except CsvError:
        pass
    with _scope() as s:
        assert get_site(s, "atomic") is None, "a rejected file must leave no site behind"


def test_unknown_and_missing_columns_are_rejected():
    _, errors = parse_csv("name,ip,color\nThing,10.0.0.1,red\n")
    assert any("unknown column" in e for e in errors), errors
    _, errors = parse_csv("ip,kind\n10.0.0.1,vm\n")
    assert any("missing required column 'name'" in e for e in errors), errors
    _, errors = parse_csv("")
    assert errors and "empty file" in errors[0]


def test_csv_is_additive_unless_told_otherwise():
    subset = "name,ip\nFront Desk Switch,192.168.10.2\n"
    with _scope() as s:
        import_text(s, DEVICES, site_slug="additive")
        import_text(s, subset, site_slug="additive")
        kept = dump_labdata(s, "additive")
        stats = import_text(s, subset, site_slug="additive", retire_missing=True)
        pruned = dump_labdata(s, "additive")
    assert len(kept["nodes"]) == 4, "a partial csv must not retire the rest of the map"
    assert stats["retired"] == 3, stats
    assert {n["id"] for n in pruned["nodes"]} == {"front-desk-switch"}


def test_csv_adopts_nothing_it_did_not_create():
    """retire_missing only ever touches csv-sourced rows."""
    with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as f:
        golden = json.load(f)
    with _scope() as s:
        load_labdata(s, copy.deepcopy(golden), site_slug="mixed")
        import_text(s, "name,ip\nNew Thing,10.9.9.9\n", site_slug="mixed",
                    retire_missing=True)
        out = dump_labdata(s, "mixed")
    ids = {n["id"] for n in out["nodes"]}
    assert "hypervisor" in ids, "csv retirement must not touch hand-charted nodes"
    assert "new-thing" in ids
    assert len(ids) == len(golden["nodes"]) + 1


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
