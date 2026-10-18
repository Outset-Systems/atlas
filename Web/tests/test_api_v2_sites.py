"""The multi-site reads — `/api/v2/sites…` (db mode only): shape, headers,
ETag/304, the status filter, unknown sites, and FILE mode 404ing the paths.

The cross-site negative controls (two seeded customers, every endpoint scoped)
live in `test_api_v2_sites_scoping.py`.
"""

import copy
import json
import os
import sys
import tempfile

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

TMP = tempfile.mkdtemp(prefix="atlas-apiv2-sites-")
DB_URL = "sqlite:///" + os.path.join(TMP, "sites.db").replace("\\", "/")

ATLAS_TEST_ENV = {
    "ATLAS_DATA_BACKEND": "db",
    "ATLAS_DB_URL": DB_URL,
    "ATLAS_SITE": "lab",
    "ATLAS_DATA": os.path.join(TMP, "no-such-lab-data.json"),
    "ATLAS_ALLOW_INSECURE": "1",
    "ATLAS_AUTH_MODE": "standalone",
}
os.environ.update(ATLAS_TEST_ENV)
os.environ.pop("ATLAS_INGEST_ENABLED", None)

from store import init_db, load_labdata, session_scope  # noqa: E402

init_db()
with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as f:
    GOLDEN = json.load(f)
with session_scope() as _s:
    load_labdata(_s, copy.deepcopy(GOLDEN), site_slug="lab", site_name="the lab")

from appfixture import fresh_app  # noqa: E402


@pytest.fixture
def client():
    return fresh_app(**ATLAS_TEST_ENV).app.test_client()


def _assert_private_read(r):
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "private, no-cache"
    vary = r.headers.get("Vary", "")
    for header in ("Cookie", "X-Hub-Auth", "X-Remote-User", "X-Remote-Groups"):
        assert header in vary, vary


def test_sites_list(client):
    r = client.get("/api/v2/sites")
    assert r.status_code == 200
    sites = r.get_json()["sites"]
    assert [s["slug"] for s in sites] == ["lab"]
    assert sites[0]["counts"]["nodes"] == len(GOLDEN["nodes"])
    assert sites[0]["updated_at"].endswith("Z")


def test_site_lab_data_and_etag(client):
    r = client.get("/api/v2/sites/lab/lab-data")
    _assert_private_read(r)
    assert r.get_json() == GOLDEN
    etag = r.headers.get("ETag")
    assert etag
    r = client.get("/api/v2/sites/lab/lab-data", headers={"If-None-Match": etag})
    assert r.status_code == 304


def test_site_nodes_and_the_status_filter(client):
    r = client.get("/api/v2/sites/lab/nodes")
    _assert_private_read(r)
    body = r.get_json()
    assert body["site"] == "lab" and body["count"] == len(body["nodes"])
    assert {n["id"] for n in body["nodes"]} == {n["id"] for n in GOLDEN["nodes"]}
    assert client.get("/api/v2/sites/lab/nodes",
                      query_string={"status": "all"}).status_code == 200
    r = client.get("/api/v2/sites/lab/nodes", query_string={"status": "bogus"})
    assert r.status_code == 400
    assert "status must be one of" in r.get_json()["error"]


def test_site_observed(client):
    r = client.get("/api/v2/sites/lab/observed")
    _assert_private_read(r)
    body = r.get_json()
    assert body["site"] == "lab" and body["count"] == 0 and body["observed"] == []
    assert client.get("/api/v2/sites/lab/observed",
                      query_string={"all": "1"}).status_code == 200


def test_unknown_site_is_404(client):
    r = client.get("/api/v2/sites/nope/lab-data")
    assert r.status_code == 404
    assert "no such site" in r.get_json()["error"]


def test_file_mode_has_no_sites(tmp_path):
    import shutil
    data = tmp_path / "lab-data.json"
    shutil.copy(os.path.join(WEB, "default-lab-data.json"), data)
    c = fresh_app(ATLAS_DATA_BACKEND="file", ATLAS_DATA=str(data),
                  ATLAS_AUTH_MODE="standalone",
                  ATLAS_ALLOW_INSECURE="1").app.test_client()
    assert c.get("/api/v2/sites").status_code == 404
    assert c.get("/api/v2/sites/lab/lab-data").status_code == 404


def test_db_mode_map_reads(client):
    """The map's own reads under the db backend: the db reader path and its
    ETag ride here (the file-mode tests live in test_api_v2_reads.py)."""
    r = client.get("/api/v2/lab-data")
    _assert_private_read(r)
    assert {n["id"] for n in r.get_json()["nodes"]} == {n["id"] for n in GOLDEN["nodes"]}
    etag = r.headers.get("ETag")
    assert etag
    assert client.get("/api/v2/lab-data", headers={"If-None-Match": etag}).status_code == 304
    _assert_private_read(client.get("/api/v2/maps"))
