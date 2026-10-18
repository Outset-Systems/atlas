"""The editing API — `/api/v2/admin/*`: the surface, one arm each.

`test_api_admin.py` carries the refusals that define the editor (no header,
cross-site, read-only, not an admin) and the write path in depth; this file
walks the rest of the surface — discovery, CSV import, repairs, the annals
ack, map art, the directory settings — asserting status, shape and the nested
blueprint's headers (`no-store, private` + `Vary: X-Hub-Auth`).
"""

import base64
import io
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app, login_as  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

PW = "a-long-enough-password"
WRITE = {"X-Atlas-Write": "1"}
ADMIN = "/api/v2/admin"

#: 1×1 transparent PNG — a real raster so `mapart.sniff` accepts the bytes.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhf"
    "DwAChwGA60e6kgAAAABJRU5ErkJggg==")


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
def client(tmp_path):
    return _app(tmp_path).app.test_client()


def _assert_admin_read(r):
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store, private"
    assert r.headers["Vary"] == "X-Hub-Auth"


# ── editor core ──────────────────────────────────────────────────────────────

def test_context_dataset_dependents_revisions(client):
    r = client.get(f"{ADMIN}/context")
    _assert_admin_read(r)
    assert {"schema", "stamp", "actor", "backend", "writable", "version"} <= set(r.get_json())
    r = client.get(f"{ADMIN}/dataset")
    _assert_admin_read(r)
    assert set(r.get_json()) == {"data", "stamp", "overridden"}
    r = client.get(f"{ADMIN}/dependents", query_string={"section": "nodes", "id": "hypervisor"})
    assert r.status_code == 200 and "dependents" in r.get_json()
    r = client.get(f"{ADMIN}/dependents", query_string={"section": "bogus", "id": "x"})
    assert r.status_code == 400 and "unknown section" in r.get_json()["error"]
    r = client.get(f"{ADMIN}/revisions")
    _assert_admin_read(r)
    assert set(r.get_json()) == {"revisions", "kept"}


def test_ops_apply_and_the_malformed_batch(client):
    ops = {"ops": [{"op": "upsert", "section": "nodes", "id": "hypervisor",
                    "body": {"lore": "The same sentence, twice."}}]}
    r = client.post(f"{ADMIN}/ops", headers=WRITE, json=ops)
    assert r.status_code == 200
    body = r.get_json()
    assert body["changed"] and body["revision"] and "overlays_cleared" in body
    r = client.post(f"{ADMIN}/ops", headers=WRITE, json=[1])
    assert r.status_code == 400 and r.get_json() == {"error": "expected {ops, expect}"}


# ── discovery inbox & import ─────────────────────────────────────────────────

def test_discovery_surface(client):
    r = client.get(f"{ADMIN}/discovery")
    _assert_admin_read(r)
    assert set(r.get_json()) == {"observed", "undocumented"}
    r = client.post(f"{ADMIN}/discovery/scan", headers=WRITE, json={})
    assert r.status_code == 400
    r = client.post(f"{ADMIN}/discovery/scan", headers=WRITE, json={"nmap_xml": "not xml"})
    assert r.status_code == 422
    r = client.post(f"{ADMIN}/discovery/scan", headers=WRITE, json={"nmap_xml": "<not-nmap/>"})
    assert r.get_json() == {"ok": True, "seen": 0, "new": 0}      # parses, files nothing
    r = client.post(f"{ADMIN}/discovery/decide", headers=WRITE,
                    json={"keys": ["k"], "action": "ignore"})
    assert r.get_json() == {"ok": True, "action": "ignore", "count": 1}
    r = client.post(f"{ADMIN}/discovery/decide", headers=WRITE,
                    json={"keys": ["k"], "action": "explode"})
    assert r.status_code == 400 and "unknown action" in r.get_json()["error"]
    r = client.post(f"{ADMIN}/discovery/decide", headers=WRITE, json={"keys": []})
    assert r.status_code == 400
    # as-nodes computes, never writes — and so skips the write gate
    r = client.post(f"{ADMIN}/discovery/as-nodes", json={"keys": []})
    assert r.status_code == 200 and r.get_json() == {"nodes": []}


