"""THE FEED IN TWO HALVES (2026-11-16): `compose` reads, `record` writes.

`api.v2.feeds.build_feed` is `compose` then `record`. What is held here:

* THE SAME ANSWER: for one small map (a place in maintenance, one unmanaged,
  a service under repair, a rite, a consequence, a monitor nobody charted)
  `build_feed` returns what it returned before it was split. The expected
  values below were taken from the function as it stood before the split,
  run on this file's own map.
* THE SAME WRITES AT THE SAME MOMENT: a fresh feed appends to the annals and
  counts the shadow answers, a cached one does neither, and the rites sweep
  runs either way, before the rites are read.
* `compose` ALONE DOES NONE OF IT: no event, no shadow count, no sweep.

Every name and address is invented (RFC 5737).
"""

import copy
import json
import os
import shutil
from types import SimpleNamespace

from appfixture import fresh_app

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

#: One of each thing the feed lays over what the sources say.
MAP = {
    "meta": {"title": "Test map", "shadow_kuma": True},
    "zones": [], "routes": [],
    "signals": {"kuma": {"Gate monitor": "gate"}},
    "nodes": [
        {"id": "gate", "name": "GATE", "ip": "192.0.2.1", "kind": "network",
         "check": "tcp", "check_port": 22},
        {"id": "patched", "name": "PATCHED", "kind": "physical"},            # under repair
        {"id": "vm", "name": "VM", "kind": "virtual", "parent": "patched"},  # down behind it
        {"id": "app", "name": "APP", "ip": "192.0.2.10", "kind": "physical",
         "links": [{"label": "Wiki", "url": "http://192.0.2.10/", "kuma": "Wiki monitor"},
                   {"label": "Files", "url": "http://192.0.2.10:81/"}]},     # Files: under repair
        {"id": "lodger", "name": "LODGER", "kind": "physical", "unmanaged": True,
         "links": [{"label": "Panel", "url": "http://192.0.2.20/", "kuma": "Lodger panel"}]},
    ],
    "rites": [{"name": "Nightly backup", "cadence": "daily"},
              {"name": "Never ran", "cadence": "weekly"}],
}

#: What the sources say, as the hub hands it over (`cached` is added per read).
HUB = {
    "nodes": {"gate": {"state": "healthy"}, "patched": {"state": "down"}, "vm": {"state": "down"},
              "app": {"state": "healthy"}, "lodger": {"state": "down"}},
    "services": {"Wiki monitor": {"state": "healthy"}, "app/Files": {"state": "down", "ms": 3},
                 "Lodger panel": {"state": "down"}, "Stray monitor": {"state": "healthy"}},
    "stones": {}, "metrics": {},
    "confirmed_by": {"gate": "kuma", "patched": "kuma", "vm": "kuma", "app": "checks",
                     "lodger": "kuma"},
    "sources": {"kuma": "ok", "checks": "ok"},
    "sources_at": {"kuma": "2026-11-16T00:00:00Z", "checks": "2026-11-16T00:00:00Z"},
    "generated": 1000.0,
}

#: One window open now (it also names a place that is unmanaged and a service
#: no longer on the map: neither is covered) and one still to come.
WINDOWS = [
    {"id": "w1", "reason": "patching", "nodes": ["patched", "lodger"],
     "services": ["app/Files", "app/Gone"],
     "starts": "2020-01-01T00:00:00Z", "ends": "2099-01-01T00:00:00Z"},
    {"id": "w2", "reason": "later", "nodes": ["gate"],
     "starts": "2098-01-01T00:00:00Z", "ends": "2098-01-02T00:00:00Z"},
]

#: `build_feed` for the map above on a fresh read, with the rite's beat dropped
#: as a file. From the function as it stood before the split.
EXPECTED = {
    "cached": False,
    "generated": 1000.0,
    "stones": {}, "metrics": {},
    "sources": {"kuma": "ok", "checks": "ok"},
    "sources_at": {"kuma": "2026-11-16T00:00:00Z", "checks": "2026-11-16T00:00:00Z"},
    "nodes": {"gate": {"state": "healthy"},
              "patched": {"state": "maintenance"},
              "vm": {"state": "down", "cause": "patched", "via": "patched", "planned": True},
              "app": {"state": "healthy"}},
    "services": {"Wiki monitor": {"state": "healthy"},
                 "app/Files": {"state": "maintenance", "ms": 3},
                 "Stray monitor": {"state": "healthy"}},
    "confirmed_by": {"gate": "kuma", "vm": "kuma", "app": "checks"},
    "maintenance": ["patched"],
    "repairs": {"active": 1, "upcoming": 1, "next": "2098-01-01T00:00:00Z", "next_reason": "later"},
    "unmanaged": ["lodger"],
    "maintenance_services": ["app/Files"],
    "causes": {"patched": ["vm"]},
    "rites": {"nightly-backup": {"state": "healthy", "name": "Nightly backup", "verdict": "kept"}},
    "drift": {"count": 1, "uncharted": ["Stray monitor"]},
}

