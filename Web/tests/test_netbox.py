"""NetBox importer tests — run directly, no pytest needed:

    python Web/tests/test_netbox.py

Drives sync() against recorded API fixtures (tests/fixtures/netbox/) through a
fake transport: pagination, zone matching by VLAN/subnet, role→kind mapping,
upsert/adoption/retirement semantics, hand-edits-win, and fetch atomicity.
Every test uses its own site slug — no ordering dependencies.
"""

import copy
import json
import os
import sys
import tempfile

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

TMP = tempfile.mkdtemp(prefix="atlas-netbox-test-")
DB_URL = "sqlite:///" + os.path.join(TMP, "netbox.db").replace("\\", "/")
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
from importers.netbox import (  # noqa: E402
    NetBoxClient, NetBoxError, fetch_snapshot, parse_role_map, sync,
)
from validation import validate  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "netbox")

init_db()  # tables exist regardless of test order (pytest or direct)


def _fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


PAGES = {
    "/api/ipam/vlans/": _fixture("vlans.json"),
    "/api/ipam/prefixes/": _fixture("prefixes.json"),
    "/api/dcim/devices/": _fixture("devices-page1.json"),
    "/api/dcim/devices/?limit=200&offset=200": _fixture("devices-page2.json"),
    "/api/virtualization/virtual-machines/": _fixture("vms.json"),
}


class FakeClient(NetBoxClient):
    """Serves fixture pages by path; a callable page raises (atomicity tests)."""

    def __init__(self, pages=None):
        super().__init__("https://netbox.test", token="fixture")
        self.pages = pages or PAGES

    def _get(self, path, params=None):
        page = self.pages.get(path)
        if page is None:
            raise NetBoxError(f"GET {path}: no fixture")
        if callable(page):
            page()
        return copy.deepcopy(page)


def _scope():
    os.environ["ATLAS_DB_URL"] = DB_URL  # immune to other test modules' env churn
    return session_scope()


def _snapshot():
    return fetch_snapshot(FakeClient())


def _nodes(session, site_slug):
    site = get_site(session, site_slug)
    return {n.slug: n for n in session.query(Node).filter(Node.site_id == site.id)}


def test_fresh_sync_builds_valid_dataset():
    snap = _snapshot()
    assert len(snap["devices"]) == 4, "pagination not followed"
    with _scope() as s:
        stats = sync(s, snap, site_slug="fresh")
        out = dump_labdata(s, "fresh")
        nodes = _nodes(s, "fresh")
    assert stats["nodes_created"] == 6 and stats["placed"] == 6, stats
    assert stats["zones_created"] == 3  # upper-deck, outset-dmz, uncharted

    assert validate(out) == [], f"netbox-built dataset must validate clean: {validate(out)}"

    n = {x["id"]: x for x in out["nodes"]}
    assert n["hypervisor"]["kind"] == "physical"
    assert n["hypervisor"]["ip"] == "10.77.33.5" and n["hypervisor"]["zone"] == "upper-deck"
    assert "Ryzen" in n["hypervisor"]["hw"] and "Server 2025" in n["hypervisor"]["hw"]
    assert n["gateway"]["kind"] == "network" and n["gateway"]["zone"] == "outset-dmz"
    assert n["gateway"]["scroll"] == "https://docs.test/gateway"  # custom_fields.atlas_url
    assert n["edge"]["kind"] == "vm" and "4 vCPU" in n["edge"]["hw"]
    assert n["shadow-box"]["zone"] == "uncharted"  # no primary ip
    for x in out["nodes"]:
        assert 0 <= x["x"] <= 100 and -40 <= x["y"] <= 140, f"{x['id']} off-table"
    assert nodes["gateway"].external_ref == "device:3"
    assert nodes["edge"].external_ref == "vm:7"


def test_resync_is_idempotent_and_stable():
    snap = _snapshot()
    with _scope() as s:
        sync(s, snap, site_slug="resync")
        pos1 = {n.slug: (n.id, n.x, n.y) for n in _nodes(s, "resync").values()}
        stats = sync(s, _snapshot(), site_slug="resync")
        pos2 = {n.slug: (n.id, n.x, n.y) for n in _nodes(s, "resync").values()}
    assert stats["nodes_created"] == 0 and stats["nodes_updated"] == 6, stats
    assert pos1 == pos2, "re-sync must not reshuffle identity or layout"


