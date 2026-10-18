"""The `deception` signal source — the decoy feed's stones, brought onto the map.

The signals layer has one law: *the map never dies with its
sources.* So the tests that matter here are the failure ones. A timeout, a 500,
garbage JSON, an unreachable host and a refused key must every one of them
resolve to an empty dict and a live map.
"""

import json
import os
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

import signals  # noqa: E402


GOOD = {
    "stones": {
        "nas-restore-share": {
            "name": "Restoration-Keys", "kind": "windows-folder",
            "host": "nas", "zone": "internal", "severity": "critical",
            "state": "speaking", "last_spoke": "2026-08-14T04:30:21+00:00",
            "trips": 1, "last_reason": "internal_stone", "planted": True,
        },
        "edge-junk-path": {
            "name": "backup-archive", "kind": "web-bug", "host": "edge",
            "zone": "wan", "severity": "low", "state": "silent",
            "last_spoke": None, "trips": 0, "last_reason": None,
            "planted": True,
        },
    },
    "unattributed_trips": 2,
    "undelivered_alerts": 1,
}


class _Resp:
    def __init__(self, payload, status=200, boom=None):
        self._payload = payload
        self.status_code = status
        self._boom = boom

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._boom:
            raise self._boom
        return self._payload


def _adapter(monkeypatch, resp=None, exc=None, key="a-read-key"):
    def fake_get(url, headers=None, timeout=None):
        if exc:
            raise exc
        return resp
    monkeypatch.setitem(sys.modules, "requests",
                        type("m", (), {"get": staticmethod(fake_get)}))
    return signals.DeceptionAdapter("http://decoys:5013", key)


# ── The good path ────────────────────────────────────────────────────────────

def test_a_good_response_merges_stone_state(monkeypatch):
    feed = _adapter(monkeypatch, _Resp(GOOD)).fetch()
    assert feed["stones"]["nas-restore-share"]["state"] == "speaking"
    assert feed["stones"]["nas-restore-share"]["last_spoke"] == \
        "2026-08-14T04:30:21+00:00"
    assert feed["stones"]["edge-junk-path"]["state"] == "silent"


def test_realm_wide_counts_ride_as_metrics(monkeypatch):
    """An unattributed trip lights no marker, which is exactly why its count
    has to be visible somewhere."""
    feed = _adapter(monkeypatch, _Resp(GOOD)).fetch()
    assert feed["metrics"]["unattributed_trips"] == 2
    assert feed["metrics"]["undelivered_alerts"] == 1


