"""Live feeds — `/api/v2/signals`, `/api/v2/rites`, `/api/v2/events`.

The side-effectful, clock-stamped GETs: their shape, the `no-store` posture
and the viewer `Vary`, the gate in front of them, and redaction — a plain
viewer never sees a `require_group` place in the feed, THE DRIFT is admin-only.
"""

import json
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


def _env(tmp_path, secret=False):
    data = tmp_path / "lab-data.json"
    if secret:
        doc = {"meta": {"title": "Test Realm"}, "zones": [], "routes": [],
               "nodes": [{"id": "public-place", "name": "Public", "kind": "physical",
                          "x": 10, "y": 10},
                         {"id": "secret-place", "name": "Secret", "kind": "physical",
                          "x": 20, "y": 20, "require_group": "HUB-decoy"}]}
        data.write_text(json.dumps(doc), encoding="utf-8")
    else:
        shutil.copy(BUNDLED, data)
    return {"ATLAS_DATA": str(data),
            "ATLAS_EVENTS": str(tmp_path / "events.json"),
            "ATLAS_BEATS": str(tmp_path / "heartbeats.json"),
            "ATLAS_BEATS_DIR": str(tmp_path / "beats"),
            "ATLAS_SIGNALS_SOURCES": "static",
            "ATLAS_SIGNALS_FILE": str(tmp_path / "signals.json")}


def _signals_file(tmp_path, nodes):
    (tmp_path / "signals.json").write_text(json.dumps({"nodes": nodes}), encoding="utf-8")


@pytest.fixture
def client(tmp_path):
    return fresh_app(**_env(tmp_path)).app.test_client()


@pytest.fixture
def realm(tmp_path):
    _signals_file(tmp_path, {"public-place": {"state": "healthy"},
                             "secret-place": {"state": "down"}})
    handle = fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
        ATLAS_SECRET_KEY="test-signing-key",
        ATLAS_INSECURE_COOKIES="1",
        ATLAS_AUTH_BACKENDS="local",
        ATLAS_MFA_REQUIRED="",
        **_env(tmp_path, secret=True),
    )
    import accounts
    accounts.create_local_user("ops", PW, is_admin=True)
    accounts.create_local_user("alice", PW)
    return handle


def _assert_live_read(r):
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    vary = r.headers.get("Vary", "")
    for header in ("Cookie", "X-Hub-Auth", "X-Remote-User", "X-Remote-Groups"):
        assert header in vary, vary


def test_signals_shape(client):
    r = client.get("/api/v2/signals")
    _assert_live_read(r)
    body = r.get_json()
    for key in ("nodes", "services", "sources", "repairs", "maintenance", "rites"):
        assert key in body, key
    assert set(body["repairs"]) == {"active", "upcoming", "next", "next_reason"}


def test_rites_shape(client):
    r = client.get("/api/v2/rites")
    _assert_live_read(r)
    rites = r.get_json()["rites"]
    assert rites, "the bundled dataset charts rites"
    assert {"key", "name", "cadence", "verdict"} <= set(rites[0])


def test_events_shape_and_limit(client):
    r = client.get("/api/v2/events")
    _assert_live_read(r)
    body = r.get_json()
    assert set(body) == {"events", "counts"}
    assert set(body["counts"]) == {"total", "unacked", "last_24h"}
    r = client.get("/api/v2/events", query_string={"limit": "5", "unacked": "1"})
    assert r.status_code == 200 and len(r.get_json()["events"]) <= 5


def test_feeds_are_gated_when_signed_out(realm):
    c = realm.app.test_client()
    for path in ("/api/v2/signals", "/api/v2/rites", "/api/v2/events"):
        assert c.get(path).status_code == 401, path


def test_feeds_are_redacted_for_a_plain_viewer(realm):
    c = realm.app.test_client()
    r, _ = login_as(c, "alice", PW)
    assert r.status_code == 200 and r.get_json()["ok"]
    feed = c.get("/api/v2/signals").get_json()
    assert "public-place" in feed["nodes"]
    assert "secret-place" not in feed["nodes"], "a require_group place leaked into the feed"
    assert "drift" not in feed
    _assert_live_read(c.get("/api/v2/rites"))
    _assert_live_read(c.get("/api/v2/events"))


def test_admin_sees_everything(realm):
    c = realm.app.test_client()
    login_as(c, "ops", PW)
    feed = c.get("/api/v2/signals").get_json()
    assert {"public-place", "secret-place"} <= set(feed["nodes"])


def test_hub_mode_feeds(tmp_path):
    """The framework gate in front of the feeds: a hub-signed admin sees the
    hidden place, a group-less viewer does not (redaction rides the plaintext
    groups in legacy hub mode)."""
    import hub_auth.auth as auth
    _signals_file(tmp_path, {"public-place": {"state": "healthy"},
                             "secret-place": {"state": "down"}})
    handle = fresh_app(ATLAS_AUTH_MODE="hub", **_env(tmp_path, secret=True))
    original = auth.AUTH_MODE
    auth.AUTH_MODE = "hub"
    try:
        c = handle.app.test_client()
        admin = {"X-Remote-User": "ops", "X-Remote-Groups": "atlas-admins"}
        plain = {"X-Remote-User": "alice", "X-Remote-Groups": "HL-Nobody"}
        r = c.get("/api/v2/signals", headers=admin)
        _assert_live_read(r)
        assert "secret-place" in r.get_json()["nodes"]
        r = c.get("/api/v2/signals", headers=plain)
        _assert_live_read(r)
        assert "secret-place" not in r.get_json()["nodes"]
        _assert_live_read(c.get("/api/v2/events", headers=plain))
    finally:
        auth.AUTH_MODE = original


def test_signals_fresh_build_records_the_annals(tmp_path):
    """A cold cache drives the fresh-feed arm: the first poll seeds the state,
    a change on the next poll becomes an event."""
    _signals_file(tmp_path, {"app-host": {"state": "healthy"}})
    handle = fresh_app(**_env(tmp_path))
    c = handle.app.test_client()
    r = c.get("/api/v2/signals")
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    _signals_file(tmp_path, {"app-host": {"state": "down"}})
    handle._signals._cache = None                      # bypass the 30s hub cache
    c.get("/api/v2/signals")
    events = c.get("/api/v2/events").get_json()["events"]
    assert any(e["target"] == "app-host" and e["to"] == "down" for e in events)
