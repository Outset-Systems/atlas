"""Dependency-aware alarm suppression — one fault, one alarm.

The risk this feature carries is the reason for most of these tests: a
monitoring system that suppresses a *real* outage because it guessed a
topology is worse than one that is merely noisy. So the tests are as much
about what must NOT be suppressed as about what must.
"""

import json
import os
import shutil
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

import dependencies  # noqa: E402

BUNDLED = os.path.join(WEB, "default-lab-data.json")
WRITE = {"X-Atlas-Write": "1"}

ATLAS_TEST_ENV = {
    "ATLAS_AUTH_MODE": "standalone",
    "ATLAS_ALLOW_INSECURE": "1",
    "ATLAS_DATA_BACKEND": "file",
    "ATLAS_INGEST_ENABLED": "0",
    "ATLAS_READONLY": "0",
}
os.environ.update(ATLAS_TEST_ENV)


def data_of(*nodes):
    return {"nodes": [{"id": n["id"], **n} for n in nodes]}


def feed_of(**states):
    return {"nodes": {k: {"state": v} for k, v in states.items()}}


# ── what counts as a dependency ─────────────────────────────────────────────

def test_parent_is_a_dependency():
    """A VM cannot be up if its hypervisor is down; that is what parent means."""
    data = data_of({"id": "hv"}, {"id": "vm", "parent": "hv"})
    out = dependencies.resolve(data, feed_of(hv="down", vm="down"))
    assert out["vm"]["cause"] == "hv"


def test_depends_on_is_a_dependency():
    data = data_of({"id": "gate"}, {"id": "app", "depends_on": ["gate"]})
    out = dependencies.resolve(data, feed_of(gate="down", app="down"))
    assert out["app"]["cause"] == "gate"


@pytest.mark.parametrize("field", ["reaches", "children"])
def test_connectivity_is_not_a_dependency(field):
    """`reaches` and `children` describe topology, not need. The monitoring host reaches
    The NAS but does not stop working when the NAS does — inferring from these
    would suppress alarms that are real."""
    data = data_of({"id": "nas"}, {"id": "host", field: ["nas"]})
    assert dependencies.resolve(data, feed_of(nas="down", host="down")) == {}


def test_routes_are_not_a_dependency():
    """In this lab the monitoring observes from the edge in the DMZ, so
    "the gateway is down, therefore the app host is unreachable" is false."""
    data = {"nodes": [{"id": "gate"}, {"id": "host"}],
            "routes": [{"from": "host", "to": "gate", "kind": "vlan"}]}
    assert dependencies.resolve(data, feed_of(gate="down", host="down")) == {}


def test_a_dependency_on_a_node_that_does_not_exist_is_ignored():
    data = data_of({"id": "app", "depends_on": ["ghost"]})
    assert dependencies.resolve(data, feed_of(app="down")) == {}


# ── what must NOT be suppressed ─────────────────────────────────────────────

def test_a_fault_with_a_healthy_ancestor_is_its_own_alarm():
    """The single most important negative: an outage nobody explains must
    still shout."""
    data = data_of({"id": "hv"}, {"id": "vm", "parent": "hv"})
    assert dependencies.resolve(data, feed_of(hv="healthy", vm="down")) == {}


def test_a_healthy_node_behind_a_dead_one_is_not_touched():
    data = data_of({"id": "hv"}, {"id": "vm", "parent": "hv"})
    assert dependencies.resolve(data, feed_of(hv="down", vm="healthy")) == {}


def test_a_degraded_node_behind_a_dead_one_is_not_suppressed():
    """Only a full fault can be a consequence; 'slow' is its own signal."""
    data = data_of({"id": "hv"}, {"id": "vm", "parent": "hv"})
    assert dependencies.resolve(data, feed_of(hv="down", vm="degraded")) == {}


def test_the_root_itself_is_never_suppressed():
    data = data_of({"id": "hv"}, {"id": "vm", "parent": "hv"})
    out = dependencies.resolve(data, feed_of(hv="down", vm="down"))
    assert "hv" not in out, "the thing to go and fix must not be hidden"


# ── the graph ───────────────────────────────────────────────────────────────

def test_the_root_cause_is_the_root_not_the_nearest_domino():
    data = data_of({"id": "a"}, {"id": "b", "depends_on": ["a"]},
                   {"id": "c", "depends_on": ["b"]})
    out = dependencies.resolve(data, feed_of(a="down", b="down", c="down"))
    assert out["c"]["cause"] == "a", "blamed the domino, not the push"
    assert out["c"]["via"] == "b", "the chain should still be visible"
    assert out["b"]["cause"] == "a"


