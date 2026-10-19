"""TRIPWIRES on the db backend — site tokens carrying the `tripwires` scope.

The same refusal ladder as the relay ingest: unknown 401, revoked 401, wrong
scope 403, a token from another site 403. The derived webhook key keeps
working beside them, and with no secret at all the webhook is still live,
because a site token can be valid.
"""

import json
import os

import pytest

from appfixture import fresh_app

import events  # noqa: E402
import tripwires  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "standalone"}
HOOK = "/api/v2/ingest/tripwires"
SECRET = "test-tripwires-secret-0123456789abcdef"
DATA = {"meta": {"title": "Db Realm"}, "zones": [],
        "nodes": [{"id": "nas", "name": "NAS", "kind": "physical", "x": 10, "y": 10}],
        "stones": [{"id": "cloud-key", "name": "backup.env", "kind": "cloud-key",
                    "zone": "internal", "severity": "critical"}]}


@pytest.fixture
def db(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "atlas.db").replace("\\", "/")
    env = {
        "ATLAS_AUTH_MODE": "standalone", "ATLAS_ALLOW_INSECURE": "1",
        "ATLAS_DATA_BACKEND": "db", "ATLAS_DB_URL": url, "ATLAS_SITE": "home",
        "ATLAS_DATA": str(tmp_path / "no-such-lab-data.json"),
        "ATLAS_EVENTS": str(tmp_path / "events.json"),
        "ATLAS_TRIPWIRES_STATE": str(tmp_path / "tripwires.json"),
        "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
        "ATLAS_SIGNALS_SOURCES": "", "ATLAS_TRIPWIRES_WEBHOOK": "1",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ATLAS_TRIPWIRES_SECRET", raising=False)
    monkeypatch.delenv("ATLAS_TRIPWIRES_SECRET_FILE", raising=False)
    monkeypatch.delenv("ATLAS_INGEST_ENABLED", raising=False)

    import store
    store.reset_engine_for_tests()
    from store import init_db, load_labdata, session_scope
    from store.tokens import issue_token, revoke_token
    init_db()
    tokens = {}
    with session_scope() as s:
        load_labdata(s, json.loads(json.dumps(DATA)), site_slug="home", site_name="Home")
        load_labdata(s, json.loads(json.dumps(DATA)), site_slug="other", site_name="Other")
        tokens["good"], _ = issue_token(s, "home", label="canary", scopes="tripwires")
        tokens["both"], _ = issue_token(s, "home", label="relay+canary", scopes="ingest,tripwires")
        tokens["relay"], _ = issue_token(s, "home", label="relay only", scopes="ingest")
        tokens["other"], _ = issue_token(s, "other", label="elsewhere", scopes="tripwires")
        tokens["revoked"], row = issue_token(s, "home", label="old", scopes="tripwires")
        s.flush()
        revoke_token(s, row.id)
    handle = fresh_app()
    tripwires.limiter.reset()
    handle.client = handle.app.test_client()
    handle.tokens = tokens
    return handle


def _post(handle, token, body=None, query=False):
    body = body or {"tripwire_id": "cloud-key"}
    if query:
        return handle.client.post(f"{HOOK}?key={token}", json=body)
    return handle.client.post(HOOK, json=body, headers={"Authorization": f"Bearer {token}"})


def test_live_without_a_secret_because_tokens_can_be_valid(db):
    assert tripwires.enabled() is True
    assert _post(db, db.tokens["good"]).status_code == 200


def test_a_tripwires_token_trips(db):
    r = _post(db, db.tokens["good"])
    assert r.status_code == 200 and r.get_json()["tripwire"] == "cloud-key"
    assert _post(db, db.tokens["both"], query=True).status_code == 200
    trips = [e for e in events.listing() if e.get("kind") == "tripwire"]
    assert len(trips) == 1 and trips[0]["trip"]["count"] == 2   # coalesced


def test_an_unknown_token_is_401(db):
    r = _post(db, "atlas_not-a-real-token")
    assert r.status_code == 401 and r.get_json() == {"error": "unknown credential"}


def test_a_revoked_token_is_401(db):
    r = _post(db, db.tokens["revoked"])
    assert r.status_code == 401 and r.get_json() == {"error": "token revoked"}


def test_a_token_without_the_scope_is_403(db):
    r = _post(db, db.tokens["relay"])
    assert r.status_code == 403 and "tripwires" in r.get_json()["error"]


def test_a_token_for_another_site_is_403(db):
    r = _post(db, db.tokens["other"])
    assert r.status_code == 403 and "this site" in r.get_json()["error"]
    assert [e for e in events.listing() if e.get("kind") == "tripwire"] == []


def test_the_derived_key_works_beside_tokens(db, monkeypatch):
    monkeypatch.setenv("ATLAS_TRIPWIRES_SECRET", SECRET)
    assert _post(db, tripwires.webhook_key(SECRET), query=True).status_code == 200
    body = db.client.get("/api/v2/tripwires/setup").get_json()
    assert "--scopes tripwires" in body["token_command"] and "--site home" in body["token_command"]
    assert db.client.get("/api/v2/tripwires").get_json()["sources"]["webhook"]["auth"] == {
        "signature": True, "key": True, "token": True}


def test_the_relay_ingest_stays_fenced_on_its_own_switch(db):
    """The webhook is on; the relay ingest beside it is not, and must 404."""
    r = db.client.post("/api/v2/ingest/signals", json={},
                       headers={"Authorization": f"Bearer {db.tokens['both']}"})
    assert r.status_code == 404
    assert os.environ.get("ATLAS_INGEST_ENABLED") is None
