"""The engines' registry (2026-11-16): each status source declares itself once.

What is held here:

* COMPLETE: every adapter class in `engines/` has one entry, and every entry
  names an adapter class that is there.
* THE OLD NAMES STAND: `signals._BUILDERS`, `integrations.SOURCES` and
  `integrations.SOURCE_NEEDS` are read from the registry and are, value for
  value and in the same order, what was written out by hand before.
* THE PAGE'S WORDS: a source's label is the word NODES shows under "Watched
  by", and the order offered to a new install is the one the settings page
  already suggests.
* BUILT AS BEFORE: the hub builds `static` and `relay` the way it did when
  they were written out inline, says the same things in the log, and guards
  only the unifi build.
* SERVED AS BEFORE: Settings › DATA SOURCES is sent the same list.

Every name and address is invented (RFC 5737). Nothing here reaches a network.
"""

import importlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import signals as S  # noqa: E402
from appfixture import fresh_app  # noqa: E402
from engines import registry  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

#: What the three names were when they were written out by hand (copied from
#: the code before the registry, 2026-11-16).
OLD_SOURCES = ("kuma", "prometheus", "unifi", "checks", "deception", "relay", "static")
OLD_SOURCE_NEEDS = {"kuma": "ATLAS_KUMA_URL", "prometheus": "ATLAS_PROM_URL",
                    "deception": "ATLAS_DECOYS_URL", "unifi": "ATLAS_UNIFI_URL"}
OLD_BUILDERS = {"kuma": S._kuma_adapter, "prometheus": S._prometheus_adapter,
                "deception": S._deception_adapter, "unifi": S._unifi_adapter,
                "checks": S._checks_adapter}


def _read(*parts):
    with open(os.path.join(WEB, *parts), encoding="utf-8") as fh:
        return fh.read()


# ── complete ────────────────────────────────────────────────────────────────

def _adapter_classes():
    """Every adapter class defined in a module of `engines/`."""
    found = set()
    for f in sorted(os.listdir(os.path.join(WEB, "engines"))):
        if not f.endswith(".py") or f == "__init__.py":
            continue
        module = importlib.import_module("engines." + f[:-3])
        for value in vars(module).values():
            if (isinstance(value, type) and issubclass(value, S._Adapter)
                    and value is not S._Adapter and value.__module__ == module.__name__):
                found.add(value)
    return found


def test_every_adapter_has_one_entry_and_every_entry_an_adapter():
    classes = _adapter_classes()
    assert len(classes) == 8
    assert {s.adapter for s in registry.REGISTRY} == classes
    assert len(registry.REGISTRY) == len(classes), "one entry each"
    for source in registry.REGISTRY:
        assert source.adapter.name == source.name, source
        assert registry.find(source.name) is source
    assert registry.find("grafana") is None


def test_an_entry_says_what_the_source_is():
    by_name = {s.name: s for s in registry.REGISTRY}
    assert sorted(by_name) == ["checks", "deception", "demo", "kuma", "prometheus", "relay",
                               "static", "unifi"]
    for source in registry.REGISTRY:
        assert isinstance(source.label, str) and source.label
        assert set(source.answers_for) <= set(registry.KINDS), source
        assert source.needs is None or source.needs in OLD_SOURCE_NEEDS.values()
        # the hub adds `demo` by itself: nobody lists it and nothing builds it by name
        assert callable(source.build) is (source.name != "demo"), source
        assert source.listed is (source.name != "demo"), source
    assert {s.name for s in registry.REGISTRY if s.handed} == {"static", "relay", "demo"}


def test_what_each_source_answers_for_is_what_its_adapter_returns():
    answers = {s.name: s.answers_for for s in registry.REGISTRY}
    assert answers == {
        "kuma": ("place", "service"),
        "prometheus": (),                      # numbers only: it sets no state
        "deception": ("stone",),
        "unifi": ("place",),
        "checks": ("place", "service"),
        "relay": ("place", "service", "stone"),
        "static": ("place", "service", "stone"),
        "demo": ("place", "service", "stone"),
    }
    # no source asks a container's own system yet
    assert not any("container" in kinds for kinds in answers.values())


def test_a_feed_file_and_kuma_return_what_their_entries_say(tmp_path):
    feed = tmp_path / "signals.json"
    feed.write_text(json.dumps({"nodes": {"box": {"state": "healthy"}},
                                "services": {"box/Wiki": {"state": "down"}},
                                "stones": {"decoy": {"state": "silent"}}}), encoding="utf-8")
    out = S.StaticFileAdapter(str(feed)).fetch()
    assert {k for k in ("nodes", "services", "stones") if out.get(k)} == {"nodes", "services", "stones"}
    out = S._parse_kuma_metrics('monitor_status{monitor_name="Box"} 1\n'
                                'monitor_status{monitor_name="Wiki"} 0\n', {"Box": "box"})
    assert out == {"nodes": {"box": {"state": "healthy"}}, "services": {"Wiki": {"state": "down"}}}