#: The annals after a second fresh read in which GATE went down, VM came back
#: and the stray monitor went down (`at` left out). Same origin.
EXPECTED_EVENTS = {
    "seq": 3,
    "state": {"node:app": "healthy", "node:gate": "down", "node:patched": "maintenance",
              "node:vm": "healthy", "rite:nightly-backup": "healthy",
              "service:Stray monitor": "down", "service:Wiki monitor": "healthy",
              "service:app/Files": "maintenance"},
    "behind": {},
    "events": [
        {"id": 1, "kind": "node", "target": "gate", "name": "GATE", "from": "healthy",
         "to": "down", "gravity": "grave", "ack": None},
        {"id": 2, "kind": "node", "target": "vm", "name": "VM", "from": "down",
         "to": "healthy", "gravity": "clear", "ack": None},
        {"id": 3, "kind": "service", "target": "Stray monitor", "name": "Stray monitor",
         "from": "healthy", "to": "down", "gravity": "grave", "ack": None},
    ],
}


class Hub:
    """Stands where the SignalsHub does: a fixed answer, fresh or cached."""
    adapters = ()

    def __init__(self):
        self.answer = copy.deepcopy(HUB)
        self.cached = False

    def feed(self):
        return {**copy.deepcopy(self.answer), "cached": self.cached}


def context(hub, dataset=None):
    data = copy.deepcopy(MAP)
    return SimpleNamespace(signals=hub, dataset=dataset or (lambda: (data, 0, [])))


def stage(root, monkeypatch):
    """Point every store the feed touches at `root`, with the windows above
    and what Atlas's own checks last heard (the shadow count reads it)."""
    import settings
    root = str(root)
    os.makedirs(os.path.join(root, "beats"), exist_ok=True)
    with open(os.path.join(root, "maintenance.json"), "w", encoding="utf-8") as fh:
        json.dump({"nodes": [], "windows": WINDOWS}, fh)
    heard(root, 1000)
    for name, value in {"DATA_DIR": root,
                        "EVENTS_PATH": os.path.join(root, "events.json"),
                        "BEATS_PATH": os.path.join(root, "heartbeats.json"),
                        "BEATS_DIR": os.path.join(root, "beats"),
                        "MAINTENANCE_PATH": os.path.join(root, "maintenance.json")}.items():
        monkeypatch.setattr(settings, name, value)


def heard(root, when):
    """Atlas's own checks answered healthy for the wiki and the gate at `when`."""
    entry = {"state": "healthy", "said": "healthy", "heard": when, "asked": when}
    with open(os.path.join(str(root), "checks.json"), "w", encoding="utf-8") as fh:
        json.dump({"v": 2, "at": when, "checks": {"k:Wiki monitor": dict(entry),
                                                  "kp:gate": dict(entry)}}, fh)


def drop_beat(root, name="nightly-backup"):
    path = os.path.join(str(root), "beats", name)
    with open(path, "w", encoding="utf-8"):
        pass
    return path


def second_poll(hub, root):
    """What changed by the next poll: GATE down, VM back, the stray monitor
    down, and Atlas's own checks heard again."""
    hub.answer["nodes"]["gate"] = {"state": "down"}
    hub.answer["nodes"]["vm"] = {"state": "healthy"}
    hub.answer["services"]["Stray monitor"] = {"state": "down"}
    heard(root, 1060)


