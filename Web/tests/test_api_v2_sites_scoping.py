"""The multi-site read API — run directly, no pytest needed:

    python Web/tests/test_api_v2_sites_scoping.py

Two sites are seeded with deliberately distinguishable data, and **every**
endpoint is asserted to return one site's rows only. Tenancy is not a P1 UI
concern to these tests: if a cross-site read is ever possible, it should fail
here, years before a second customer exists.
"""

import copy
import json
import os
import sys

import pytest
import tempfile

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

TMP = tempfile.mkdtemp(prefix="atlas-sites-test-")
DB_URL = "sqlite:///" + os.path.join(TMP, "sites.db").replace("\\", "/")

# Declared once so conftest can re-apply it before every test in this
# module. pytest imports all test modules before running any of them, so
# without this the last module imported owns os.environ for the whole run.
ATLAS_TEST_ENV = {
    "ATLAS_DATA_BACKEND": "db",
    "ATLAS_DB_URL": DB_URL,
    "ATLAS_SITE": "lab",
    "ATLAS_DATA": os.path.join(TMP, "no-such-lab-data.json"),
    "ATLAS_ALLOW_INSECURE": "1",
}
os.environ.update(ATLAS_TEST_ENV)
os.environ.pop("ATLAS_INGEST_ENABLED", None)

from importers.nmap import import_observations  # noqa: E402
from store import init_db, load_labdata, session_scope  # noqa: E402

init_db()

with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as f:
    GOLDEN = json.load(f)

# Site 2 is a different customer entirely: no node id, zone id, or IP overlaps.
ACME = {
    "meta": {"title": "Acme HQ"},
    "zones": [{"id": "acme-lan", "name": "Acme LAN", "vlan": 5,
               "subnet": "192.168.5.0/24", "hue": "#888", "lore": "",
               "label_x": 20.0, "label_y": 30.0}],
    "nodes": [
        {"id": "acme-switch", "name": "Acme Switch", "kind": "network",
         "zone": "acme-lan", "x": 20.0, "y": 30.0, "role": "switch", "lore": "",
         "ip": "192.168.5.2",
         "links": [{"label": "Switch UI", "url": "https://192.168.5.2"}]},
        {"id": "acme-secret", "name": "Acme Payroll", "kind": "vm",
         "zone": "acme-lan", "x": 30.0, "y": 30.0, "role": "payroll", "lore": "",
         "ip": "192.168.5.9", "require_group": "ACME-Finance",
         "links": [{"label": "Payroll", "url": "https://payroll.acme.test",
                    "require_group": "ACME-Finance"}]},
    ],
    "routes": [],
}

#: any charted address in the dataset: the observation that must MATCH a place
_KNOWN_IP = next(n["ip"] for n in GOLDEN["nodes"] if str(n.get("ip", ""))[:1].isdigit())

with session_scope() as _s:
    load_labdata(_s, copy.deepcopy(GOLDEN), site_slug="lab", site_name="the lab")
    load_labdata(_s, copy.deepcopy(ACME), site_slug="acme", site_name="Acme HQ")
    import_observations(_s, [{"ip": _KNOWN_IP, "hostname": "known"},
                             {"ip": "10.77.33.99", "hostname": "lab-stranger"}],
                        site_slug="lab")
    import_observations(_s, [{"ip": "192.168.5.55", "hostname": "acme-stranger",
                              "mac": "AA:00:00:00:00:55"}], site_slug="acme")

from appfixture import fresh_app  # noqa: E402

# Build the app against the env this module just set, so the suite is
# order-independent (see tests/appfixture.py).
atlas_app = fresh_app()

CLIENT = atlas_app.app.test_client()
LAB_IDS = {n["id"] for n in GOLDEN["nodes"]}
ACME_IDS = {n["id"] for n in ACME["nodes"]}


def _get(path, groups=None):
    # X-Remote-User rides along because the hub-mode session gate demands one;
    # without it the redaction tests get a 403 instead of a redacted body.
    headers = {"X-Remote-Groups": groups, "X-Remote-User": "tester"} if groups is not None else {}
    return CLIENT.get(path, headers=headers)


def test_sites_exist_in_db_mode():
    assert atlas_app.DATA_BACKEND == "db"
    assert _get("/api/v2/sites").status_code == 200


def test_sites_lists_both_with_counts():
    body = _get("/api/v2/sites").get_json()
    by_slug = {s["slug"]: s for s in body["sites"]}
    assert set(by_slug) == {"acme", "lab"}
    assert by_slug["lab"]["counts"]["nodes"] == len(GOLDEN["nodes"])
    assert by_slug["acme"]["counts"]["nodes"] == len(ACME["nodes"])
    assert by_slug["acme"]["name"] == "Acme HQ"
    assert by_slug["lab"]["updated_at"].endswith("Z")


def test_lab_data_is_scoped_and_matches_the_map_shape():
    lab = _get("/api/v2/sites/lab/lab-data")
    assert lab.status_code == 200
    assert lab.get_json() == GOLDEN, "the site read must serve the canonical dataset unchanged"

    acme = _get("/api/v2/sites/acme/lab-data").get_json()
    ids = {n["id"] for n in acme["nodes"]}
    assert ids == ACME_IDS
    assert not (ids & LAB_IDS), "cross-site leak in lab-data"
    assert acme["meta"]["title"] == "Acme HQ"


