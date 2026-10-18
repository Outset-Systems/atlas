"""THE REPAIRS — scheduled maintenance windows.

The feature exists because a flat list of node ids is true until somebody
remembers to delete it, and a forgotten entry suppresses a real outage
forever. So the tests that matter are the ones about windows closing
themselves, and about not breaking the ops tooling, which writes the same file.
"""

import json
import os
import shutil
import sys
from datetime import datetime, timezone

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

BUNDLED = os.path.join(WEB, "default-lab-data.json")
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)

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
def store(tmp_path, monkeypatch):
    import maintenance
    import settings
    monkeypatch.setattr(settings, "MAINTENANCE_PATH", str(tmp_path / "maintenance.json"))
    return maintenance


def write(store, payload):
    with open(store.settings.MAINTENANCE_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


# ── the shapes the ops tooling and older hands wrote ────────────────────────────

@pytest.mark.parametrize("payload", [
    ["downloads"],                                   # oldest hand-edit: a bare list
    {"nodes": ["downloads"]},                        # what maintenance_prep writes
    {"nodes": ["downloads"], "windows": []},         # what this module writes
])
def test_every_historical_file_shape_still_suppresses(store, payload):
    write(store, payload)
    assert store.under_repair(NOW) == {"downloads"}


def test_saving_windows_leaves_the_mcps_node_list_alone(store):
    """Two writers own different halves of one file; neither may clobber."""
    write(store, {"nodes": ["downloads"]})
    store.save([{"id": "w", "reason": "r", "nodes": ["app-host"],
                 "starts": "2026-07-27T11:00:00Z", "ends": "2026-07-27T14:00:00Z"}])
    reread = store.read()
    assert reread["nodes"] == ["downloads"], "the MCP's list was destroyed by an editor save"
    assert len(reread["windows"]) == 1
    assert store.under_repair(NOW) == {"downloads", "app-host"}


def test_a_garbage_file_suppresses_nothing(store):
    with open(store.settings.MAINTENANCE_PATH, "w", encoding="utf-8") as fh:
        fh.write("{ not json")
    assert store.under_repair(NOW) == set()


# ── windows close themselves ────────────────────────────────────────────────

def test_a_finished_window_stops_suppressing(store):
    """The entire point of the feature."""
    write(store, {"windows": [{"id": "past", "nodes": ["downloads"],
                               "starts": "2026-07-26T01:00:00Z",
                               "ends": "2026-07-26T03:00:00Z"}]})
    assert store.under_repair(NOW) == set()
    assert store.annotated(NOW)[0]["state"] == "ended"


def test_a_future_window_does_not_suppress_yet(store):
    write(store, {"windows": [{"id": "soon", "nodes": ["downloads"],
                               "starts": "2026-07-27T20:00:00Z",
                               "ends": "2026-07-27T22:00:00Z"}]})
    assert store.under_repair(NOW) == set()
    assert store.annotated(NOW)[0]["state"] == "upcoming"


@pytest.mark.parametrize("repeat,starts,ends,expected", [
    # a daily 02:00-04:00 window is closed at noon
    ("daily", "2026-07-01T02:00:00Z", "2026-07-01T04:00:00Z", "upcoming"),
    # a daily 11:00-14:00 window is open at noon
    ("daily", "2026-07-01T11:00:00Z", "2026-07-01T14:00:00Z", "active"),
    # weekly on the same weekday as NOW (a Monday)
    ("weekly", "2026-07-20T11:00:00Z", "2026-07-20T14:00:00Z", "active"),
    # weekly on a different weekday
    ("weekly", "2026-07-19T11:00:00Z", "2026-07-19T14:00:00Z", "upcoming"),
    ("monthly", "2026-01-27T11:00:00Z", "2026-01-27T14:00:00Z", "active"),
])
def test_recurrence(store, repeat, starts, ends, expected):
    window = {"id": "r", "nodes": ["downloads"], "starts": starts, "ends": ends, "repeat": repeat}
    assert store.occurrence(window, NOW)[0] == expected


def test_monthly_on_the_31st_does_not_drift_to_the_28th(store):
    """Clamping Jan 31 to Feb 28 must not move every later occurrence.

    Stepping month by month from the previous (clamped) date is the classic
    way to turn a last-day-of-month window into a 28th-of-month window
    forever.
    """
    window = {"id": "eom", "nodes": ["downloads"], "repeat": "monthly",
              "starts": "2026-01-31T11:00:00Z", "ends": "2026-01-31T14:00:00Z"}
    _state, start, _end = store.occurrence(window, NOW)
    assert start.day == 31 and start.month == 7, f"drifted to {start}"


def test_an_incoherent_window_suppresses_nothing(store):
    write(store, {"windows": [{"id": "bad", "nodes": ["downloads"],
                               "starts": "2026-07-27T14:00:00Z",
                               "ends": "2026-07-27T11:00:00Z"}]})
    assert store.occurrence(store.read()["windows"][0], NOW)[0] == "invalid"
    assert store.under_repair(NOW) == set(), "a window nobody can read must not silence alarms"


def test_an_open_ended_window_stays_open(store):
    """Hand-edits keep the old "until removed" meaning; the editor requires
    an end, which is what stops new ones being forgotten."""
    write(store, {"windows": [{"id": "open", "nodes": ["downloads"],
                               "starts": "2026-07-01T00:00:00Z"}]})
    assert store.under_repair(NOW) == {"downloads"}


# ── through the API ─────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    app = fresh_app(ATLAS_DATA=str(data), ATLAS_READONLY="0",
                    ATLAS_MAINTENANCE=str(tmp_path / "maintenance.json"),
                    ATLAS_EVENTS=str(tmp_path / "events.json"),
                    ATLAS_REVISIONS=str(tmp_path / "rev"))
    return app.app.test_client()