def test_a_cycle_does_not_hang():
    data = data_of({"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]})
    out = dependencies.resolve(data, feed_of(a="down", b="down"))
    assert isinstance(out, dict)        # terminates; either answer is defensible


def test_a_self_dependency_is_ignored():
    data = data_of({"id": "a", "depends_on": ["a"]})
    assert dependencies.resolve(data, feed_of(a="down")) == {}


def test_any_faulted_ancestor_explains_it():
    data = data_of({"id": "a"}, {"id": "b"}, {"id": "c", "depends_on": ["a", "b"]})
    out = dependencies.resolve(data, feed_of(a="healthy", b="down", c="down"))
    assert out["c"]["cause"] == "b"


# ── maintenance interaction ─────────────────────────────────────────────────

def test_fallout_from_planned_work_is_planned():
    data = data_of({"id": "hv"}, {"id": "vm", "parent": "hv"})
    out = dependencies.resolve(data, feed_of(hv="maintenance", vm="down"))
    assert out["vm"]["cause"] == "hv" and out["vm"]["planned"] is True


# ── the feed ────────────────────────────────────────────────────────────────

def test_apply_to_annotates_and_summarises():
    data = data_of({"id": "hv"}, {"id": "a", "parent": "hv"}, {"id": "b", "parent": "hv"})
    feed = dependencies.apply_to(data, feed_of(hv="down", a="down", b="down"))
    assert feed["causes"] == {"hv": ["a", "b"]}
    assert feed["nodes"]["a"]["cause"] == "hv"
    assert "cause" not in feed["nodes"]["hv"]


def test_a_map_with_no_declared_dependencies_is_untouched():
    data = data_of({"id": "a"}, {"id": "b"})
    feed = dependencies.apply_to(data, feed_of(a="down", b="down"))
    assert feed["causes"] == {}


# ── end to end ──────────────────────────────────────────────────────────────

@pytest.fixture
def arena(tmp_path):
    from appfixture import fresh_app
    with open(BUNDLED, encoding="utf-8") as fh:
        dataset = json.load(fh)
    data = tmp_path / "lab-data.json"
    data.write_text(json.dumps(dataset), encoding="utf-8")
    signals = tmp_path / "signals.json"
    signals.write_text("{}", encoding="utf-8")
    app = fresh_app(ATLAS_DATA=str(data), ATLAS_READONLY="0",
                    ATLAS_MAINTENANCE=str(tmp_path / "m.json"),
                    ATLAS_EVENTS=str(tmp_path / "events.json"),
                    ATLAS_REVISIONS=str(tmp_path / "rev"),
                    ATLAS_SIGNALS_SOURCES="static", ATLAS_SIGNALS_FILE=str(signals))

    def poll(states):
        signals.write_text(json.dumps({"nodes": {k: {"state": v} for k, v in states.items()}}),
                           encoding="utf-8")
        app.app.extensions["atlas"].signals._cache = None
        return app.app.test_client().get("/api/v2/signals").get_json()

    return {"client": app.app.test_client(), "poll": poll, "dataset": dataset}


def test_the_hypervisor_falling_produces_one_alarm_not_seven(arena):
    vassals = [n["id"] for n in arena["dataset"]["nodes"]
               if n.get("parent") == "hypervisor"]
    assert len(vassals) >= 5, "the bundled map should have vassals to test with"

    feed = arena["poll"]({"hypervisor": "down", **{v: "down" for v in vassals}})
    unexplained = [n for n, i in feed["nodes"].items()
                   if i.get("state") == "down" and not i.get("cause")]
    assert unexplained == ["hypervisor"]
    assert sorted(feed["causes"]["hypervisor"]) == sorted(vassals)


def test_consequences_are_recorded_but_never_queued(arena):
    vassals = [n["id"] for n in arena["dataset"]["nodes"]
               if n.get("parent") == "hypervisor"][:2]
    arena["poll"]({"hypervisor": "healthy", **{v: "healthy" for v in vassals}})
    arena["poll"]({"hypervisor": "down", **{v: "down" for v in vassals}})

    body = arena["client"].get("/api/v2/events").get_json()
    by_target = {e["target"]: e for e in body["events"]}
    assert by_target["hypervisor"]["gravity"] == "grave"
    for vassal in vassals:
        assert by_target[vassal]["gravity"] == "consequence"
        assert by_target[vassal]["cause"] == "hypervisor"
    assert body["counts"]["unacked"] == 1, \
        "one fault must leave exactly one thing demanding a human"
