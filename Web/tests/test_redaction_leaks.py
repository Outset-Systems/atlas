"""Redaction beyond the node list — the ways a hidden place leaked anyway.

`redact_for_groups` dropped hidden entries from `nodes[]` and stopped there,
and `/api/signals` applied no redaction at all. Both left a viewer with partial
clearance able to name every place they were not cleared for, and in the
signals case to watch it go up and down. These are the regressions for that.

The rule each test is defending: a redacted response must not contain the ID of
a hidden place ANYWHERE — not as a route endpoint, not as somebody else's
`reaches`, not as a rack occupant, not as a key in a live feed.
"""

import json
import sys

import pytest

from appfixture import fresh_app

#: Non-empty on purpose — conftest only snapshots and restores the Atlas
#: environment for a module that declares one, and this suite sets an auth mode
#: that must not follow the run into the next file.
ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts"}

PW = "correct-horse-battery"


def _dataset(tmp_path):
    """Two places, one of them behind a group — and every kind of reference to
    it the dataset can hold."""
    data = {
        "meta": {"title": "Test Realm"},
        "zones": [],
        "nodes": [
            {"id": "public-place", "name": "Public", "kind": "physical",
             "x": 10, "y": 10,
             "reaches": ["secret-place"],
             "depends_on": ["secret-place"],
             "links": [
                 {"label": "Open", "url": "http://example.test/",
                  "kuma": "public-monitor",
                  "connects": ["secret-place"],
                  "path": ["public-place", "secret-place"]},
             ]},
            {"id": "secret-place", "name": "Secret", "kind": "physical",
             "x": 20, "y": 20, "require_group": "HUB-decoy",
             "links": [{"label": "Hidden", "url": "http://secret.test/",
                        "kuma": "secret-monitor"}]},
        ],
        "routes": [
            {"from": "public-place", "to": "secret-place", "kind": "vlan"},
        ],
        "rack": [
            {"u": "U1", "name": "Public box", "node": "public-place"},
            {"u": "U2", "name": "Secret box", "node": "secret-place"},
        ],
        "vms": [
            {"id": "secret-place", "host": "public-place", "name": "Secret VM"},
        ],
        "signals": {"kuma": {"secret-monitor": "secret-place",
                             "public-monitor": "public-place"}},
    }
    path = tmp_path / "lab-data.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def realm(tmp_path):
    """An accounts-mode Atlas with an admin and a user cleared for nothing."""
    handle = fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
        ATLAS_SECRET_KEY="test-signing-key",
        ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
        ATLAS_AUTH_BACKENDS="local",
        ATLAS_MFA_REQUIRED="",
    )
    import accounts
    accounts.create_local_user("alice", PW, is_admin=False)
    accounts.create_local_user("ops", PW, is_admin=True)
    return handle


def _login(handle, username):
    c = handle.app.test_client()
    r = c.post("/api/v2/auth/login", json={"username": username, "password": PW},
               headers={"X-Atlas-Write": "1"})
    assert r.get_json()["ok"] is True, f"{username} could not sign in"
    return c


def test_the_dataset_never_names_a_hidden_place(realm):
    """The whole body, not just `nodes[]`. Serialising the response and looking
    for the id is the point: it does not matter which key it came back under."""
    body = _login(realm, "alice").get("/api/v2/lab-data").get_json()

    assert [n["id"] for n in body["nodes"]] == ["public-place"]
    assert "secret-place" not in json.dumps(body), (
        "a hidden place's id survived somewhere in the payload")


def test_the_dataset_scrubs_each_kind_of_reference(realm):
    """The same rule, said field by field, so a failure names what broke."""
    body = _login(realm, "alice").get("/api/v2/lab-data").get_json()
    public = body["nodes"][0]

    assert body["routes"] == []                      # required ref ⇒ whole road
    assert public.get("reaches") == []               # optional list ⇒ filtered
    assert public.get("depends_on") == []
    assert public["links"][0].get("connects") == []
    # An ordered chain cannot be filtered: dropping the hidden hop out of
    # ["public-place", "secret-place"] would assert an adjacency that is not
    # there. It goes entirely.
    assert "path" not in public["links"][0]
    assert [r["name"] for r in body.get("rack", [])] == ["Public box"]
    assert body.get("vms", []) == []                 # its `id` was the hidden one
    # `signals` is unmodelled by the schema and was scrubbed by hand: the map
    # from monitor NAME to node id leaks both halves.
    assert body["signals"]["kuma"] == {"public-monitor": "public-place"}


def test_an_admin_still_sees_the_whole_map(realm):
    body = _login(realm, "ops").get("/api/v2/lab-data").get_json()
    assert {n["id"] for n in body["nodes"]} == {"public-place", "secret-place"}
    assert len(body["routes"]) == 1
    assert body["nodes"][0]["links"][0]["path"] == ["public-place", "secret-place"]


def test_the_signals_feed_is_redacted_too(realm):
    """The feed is keyed by node id and by monitor name, and it updates live —
    it was the richest of the leaks and the one with no test at all."""
    handle = realm
    handle._signals.feed = lambda: {
        "nodes": {"public-place": {"state": "up"},
                  "secret-place": {"state": "down"}},
        "services": {"public-monitor": {"state": "up"},
                     "secret-monitor": {"state": "down"}},
        "sources": {"kuma": "ok"}, "generated": 0, "cached": True,
    }

    body = _login(handle, "alice").get("/api/v2/signals").get_json()

    assert set(body["nodes"]) == {"public-place"}
    assert set(body["services"]) == {"public-monitor"}
    assert "secret-place" not in json.dumps(body)
    assert "secret-monitor" not in json.dumps(body)


def test_the_signals_feed_hides_a_hidden_cause(realm):
    """A visible place may be dark BECAUSE of a hidden one. The outage is the
    viewer's to see; the explanation names a place that is not."""
    handle = realm
    handle._signals.feed = lambda: {
        "nodes": {"public-place": {"state": "down", "cause": "secret-place",
                                   "via": "secret-place"}},
        "services": {}, "sources": {}, "generated": 0, "cached": True,
    }

    body = _login(handle, "alice").get("/api/v2/signals").get_json()

    assert body["nodes"]["public-place"]["state"] == "down"
    assert "cause" not in body["nodes"]["public-place"]
    assert "secret-place" not in json.dumps(body)


def test_the_drift_list_is_admin_only(realm):
    """THE DRIFT is monitors the map has not charted. Every entry belongs to no
    visible place by definition, so no partial clearance can cover it."""
    handle = realm
    handle._signals.feed = lambda: {
        "nodes": {}, "services": {"unknown-monitor": {"state": "up"}},
        "sources": {}, "generated": 0, "cached": True,
    }

    assert "drift" not in _login(handle, "alice").get("/api/v2/signals").get_json()
    assert _login(handle, "ops").get("/api/v2/signals").get_json()["drift"][
        "uncharted"] == ["unknown-monitor"]


def test_per_viewer_responses_say_they_vary(realm):
    """Behind a shared cache, a redacted body with no `Vary` is one viewer's
    map served to the next. `no-cache` alone does not prevent STORING it."""
    c = _login(realm, "alice")
    for path in ("/api/v2/lab-data", "/api/v2/signals", "/api/v2/events", "/api/v2/rites"):
        resp = c.get(path)
        assert "Cookie" in resp.headers.get("Vary", ""), f"{path} has no Vary"
    assert "private" in c.get("/api/v2/lab-data").headers["Cache-Control"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