WRITE = {"X-Atlas-Write": "1"}
OPEN_NOW = {"id": "now", "reason": "patching", "nodes": ["downloads"],
            "starts": "2020-01-01T00:00:00Z", "ends": "2099-01-01T00:00:00Z",
            "repeat": "none"}


def test_an_open_window_forces_the_marker_to_maintenance(client):
    assert client.post("/api/v2/admin/maintenance", headers=WRITE,
                       json={"windows": [OPEN_NOW]}).status_code == 200
    feed = client.get("/api/v2/signals").get_json()
    assert feed["maintenance"] == ["downloads"]
    assert feed["nodes"]["downloads"]["state"] == "maintenance"
    assert feed["repairs"]["active"] == 1


def test_a_window_that_ends_before_it_starts_is_refused(client):
    bad = {**OPEN_NOW, "starts": "2099-01-01T00:00:00Z", "ends": "2020-01-01T00:00:00Z"}
    r = client.post("/api/v2/admin/maintenance", headers=WRITE, json={"windows": [bad]})
    assert r.status_code == 422
    assert any("ends before it starts" in p for p in r.get_json()["problems"])


def test_a_window_missing_required_fields_is_refused(client):
    r = client.post("/api/v2/admin/maintenance", headers=WRITE,
                    json={"windows": [{"id": "x"}]})
    assert r.status_code == 422
    assert any("missing" in p for p in r.get_json()["problems"])


def test_windows_cannot_be_written_through_the_dataset(client):
    """They live in their own store on purpose — a 2am schedule change is not
    a commit to the map."""
    r = client.post("/api/v2/admin/ops", headers=WRITE, json={
        "ops": [{"op": "insert", "section": "maintenance", "body": OPEN_NOW}]})
    assert r.status_code == 422
    assert any("not part of the dataset" in p for p in r.get_json()["problems"])


def test_writes_are_guarded_like_every_other(client):
    assert client.post("/api/v2/admin/maintenance", json={"windows": []}).status_code == 403
    assert client.post("/api/v2/admin/maintenance",
                       headers={**WRITE, "Sec-Fetch-Site": "cross-site"},
                       json={"windows": []}).status_code == 403


def test_a_stale_stamp_is_a_conflict(client):
    stamp = client.get("/api/v2/admin/maintenance").get_json()["stamp"]
    client.post("/api/v2/admin/maintenance", headers=WRITE, json={"windows": [OPEN_NOW]})
    r = client.post("/api/v2/admin/maintenance", headers=WRITE,
                    json={"windows": [], "expect": stamp})
    assert r.status_code == 409
