"""The shared plumbing (2026-11-16): one HTTP call for the sources, one
lock-then-write for the checks' round and the shadow counts, one reader for a
whole-number knob from the environment.

What is held here:

* THE CALL: `engines.runtime.get` passes on only what its caller gave, with
  the shared timeout, raises on an error status, and imports `requests` only
  when asked. Kuma and Prometheus ask through it with their own arguments,
  exactly as before (the decoy feed's are held in test_signals_deception.py).
* THE WRITE: `filelock.writing_now` does not wait for another writer, writes
  atomically with no `.bak`, and hands a folder that cannot be written to its
  caller, which falls back its own way.
* THE KNOB: `settings.env_int` gives the default when unset, garbage or below
  the floor, keeps 0 only where 0 means off, and has no upper bound.

Every address is invented (RFC 5737). Nothing here reaches a network.
"""

import json
import logging
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engines.runtime as runtime  # noqa: E402
import filelock  # noqa: E402
import settings  # noqa: E402
import signals  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Resp:
    def __init__(self, status=200, text="", payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _fake_requests(monkeypatch, resp=None, exc=None):
    """A `requests` module whose `get` records exactly what it was given."""
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if exc:
            raise exc
        return resp

    monkeypatch.setitem(sys.modules, "requests", type("m", (), {"get": staticmethod(get)}))
    return calls


# ── the call ────────────────────────────────────────────────────────────────

def test_the_call_passes_on_only_what_it_was_given_with_the_shared_timeout(monkeypatch):
    calls = _fake_requests(monkeypatch, _Resp())
    resp = runtime.get("http://192.0.2.5/x", headers={"X-Api-Key": "k"})
    assert resp.status_code == 200
    assert calls == [("http://192.0.2.5/x", {"headers": {"X-Api-Key": "k"}, "timeout": signals._TIMEOUT})]


def test_a_timeout_the_caller_names_is_the_one_sent(monkeypatch):
    calls = _fake_requests(monkeypatch, _Resp())
    runtime.get("http://192.0.2.5/x", timeout=1.5, verify=False)
    assert calls[0][1] == {"timeout": 1.5, "verify": False}


def test_an_error_status_raises(monkeypatch):
    _fake_requests(monkeypatch, _Resp(status=503))
    with pytest.raises(RuntimeError, match="503"):
        runtime.get("http://192.0.2.5/x")


def test_a_transport_failure_is_not_caught_here(monkeypatch):
    _fake_requests(monkeypatch, exc=ConnectionError("refused"))
    with pytest.raises(ConnectionError):
        runtime.get("http://192.0.2.5/x")


def test_the_call_loads_with_no_web_stack_beside_it():
    """A relay box imports `signals`, and so this module: `requests` and
    `settings` are not loaded until a source asks."""
    code = ("import sys; import engines.runtime; "
            "print(sorted(m for m in ('requests', 'settings', 'integrations') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=WEB, capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


KUMA_METRICS = 'monitor_status{monitor_name="Wiki"} 1\nmonitor_status{monitor_name="Gate"} 0\n'


def test_kuma_asks_with_its_key_its_verify_and_the_timeout(monkeypatch):
    calls = _fake_requests(monkeypatch, _Resp(text=KUMA_METRICS))
    feed = signals.KumaAdapter("http://192.0.2.7:3001/", "a-key", {"Gate": "gate"}, verify=False).fetch()
    assert calls == [("http://192.0.2.7:3001/metrics",
                      {"auth": ("", "a-key"), "timeout": signals._TIMEOUT, "verify": False})]
    assert feed == {"nodes": {"gate": {"state": "down"}}, "services": {"Wiki": {"state": "healthy"}}}


def test_kuma_with_no_key_sends_no_auth_and_an_error_status_is_no_signal(monkeypatch):
    calls = _fake_requests(monkeypatch, _Resp(status=401))
    assert signals.KumaAdapter("http://192.0.2.7:3001", None).fetch() == {}
    assert calls == [("http://192.0.2.7:3001/metrics",
                      {"auth": None, "timeout": signals._TIMEOUT, "verify": True})]


def test_prometheus_asks_each_listed_query_and_nothing_more(monkeypatch):
    answer = {"data": {"result": [{"value": [0, "3"], "metric": {"instance": "192.0.2.9:9100"}}]}}
    calls = _fake_requests(monkeypatch, _Resp(payload=answer))
    adapter = signals.PrometheusAdapter("http://192.0.2.8:9090/")
    adapter.use_map({"nodes": [{"id": "box", "ip": "192.0.2.9"}]})
    feed = adapter.fetch()
    queries = list(signals.PrometheusAdapter._PROM_QUERIES.values()) + \
        list(signals.PrometheusAdapter._PATCH_QUERIES.values())
    assert calls == [("http://192.0.2.8:9090/api/v1/query",
                      {"params": {"query": q}, "timeout": signals._TIMEOUT}) for q in queries]
    assert feed["metrics"] == {"watchfires_up": 3.0, "watchfires_total": 3.0}
    assert feed["nodes"]["box"]["patches_pending"] == 3.0


def test_prometheus_that_errors_is_no_signal(monkeypatch):
    _fake_requests(monkeypatch, _Resp(status=500))
    assert signals.PrometheusAdapter("http://192.0.2.8:9090").fetch() == {}


# ── the write ───────────────────────────────────────────────────────────────

def test_the_write_is_atomic_json_with_no_backup(tmp_path):
    where = str(tmp_path / "store.json")
    with open(where, "w", encoding="utf-8") as fh:
        fh.write("{}")
    with filelock.writing_now(where) as save:
        save({"a": 1})
    with open(where, encoding="utf-8") as fh:
        text = fh.read()
    assert json.loads(text) == {"a": 1} and text.endswith("\n")
    assert sorted(os.listdir(tmp_path)) == ["store.json", "store.json.lock"]


def test_a_second_writer_is_not_waited_for(tmp_path):
    where = str(tmp_path / "store.json")
    with filelock.exclusive(filelock.lock_for(where)):
        with pytest.raises(filelock.LockTimeout):
            with filelock.writing_now(where):
                pytest.fail("the body ran without the lock")
    assert not os.path.exists(where)


def test_a_folder_that_cannot_be_written_goes_to_the_caller(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(filelock, "exclusive", refuse)
    with pytest.raises(OSError, match="read-only"):
        with filelock.writing_now(str(tmp_path / "store.json")):
            pytest.fail("the body ran without the lock")


def test_a_write_that_fails_under_the_lock_goes_to_the_caller(tmp_path, monkeypatch):
    import jsonio

    def refuse(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(jsonio, "write_json_atomic", refuse)
    where = str(tmp_path / "store.json")
    with pytest.raises(OSError, match="disk full"):
        with filelock.writing_now(where) as save:
            save({"a": 1})
    with filelock.writing_now(where) as save:      # the lock was let go
        pass


def test_the_watch_keeps_its_round_when_the_store_cannot_be_written(tmp_path, monkeypatch, caplog):
    import jsonio
    import watch

    def refuse(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(jsonio, "write_json_atomic", refuse)
    monkeypatch.setattr(watch, "probe", lambda t: ("healthy", 1, {}))
    data = {"nodes": [{"id": "box", "links": [{"label": "Web", "url": "http://192.0.2.10/"}]}]}
    with caplog.at_level(logging.WARNING, logger="atlas.live.watch"):
        store = watch.tick(data, str(tmp_path / "checks.json"), now=1000)
    assert store["checks"]["s:box/Web"]["state"] == "healthy"
    assert any("the round could not be stored" in r.getMessage() for r in caplog.records)


def _shadow_map():
    return {"meta": {"shadow_kuma": True},
            "nodes": [{"id": "app", "name": "APP", "ip": "192.0.2.10",
                       "links": [{"label": "Wiki", "url": "http://192.0.2.10/", "kuma": "Wiki monitor"}]}]}


def _shadow_heard(tmp_path):
    body = {"v": 2, "at": 1000, "checks": {"k:Wiki monitor": {
        "state": "healthy", "said": "healthy", "heard": 1000, "asked": 1000}}}
    (tmp_path / "checks.json").write_text(json.dumps(body), encoding="utf-8")


SHADOW_FEED = {"services": {"Wiki monitor": {"state": "healthy"}}}


def test_shadow_does_not_count_while_another_worker_holds_the_lock(tmp_path):
    import shadow
    _shadow_heard(tmp_path)
    where = str(tmp_path / "shadow.json")
    with filelock.exclusive(filelock.lock_for(where)):
        assert shadow.observe(SHADOW_FEED, _shadow_map(), path=where,
                              watch_path=str(tmp_path / "checks.json"), now=2000) is None
    assert not os.path.exists(where)
    assert shadow.observe(SHADOW_FEED, _shadow_map(), path=where,
                          watch_path=str(tmp_path / "checks.json"), now=2000) == 1


def test_shadow_that_cannot_write_says_so_and_does_not_raise(tmp_path, monkeypatch, caplog):
    import jsonio
    import shadow

    def refuse(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(jsonio, "write_json_atomic", refuse)
    _shadow_heard(tmp_path)
    with caplog.at_level(logging.WARNING, logger="atlas.live.shadow"):
        out = shadow.observe(SHADOW_FEED, _shadow_map(), path=str(tmp_path / "shadow.json"),
                             watch_path=str(tmp_path / "checks.json"), now=2000)
    assert out is None
    assert any("shadow: could not compare (OSError: disk full)" in r.getMessage() for r in caplog.records)


# ── the knob ────────────────────────────────────────────────────────────────

KNOB = "ATLAS_TEST_E3_KNOB"


@pytest.mark.parametrize("raw,zero_off,want", [
    (None, False, 60),          # unset
    ("", False, 60),            # empty
    ("junk", False, 60),        # garbage
    ("1.5", False, 60),         # not a whole number
    (" 90 ", False, 90),        # spaces around it are fine
    ("15", False, 15),          # the floor itself
    ("14", False, 60),          # below the floor: the default, not the floor
    ("-5", False, 60),
    ("0", False, 60),           # 0 is below the floor unless it means off
    ("0", True, 0),
    ("-1", True, 60),
    ("999999", False, 999999),  # no upper bound
])
def test_the_knob_reader(monkeypatch, raw, zero_off, want):
    if raw is None:
        monkeypatch.delenv(KNOB, raising=False)
    else:
        monkeypatch.setenv(KNOB, raw)
    assert settings.env_int(KNOB, 60, 15, zero_off=zero_off) == want


@pytest.mark.parametrize("raw,want", [(None, 600), ("", 600), ("junk", 600), ("9", 600),
                                      ("0", 600), ("10", 10), ("5000", 5000)])
def test_the_checks_budget_reads_as_before(monkeypatch, raw, want):
    import watch
    if raw is None:
        monkeypatch.delenv("ATLAS_CHECKS_PER_MINUTE", raising=False)
    else:
        monkeypatch.setenv("ATLAS_CHECKS_PER_MINUTE", raw)
    assert watch.PER_MINUTE == 600
    assert watch.per_minute() == want


@pytest.mark.parametrize("raw,want", [(None, 5), ("", 5), ("junk", 5), ("0", 0), ("1", 5),
                                      ("-3", 5), ("2", 2), ("30", 30)])
def test_the_checks_poll_reads_as_before(monkeypatch, raw, want):
    import watch
    if raw is None:
        monkeypatch.delenv("ATLAS_CHECKS_POLL", raising=False)
    else:
        monkeypatch.setenv("ATLAS_CHECKS_POLL", raw)
    assert watch.POLL == 5
    assert watch.poll_every() == want