def test_netbox_owns_facts_but_hand_edits_win():
    with _scope() as s:
        sync(s, _snapshot(), site_slug="hand")
        n = _nodes(s, "hand")["hypervisor"]
        n.lore = "The hand-written legend."
        n.scroll = "D:\\docs\\scroll.md"
        n.x, n.y, n.layout_locked = 42.0, 24.0, True
        s.flush()
        snap = _snapshot()
        dev = next(d for d in snap["devices"] if d["id"] == 1)
        dev["primary_ip4"]["address"] = "10.77.33.7/24"
        dev["custom_fields"]["atlas_url"] = "https://netbox.test/should-not-win"
        sync(s, snap, site_slug="hand")
        n = _nodes(s, "hand")["hypervisor"]
    assert n.ip == "10.77.33.7", "NetBox-owned facts must refresh"
    assert n.lore == "The hand-written legend."
    assert n.scroll == "D:\\docs\\scroll.md", "hand-set scroll overwritten"
    assert (n.x, n.y) == (42.0, 24.0), "locked position moved"


def test_retirement_hides_from_map_and_resurrects():
    with _scope() as s:
        sync(s, _snapshot(), site_slug="ret")
        snap = _snapshot()
        snap["devices"] = [d for d in snap["devices"] if d["id"] != 2]  # The NAS gone
        stats = sync(s, snap, site_slug="ret")
        hidden = dump_labdata(s, "ret")
        assert stats["nodes_retired"] == 1, stats
        assert "nas" not in {x["id"] for x in hidden["nodes"]}, "retired node still on map"
        assert _nodes(s, "ret")["nas"].status == "retired"  # kept, not deleted
        stats = sync(s, _snapshot(), site_slug="ret")
        back = dump_labdata(s, "ret")
    assert stats["nodes_resurrected"] == 1, stats
    assert "nas" in {x["id"] for x in back["nodes"]}


def test_adoption_of_hand_charted_node():
    with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as f:
        golden = json.load(f)
    lore_before = next(n for n in golden["nodes"] if n["id"] == "nas")["lore"]
    snap = {"vlans": [], "prefixes": [],
            "devices": [_fixture("devices-page1.json")["results"][1]], "vms": []}
    with _scope() as s:
        load_labdata(s, golden, site_slug="mix")
        count_before = len(_nodes(s, "mix"))
        stats = sync(s, snap, site_slug="mix")
        nodes = _nodes(s, "mix")
    assert stats["nodes_adopted"] == 1 and stats["nodes_created"] == 0, stats
    assert len(nodes) == count_before, "adoption must not duplicate the node"
    n = nodes["nas"]
    assert n.external_source == "netbox" and n.external_ref == "device:2"
    assert n.lore == lore_before, "adoption must not touch hand-written lore"
    assert n.zone_slug == "sky", "adoption must not move the node's realm"


def test_fetch_failure_aborts_before_any_write():
    def boom():
        raise NetBoxError("GET page2: HTTP 500")
    pages = dict(PAGES)
    pages["/api/dcim/devices/?limit=200&offset=200"] = boom
    try:
        fetch_snapshot(FakeClient(pages))
        assert False, "expected NetBoxError"
    except NetBoxError:
        pass
    with _scope() as s:
        assert get_site(s, "never-created") is None


def test_role_map_parsing():
    m = parse_role_map("nas=physical, edge-router=network")
    assert m["nas"] == "physical" and m["edge-router"] == "network"
    assert m["firewall"] == "network"  # defaults preserved
    try:
        parse_role_map("garbage")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_cli_requires_token():
    os.environ.pop("NETBOX_TOKEN", None)
    os.environ.pop("NETBOX_TOKEN_FILE", None)
    import cli
    assert cli.main(["--db", DB_URL, "import-netbox", "--url", "https://netbox.test"]) == 2


if __name__ == "__main__":
    init_db()
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
