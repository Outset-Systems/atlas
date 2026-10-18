"""THE ANNALS — the map's memory.

What matters: a transition is recorded once and only once (two workers poll
independently), the first sighting of anything is not an event, a planned
outage is not an alarm, and a viewer never sees history for a place the map
hides from them.
"""

import json
import os
import shutil
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

BUNDLED = os.path.join(WEB, "default-lab-data.json")
WRITE = {"X-Atlas-Write": "1"}

# Declared in full so conftest can reset it per test. Under-declaring lets an
# earlier module's db/ingest configuration leak in, and the app then serves an
# unseeded fallback with none of this map's places in it.
ATLAS_TEST_ENV = {
    "ATLAS_AUTH_MODE": "standalone",
    "ATLAS_ALLOW_INSECURE": "1",
    "ATLAS_DATA_BACKEND": "file",
    "ATLAS_INGEST_ENABLED": "0",
    "ATLAS_READONLY": "0",
}
os.environ.update(ATLAS_TEST_ENV)


@pytest.fixture
def arena(tmp_path):
    """An app with a static signals file we can rewrite between polls."""
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    signals = tmp_path / "signals.json"
    signals.write_text("{}", encoding="utf-8")
    app = fresh_app(ATLAS_DATA=str(data), ATLAS_READONLY="0",
                    ATLAS_MAINTENANCE=str(tmp_path / "maintenance.json"),
                    ATLAS_EVENTS=str(tmp_path / "events.json"),
                    ATLAS_REVISIONS=str(tmp_path / "rev"),
                    ATLAS_SIGNALS_SOURCES="static", ATLAS_SIGNALS_FILE=str(signals))

    def poll(nodes, services=None):
        signals.write_text(json.dumps({
            "nodes": {k: {"state": v} for k, v in nodes.items()},
            "services": {k: {"state": v} for k, v in (services or {}).items()},
        }), encoding="utf-8")
        app.app.extensions["atlas"].signals._cache = None   # force a fresh build
        return app.app.test_client().get("/api/v2/signals").get_json()

    client = app.app.test_client()
    return {"client": client, "poll": poll, "app": app}


