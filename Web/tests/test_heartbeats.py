"""THE RITES, told the truth — last-run heartbeats.

What matters: a rite that has never reported is not an alarm, a rite that
stopped reporting is, the two ingest paths agree, a beat cannot be forged
without the token, and a missed turning reaches THE ANNALS exactly once so it
can be acknowledged like any other fault.
"""

import json
import os
import shutil
import sys
import time

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {
    "ATLAS_AUTH_MODE": "standalone",
    "ATLAS_ALLOW_INSECURE": "1",
    "ATLAS_DATA_BACKEND": "file",
    "ATLAS_INGEST_ENABLED": "0",
    "ATLAS_READONLY": "0",
}
os.environ.update(ATLAS_TEST_ENV)

TOKEN = "a-shared-secret-for-tests"


@pytest.fixture
def beats(tmp_path):
    """`heartbeats` pointed at a scratch store, reloaded per test."""
    import importlib
    os.environ["ATLAS_BEATS"] = str(tmp_path / "heartbeats.json")
    os.environ["ATLAS_BEATS_DIR"] = str(tmp_path / "beats")
    import settings
    importlib.reload(settings)
    import heartbeats as hb
    importlib.reload(hb)
    hb.forget_all()
    return hb


@pytest.fixture
def arena(tmp_path):
    """An app whose dataset has rites we control."""
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    with open(BUNDLED, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["rites"] = [
        {"name": "Nightly Backup", "cadence": "daily", "when": "02:00",
         "host": "app-host", "note": "the one that died in April",
         "expect_every": "24h", "grace": "1h"},
        {"name": "Patch Survey", "cadence": "weekly", "when": "Sun 04:15",
         "host": "all guests", "note": ""},
        {"name": "Unclocked Thing", "cadence": "on demand", "when": "whenever",
         "host": "gpu-box", "note": ""},
    ]
    data.write_text(json.dumps(payload), encoding="utf-8")
    signals = tmp_path / "signals.json"
    signals.write_text("{}", encoding="utf-8")
    return fresh_app(
        ATLAS_DATA=str(data), ATLAS_READONLY="0",
        ATLAS_BEATS=str(tmp_path / "heartbeats.json"),
        ATLAS_BEATS_DIR=str(tmp_path / "beats"),
        ATLAS_BEAT_TOKEN=TOKEN,
        ATLAS_EVENTS=str(tmp_path / "events.json"),
        ATLAS_MAINTENANCE=str(tmp_path / "maintenance.json"),
        ATLAS_REVISIONS=str(tmp_path / "rev"),
        ATLAS_SIGNALS_SOURCES="static", ATLAS_SIGNALS_FILE=str(signals))


# ── Reading a schedule ───────────────────────────────────────────────────────
@pytest.mark.parametrize("text,seconds", [
    ("24h", 86400), ("7d", 604800), ("15m", 900), ("90s", 90), ("2w", 1209600),
    ("  6h  ", 21600), ("6H", 21600), ("30", 1800),          # bare = minutes
])
def test_parse_duration(beats, text, seconds):
    assert beats.parse_duration(text) == seconds


def test_parse_duration_refuses_nonsense_rather_than_guessing(beats):
    assert beats.parse_duration("every other tuesday", default=None) is None
    assert beats.parse_duration("", default=7) == 7


def test_cadence_supplies_the_interval_when_the_rite_does_not(beats):
    interval, grace = beats.expectations({"cadence": "weekly"})
    assert interval == 604800
    assert grace == 604800 * 0.25

    # an explicit interval always wins over the cadence it contradicts
    interval, _ = beats.expectations({"cadence": "weekly", "expect_every": "6h"})
    assert interval == 21600


def test_a_cadence_with_no_known_period_is_left_unwatched(beats):
    assert beats.expectations({"cadence": "on demand"}) == (None, None)


def test_parked_is_a_legal_cadence_that_is_never_watched(beats):
    """`parked` must stay a valid choice AND stay unwatched — both halves.

    It is the one cadence in the schema's list that heartbeats deliberately
    cannot time: a parked rite is listed and uncoloured rather than crying
    MISSED nightly for a host nobody is running. Giving it a period here would
    silently un-park every parked rite on the map, so the two files are pinned
    against each other rather than trusted to stay in agreement.
    """
    from schema import RITE_CADENCES

    assert "parked" in RITE_CADENCES, "the editor must still offer it"
    assert "parked" not in beats.CADENCE_SECONDS, "it must have no period"
    assert beats.expectations({"cadence": "parked"}) == (None, None)
    assert beats.status_for([{"name": "Parked Rite", "cadence": "parked"}])[0][
        "verdict"
    ] == "unwatched"


def test_grace_never_falls_below_the_floor(beats):
    _, grace = beats.expectations({"expect_every": "5m"})
    assert grace == beats.GRACE_FLOOR


# ── The verdict ──────────────────────────────────────────────────────────────
def _rite(**over):
    return {"name": "Nightly Backup", "cadence": "daily", **over}


def test_a_rite_that_never_reported_is_awaited_not_missed(beats):
    """The distinction the whole feature turns on.

    Shipping this against twenty unwired rites must not invent twenty
    outages — 'nobody has taught this one to report yet' is a different
    statement from 'this one stopped'.
    """
    row = beats.status_for([_rite()])[0]
    assert row["verdict"] == "awaited"
    assert beats.VERDICT_STATE["awaited"] is None      # so it reaches no event


def test_a_fresh_beat_is_kept(beats):
    beats.record_beat("nightly-backup")
    assert beats.status_for([_rite()])[0]["verdict"] == "kept"


def test_overdue_within_grace_is_late_and_beyond_it_is_missed(beats):
    beats.record_beat("nightly-backup")
    now = time.time()
    rite = _rite(expect_every="24h", grace="1h")

    assert beats.status_for([rite], now=now + 3600)[0]["verdict"] == "kept"
    assert beats.status_for([rite], now=now + 86400 + 60)[0]["verdict"] == "late"
    assert beats.status_for([rite], now=now + 86400 + 7200)[0]["verdict"] == "missed"


def test_a_rite_reporting_its_own_failure_is_failed_not_kept(beats):
    """Ran and broke is a different problem from did not run."""
    beats.record_beat("nightly-backup", status="fail", note="disk full")
    row = beats.status_for([_rite()])[0]
    assert row["verdict"] == "failed"
    assert row["last"]["note"] == "disk full"


def test_the_suite_backup_regression(beats):
    """The actual 2026 incident: a daily backup, dead since April, listed in
    gold the entire time. It must read as missed, not as scheduled."""
    april = time.time() - 90 * 86400
    beats.record_beat("suite-db-backup")
    store = json.loads(open(os.environ["ATLAS_BEATS"], encoding="utf-8").read())
    store["beats"]["suite-db-backup"]["epoch"] = april
    open(os.environ["ATLAS_BEATS"], "w", encoding="utf-8").write(json.dumps(store))

    row = beats.status_for([{"name": "Suite DB Backup", "cadence": "daily"}])[0]
    assert row["verdict"] == "missed"
    assert row["age_s"] > 89 * 86400


# ── Keys ─────────────────────────────────────────────────────────────────────
def test_the_key_defaults_to_the_slug_and_an_explicit_key_survives_renaming(beats):
    assert beats.key_for({"name": "The Patch Survey"}) == "the-patch-survey"
    assert beats.key_for({"name": "Renamed Entirely", "key": "patch-survey"}) == "patch-survey"
    assert beats.key_for({"name": "Sun 03:00 — SSH/cert renewal!"}) == "sun-03-00-ssh-cert-renewal"


def test_a_beat_key_cannot_be_a_path_or_unbounded(beats):
    entry = beats.record_beat("../../etc/passwd")
    assert entry is not None
    stored = json.loads(open(os.environ["ATLAS_BEATS"], encoding="utf-8").read())
    assert list(stored["beats"]) == ["etc-passwd"]
    assert len(beats.key_for({"name": "x" * 500})) <= 64


def test_an_empty_key_is_refused(beats):
    with pytest.raises(ValueError):
        beats.record_beat("!!!")


# ── The file drop ────────────────────────────────────────────────────────────
def test_touching_a_file_reports_a_turning_and_the_file_is_consumed(beats):
    directory = os.environ["ATLAS_BEATS_DIR"]
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "nightly-backup")
    open(path, "w", encoding="utf-8").close()

    assert beats.sweep_dropped_files() == ["nightly-backup"]
    assert not os.path.exists(path)                    # consumed, not re-read forever
    assert beats.status_for([_rite()])[0]["verdict"] == "kept"