def test_lab_data_etag_revalidates_and_is_per_site():
    a = _get("/api/v2/sites/lab/lab-data")
    etag = a.headers["ETag"]
    assert CLIENT.get("/api/v2/sites/lab/lab-data",
                      headers={"If-None-Match": etag}).status_code == 304
    # the same ETag must not satisfy a different site
    other = CLIENT.get("/api/v2/sites/acme/lab-data", headers={"If-None-Match": etag})
    assert other.status_code == 200, "one site's ETag validated another site's response"


def test_nodes_are_scoped_and_carry_provenance():
    body = _get("/api/v2/sites/acme/nodes").get_json()
    assert body["site"] == "acme"
    ids = {n["id"] for n in body["nodes"]}
    assert ids == ACME_IDS and not (ids & LAB_IDS), "cross-site leak in nodes"
    switch = next(n for n in body["nodes"] if n["id"] == "acme-switch")
    assert switch["source"] == "file" and switch["status"] == "documented"
    assert switch["ip"] == "192.168.5.2" and switch["zone"] == "acme-lan"
    assert switch["links"] == [{"label": "Switch UI", "url": "https://192.168.5.2"}]

    lab_ids = {n["id"] for n in _get("/api/v2/sites/lab/nodes").get_json()["nodes"]}
    assert not (lab_ids & ACME_IDS), "cross-site leak in nodes (reverse direction)"


def test_nodes_status_and_source_filters():
    with session_scope() as s:
        from store.labdata import get_site
        from store.models import Node
        node = s.query(Node).filter(Node.site_id == get_site(s, "acme").id,
                                    Node.slug == "acme-switch").one()
        node.status = "retired"

    live = {n["id"] for n in _get("/api/v2/sites/acme/nodes").get_json()["nodes"]}
    assert "acme-switch" not in live, "retired nodes must be hidden by default"
    everything = {n["id"] for n in
                  _get("/api/v2/sites/acme/nodes?status=all").get_json()["nodes"]}
    assert "acme-switch" in everything
    only_retired = _get("/api/v2/sites/acme/nodes?status=retired").get_json()["nodes"]
    assert [n["id"] for n in only_retired] == ["acme-switch"]
    assert _get("/api/v2/sites/acme/nodes?status=bogus").status_code == 400
    assert _get("/api/v2/sites/acme/nodes?source=netbox").get_json()["count"] == 0

    with session_scope() as s:  # restore for later tests
        from store.labdata import get_site
        from store.models import Node
        s.query(Node).filter(Node.site_id == get_site(s, "acme").id,
                             Node.slug == "acme-switch").one().status = "documented"


def test_observed_defaults_to_the_drift_list_and_is_scoped():
    body = _get("/api/v2/sites/lab/observed").get_json()
    assert body["undocumented"] == 1 and body["count"] == 1
    assert body["observed"][0]["ip"] == "10.77.33.99"
    assert body["observed"][0]["hostname"] == "lab-stranger"
    assert body["observed"][0]["undocumented"] is True

    everything = _get("/api/v2/sites/lab/observed?all=1").get_json()
    assert everything["count"] == 2
    matched = [o for o in everything["observed"] if not o["undocumented"]]
    assert matched[0]["matched_node"] == next(n["id"] for n in GOLDEN["nodes"] if n.get("ip") == _KNOWN_IP)

    acme = _get("/api/v2/sites/acme/observed").get_json()
    assert [o["ip"] for o in acme["observed"]] == ["192.168.5.55"], "cross-site leak in observed"
    assert acme["observed"][0]["mac"] == "AA:00:00:00:00:55"


def test_unknown_and_hostile_slugs_are_404_not_crashes():
    for slug in ("no-such-site", "lab%20", "..", "%2e%2e%2flab", "'; DROP TABLE nodes;--"):
        for suffix in ("lab-data", "nodes", "observed"):
            r = CLIENT.get(f"/api/v2/sites/{slug}/{suffix}")
            assert r.status_code in (404, 400), f"{slug}/{suffix} -> {r.status_code}"
    # the database is intact
    assert _get("/api/v2/sites/lab/nodes").get_json()["count"] == len(GOLDEN["nodes"])


@pytest.fixture
def hub_mode():
    """Redaction only applies behind the Hub — say so, instead of assuming it.

    These two tests exercise `require_group`, which `redaction.viewer_groups()`
    ignores entirely outside hub mode. They never set the mode, so they had
    been asserting on an unredacted response and failing on every run.
    """
    import hub_auth.auth as auth
    original = auth.AUTH_MODE
    auth.AUTH_MODE = "hub"
    try:
        yield
    finally:
        auth.AUTH_MODE = original