def events_of(client, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/v2/events{'?' + query if query else ''}").get_json()


# ── what counts as an event ─────────────────────────────────────────────────

def test_the_first_sighting_seeds_but_does_not_narrate(arena):
    """Booting must not write forty 'unknown -> healthy' rows."""
    arena["poll"]({"app-host": "healthy", "downloads": "healthy"})
    assert events_of(arena["client"])["events"] == []


def test_a_transition_is_recorded_once(arena):
    arena["poll"]({"app-host": "healthy"})
    arena["poll"]({"app-host": "down"})
    events = events_of(arena["client"])["events"]
    assert len(events) == 1
    assert (events[0]["from"], events[0]["to"]) == ("healthy", "down")
    assert events[0]["name"] == "APP HOST", "the annals should name the place, not its id"
    assert events[0]["gravity"] == "grave"


def test_an_unchanged_state_writes_nothing(arena):
    arena["poll"]({"app-host": "healthy"})
    arena["poll"]({"app-host": "down"})
    for _ in range(4):
        arena["poll"]({"app-host": "down"})
    assert len(events_of(arena["client"])["events"]) == 1


def test_a_cached_feed_does_not_rerecord(arena):
    arena["poll"]({"app-host": "healthy"})
    arena["poll"]({"app-host": "down"})
    before = len(events_of(arena["client"])["events"])
    for _ in range(5):
        arena["client"].get("/api/v2/signals")     # all served from the 30s cache
    assert len(events_of(arena["client"])["events"]) == before


def test_a_target_vanishing_is_not_a_transition(arena):
    """A monitor being deleted is not the host going down."""
    arena["poll"]({"app-host": "healthy", "downloads": "healthy"})
    arena["poll"]({"app-host": "healthy"})       # downloads gone from the feed
    assert events_of(arena["client"])["events"] == []


def test_services_are_remembered_too(arena):
    arena["poll"]({}, {"Hub": "healthy"})
    arena["poll"]({}, {"Hub": "down"})
    events = events_of(arena["client"])["events"]
    assert len(events) == 1 and events[0]["kind"] == "service"


# ── maintenance interaction ─────────────────────────────────────────────────

def test_an_outage_inside_a_window_is_planned_not_an_alarm(arena):
    arena["poll"]({"downloads": "healthy"})
    arena["client"].post("/api/v2/admin/maintenance", headers=WRITE, json={"windows": [{
        "id": "w", "reason": "patching", "nodes": ["downloads"],
        "starts": "2020-01-01T00:00:00Z", "ends": "2099-01-01T00:00:00Z"}]})
    arena["poll"]({"downloads": "down"})

    body = events_of(arena["client"])
    assert body["events"][0]["to"] == "maintenance"
    assert body["events"][0]["gravity"] == "planned"
    assert body["counts"]["unacked"] == 0, \
        "a planned outage must not sit in the queue demanding acknowledgement"


# ── acknowledgement ─────────────────────────────────────────────────────────

def test_acknowledging_records_who_and_why(arena):
    arena["poll"]({"app-host": "healthy"})
    arena["poll"]({"app-host": "down"})
    event_id = events_of(arena["client"])["events"][0]["id"]

    assert events_of(arena["client"])["counts"]["unacked"] == 1
    r = arena["client"].post(f"/api/v2/admin/events/{event_id}/ack", headers=WRITE,
                             json={"note": "PSU replaced"})
    assert r.status_code == 200
    ack = r.get_json()["event"]["ack"]
    assert ack["note"] == "PSU replaced" and ack["by"] and ack["at"]
    assert events_of(arena["client"])["counts"]["unacked"] == 0


def test_acknowledging_is_idempotent_and_guarded(arena):
    arena["poll"]({"app-host": "healthy"})
    arena["poll"]({"app-host": "down"})
    event_id = events_of(arena["client"])["events"][0]["id"]

    arena["client"].post(f"/api/v2/admin/events/{event_id}/ack", headers=WRITE, json={"note": "one"})
    again = arena["client"].post(f"/api/v2/admin/events/{event_id}/ack", headers=WRITE,
                                 json={"note": "two"})
    assert again.get_json()["event"]["ack"]["note"] == "one", "a second ack must not overwrite"

    assert arena["client"].post(f"/api/v2/admin/events/{event_id}/ack",
                                json={}).status_code == 403, "no write header"
    assert arena["client"].post("/api/v2/admin/events/9999/ack", headers=WRITE,
                                json={}).status_code == 404


def test_unacked_filter(arena):
    arena["poll"]({"app-host": "healthy", "downloads": "healthy"})
    arena["poll"]({"app-host": "down", "downloads": "down"})
    first = events_of(arena["client"])["events"][0]["id"]
    arena["client"].post(f"/api/v2/admin/events/{first}/ack", headers=WRITE, json={})
    assert len(events_of(arena["client"], unacked=1)["events"]) == 1


# ── redaction ───────────────────────────────────────────────────────────────

def test_history_inherits_the_maps_clearance(tmp_path):
    """A node hidden behind require_group must not reappear as a row here."""
    import events as events_mod
    from appfixture import fresh_app

    data = tmp_path / "lab-data.json"
    with open(BUNDLED, encoding="utf-8") as fh:
        dataset = json.load(fh)
    dataset["nodes"][0]["require_group"] = "SECRET-Ops"
    hidden_id = dataset["nodes"][0]["id"]
    open_id = dataset["nodes"][1]["id"]
    data.write_text(json.dumps(dataset), encoding="utf-8")

    signals = tmp_path / "signals.json"
    app = fresh_app(ATLAS_DATA=str(data), ATLAS_EVENTS=str(tmp_path / "events.json"),
                    ATLAS_MAINTENANCE=str(tmp_path / "m.json"),
                    ATLAS_REVISIONS=str(tmp_path / "rev"),
                    ATLAS_SIGNALS_SOURCES="static", ATLAS_SIGNALS_FILE=str(signals),
                    ATLAS_AUTH_MODE="standalone")

    def poll(states):
        signals.write_text(json.dumps({"nodes": {k: {"state": v} for k, v in states.items()}}),
                           encoding="utf-8")
        app.app.extensions["atlas"].signals._cache = None
        app.app.test_client().get("/api/v2/signals")

    poll({hidden_id: "healthy", open_id: "healthy"})
    poll({hidden_id: "down", open_id: "down"})
    assert len(events_mod.listing(limit=50)) == 2, "both transitions were recorded"

    # a viewer cleared for neither group sees only the open node's history
    visible = {open_id}
    shown = events_mod.listing(limit=50, visible=visible)
    assert [e["target"] for e in shown] == [open_id]


def test_the_log_is_capped(tmp_path, monkeypatch):
    import events as events_mod
    import settings
    monkeypatch.setattr(settings, "EVENTS_PATH", str(tmp_path / "events.json"))
    monkeypatch.setattr(events_mod, "KEEP", 5)
    for i in range(20):
        state = "down" if i % 2 else "healthy"
        events_mod.record({"nodes": {"n": {"state": state}}})
    assert len(events_mod.listing(limit=100)) == 5