# ── the old names stand ─────────────────────────────────────────────────────

def test_the_three_old_names_are_what_they_were():
    import integrations
    assert isinstance(integrations.SOURCES, tuple) and integrations.SOURCES == OLD_SOURCES
    assert isinstance(integrations.SOURCE_NEEDS, dict)
    assert integrations.SOURCE_NEEDS == OLD_SOURCE_NEEDS
    # a save names the first source whose setting is missing: the order counts
    assert list(integrations.SOURCE_NEEDS.items()) == list(OLD_SOURCE_NEEDS.items())
    assert isinstance(S._BUILDERS, dict) and S._BUILDERS == OLD_BUILDERS
    assert list(S._BUILDERS) == list(OLD_BUILDERS)
    for name, builder in OLD_BUILDERS.items():
        assert S._BUILDERS[name] is builder


def test_the_old_names_are_read_from_the_registry():
    import integrations
    assert integrations.SOURCES == registry.listed_names()
    assert integrations.SOURCE_NEEDS == registry.needs()
    assert S._BUILDERS == registry.builders()
    assert tuple(s.name for s in registry.listed()) == OLD_SOURCES


def test_the_registry_loads_with_no_web_stack_beside_it():
    """A relay box imports it. Nothing in `engines/` may load `integrations`,
    `settings`, `signals` or `watch` on its own."""
    code = ("import sys; import engines.registry; "
            "print(sorted(m for m in ('integrations', 'settings', 'signals', 'watch') "
            "if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=WEB, capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


# ── the page's words ────────────────────────────────────────────────────────

def test_a_label_is_the_word_the_page_shows_under_watched_by():
    page = dict(re.findall(r"\bnodes_by_(\w+):\s*'([^']*)'", _read("static", "js", "nodes-text.js")))
    page.pop("nothing")                               # no source: nothing watches the place
    assert page, "the page's words were not found"
    labels = {s.name: s.label for s in registry.REGISTRY}
    assert set(page) <= set(labels), "the page has a word for a source the registry lacks"
    for name, word in page.items():
        assert labels[name] == word, name
    # the decoy feed gives no place a state, so the page has no word for it
    assert set(labels) - set(page) == {"deception"}
    assert registry.label_of("kuma") == "Kuma" and registry.label_of("checks") == "Atlas"
    assert registry.label_of("first") == "first"      # a name nothing declares is shown as it is


def test_the_plain_theme_uses_the_same_words():
    with open(os.path.join(WEB, "themes", "plain.json"), encoding="utf-8") as fh:
        text = json.load(fh)["text"]
    for source in registry.REGISTRY:
        key = f"nodes_by_{source.name}"
        if key in text:
            assert text[key] == source.label, source
    assert text["decoy_source"] == registry.find("deception").label


def test_the_default_order_is_the_rule_and_the_one_the_settings_page_suggests():
    order = registry.default_order()
    assert order == ["kuma", "prometheus", "unifi", "checks", "deception"]
    # the monitor the owner named, then the connected systems, then Atlas's own checks
    assert order.index("kuma") < order.index("prometheus") < order.index("checks")
    assert order.index("kuma") < order.index("unifi") < order.index("checks")
    # an offer, never a rule: a relay's push and a feed file are not offered
    assert not {"relay", "static", "demo"} & set(order)
    # the settings page writes its suggestion out by hand; this holds it to the ranks
    hint = re.search(r"\['ATLAS_SIGNALS_SOURCES',\s*'[^']*',\s*'([^']*)'\]",
                     _read("static", "js", "account.js"))
    assert hint and hint.group(1) == ",".join(order)
    # and the names the settings offer start with it
    assert list(registry.listed_names()[:len(order)]) == order


# ── built as before ─────────────────────────────────────────────────────────

def _sources(monkeypatch, tmp_path, listed, **env):
    monkeypatch.setenv("ATLAS_INTEGRATIONS", str(tmp_path / "integrations.json"))
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", listed)
    for name in ("ATLAS_KUMA_URL", "ATLAS_PROM_URL", "ATLAS_DECOYS_URL", "ATLAS_UNIFI_URL",
                 "ATLAS_SIGNALS_FILE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    import integrations
    integrations._cache["mtime"] = None


def test_static_and_relay_are_built_as_they_were(monkeypatch, tmp_path):
    import settings
    monkeypatch.setattr(settings, "SITE_SLUG", "a-site")
    _sources(monkeypatch, tmp_path, "relay, STATIC", ATLAS_SIGNALS_FILE=str(tmp_path / "feed.json"))
    relay, static = S.make_adapters()
    assert type(relay) is S.RelayAdapter and relay.site_slug == "a-site"
    assert type(static) is S.StaticFileAdapter and static.path == str(tmp_path / "feed.json")
    _sources(monkeypatch, tmp_path, "static")
    assert S.make_adapters()[0].path == "/data/signals.json"   # where it looks when nothing says


def test_the_listed_order_is_the_order_they_are_built_in(monkeypatch, tmp_path):
    _sources(monkeypatch, tmp_path, "checks,prometheus,static,kuma",
             ATLAS_KUMA_URL="http://192.0.2.5:3001", ATLAS_PROM_URL="http://192.0.2.6:9090/")
    adapters = S.make_adapters()
    assert [a.name for a in adapters] == ["checks", "prometheus", "static", "kuma"]
    assert adapters[1].url == "http://192.0.2.6:9090" and adapters[3].url == "http://192.0.2.5:3001"


def test_the_log_says_what_it_said(monkeypatch, tmp_path, caplog):
    _sources(monkeypatch, tmp_path, "kuma,grafana,demo,static")
    with caplog.at_level(logging.INFO, logger="atlas.live.signals"):
        adapters = S.make_adapters()
    assert [a.name for a in adapters] == ["static"]
    said = [(r.name, r.levelname, r.getMessage()) for r in caplog.records]
    assert said == [
        ("atlas.live.signals", "WARNING", "kuma source requested but ATLAS_KUMA_URL unset — skipping"),
        ("atlas.live.signals", "WARNING", "unknown signals source 'grafana' — ignoring"),
        # the hub adds the demo feed by itself; listed, it is a name nobody knows
        ("atlas.live.signals", "WARNING", "unknown signals source 'demo' — ignoring"),
        ("atlas.live.signals", "INFO", "signals: 1 source(s) enabled: static"),
    ]
    caplog.clear()
    _sources(monkeypatch, tmp_path, "")
    monkeypatch.setattr(S, "demo_feed_path", lambda: None)
    with caplog.at_level(logging.INFO, logger="atlas.live.signals"):
        assert S.make_adapters() == []
    assert [r.getMessage() for r in caplog.records] == [
        "signals: 0 source(s) enabled: (none — static/degraded map)"]


def test_only_the_unifi_build_is_guarded(monkeypatch, tmp_path, caplog):
    def broken(_given):
        raise RuntimeError("could not be built")

    for name in ("checks", "static", "relay", "kuma"):
        with monkeypatch.context() as patch:
            _sources(patch, tmp_path, name, ATLAS_KUMA_URL="http://192.0.2.5:3001")
            patch.setattr(registry.find(name), "build", broken)
            with pytest.raises(RuntimeError):
                S.make_adapters()
    _sources(monkeypatch, tmp_path, "unifi,static", ATLAS_UNIFI_URL="https://192.0.2.7")
    monkeypatch.setattr(registry.find("unifi"), "build", broken)
    with caplog.at_level(logging.WARNING, logger="atlas.live.signals"):
        assert [a.name for a in S.make_adapters()] == ["static"]
    assert [r.getMessage() for r in caplog.records] == [
        "unifi source could not be built (RuntimeError) — skipping"]


# ── served as before ────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    for var in ("ATLAS_PROM_URL", "ATLAS_LOKI_URL", "ATLAS_KUMA_URL", "ATLAS_KUMA_API_KEY",
                "ATLAS_KUMA_API_KEY_FILE", "ATLAS_DECOYS_URL", "ATLAS_DECOYS_KEY",
                "ATLAS_DECOYS_KEY_FILE", "ATLAS_SIGNALS_SOURCES", "ATLAS_ENCRYPTION_KEY_FILE",
                "ATLAS_ENCRYPTION_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ATLAS_INTEGRATIONS", str(tmp_path / "integrations.json"))
    h = fresh_app(ATLAS_DATA=str(data), ATLAS_POSITIONS=str(tmp_path / "positions.json"),
                  ATLAS_RACK=str(tmp_path / "rack.json"), ATLAS_READONLY="0")
    import integrations
    integrations._cache["mtime"] = None
    return h.app.test_client()


def test_the_settings_page_is_sent_the_same_sources(client):
    import integrations
    r = client.get("/api/v2/admin/integrations")
    assert r.status_code == 200
    body = r.get_json()
    assert body == {
        "settings": integrations.describe(),
        "allowed": list(integrations.ALLOWED),
        "groups": {k: list(v) for k, v in integrations.GROUPS.items()},
        "sources": ["kuma", "prometheus", "unifi", "checks", "deception", "relay", "static"],
        "hub": {"enabled": [], "last": {}},
    }
    # to the byte: the list as it was written out before the registry
    sent = "".join(r.get_data(as_text=True).split())
    assert '"sources":["kuma","prometheus","unifi","checks","deception","relay","static"]' in sent


def test_a_save_still_names_the_sources_and_the_first_missing_setting(client):
    w = {"X-Atlas-Write": "1", "Content-Type": "application/json"}
    r = client.post("/api/v2/admin/integrations", headers=w,
                    json={"settings": {"ATLAS_SIGNALS_SOURCES": "kuma,grafana"}})
    assert r.status_code == 422
    assert r.get_json() == {"error": "unknown signals source: grafana — one of "
                                     "kuma, prometheus, unifi, checks, deception, relay, static"}
    # the hub adds the demo feed by itself: it is not a name to list
    r = client.post("/api/v2/admin/integrations", headers=w,
                    json={"settings": {"ATLAS_SIGNALS_SOURCES": "demo"}})
    assert r.status_code == 422 and "unknown signals source: demo" in r.get_json()["error"]
    # unifi is listed first, and the decoy feed's setting is still the one asked for first
    r = client.post("/api/v2/admin/integrations", headers=w,
                    json={"settings": {"ATLAS_SIGNALS_SOURCES": "unifi,deception"}})
    assert r.status_code == 422
    assert r.get_json() == {"error": "the deception source needs ATLAS_DECOYS_URL before it "
                                     "can be enabled."}


# ── who speaks for a thing (engines/authority.py) ───────────────────────────

def test_a_named_monitor_speaks_before_atlas_and_a_shadow_only_stands_beside_it():
    from engines import authority as A
    # a place: its own check, unless a monitor watches it; then only as a shadow
    assert A.place_check(False, False) == "place"
    assert A.place_check(False, True) == "place"
    assert A.place_check(True, False) is None
    assert A.place_check(True, True) == "shadow-place"
    # a service: the same, and a monitor tied to a place has nothing to set beside
    assert A.service_check(False, False, False) == "service"
    assert A.service_check(False, False, True) == "service"
    assert A.service_check(True, False, False) is None
    assert A.service_check(True, True, True) is None
    assert A.service_check(True, False, True) == "shadow"
    # a service answers for its place only where no monitor does
    assert A.rolls_up(False, False) is True
    assert A.rolls_up(True, False) is False
    assert A.rolls_up(False, True) is False


def test_only_an_answer_with_a_state_is_credited():
    from engines import authority as A
    assert A.gives_state({"state": "healthy"}) is True
    assert A.gives_state({"latency": 3}) is False
    assert A.gives_state({"state": ""}) is False
    assert A.gives_state(None) is False
    assert A.gives_state("healthy") is False


def test_the_listed_order_still_decides_between_sources():
    """The pin for 2026-11-16: the merge is what it was. The source listed
    later is believed, and `confirmed_by` names the last one that gave a
    state, in either order."""
    kuma = {"nodes": {"gate": {"state": "down"}, "app": {"state": "healthy"}},
            "services": {"Wiki monitor": {"state": "healthy"}}}
    prom = {"nodes": {"gate": {"cpu": 12}}, "metrics": {"targets": 4}}
    unifi = {"nodes": {"gate": {"state": "healthy", "clients": 9}}}
    lab = S._merge([kuma, prom, unifi], names=["kuma", "prometheus", "unifi"])
    assert lab["nodes"]["gate"] == {"state": "healthy", "cpu": 12, "clients": 9}
    assert lab["confirmed_by"] == {"gate": "unifi", "app": "kuma"}
    assert lab["metrics"] == {"targets": 4}
    turned = S._merge([unifi, prom, kuma], names=["unifi", "prometheus", "kuma"])
    assert turned["nodes"]["gate"] == {"state": "down", "cpu": 12, "clients": 9}
    assert turned["confirmed_by"] == {"gate": "kuma", "app": "kuma"}
    # without names nobody is credited, as before
    assert "confirmed_by" not in S._merge([kuma, unifi])


def test_the_checks_and_the_merge_read_the_rule_from_one_place():
    for name in ("watch.py", "signals.py"):
        assert "import engines.authority as authority" in _read(name), name
    watch = _read("watch.py")
    assert "authority.place_check(" in watch and "authority.service_check(" in watch
    assert "authority.rolls_up(" in watch
    assert "authority.gives_state(" in _read("signals.py")
