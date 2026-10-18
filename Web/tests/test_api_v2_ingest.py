"""Relay ingest — `/api/v2/ingest/*` (db + opt-in only).

The bearer token is the whole boundary, so its refusals are the workstation:
missing 401, unknown 401, wrong-site 403, malformed 422 — plus the happy
paths with deterministic counts, and the fence: disabled or file mode, the
paths 404. `test_ingest.py` goes deeper (scopes, revocation, size, rate).
"""

import copy
import json
import os
import sys
import tempfile

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

TMP = tempfile.mkdtemp(prefix="atlas-apiv2-ingest-")
DB_URL = "sqlite:///" + os.path.join(TMP, "ingest.db").replace("\\", "/")

ATLAS_TEST_ENV = {
    "ATLAS_DATA_BACKEND": "db",
    "ATLAS_DB_URL": DB_URL,
    "ATLAS_SITE": "lab",
    "ATLAS_DATA": os.path.join(TMP, "no-such-lab-data.json"),
    "ATLAS_ALLOW_INSECURE": "1",
    "ATLAS_AUTH_MODE": "standalone",
    "ATLAS_INGEST_ENABLED": "1",
}
os.environ.update(ATLAS_TEST_ENV)

from store import init_db, load_labdata, session_scope  # noqa: E402
from store.tokens import issue_token  # noqa: E402

init_db()
with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as f:
    GOLDEN = json.load(f)
with session_scope() as _s:
    load_labdata(_s, copy.deepcopy(GOLDEN), site_slug="lab", site_name="the lab")
    TOKEN, _row = issue_token(_s, "lab", label="v2 ingest test")

import ingest  # noqa: E402
from appfixture import fresh_app  # noqa: E402

AUTH = {"Authorization": f"Bearer {TOKEN}"}
INGEST = "/api/v2/ingest"


@pytest.fixture
def client():
    handle = fresh_app(**ATLAS_TEST_ENV)
    assert handle.app.config["INGEST_ENABLED"] is True
    ingest.limiter.reset()
    return handle.app.test_client()


def test_token_refusals(client):
    r = client.post(f"{INGEST}/signals", json={})
    assert r.status_code == 401 and r.get_json() == {"error": "missing bearer token"}
    r = client.post(f"{INGEST}/signals", headers={"Authorization": "Bearer nope"}, json={})
    assert r.status_code == 401 and r.get_json() == {"error": "unknown token"}


def test_signals(client):
    feed = {"nodes": {"app-host": {"state": "healthy"}}, "metrics": {"up": 9}}
    r = client.post(f"{INGEST}/signals", headers=AUTH, json=feed)
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "site": "lab", "nodes": 1, "services": 0, "metrics": 1}
    r = client.post(f"{INGEST}/signals", headers=AUTH, json={"nothing": True})
    assert r.status_code == 422 and "no recognisable signal data" in r.get_json()["error"]
    r = client.post(f"{INGEST}/signals", headers=AUTH, json=[1, 2])
    assert r.status_code == 422 and r.get_json() == {"error": "expected a JSON object"}


def test_wrong_site_is_403(client):
    feed = {"site": "someone-else", "nodes": {"x": {"state": "down"}}}
    r = client.post(f"{INGEST}/signals", headers=AUTH, json=feed)
    assert r.status_code == 403
    assert r.get_json() == {"error": "token is not valid for that site"}


def test_inventory(client):
    r = client.post(f"{INGEST}/inventory", headers=AUTH, json={"devices": "not-a-list"})
    assert r.status_code == 422 and "must be a list of objects" in r.get_json()["error"]
    r = client.post(f"{INGEST}/inventory", headers=AUTH, json={"devices": [{"name": "no-id"}]})
    assert r.status_code == 422 and "needs an 'id'" in r.get_json()["error"]
    r = client.post(f"{INGEST}/inventory", headers=AUTH, json={})
    assert r.status_code == 422 and r.get_json() == {"error": "empty snapshot"}
    good = {"devices": [{"id": 1, "name": "core-sw"}]}
    r = client.post(f"{INGEST}/inventory", headers=AUTH, json=good)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] and body["site"] == "lab" and "stats" in body
    # a second identical sync is steady state: same answer
    ingest.limiter.reset()
    assert client.post(f"{INGEST}/inventory", headers=AUTH, json=good).get_json() == \
        client.post(f"{INGEST}/inventory", headers=AUTH, json=good).get_json()


def test_observed(client):
    r = client.post(f"{INGEST}/observed", headers=AUTH, json={"hosts": "nope"})
    assert r.status_code == 422 and "'hosts' must be a list" in r.get_json()["error"]
    r = client.post(f"{INGEST}/observed", headers=AUTH, json={"hosts": [{"vendor": "x"}]})
    assert r.status_code == 422 and "needs an 'ip' or a 'mac'" in r.get_json()["error"]
    r = client.post(f"{INGEST}/observed", headers=AUTH,
                    json={"hosts": [{"ip": "10.9.9.9"}], "source": "wat"})
    assert r.status_code == 422 and "source must be" in r.get_json()["error"]
    good = {"hosts": [{"ip": "10.9.9.9", "mac": "aa:bb:cc:dd:ee:ff"}]}
    r = client.post(f"{INGEST}/observed", headers=AUTH, json=good)
    assert r.status_code == 200
    assert r.get_json()["ok"] and r.get_json()["stats"]["undocumented"] == 1


def test_disabled_or_file_mode_404s(tmp_path):
    import shutil
    data = tmp_path / "lab-data.json"
    shutil.copy(os.path.join(WEB, "default-lab-data.json"), data)
    c = fresh_app(ATLAS_DATA_BACKEND="file", ATLAS_DATA=str(data),
                  ATLAS_INGEST_ENABLED="0", ATLAS_AUTH_MODE="standalone",
                  ATLAS_ALLOW_INSECURE="1").app.test_client()
    assert c.post(f"{INGEST}/signals", headers=AUTH, json={}).status_code == 404