def annals(root):
    """The annals as stored, each event without its `at`; None if never written."""
    path = os.path.join(str(root), "events.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        store = json.load(fh)
    store["events"] = [{k: v for k, v in e.items() if k != "at"} for e in store["events"]]
    return store


def shadow_counts(root):
    """{key: (agree, differ)} from the shadow store; None if never written."""
    path = os.path.join(str(root), "shadow.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        things = json.load(fh)["things"]
    return {k: (v.get("agree", 0), v.get("differ", 0)) for k, v in things.items()}


def raw(root, name):
    path = os.path.join(str(root), name)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


# ── the same answer ──────────────────────────────────────────────────────────

def test_build_feed_returns_what_it_did_before_the_split(tmp_path, monkeypatch):
    from api.v2 import feeds
    stage(tmp_path, monkeypatch)
    drop_beat(tmp_path)
    feed = feeds.build_feed(context(Hub()))
    assert feed == EXPECTED
    # the parts by name, so a failure says which overlay moved
    assert feed["maintenance"] == ["patched"] and feed["nodes"]["patched"] == {"state": "maintenance"}
    assert feed["unmanaged"] == ["lodger"] and "lodger" not in feed["nodes"]
    assert feed["maintenance_services"] == ["app/Files"]
    assert feed["services"]["app/Files"] == {"state": "maintenance", "ms": 3}
    assert feed["rites"] == {"nightly-backup": {"state": "healthy", "name": "Nightly backup",
                                                "verdict": "kept"}}
    assert feed["causes"] == {"patched": ["vm"]}
    assert feed["drift"] == {"count": 1, "uncharted": ["Stray monitor"]}
    assert "unmanaged_services" not in feed, "the annals' bookkeeping is never returned"


def test_a_map_that_cannot_be_read_gets_the_same_answer_too(tmp_path, monkeypatch):
    """No map: the sources' answer with the windows that name places, no
    rites, no sweep, no shadow count. The annals are still written."""
    from api.v2 import feeds
    stage(tmp_path, monkeypatch)
    beat = drop_beat(tmp_path)

    def unreadable():
        raise OSError("the map is away")

    feed = feeds.build_feed(context(Hub(), dataset=unreadable))
    nodes = copy.deepcopy(HUB["nodes"])
    nodes["patched"] = {"state": "maintenance"}
    nodes["lodger"] = {"state": "maintenance"}        # nothing says it is unmanaged
    assert feed == {**copy.deepcopy(HUB), "cached": False, "nodes": nodes,
                    "confirmed_by": {"gate": "kuma", "vm": "kuma", "app": "checks"},
                    "maintenance": ["lodger", "patched"],
                    "repairs": {"active": 1, "upcoming": 1, "next": "2098-01-01T00:00:00Z",
                                "next_reason": "later"},
                    "unmanaged": [], "maintenance_services": [], "causes": {}}
    assert os.path.exists(beat), "the sweep comes after the map is read, so it did not run"
    assert shadow_counts(tmp_path) is None
    assert annals(tmp_path)["state"]["node:gate"] == "healthy"


# ── the same writes, at the same moment ──────────────────────────────────────

def test_a_fresh_feed_records_what_it_recorded_before(tmp_path, monkeypatch):
    from api.v2 import feeds
    stage(tmp_path, monkeypatch)
    hub = Hub()
    ctx = context(hub)
    beat = drop_beat(tmp_path)
    feeds.build_feed(ctx)                                  # the first sighting only seeds
    assert annals(tmp_path)["events"] == []
    assert shadow_counts(tmp_path) == {"k:Wiki monitor": (1, 0), "kp:gate": (1, 0)}
    assert not os.path.exists(beat), "the sweep adopted the dropped beat"

    second_poll(hub, tmp_path)
    feeds.build_feed(ctx)
    assert annals(tmp_path) == EXPECTED_EVENTS
    assert shadow_counts(tmp_path) == {"k:Wiki monitor": (2, 0), "kp:gate": (1, 1)}


def test_a_cached_feed_records_nothing_and_still_sweeps(tmp_path, monkeypatch):
    from api.v2 import feeds
    stage(tmp_path, monkeypatch)
    hub = Hub()
    ctx = context(hub)
    feeds.build_feed(ctx)
    before = raw(tmp_path, "events.json"), raw(tmp_path, "shadow.json")
    assert None not in before

    second_poll(hub, tmp_path)
    hub.cached = True
    beat = drop_beat(tmp_path)
    feed = feeds.build_feed(ctx)
    assert (raw(tmp_path, "events.json"), raw(tmp_path, "shadow.json")) == before
    # the sweep is not under the cached guard, and it comes before the read
    assert not os.path.exists(beat)
    assert feed["rites"]["nightly-backup"]["verdict"] == "kept"
    assert feed["cached"] is True and "unmanaged_services" not in feed


def test_the_hubs_own_cached_read_adds_nothing_to_the_annals(tmp_path):
    """Through the route and the real hub: inside its cache window a second
    read is a cached one, so a change at the source waits for the next poll."""
    def source(state):
        (tmp_path / "signals.json").write_text(
            json.dumps({"nodes": {"app-host": {"state": state}}}), encoding="utf-8")

    source("healthy")
    # a copy of the bundled map, so every store beside the dataset is in tmp_path
    web = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    shutil.copy(os.path.join(web, "default-lab-data.json"), tmp_path / "lab-data.json")
    handle = fresh_app(ATLAS_DATA=str(tmp_path / "lab-data.json"),
                       ATLAS_EVENTS=str(tmp_path / "events.json"),
                       ATLAS_BEATS=str(tmp_path / "heartbeats.json"),
                       ATLAS_BEATS_DIR=str(tmp_path / "beats"),
                       ATLAS_SIGNALS_SOURCES="static",
                       ATLAS_SIGNALS_FILE=str(tmp_path / "signals.json"))
    c = handle.app.test_client()
    assert c.get("/api/v2/signals").get_json()["cached"] is False     # seeds
    source("down")
    assert c.get("/api/v2/signals").get_json()["cached"] is True
    assert c.get("/api/v2/events").get_json()["events"] == []
    handle._signals._cache = None                                     # the next poll
    c.get("/api/v2/signals")
    events = c.get("/api/v2/events").get_json()["events"]
    assert [(e["target"], e["to"]) for e in events] == [("app-host", "down")]


def test_the_effects_keep_their_order(tmp_path, monkeypatch):
    """Consequences, the sweep, the rites, the annals, shadow, then drift;
    the unmanaged services' keys are there for the annals and gone by drift."""
    import dependencies
    import events
    import heartbeats
    import shadow
    from api.v2 import feeds
    stage(tmp_path, monkeypatch)
    order = []

    def spy(module, name, tag, note=None):
        real = getattr(module, name)

        def wrapped(*args, **kwargs):
            order.append(tag if note is None else (tag, note(*args)))
            return real(*args, **kwargs)
        monkeypatch.setattr(module, name, wrapped)

    has_keys = lambda feed, *rest: "unmanaged_services" in feed            # noqa: E731
    spy(dependencies, "apply_to", "consequences")
    spy(heartbeats, "sweep_dropped_files", "sweep")
    spy(heartbeats, "as_feed", "rites")
    spy(events, "record", "annals", has_keys)
    spy(shadow, "observe", "shadow", has_keys)
    spy(feeds, "_drift", "drift", lambda ctx, feed: "unmanaged_services" in feed)

    feeds.build_feed(context(Hub()))
    assert order == ["consequences", "sweep", "rites", ("annals", True), ("shadow", True),
                     ("drift", False)]

    del order[:]
    hub = Hub()
    hub.cached = True
    feeds.build_feed(context(hub))
    assert order == ["consequences", "sweep", "rites", ("drift", False)]


def test_a_failure_to_write_the_annals_is_logged_and_the_feed_still_comes(tmp_path, monkeypatch):
    import events
    from api.v2 import feeds
    stage(tmp_path, monkeypatch)
    said = []
    monkeypatch.setattr(events, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(feeds.log, "warning", lambda *a: said.append(a))
    drop_beat(tmp_path)
    assert feeds.build_feed(context(Hub())) == EXPECTED
    assert [(a[0], str(a[1])) for a in said] == [("could not record events: %s", "boom")]
    assert shadow_counts(tmp_path) == {"k:Wiki monitor": (1, 0), "kp:gate": (1, 0)}, \
        "shadow is counted whether or not the annals could be written"


# ── compose alone ────────────────────────────────────────────────────────────

def test_compose_alone_records_no_event_counts_no_answer_and_sweeps_nothing(tmp_path, monkeypatch):
    from api.v2 import feeds
    stage(tmp_path, monkeypatch)
    hub = Hub()
    ctx = context(hub)
    beat = drop_beat(tmp_path)
    feeds.compose(ctx)
    second_poll(hub, tmp_path)                 # a change `build_feed` would have recorded
    feed, map_now = feeds.compose(ctx)

    assert annals(tmp_path) is None, "compose wrote to the annals"
    assert shadow_counts(tmp_path) is None, "compose counted a shadow answer"
    assert raw(tmp_path, "heartbeats.json") is None and os.path.exists(beat), "compose swept"
    assert sorted(os.listdir(str(tmp_path))) == ["beats", "checks.json", "maintenance.json"]

    # what it hands on: the map for `record`, and a feed not yet a reader's
    assert map_now == MAP
    assert feed["unmanaged_services"] == ["Lodger panel"]
    assert "drift" not in feed
    assert feed["rites"] == {}, "the beat was not adopted, so the rite is still awaited"
    assert feed["nodes"]["gate"] == {"state": "down"} and feed["maintenance"] == ["patched"]


def test_compose_then_record_is_build_feed(tmp_path, monkeypatch):
    """The two halves by hand, with the sweep handed in, write what
    `build_feed` writes."""
    import heartbeats
    from api.v2 import feeds
    stage(tmp_path, monkeypatch)
    hub = Hub()
    ctx = context(hub)
    drop_beat(tmp_path)
    feed, map_now = feeds.compose(ctx, before_rites=heartbeats.sweep_dropped_files)
    assert feeds.record(ctx, feed, map_now) is None
    second_poll(hub, tmp_path)
    feed, map_now = feeds.compose(ctx, before_rites=heartbeats.sweep_dropped_files)
    assert feeds.record(ctx, feed, map_now) is None
    assert annals(tmp_path) == EXPECTED_EVENTS
    assert shadow_counts(tmp_path) == {"k:Wiki monitor": (2, 0), "kp:gate": (1, 1)}
    assert feed["rites"]["nightly-backup"]["verdict"] == "kept"