def test_a_dropped_file_can_report_failure_and_a_note(beats):
    directory = os.environ["ATLAS_BEATS_DIR"]
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "nightly-backup"), "w", encoding="utf-8") as handle:
        handle.write("fail: rsync exited 24\n")

    beats.sweep_dropped_files()
    row = beats.status_for([_rite()])[0]
    assert row["verdict"] == "failed"
    assert "rsync exited 24" in row["last"]["note"]


def test_sweeping_a_missing_directory_is_not_an_error(beats):
    """A rite must never be able to take the map down by not existing."""
    assert beats.sweep_dropped_files() == []


# ── The HTTP path ────────────────────────────────────────────────────────────
def test_a_beat_needs_the_token(arena):
    client = arena.app.test_client()
    assert client.post("/api/v2/rites/nightly-backup/beat").status_code == 403
    assert client.post("/api/v2/rites/nightly-backup/beat",
                       headers={"Authorization": "Bearer wrong"}).status_code == 403

    ok = client.post("/api/v2/rites/nightly-backup/beat",
                     headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200
    assert ok.get_json()["ok"] is True


def test_the_beat_route_is_off_when_no_token_is_configured(tmp_path):
    """Absent configuration must close the route, never open it."""
    from appfixture import fresh_app
    os.environ.pop("ATLAS_BEAT_TOKEN", None)
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    app = fresh_app(ATLAS_DATA=str(data), ATLAS_READONLY="0",
                    ATLAS_BEATS=str(tmp_path / "hb.json"),
                    ATLAS_BEATS_DIR=str(tmp_path / "beats"),
                    ATLAS_MAINTENANCE=str(tmp_path / "m.json"),
                    ATLAS_EVENTS=str(tmp_path / "e.json"),
                    ATLAS_REVISIONS=str(tmp_path / "rev"))
    resp = app.app.test_client().post("/api/v2/rites/x/beat",
                                      headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 503


def test_a_read_only_atlas_refuses_beats(tmp_path):
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    app = fresh_app(ATLAS_DATA=str(data), ATLAS_READONLY="1",
                    ATLAS_BEAT_TOKEN=TOKEN,
                    ATLAS_BEATS=str(tmp_path / "hb.json"),
                    ATLAS_BEATS_DIR=str(tmp_path / "beats"),
                    ATLAS_MAINTENANCE=str(tmp_path / "m.json"),
                    ATLAS_EVENTS=str(tmp_path / "e.json"),
                    ATLAS_REVISIONS=str(tmp_path / "rev"))
    resp = app.app.test_client().post("/api/v2/rites/x/beat",
                                      headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 403
    os.environ["ATLAS_READONLY"] = "0"


def test_the_rites_endpoint_carries_intent_and_truth_together(arena):
    client = arena.app.test_client()
    client.post("/api/v2/rites/nightly-backup/beat",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"note": "23 files", "duration_s": 4.25})

    rites = client.get("/api/v2/rites").get_json()["rites"]
    backup = next(r for r in rites if r["name"] == "Nightly Backup")
    assert backup["when"] == "02:00"                    # intent survives
    assert backup["verdict"] == "kept"                  # truth joins it
    assert backup["last"]["duration_s"] == 4.25
    assert backup["last"]["note"] == "23 files"

    # the rite with a cadence the map cannot time stays listed and uncoloured
    unclocked = next(r for r in rites if r["name"] == "Unclocked Thing")
    assert unclocked["verdict"] == "unwatched"


def test_last_run_truth_is_never_cached(arena):
    resp = arena.app.test_client().get("/api/v2/rites")
    assert resp.headers["Cache-Control"] == "no-store"


# ── THE ANNALS ───────────────────────────────────────────────────────────────
def test_a_missed_rite_becomes_one_acknowledgeable_event(arena, monkeypatch):
    """The point of routing rites through the annals: a dead backup is a fault
    a human can mark as seen, with a reason, like every other fault."""
    import events
    import heartbeats as hb
    client = arena.app.test_client()

    client.post("/api/v2/rites/nightly-backup/beat",
                headers={"Authorization": f"Bearer {TOKEN}"})
    client.get("/api/v2/signals")                          # seed: kept, no event

    # a day and a half later, nothing has reported
    later = time.time() + 86400 + 7200
    monkeypatch.setattr(hb, "_now", lambda: later)
    arena._signals._cache = None                        # force a fresh feed
    client.get("/api/v2/signals")

    rows = [e for e in events.listing(limit=50) if e["kind"] == "rite"]
    assert len(rows) == 1
    assert rows[0]["to"] == "down"
    assert rows[0]["name"] == "Nightly Backup"          # named, not slugged

    events.acknowledge(rows[0]["id"], "ops", "the download host is off this week")
    assert events.listing(limit=50)[0]["ack"]["by"] == "ops"


def test_a_rite_that_never_reported_writes_no_event(arena):
    """Twenty unwired rites on the day this ships must produce zero alarms."""
    import events
    client = arena.app.test_client()
    client.get("/api/v2/signals")
    arena._signals._cache = None
    client.get("/api/v2/signals")
    assert [e for e in events.listing(limit=50) if e["kind"] == "rite"] == []
