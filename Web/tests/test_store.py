"""DB backbone tests (Atlas for Teams Phase 1) — run directly, no pytest needed:

    python Web/tests/test_store.py

Covers the design notes compatibility contract: the golden round-trip
(import the bundled dataset -> export -> deep-compare), upsert identity,
dirty-dataset tolerance, and the db-mode /api/lab-data endpoint serving the
exact file-mode payload with working ETag/304 semantics.
"""

import copy
import json
import os
import sys
import tempfile

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

TMP = tempfile.mkdtemp(prefix="atlas-store-test-")
DB_PATH = os.path.join(TMP, "test.db").replace("\\", "/")

# db-mode env must be set before app import (module-level config)
# Declared once so conftest can re-apply it before every test in this
# module. pytest imports all test modules before running any of them, so
# without this the last module imported owns os.environ for the whole run.
ATLAS_TEST_ENV = {
    "ATLAS_DATA_BACKEND": "db",
    "ATLAS_DB_URL": f"sqlite:///{DB_PATH}",
    "ATLAS_SITE": "default",
    "ATLAS_DATA": os.path.join(TMP, "no-such-lab-data.json"),  # overlays land in TMP
    "ATLAS_ALLOW_INSECURE": "1",
}
os.environ.update(ATLAS_TEST_ENV)

import store  # noqa: E402
from store import init_db, load_labdata, dump_labdata, session_scope  # noqa: E402
from store.models import Node  # noqa: E402

GOLDEN_PATH = os.path.join(WEB, "default-lab-data.json")
with open(GOLDEN_PATH, encoding="utf-8") as f:
    GOLDEN = json.load(f)

init_db()  # tables exist regardless of which test runs first (pytest or direct)


def test_golden_round_trip():
    """the design notes: import default-lab-data.json -> export -> deep equal."""
    with session_scope() as s:
        load_labdata(s, copy.deepcopy(GOLDEN), site_slug="golden")
        out = dump_labdata(s, "golden")
    assert out == GOLDEN, "round-trip diverged from source dataset"
    assert list(out.keys()) == list(GOLDEN.keys()), "top-level key order lost"
    assert [n["id"] for n in out["nodes"]] == [n["id"] for n in GOLDEN["nodes"]], "node order lost"


def test_reimport_is_idempotent_and_preserves_identity():
    with session_scope() as s:
        load_labdata(s, copy.deepcopy(GOLDEN), site_slug="twice")
        first = {n.slug: (n.id, n.first_seen) for n in s.query(Node).all() if n.site.slug == "twice"}
        site = load_labdata(s, copy.deepcopy(GOLDEN), site_slug="twice")
        second = {n.slug: (n.id, n.first_seen) for n in s.query(Node).all() if n.site.slug == "twice"}
        out = dump_labdata(s, "twice")
    assert out == GOLDEN
    assert first == second, "node identity (pk/first_seen) did not survive re-import"
    assert site.data_version == 2


def test_dirty_dataset_round_trips_and_still_validates_loudly():
    """Tolerance doctrine: dangling refs, explicit nulls, empty links, unknown
    keys — all survive the round-trip; the validator still flags what it always
    flagged."""
    dirty = {
        "meta": {"title": "Dirty"},
        "zones": [{"id": "z1", "name": "Zone", "vlan": None, "subnet": "10.0.0.0/24",
                   "hue": "#fff", "lore": "", "label_x": 1, "label_y": 2,
                   "custom_zone_key": {"nested": True}}],
        "nodes": [
            {"id": "a", "name": "A", "kind": "physical", "zone": "z1", "x": 1, "y": 2,
             "role": "r", "lore": "l", "links": [], "mystery": [1, 2]},
            {"id": "b", "name": "B", "kind": "weird-kind", "zone": "no-such-zone",
             "x": 3, "y": 4, "role": "r", "lore": "l",
             "links": [{"label": "svc", "url": "https://x", "kuma": "svc-mon"}]},
        ],
        "routes": [{"from": "a", "to": "ghost"}],
        "unmodeled_section": {"anything": "goes"},
    }
    with session_scope() as s:
        load_labdata(s, copy.deepcopy(dirty), site_slug="dirty")
        out = dump_labdata(s, "dirty")
    assert out == dirty, "dirty dataset did not round-trip exactly"

    from app import _validate
    problems = "\n".join(_validate(out))
    assert "unknown zone" in problems and "unknown kind" in problems and "ghost" in problems


def test_db_mode_endpoint_serves_file_mode_payload():
    init_db()
    with session_scope() as s:
        load_labdata(s, copy.deepcopy(GOLDEN), site_slug="default")

    from appfixture import fresh_app
    atlas_app = fresh_app()
    assert atlas_app.DATA_BACKEND == "db"
    client = atlas_app.app.test_client()

    r = client.get("/api/v2/lab-data")
    assert r.status_code == 200, r.data[:200]
    assert r.get_json() == GOLDEN, "db-mode payload differs from the dataset"
    assert "X-Atlas-Data-Problems" not in r.headers

    etag = r.headers.get("ETag")
    assert etag, "db mode must set an ETag"
    r304 = client.get("/api/v2/lab-data", headers={"If-None-Match": etag})
    assert r304.status_code == 304, "conditional revalidation broken in db mode"

    status = client.get("/api/status").get_json()
    assert status["healthy"] is True
    assert status["summary"]["headline_metric"] == len(GOLDEN["nodes"])

    # a new import bumps the stamp -> fresh ETag, cache invalidated
    with session_scope() as s:
        load_labdata(s, copy.deepcopy(GOLDEN), site_slug="default")
    r2 = client.get("/api/v2/lab-data", headers={"If-None-Match": etag})
    assert r2.status_code == 200 and r2.headers.get("ETag") != etag, "ETag did not roll on data change"


def test_db_mode_problem_dataset_is_loud():
    bad = copy.deepcopy(GOLDEN)
    bad["nodes"][0]["zone"] = "no-such-zone"
    with session_scope() as s:
        load_labdata(s, bad, site_slug="default")
    from appfixture import fresh_app
    client = fresh_app().app.test_client()
    r = client.get("/api/v2/lab-data")
    assert r.status_code == 200
    assert int(r.headers.get("X-Atlas-Data-Problems", 0)) >= 1
    assert client.get("/api/status").get_json()["healthy"] is False
    # restore a clean default site for anything running after us
    with session_scope() as s:
        load_labdata(s, copy.deepcopy(GOLDEN), site_slug="default")


if __name__ == "__main__":
    init_db()
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as e:
                failures += 1
                print(f"  FAIL {name}: {e}")
    print("PASS" if not failures else f"{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)