def test_group_redaction_applies_to_the_site_reads(hub_mode):
    """Same rule, one implementation (redaction.py)."""
    outsider = _get("/api/v2/sites/acme/lab-data", groups="ACME-Staff").get_json()
    assert {n["id"] for n in outsider["nodes"]} == {"acme-switch"}, "restricted node leaked"

    insider = _get("/api/v2/sites/acme/lab-data", groups="ACME-Finance").get_json()
    assert {n["id"] for n in insider["nodes"]} == ACME_IDS
    assert insider["nodes"][1]["links"], "cleared viewer lost their link"

    admin = _get("/api/v2/sites/acme/lab-data", groups="atlas-admins").get_json()
    assert {n["id"] for n in admin["nodes"]} == ACME_IDS

    nodes = _get("/api/v2/sites/acme/nodes", groups="ACME-Staff").get_json()
    assert {n["id"] for n in nodes["nodes"]} == {"acme-switch"}, "restricted node leaked in /nodes"
    cleared_nodes = _get("/api/v2/sites/acme/nodes", groups="ACME-Finance").get_json()
    payroll = next(n for n in cleared_nodes["nodes"] if n["id"] == "acme-secret")
    assert payroll["links"] and payroll["links"][0]["label"] == "Payroll"


def test_observed_is_scoped_by_clearance_like_its_sibling(hub_mode):
    """`/observed` returned every discovered device — ip, mac, hostname,
    vendor, open ports — to any authenticated viewer, while `/nodes` right
    beside it filtered each row through `cleared()`. Two rules for one estate,
    and this was the permissive one.

    A row matched to a place the viewer may not see IS that place under another
    name. An unmatched row is the survey's drift list — it belongs to no
    charted place, so no partial clearance can cover it and it stays
    admin-only, the same call THE DRIFT gets in the signals feed.
    """
    outsider = _get("/api/v2/sites/acme/observed?all=1", groups="ACME-Staff").get_json()
    ips = {o["ip"] for o in outsider["observed"]}
    assert all(not o["undocumented"] for o in outsider["observed"]), \
        "the drift list is survey information, not a viewer's to read"
    assert "192.168.5.9" not in ips, "a restricted node's device leaked in /observed"

    admin = _get("/api/v2/sites/acme/observed?all=1", groups="atlas-admins").get_json()
    assert admin["count"] >= outsider["count"]


def test_redacted_viewers_do_not_share_a_cache_entry(hub_mode):
    outsider = _get("/api/v2/sites/acme/lab-data", groups="ACME-Staff")
    insider = _get("/api/v2/sites/acme/lab-data", groups="ACME-Finance")
    assert outsider.headers["ETag"] != insider.headers["ETag"], \
        "clearance levels must not share an ETag"
    reused = CLIENT.get("/api/v2/sites/acme/lab-data",
                        headers={"If-None-Match": outsider.headers["ETag"],
                                 "X-Remote-Groups": "ACME-Finance",
                                 "X-Remote-User": "tester"})
    assert reused.status_code == 200, "an outsider's ETag served an insider a 304"


def test_sites_stay_behind_the_session_gate():
    """Unlike ingest, the site reads are NOT exempt: a hub-mode request with no
    user is refused."""
    import hub_auth.auth as auth
    from api import v2 as api_v2
    check = auth.require_hub_or_standalone(
        exempt_prefixes=["/static/", api_v2.INGEST_URL_PREFIX + "/"])
    original = auth.AUTH_MODE
    auth.AUTH_MODE = "hub"
    try:
        with atlas_app.app.test_request_context("/api/v2/sites/lab/lab-data"):
            result = check()
        assert result is not None, "the site reads must not bypass the Hub session gate"
        assert result[1] == 403
        with atlas_app.app.test_request_context(
                "/api/v2/sites/lab/lab-data", headers={"X-Remote-User": "ops"}):
            assert check() is None, "a signed-in hub user must be allowed through"
    finally:
        auth.AUTH_MODE = original


def test_lab_data_is_marked_private_and_varies_on_the_viewer():
    """The body is redacted per viewer, so it needs the same two headers its
    siblings carry: `private` (a shared cache may not store it) and the viewer
    `Vary`. It had bare `no-cache` and no `Vary` at all — a cache in front of
    the app could have stored an admin's unredacted dataset under the bare URL
    and served it to the next viewer. The admin response is the one that
    matters most: it is the unredacted one."""
    for groups in ("atlas-admins", "ACME-Staff"):
        r = _get("/api/v2/sites/acme/lab-data", groups=groups)
        assert r.status_code == 200
        cc = r.headers["Cache-Control"]
        assert "private" in cc and "no-cache" in cc, cc
        vary = r.headers.get("Vary", "")
        for header in ("Cookie", "X-Hub-Auth", "X-Remote-User", "X-Remote-Groups"):
            assert header in vary, (groups, vary)
    # and the conditional path keeps them too
    a = _get("/api/v2/sites/acme/lab-data", groups="ACME-Finance")
    b = CLIENT.get("/api/v2/sites/acme/lab-data",
                   headers={"X-Remote-Groups": "ACME-Finance", "X-Remote-User": "tester",
                            "If-None-Match": a.headers["ETag"]})
    assert b.status_code == 304
    assert "Cookie" in b.headers.get("Vary", "")


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