def test_import_csv(client):
    r = client.post(f"{ADMIN}/import/csv", json={"csv": "name,ip\nNEWPLACE,10.9.9.9\n"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["count"] == 1 and body["nodes"][0]["name"] == "NEWPLACE"
    r = client.post(f"{ADMIN}/import/csv", json={"csv": ""})
    assert r.status_code == 400


# ── repairs & annals ─────────────────────────────────────────────────────────

def test_maintenance_surface(client):
    r = client.get(f"{ADMIN}/maintenance")
    _assert_admin_read(r)
    assert set(r.get_json()) == {"windows", "legacy_nodes", "summary", "stamp"}
    r = client.post(f"{ADMIN}/maintenance", headers=WRITE, json={"windows": []})
    assert r.status_code == 200 and r.get_json()["ok"] and r.get_json()["stamp"]
    r = client.post(f"{ADMIN}/maintenance", headers=WRITE, json={"nope": 1})
    assert r.status_code == 400 and r.get_json() == {"error": "expected {windows: [...]}"}


def test_event_ack_unknown_event(client):
    r = client.post(f"{ADMIN}/events/12345/ack", headers=WRITE, json={"note": "seen"})
    assert r.status_code == 404 and r.get_json() == {"error": "no event 12345"}


# ── map art ──────────────────────────────────────────────────────────────────

def test_map_art_list(client):
    r = client.get(f"{ADMIN}/map-art")
    _assert_admin_read(r)
    assert set(r.get_json()) == {"images", "default", "max_bytes"}


def test_map_art_upload_and_delete(client):
    r = client.post(f"{ADMIN}/map-art", headers=WRITE,
                    data={"image": (io.BytesIO(PNG), "one.png"), "name": "one.png"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] and body["name"] == "one.png"
    assert any(i["name"] == "one.png" for i in body["images"])
    assert client.delete(f"{ADMIN}/map-art/one.png", headers=WRITE).status_code == 200
    # bundled art is not deletable
    import mapart
    r = client.delete(f"{ADMIN}/map-art/{mapart.DEFAULT}", headers=WRITE)
    assert r.status_code == 422


def test_map_art_survey_refusal(client, monkeypatch):
    import worldsurvey
    monkeypatch.setattr(worldsurvey, "survey",
                        lambda q: (_ for _ in ()).throw(worldsurvey.SurveyError("no such place")))
    r = client.post(f"{ADMIN}/map-art/survey", headers=WRITE, json={"query": "nowhere"})
    assert r.status_code == 422 and r.get_json() == {"error": "no such place"}


# ── directory settings ───────────────────────────────────────────────────────

def test_auth_settings_surface(client):
    r = client.get(f"{ADMIN}/auth")
    _assert_admin_read(r)
    assert {"settings", "sources", "allowed", "mode", "ldap_ready", "backends",
            "local_admin_exists"} == set(r.get_json())
    # test: refusal shapes (no outbound bind is attempted for these)
    r = client.post(f"{ADMIN}/auth/test", headers=WRITE, json={})
    assert r.status_code == 400 and r.get_json()["ok"] is False
    r = client.post(f"{ADMIN}/auth/test", headers=WRITE,
                    json={"settings": {"NOT_A_KEY": "x"}, "username": "u", "password": "p"})
    assert r.status_code == 400 and "not a directory setting" in r.get_json()["error"]
    # save: validation refusals
    r = client.post(f"{ADMIN}/auth", headers=WRITE, json={"settings": {"NOT_A_KEY": "x"}})
    assert r.status_code == 400
    r = client.post(f"{ADMIN}/auth", headers=WRITE,
                    json={"settings": {"ATLAS_AUTH_BACKENDS": "nothing-real"}})
    assert r.status_code == 422 and "At least one" in r.get_json()["error"]


# ── The admin fence itself ───────────────────────────────────────────────────

def test_non_admin_is_refused_everywhere(tmp_path):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    handle = fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(data),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
        ATLAS_SECRET_KEY="test-signing-key",
        ATLAS_INSECURE_COOKIES="1",
        ATLAS_AUTH_BACKENDS="local",
        ATLAS_MFA_REQUIRED="",
    )
    import accounts
    accounts.create_local_user("alice", PW)
    c = handle.app.test_client()
    r, _ = login_as(c, "alice", PW)
    assert r.status_code == 200
    for path in ("context", "dataset", "revisions", "discovery", "maintenance", "map-art", "auth"):
        r = c.get(f"{ADMIN}/{path}")
        assert r.status_code == 403, path
        assert r.get_json() == {"error": "admins only"}
        assert r.headers["Cache-Control"] == "no-store, private"
