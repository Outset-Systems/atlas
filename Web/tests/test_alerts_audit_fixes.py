"""ALERTS' prerequisites from the 11-12 audit (2026-11-13).

ALERTS rides the annalist, so three of its faults are fixed first:

* a consequence that outlives its cause raises no event (events.py);
* a failed annalist start is swallowed with no line (gunicorn.conf.py), and
  nothing says whether the poll runs (`/api/v2/health` now does);
* one id-less or non-object place 500s `/api/v2/signals` and stops the poll.
"""

import importlib.util
import json
import logging
import os
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import viewers  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file"}


# ── a consequence that outlives its cause ────────────────────────────────────
@pytest.fixture
def annals(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_EVENTS", str(tmp_path / "events.json"))
    import settings
    importlib.reload(settings)
    import events
    return events


def _feed(**nodes):
    return {"nodes": {k: (v if isinstance(v, dict) else {"state": v}) for k, v in nodes.items()}}


def test_a_vm_that_stays_down_after_its_host_recovers_is_an_event(annals):
    annals.record(_feed(host="healthy", vm="healthy"))                 # seeds
    annals.record(_feed(host="down", vm={"state": "down", "cause": "host"}))
    fresh = annals.record(_feed(host="healthy", vm="down"))
    by_target = {e["target"]: e for e in fresh}
    assert set(by_target) == {"host", "vm"}
    vm = by_target["vm"]
    assert (vm["from"], vm["to"], vm["gravity"]) == ("down", "down", "grave")
    assert vm["outlived"] is True and "cause" not in vm
    # it joins the queue a human acknowledges, which a consequence never did
    assert annals.counts()["unacked"] >= 1
    # and it is said once, not on every poll after
    assert annals.record(_feed(host="healthy", vm="down")) == []


def test_a_fault_that_becomes_a_consequence_is_not_a_second_event(annals):
    annals.record(_feed(host="healthy", vm="healthy"))
    annals.record(_feed(host="healthy", vm="down"))                     # vm's own fault
    fresh = annals.record(_feed(host="down", vm={"state": "down", "cause": "host"}))
    assert [e["target"] for e in fresh] == ["host"]


def test_a_store_written_before_the_fix_reads_unchanged(annals, tmp_path):
    import settings
    with open(settings.EVENTS_PATH, "w", encoding="utf-8") as fh:
        json.dump({"seq": 3, "state": {"node:vm": "down"}, "events": []}, fh)
    # a place down as a consequence when the store had no `behind`: no event
    assert annals.record(_feed(vm={"state": "down", "cause": "host"})) == []
    assert annals.load()["behind"] == {"node:vm": "host"}


def test_where_a_send_went_is_not_a_viewers(annals):
    row = {"id": 1, "kind": "node", "target": "a", "ack": None, "sent": [{"to": "pager"}]}
    assert "sent" not in annals.for_viewer(row)
    assert "sent" not in annals.for_viewer({**row, "ack": {"by": "x", "at": "t", "note": "n"}})


# ── the annalist: a failed start is logged, and health says whether it runs ──
def _gunicorn_conf():
    spec = importlib.util.spec_from_file_location("atlas_gunicorn_conf",
                                                  os.path.join(WEB, "gunicorn.conf.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_failed_annalist_start_is_logged_not_swallowed(monkeypatch, caplog):
    import annalist

    def boom(app):
        raise RuntimeError("no thread for you")
    monkeypatch.setattr(annalist, "start", boom)

    class Worker:
        pid = 4242
        wsgi = object()

        class log:
            lines = []

            @classmethod
            def error(cls, msg, *a):
                cls.lines.append(msg % a if a else msg)

    with caplog.at_level(logging.ERROR, logger="atlas.live.annalist"):
        _gunicorn_conf().post_worker_init(Worker)       # never raises
    assert any("could not start" in r.getMessage() and r.exc_info for r in caplog.records)
    assert Worker.log.lines


ID_LESS = {"name": "no id", "parent": "alpha", "monitors": ["m1"], "ip": "192.0.2.77"}
#: Entries that are not objects at all. A viewer who is not an admin cannot be
#: served at all while one is in the file: `redaction.py` and the app's frame
#: header trip on it before any route runs (the 11-12 audit's Data item 8, not
#: this stage's). The admin's feed and the annalist are this stage's.
NON_OBJECTS = ["not a place", 7, None]


def _realm(tmp_path, monkeypatch, extra):
    bad = viewers.dataset()
    bad["nodes"] += [*extra, viewers.place("gamma", "Gamma", parent="alpha", depends_on=["beta"])]
    viewers.build(tmp_path, monkeypatch, bad)
    signals = tmp_path / "signals.json"
    signals.write_text(json.dumps({"nodes": {"alpha": {"state": "down"},
                                             "gamma": {"state": "down"}}}), encoding="utf-8")
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", "static")
    monkeypatch.setenv("ATLAS_SIGNALS_FILE", str(signals))
    from appfixture import fresh_app
    return fresh_app()


@pytest.fixture
def realm(tmp_path, monkeypatch):
    return _realm(tmp_path, monkeypatch, [ID_LESS, *NON_OBJECTS])


@pytest.fixture
def id_less_realm(tmp_path, monkeypatch):
    return _realm(tmp_path, monkeypatch, [ID_LESS])


def test_health_says_whether_the_poll_runs_and_nothing_more(realm, monkeypatch):
    import annalist
    monkeypatch.setattr(annalist, "_last_tick", None)     # another suite may have polled
    body = realm.app.test_client().get("/api/v2/health").get_json()
    assert body["annalist"] == {"running": False, "last_tick": None}


def test_health_carries_the_last_tick_after_a_poll(realm):
    import annalist
    assert annalist.poll_once(realm.app) is True
    body = realm.app.test_client().get("/api/v2/health").get_json()
    assert body["annalist"]["last_tick"]


# ── one bad place never 500s the feed or stops the poll ─────────────────────
def test_an_id_less_or_non_object_place_never_500s_signals(realm):
    admin = viewers.signed_in(realm, "ops")
    r = admin.get("/api/v2/signals")
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert r.get_json()["nodes"]["gamma"].get("cause") == "alpha"


def test_an_id_less_place_never_500s_signals_for_a_viewer(id_less_realm):
    viewer = viewers.signed_in(id_less_realm, "alice")
    r = viewer.get("/api/v2/signals")
    assert r.status_code == 200 and r.get_json()["nodes"]["gamma"].get("cause") == "alpha"


def test_an_id_less_or_non_object_place_never_stops_the_annalist(realm):
    import annalist
    import events
    assert annalist.poll_once(realm.app) is True
    assert any(k.startswith("node:alpha") for k in events.load()["state"])
