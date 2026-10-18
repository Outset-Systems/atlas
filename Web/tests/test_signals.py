"""Tests for the signals layer — the contract that must never break the map.

The central guarantee: adapters and the hub fail silent. Every
test here that injects a failure asserts the feed still comes back well-formed,
never an exception. Run: `python -m pytest Web/tests/ -q` (or `python Web/tests/test_signals.py`).
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import signals as S  # noqa: E402


# ── Adapters fail silent ────────────────────────────────────────────────────────

def test_static_adapter_missing_file_is_silent(tmp_path):
    a = S.StaticFileAdapter(str(tmp_path / "nope.json"))
    assert a.fetch() == {}  # missing file -> empty, not an error


def test_static_adapter_bad_json_is_silent(tmp_path):
    p = tmp_path / "signals.json"
    p.write_text("{ this is not json", encoding="utf-8")
    assert S.StaticFileAdapter(str(p)).fetch() == {}  # parse error swallowed


def test_static_adapter_reads_and_coerces(tmp_path):
    p = tmp_path / "signals.json"
    p.write_text(json.dumps({
        "nodes": {
            "app-host": {"state": "healthy", "uptime_30d": 99.9},
            "gateway": {"state": "down"},
            "junk": {"state": "not-a-real-state"},   # dropped state, entry kept
            "bad": "not-a-dict",                       # dropped entirely
        },
        "services": {"hub": {"state": "healthy"}},
        "metrics": {"watchfires_up": 12, "bogus": "nan"},  # non-number dropped
    }), encoding="utf-8")

    feed = S.StaticFileAdapter(str(p)).fetch()
    assert feed["nodes"]["app-host"] == {"state": "healthy", "uptime_30d": 99.9}
    assert feed["nodes"]["gateway"]["state"] == "down"
    assert "state" not in feed["nodes"]["junk"]      # invalid state stripped
    assert "bad" not in feed["nodes"]                # non-dict dropped
    assert feed["metrics"] == {"watchfires_up": 12}  # non-number metric dropped


def test_adapter_that_raises_is_silent():
    class Boom(S._Adapter):
        name = "boom"

        def _fetch(self):
            raise RuntimeError("source on fire")

    assert Boom().fetch() == {}  # exception -> empty dict, never propagates


# ── Merge semantics ─────────────────────────────────────────────────────────────

def test_merge_later_source_wins_per_key():
    merged = S._merge([
        {"nodes": {"app-host": {"state": "healthy", "uptime_30d": 98.0}}},
        {"nodes": {"app-host": {"state": "down"}}},   # later adapter overrides state
    ])
    assert merged["nodes"]["app-host"]["state"] == "down"
    assert merged["nodes"]["app-host"]["uptime_30d"] == 98.0  # untouched key preserved


def test_kuma_parse_no_map_identity():
    # no map → monitor name is used as the id (mock / name-match case), all statuses mapped
    text = (
        'monitor_status{monitor_name="app-host",monitor_type="ping"} 1\n'   # up
        'monitor_status{monitor_name="gateway"} 0\n'                       # down
        'monitor_status{monitor_name="downloads"} 2\n'                          # pending
        'monitor_status{monitor_name="media"} 3\n'                       # maintenance
        'monitor_response_time{monitor_name="app-host"} 42\n'               # ignored
        'some_other_metric 5\n'
    )
    out = S._parse_kuma_metrics(text, {})
    assert out["nodes"]["app-host"]["state"] == S.HEALTHY
    assert out["nodes"]["gateway"]["state"] == S.DOWN
    assert out["nodes"]["downloads"]["state"] == S.DEGRADED          # pending -> amber
    assert out["nodes"]["media"]["state"] == "maintenance"    # Kuma maintenance
    assert "monitor_response_time" not in str(out)               # only monitor_status parsed


def test_kuma_parse_with_map_filters_and_remaps():
    # a configured map remaps names → node ids AND filters out unmapped monitors
    text = (
        'monitor_status{monitor_name="Edge"} 0\n'
        'monitor_status{monitor_name="App Host"} 1\n'
        'monitor_status{monitor_name="Some Service"} 1\n'
    )
    out = S._parse_kuma_metrics(text, {"Edge": "edge", "App Host": "app-host"})
    assert out["nodes"]["edge"]["state"] == S.DOWN
    assert out["nodes"]["app-host"]["state"] == S.HEALTHY
    assert "Some Service" not in out["nodes"]     # unmapped monitor skipped when a map exists
    assert len(out["nodes"]) == 2


def test_two_monitors_on_one_place_take_the_worse_state():
    """A place is healthy only if everything watching it is.

    The domain controller is watched by `DC LDAP` and `DC LDAPS`; the edge by
    `Step CA` and `Edge`. This was last-writer-wins, so a down monitor
    could be overwritten by a healthy one purely because Kuma emitted it
    earlier in /metrics — the marker would then say the place was fine while a
    monitor on it was dark. Asserted in BOTH orders, because the bug was
    invisible in exactly one of them.
    """
    healthy_first = (
        'monitor_status{monitor_name="DC LDAP"} 1\n'
        'monitor_status{monitor_name="DC LDAPS"} 0\n'
    )
    down_first = (
        'monitor_status{monitor_name="DC LDAPS"} 0\n'
        'monitor_status{monitor_name="DC LDAP"} 1\n'
    )
    mapping = {"DC LDAP": "dc", "DC LDAPS": "dc"}
    for text in (healthy_first, down_first):
        out = S._parse_kuma_metrics(text, mapping)
        assert out["nodes"]["dc"]["state"] == S.DOWN

    # ...and a known maintenance window still outranks healthy
    out = S._parse_kuma_metrics(
        'monitor_status{monitor_name="Step CA"} 3\n'
        'monitor_status{monitor_name="Edge"} 1\n',
        {"Step CA": "edge", "Edge": "edge"})
    assert out["nodes"]["edge"]["state"] == "maintenance"


# ── Hub: caching, source status, never-raises ───────────────────────────────────

def test_hub_caches_within_ttl():
    calls = {"n": 0}

    class Counting(S._Adapter):
        name = "count"

        def _fetch(self):
            calls["n"] += 1
            return {"nodes": {"x": {"state": "healthy"}}}

    hub = S.SignalsHub([Counting()], ttl=60)
    first = hub.feed()
    second = hub.feed()
    assert calls["n"] == 1            # second call served from cache
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["sources"]["count"] == "ok"


def test_hub_reports_silent_source():
    class Empty(S._Adapter):
        name = "empty"

        def _fetch(self):
            return {}

    hub = S.SignalsHub([Empty()])
    feed = hub.feed()
    assert feed["sources"]["empty"] == "silent"
    assert feed["nodes"] == {}       # no data, but a well-formed feed


def test_hub_with_no_adapters_is_degraded_not_broken():
    feed = S.SignalsHub([]).feed()
    assert feed["nodes"] == {} and feed["services"] == {} and feed["metrics"] == {}
    assert feed["sources"] == {}     # the "watchers are silent" case


def test_build_hub_from_env_static(tmp_path, monkeypatch):
    p = tmp_path / "signals.json"
    p.write_text(json.dumps({"nodes": {"w": {"state": "healthy"}}}), encoding="utf-8")
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", "static")
    monkeypatch.setenv("ATLAS_SIGNALS_FILE", str(p))
    hub = S.build_hub_from_env()
    assert hub.enabled == ["static"]
    assert hub.feed()["nodes"]["w"]["state"] == "healthy"


def test_build_hub_from_env_empty_is_no_sources(monkeypatch):
    monkeypatch.delenv("ATLAS_SIGNALS_SOURCES", raising=False)
    monkeypatch.setattr(S, "demo_feed_path", lambda: None)
    assert S.build_hub_from_env().enabled == []


# ── The bundled demo's own feed (first run) ──────────────────────────────────

def _demo_setup(tmp_path, monkeypatch, fallback="bundled", backend="file"):
    import settings
    feed = tmp_path / "demo-signals.json"
    feed.write_text(json.dumps({"nodes": {"app-host": {"state": "healthy"}}}), encoding="utf-8")
    data = tmp_path / "lab-data.json"                 # not created: an unseeded instance
    monkeypatch.delenv("ATLAS_SIGNALS_SOURCES", raising=False)
    monkeypatch.setattr(S, "demo_feed_path", lambda: str(feed))
    monkeypatch.setattr(settings, "FALLBACK", fallback)
    monkeypatch.setattr(settings, "DATA_BACKEND", backend)
    monkeypatch.setattr(settings, "DATA_PATH", str(data))
    return data


def test_bundled_demo_with_no_sources_reads_its_own_feed(tmp_path, monkeypatch):
    _demo_setup(tmp_path, monkeypatch)
    hub = S.build_hub_from_env()
    assert hub.enabled == ["demo"]
    feed = hub.feed()
    assert feed["nodes"]["app-host"]["state"] == "healthy"
    assert feed["sources"] == {"demo": "ok"}


def test_demo_feed_goes_silent_once_the_instance_is_seeded(tmp_path, monkeypatch):
    data = _demo_setup(tmp_path, monkeypatch)
    hub = S.build_hub_from_env()
    data.write_text("{}", encoding="utf-8")           # the first save writes the operator's own map
    feed = hub.feed()
    assert feed["nodes"] == {}
    assert feed["sources"] == {"demo": "silent"}


def test_no_demo_feed_for_an_empty_fallback_or_configured_sources(tmp_path, monkeypatch):
    _demo_setup(tmp_path, monkeypatch, fallback="empty")
    assert S.build_hub_from_env().enabled == []
    _demo_setup(tmp_path, monkeypatch, backend="db")
    assert S.build_hub_from_env().enabled == []
    _demo_setup(tmp_path, monkeypatch)
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", "static")
    monkeypatch.setenv("ATLAS_SIGNALS_FILE", str(tmp_path / "missing.json"))
    assert S.build_hub_from_env().enabled == ["static"]   # an operator's choice wins


def test_read_secret_prefers_env_then_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_KUMA_API_KEY", "from-env")
    assert S._read_secret("ATLAS_KUMA_API_KEY") == "from-env"
    monkeypatch.delenv("ATLAS_KUMA_API_KEY")
    f = tmp_path / "key"
    f.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setenv("ATLAS_KUMA_API_KEY_FILE", str(f))
    assert S._read_secret("ATLAS_KUMA_API_KEY") == "from-file"


# ── Minimal runner so the suite works without pytest installed ───────────────────

if __name__ == "__main__":
    import tempfile
    import types

    class _MP:
        """Tiny monkeypatch/tmp_path stand-in for running without pytest."""

        def __init__(self):
            self._saved = {}

        def setenv(self, k, v):
            self._saved.setdefault(k, os.environ.get(k))
            os.environ[k] = v

        def delenv(self, k, raising=True):
            self._saved.setdefault(k, os.environ.get(k))
            os.environ.pop(k, None)

        def undo(self):
            for k, v in self._saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if not (name.startswith("test_") and isinstance(fn, types.FunctionType)):
            continue
        kwargs = {}
        mp = _MP()
        tmp = None
        params = fn.__code__.co_varnames[: fn.__code__.co_argcount]
        if "tmp_path" in params:
            import pathlib
            tmp = tempfile.mkdtemp()
            kwargs["tmp_path"] = pathlib.Path(tmp)
        if "monkeypatch" in params:
            kwargs["monkeypatch"] = mp
        try:
            fn(**kwargs)
            passed += 1
            print(f"  ok   {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERR  {name}: {type(e).__name__}: {e}")
        finally:
            mp.undo()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
