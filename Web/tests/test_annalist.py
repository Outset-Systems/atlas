"""THE ANNALIST — the annals must advance with nobody watching.

The 09-17 power outage and the 09-24 patch window recorded nothing because
only a browser ever built a fresh feed. What matters: a poll with no request
records a transition, it is the SAME recording path as the route (so the
dedupe/cache rules hold), a failure never escapes, and the interval knob is
safe against garbage.
"""

import json
import os
import shutil
import sys
import threading

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


@pytest.fixture
def arena(tmp_path):
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

    def set_state(nodes):
        signals.write_text(json.dumps({"nodes": {k: {"state": v} for k, v in nodes.items()},
                                       "services": {}}), encoding="utf-8")
        app.app.extensions["atlas"].signals._cache = None   # a fresh source poll

    return {"app": app.app, "set": set_state, "client": app.app.test_client()}


def _events(client):
    return client.get("/api/v2/events").get_json()["events"]


def test_a_poll_with_nobody_watching_records_the_transition(arena):
    import annalist
    arena["set"]({"app-host": "healthy"})
    assert annalist.poll_once(arena["app"]) is True          # seeds, no request anywhere
    arena["set"]({"app-host": "down"})
    assert annalist.poll_once(arena["app"]) is True
    events = _events(arena["client"])
    assert len(events) == 1 and (events[0]["from"], events[0]["to"]) == ("healthy", "down")


def test_the_annalist_and_a_browser_do_not_double_record(arena):
    """Same path as the route: a browser poll after the annalist saw the same
    transition is a no-op, exactly like the second gunicorn worker."""
    import annalist
    arena["set"]({"app-host": "healthy"})
    annalist.poll_once(arena["app"])
    arena["set"]({"app-host": "down"})
    annalist.poll_once(arena["app"])
    arena["app"].extensions["atlas"].signals._cache = None
    arena["client"].get("/api/v2/signals")
    assert len(_events(arena["client"])) == 1


def test_a_failing_poll_never_escapes(arena, monkeypatch):
    import annalist
    import api.v2.feeds as feeds
    monkeypatch.setattr(feeds, "build_feed", lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
    assert annalist.poll_once(arena["app"]) is False


@pytest.mark.parametrize("raw,want", [("60", 60), ("0", 0), ("120", 120), ("5", 60),
                                      ("-3", 60), ("nope", 60), ("", 60)])
def test_interval_knob_is_safe(monkeypatch, raw, want):
    import annalist
    monkeypatch.setenv("ATLAS_ANNALS_POLL", raw)
    assert annalist.interval() == want


def test_start_is_once_per_process_and_off_means_off(monkeypatch, arena):
    import annalist
    monkeypatch.setattr(annalist, "_started", False)
    monkeypatch.setenv("ATLAS_ANNALS_POLL", "0")
    assert annalist.start(arena["app"]) is None
    monkeypatch.setenv("ATLAS_ANNALS_POLL", "15")
    stop = threading.Event()
    t = annalist.start(arena["app"], stop=stop)
    assert t is not None and t.daemon
    assert annalist.start(arena["app"], stop=stop) is None      # second call: already running
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive()