def test_the_key_is_actually_sent(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        return _Resp(GOOD)

    monkeypatch.setitem(sys.modules, "requests",
                        type("m", (), {"get": staticmethod(fake_get)}))
    signals.DeceptionAdapter("http://decoys:5013/", "sekrit").fetch()
    assert seen["url"] == "http://decoys:5013/api/stones"
    assert seen["headers"]["X-Api-Key"] == "sekrit"


def test_a_timeout_is_actually_passed(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["timeout"] = timeout
        return _Resp(GOOD)

    monkeypatch.setitem(sys.modules, "requests",
                        type("m", (), {"get": staticmethod(fake_get)}))
    signals.DeceptionAdapter("http://decoys:5013", "k").fetch()
    assert seen["timeout"] == signals._TIMEOUT


# ── The law: never raise, never stall ────────────────────────────────────────

@pytest.mark.parametrize("exc", [
    TimeoutError("timed out"),
    ConnectionError("unreachable host"),
    OSError("network is down"),
    ValueError("something odd"),
])
def test_every_transport_failure_resolves_to_an_empty_feed(monkeypatch, exc):
    assert _adapter(monkeypatch, exc=exc).fetch() == {}


@pytest.mark.parametrize("status", [400, 401, 403, 500, 502, 503])
def test_every_error_status_resolves_to_an_empty_feed(monkeypatch, status):
    assert _adapter(monkeypatch, _Resp(None, status=status)).fetch() == {}


def test_malformed_json_resolves_to_an_empty_feed(monkeypatch):
    boom = _Resp(None, boom=json.JSONDecodeError("bad", "doc", 0))
    assert _adapter(monkeypatch, boom).fetch() == {}


@pytest.mark.parametrize("payload", [None, [], "a string", 42, True])
def test_a_non_object_payload_resolves_to_an_empty_feed(monkeypatch, payload):
    assert _adapter(monkeypatch, _Resp(payload)).fetch() == {}


def test_a_missing_key_is_reported_and_does_not_call_out(monkeypatch, caplog):
    """No key means the map can never show a stone speaking — a symptom that
    looks exactly like a quiet realm, so it is said out loud."""
    import logging
    called = []

    def fake_get(*a, **kw):
        called.append(1)
        return _Resp(GOOD)

    monkeypatch.setitem(sys.modules, "requests",
                        type("m", (), {"get": staticmethod(fake_get)}))
    with caplog.at_level(logging.WARNING, logger="atlas.live.signals"):
        out = signals.DeceptionAdapter("http://decoys:5013", None).fetch()
    assert out == {}
    assert called == []                       # no pointless request
    assert any("no ATLAS_DECOYS_KEY" in r.getMessage() for r in caplog.records)


# ── Out-of-vocabulary state is discarded, not forwarded ──────────────────────

@pytest.mark.parametrize("bad", ["healthy", "down", "SPEAKING", "", None, 1,
                                 "on fire", "silent "])
def test_an_unknown_voice_is_dropped(monkeypatch, bad):
    """The front-end swaps a CSS class on this value. A junk state would render
    an unstyled marker — neither visibly quiet nor visibly shouting."""
    payload = {"stones": {"s": dict(GOOD["stones"]["nas-restore-share"],
                                    state=bad)}}
    entry = _adapter(monkeypatch, _Resp(payload)).fetch()["stones"]["s"]
    assert "state" not in entry
    assert entry["name"] == "Restoration-Keys"     # the rest of it survives


@pytest.mark.parametrize("good", ["silent", "stirred", "speaking"])
def test_every_declared_voice_survives(monkeypatch, good):
    payload = {"stones": {"s": {"state": good}}}
    assert _adapter(monkeypatch, _Resp(payload)).fetch()["stones"]["s"]["state"] == good


def test_stone_states_are_not_node_states():
    """A silent stone is not 'healthy' — it is unvisited, which is the ordinary
    case and the one we hope for. Keeping the vocabularies apart stops the map
    from saying something false."""
    assert signals._VALID_STONE_STATES.isdisjoint(signals._VALID_STATES)


def test_a_non_dict_stone_entry_is_skipped(monkeypatch):
    payload = {"stones": {"ok": {"state": "silent"}, "junk": "not a dict"}}
    stones = _adapter(monkeypatch, _Resp(payload)).fetch()["stones"]
    assert "junk" not in stones and "ok" in stones


# ── It plays with the rest of the layer ──────────────────────────────────────

def test_the_merged_feed_always_has_a_stones_key():
    """The scene reads `feed.stones`. Absent, it would have to guard every
    access; empty, it simply draws nothing."""
    hub = signals.SignalsHub([])
    assert hub.feed()["stones"] == {}


def test_a_silent_deception_source_is_visible_in_sources(monkeypatch):
    """The distinction the scene depends on: "no stone is speaking" and "I
    cannot reach the engine" look identical in `stones`, and are told apart
    here."""
    adapter = _adapter(monkeypatch, exc=TimeoutError("nope"))
    feed = signals.SignalsHub([adapter]).feed()
    assert feed["sources"]["deception"] == "silent"
    assert feed["stones"] == {}


def test_a_live_deception_source_reports_ok(monkeypatch):
    adapter = _adapter(monkeypatch, _Resp(GOOD))
    feed = signals.SignalsHub([adapter]).feed()
    assert feed["sources"]["deception"] == "ok"
    assert feed["stones"]["nas-restore-share"]["state"] == "speaking"


def test_one_dead_source_does_not_take_the_others_down(monkeypatch):
    """The whole point of the layer. A dead decoy feed must not cost us Kuma."""
    dead = _adapter(monkeypatch, exc=TimeoutError("nope"))
    alive = signals.StaticFileAdapter("/nonexistent")   # yields {} harmlessly
    feed = signals.SignalsHub([dead, alive]).feed()
    assert set(feed) >= {"nodes", "services", "stones", "metrics", "sources"}


# ── Wiring from env ──────────────────────────────────────────────────────────

def test_the_source_is_selectable_by_env(monkeypatch):
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", "deception")
    monkeypatch.setenv("ATLAS_DECOYS_URL", "http://decoys:5013")
    monkeypatch.setenv("ATLAS_DECOYS_KEY", "k")
    assert signals.build_hub_from_env().enabled == ["deception"]


def test_it_is_skipped_without_a_url(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", "deception")
    monkeypatch.delenv("ATLAS_DECOYS_URL", raising=False)
    with caplog.at_level(logging.WARNING, logger="atlas.live.signals"):
        hub = signals.build_hub_from_env()
    assert hub.enabled == []
    assert any("ATLAS_DECOYS_URL" in r.getMessage() for r in caplog.records)


def test_the_key_can_come_from_a_docker_secret(monkeypatch, tmp_path):
    f = tmp_path / "read_key"
    f.write_text("from-the-mount\n", encoding="utf-8")
    monkeypatch.delenv("ATLAS_DECOYS_KEY", raising=False)
    monkeypatch.setenv("ATLAS_DECOYS_KEY_FILE", str(f))
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", "deception")
    monkeypatch.setenv("ATLAS_DECOYS_URL", "http://decoys:5013")
    hub = signals.build_hub_from_env()
    assert hub.adapters[0].read_key == "from-the-mount"
