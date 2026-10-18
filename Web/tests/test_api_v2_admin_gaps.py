"""The editor's darker arms: revert, the ops 409/503, the scan/as-nodes happy
paths, the survey success + 502, the LDAP admin-proof receipt (TTL'd, and it
unlocks the directory-only save), the maintenance 409/422, acking a real
event, and the editor under hub mode's gate.
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

WRITE = {"X-Atlas-Write": "1"}
ADMIN = "/api/v2/admin"


def _app(tmp_path, **extra):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    return fresh_app(
        ATLAS_DATA=str(data),
        ATLAS_POSITIONS=str(tmp_path / "positions.json"),
        ATLAS_RACK=str(tmp_path / "rack.json"),
        ATLAS_REVISIONS=str(tmp_path / "revisions"),
        ATLAS_OBSERVED=str(tmp_path / "observed.json"),
        ATLAS_EVENTS=str(tmp_path / "events.json"),
        ATLAS_MAINTENANCE=str(tmp_path / "maintenance.json"),
        ATLAS_MAPS=str(tmp_path / "maps"),
        **{**{"ATLAS_READONLY": "0"}, **extra},
    )


@pytest.fixture
def handle(tmp_path):
    return _app(tmp_path)


@pytest.fixture
def client(handle):
    return handle.app.test_client()


def test_revert(client):
    ops = {"ops": [{"op": "upsert", "section": "nodes", "id": "hypervisor",
                    "body": {"lore": "A line to revert."}}]}
    assert client.post(f"{ADMIN}/ops", headers=WRITE, json=ops).status_code == 200
    rev = client.get(f"{ADMIN}/revisions").get_json()["revisions"][0]["id"]
    r = client.post(f"{ADMIN}/revisions/{rev}/revert", headers=WRITE)
    assert r.status_code == 200 and r.get_json()["revision"] > rev
    r = client.post(f"{ADMIN}/revisions/999999/revert", headers=WRITE)
    assert r.status_code == 422 and r.get_json()["problems"]


def test_ops_conflict_and_busy(handle, monkeypatch):
    import dataset as ds
    client = handle.app.test_client()
    r = client.post(f"{ADMIN}/ops", headers=WRITE,
                    json={"ops": [], "expect": "a-stale-stamp-from-another-editor"})
    assert r.status_code == 409 and r.get_json()["problems"]

    ctx = handle.app.extensions["atlas"]

    def busy(*a, **k):
        raise ds.BusyError("another save is in flight")
    monkeypatch.setattr(ctx.store, "apply", busy)
    r = client.post(f"{ADMIN}/ops", headers=WRITE, json={"ops": []})
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "2"


def test_discovery_scan_and_as_nodes_happy_path(client):
    with open(os.path.join(FIXTURES, "nmap", "scan.xml"), encoding="utf-8") as f:
        xml = f.read()
    r = client.post(f"{ADMIN}/discovery/scan", headers=WRITE, json={"nmap_xml": xml})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] and body["seen"] >= 1 and body["new"] == body["seen"]
    rows = client.get(f"{ADMIN}/discovery").get_json()["observed"]
    keys = [row["key"] for row in rows]
    assert keys, "the scan filed hosts"
    drafts = client.post(f"{ADMIN}/discovery/as-nodes", json={"keys": keys}).get_json()["nodes"]
    assert len(drafts) == len(keys)
    assert all(d["kind"] == "unknown" for d in drafts), "a scan cannot say what a thing is"


def test_map_art_survey_happy_and_502(client, monkeypatch):
    import worldsurvey
    monkeypatch.setattr(worldsurvey, "survey",
                        lambda q: ("survey-test.png", "Somewhere, the lab"))
    r = client.post(f"{ADMIN}/map-art/survey", headers=WRITE, json={"query": "somewhere"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] and body["name"] == "survey-test.png" and body["surveyed"] == "Somewhere, the lab"

    def boom(q):
        raise RuntimeError("render exploded")
    monkeypatch.setattr(worldsurvey, "survey", boom)
    r = client.post(f"{ADMIN}/map-art/survey", headers=WRITE, json={"query": "somewhere"})
    assert r.status_code == 502
    assert r.get_json() == {"error": "the survey failed — see the server log"}


def test_ldap_admin_proof_unlocks_the_directory_only_save(client, monkeypatch):
    """The receipt: a directory-only config is refused until a directory admin
    has proven they can bind under it — then the save goes through."""
    from api.v2 import admin as api_admin
    import auth_config
    import ldap_backend
    monkeypatch.setattr(ldap_backend, "authenticate",
                        lambda u, p, overrides=None:
                        (True, {"is_admin": True, "groups": ["atlas-admins"],
                                "display_name": "Ops", "username": u, "email": ""}))
    monkeypatch.setattr(auth_config, "save", lambda v: dict(v))
    ldap_only = {"settings": {"ATLAS_AUTH_BACKENDS": "ldap",
                              "ATLAS_LDAP_URL": "ldaps://dc.lab.test",
                              "ATLAS_LDAP_BASE_DN": "dc=lab,dc=test"}}

    api_admin._proof_by_actor.clear()
    r = client.post(f"{ADMIN}/auth", headers=WRITE, json=ldap_only)
    assert r.status_code == 422 and r.get_json()["needs_proof"] is True

    r = client.post(f"{ADMIN}/auth/test", headers=WRITE,
                    json={"settings": {}, "username": "ops", "password": "pw"})
    assert r.status_code == 200 and r.get_json()["is_admin"]
    r = client.post(f"{ADMIN}/auth", headers=WRITE, json=ldap_only)
    assert r.status_code == 200 and r.get_json()["ok"]


def test_maintenance_conflict_and_problems(client):
    r = client.post(f"{ADMIN}/maintenance", headers=WRITE,
                    json={"windows": [], "expect": "a-stale-stamp"})
    assert r.status_code == 409
    r = client.post(f"{ADMIN}/maintenance", headers=WRITE, json={"windows": [{"id": "w1"}]})
    assert r.status_code == 422
    assert r.get_json()["error"] == "those repairs have problems" and r.get_json()["problems"]


def test_event_ack_real_event(client):
    import events
    events.record({"nodes": {"app-host": {"state": "healthy"}}, "cached": False})
    events.record({"nodes": {"app-host": {"state": "down"}}, "cached": False})
    rows = events.listing(limit=1)
    assert rows, "the transition produced an event"
    eid = rows[0]["id"]
    r = client.post(f"{ADMIN}/events/{eid}/ack", headers=WRITE, json={"note": "seen"})
    assert r.status_code == 200
    ack = r.get_json()["event"]["ack"]
    assert ack["note"] == "seen" and ack["by"] and ack["at"].endswith("Z")
    # idempotent: a second ack keeps the first
    again = client.post(f"{ADMIN}/events/{eid}/ack", headers=WRITE, json={"note": "two"})
    assert again.get_json()["event"]["ack"]["note"] == "seen"


def test_hub_mode_admin(tmp_path):
    """The editor under the framework gate: a hub-signed admin reaches it, a
    group-less viewer is refused."""
    import hub_auth.auth as auth
    handle = _app(tmp_path, ATLAS_AUTH_MODE="hub")
    original = auth.AUTH_MODE
    auth.AUTH_MODE = "hub"
    try:
        c = handle.app.test_client()
        r = c.get(f"{ADMIN}/context",
                  headers={"X-Remote-User": "ops", "X-Remote-Groups": "atlas-admins"})
        assert r.status_code == 200 and r.get_json()["actor"] == "ops"
        assert r.headers["Cache-Control"] == "no-store, private"
        r = c.get(f"{ADMIN}/context",
                  headers={"X-Remote-User": "alice", "X-Remote-Groups": "HL-Nobody"})
        assert r.status_code == 403 and r.get_json() == {"error": "admins only"}
    finally:
        auth.AUTH_MODE = original
