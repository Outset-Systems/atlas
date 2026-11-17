"""Where does it break? (2026-11-17): diagnose.py and `POST /api/v2/admin/diagnose`.

What is held here:

* IN ORDER: the path from the head down (stubs and places with nothing to
  ask listed as not asked), then DNS for a charted name, then the place, then
  the internet only when the operator named an outside address.
* STOPPED: the first step that fails is `broke_at`; nothing after it is asked.
* ONLY THE CHART: every address asked is one the map charts, or the one
  outside address; the body names a place, never an address.
* THE BUDGET: a diagnose costs what its steps cost, out of the per-minute
  budget, and is refused (429) before anything is asked when it cannot be
  covered; only the place's own check is stored.
* GATED AS "CHECK NOW": admins only, unknown and hidden ids are one 404,
  unmanaged and planned places 409, a place Kuma watches is not asked.

Every name and address is invented (RFC 5737 and example.org). Nothing here
reaches a network: `watch.probe` and `watch.peer_certificate` are replaced.
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import diagnose as D  # noqa: E402
import watch as W  # noqa: E402
from appfixture import fresh_app, login_as  # noqa: E402

PW = "a-long-enough-password"
WRITE = {"X-Atlas-Write": "1"}
OUTSIDE = "198.51.100.1:443"
APP_HEALTH = "https://app.example.org/health"

LAB = {
    "meta": {"title": "Test map"}, "zones": [],
    "signals": {"kuma": {"Watched monitor": "watched"}},
    "nodes": [
        {"id": "gate", "name": "GATE", "kind": "network", "ip": "192.0.2.1", "x": 1, "y": 1,
         "check": "tcp", "check_port": 22},
        {"id": "sw-1", "name": "SW 1", "kind": "network", "ip": "192.0.2.2", "x": 2, "y": 2,
         "links": [{"label": "Admin", "url": "https://192.0.2.2:8443/"}]},
        {"id": "host", "name": "HOST", "kind": "physical", "ip": "192.0.2.10", "x": 3, "y": 3},
        {"id": "app", "name": "APP", "kind": "physical", "ip": "192.0.2.20", "x": 4, "y": 4,
         "check": "http", "check_host": APP_HEALTH, "check_retries": 0},
        {"id": "vm", "name": "VM", "kind": "vm", "ip": "192.0.2.21", "parent": "app", "x": 5, "y": 5,
         "links": [{"label": "Web", "url": "http://192.0.2.21:8080/"}]},
        {"id": "named", "name": "NAMED", "kind": "physical", "ip": "192.0.2.30", "x": 6, "y": 6,
         "links": [{"label": "Wiki", "url": "https://wiki.example.org/"}]},
        {"id": "watched", "name": "WATCHED", "kind": "physical", "ip": "192.0.2.50", "x": 7, "y": 7,
         "check": "tcp", "check_port": 22},
        {"id": "old", "name": "OLD", "kind": "physical", "ip": "192.0.2.60", "x": 8, "y": 8,
         "unmanaged": True, "check": "tcp", "check_port": 22},
        {"id": "under-old", "name": "UNDER OLD", "kind": "physical", "ip": "192.0.2.61", "x": 8, "y": 9,
         "check": "tcp", "check_port": 22},
        {"id": "future", "name": "FUTURE", "kind": "physical", "ip": "192.0.2.70", "x": 9, "y": 9,
         "planned": True},
        {"id": "back-room", "name": "BACK ROOM", "kind": "network", "ip": "192.0.2.40", "x": 10, "y": 10,
         "require_group": "ops-team", "check": "tcp", "check_port": 22},
        {"id": "deep", "name": "DEEP", "kind": "physical", "ip": "192.0.2.41", "x": 11, "y": 11,
         "check": "tcp", "check_port": 22},
        {"id": "nowhere", "name": "NOWHERE", "kind": "physical", "ip": "—", "x": 12, "y": 12},
        {"id": "lonely", "name": "LONELY", "kind": "physical", "ip": "192.0.2.99", "x": 13, "y": 13,
         "check": "tcp", "check_port": 22},
    ],
    "stubs": [{"id": "line", "name": "LINE IN", "kind": "internet"},
              {"id": "desk-sw", "name": "DESK SWITCH", "kind": "switch"}],
    "cables": [
        {"id": "w", "a_stub": "line", "a_port": "lan", "b": "gate", "b_port": "wan"},
        {"id": "c1", "a": "gate", "a_port": "2", "b": "sw-1", "b_port": "24"},
        {"id": "c2", "a": "sw-1", "a_port": "3", "b_stub": "desk-sw", "b_port": "1"},
        {"id": "c3", "a_stub": "desk-sw", "a_port": "2", "b": "host", "b_port": "eth0"},
        {"id": "c4", "a": "host", "a_port": "eth1", "b": "app", "b_port": "eth0"},
        {"id": "c5", "a": "sw-1", "a_port": "5", "b": "named", "b_port": "eth0"},
        {"id": "c6", "a": "sw-1", "a_port": "6", "b": "watched", "b_port": "eth0"},
        {"id": "c7", "a": "gate", "a_port": "3", "b": "old", "b_port": "eth0"},
        {"id": "c8", "a": "old", "a_port": "eth1", "b": "under-old", "b_port": "eth0"},
        {"id": "c9", "a": "gate", "a_port": "4", "b": "back-room", "b_port": "1"},
        {"id": "c10", "a": "back-room", "a_port": "2", "b": "deep", "b_port": "eth0"},
        {"id": "c11", "a": "sw-1", "a_port": "7", "b": "nowhere", "b_port": "eth0"},
        {"id": "c12", "a": "sw-1", "a_port": "8", "b": "future", "b_port": "eth0"},
    ],
    "routes": [],
}

#: Every address and name the map above charts (ips, check hosts, service hosts).
CHARTED = {"192.0.2.1", "192.0.2.2", "192.0.2.10", "192.0.2.20", "192.0.2.21", "192.0.2.30",
           "192.0.2.50", "192.0.2.60", "192.0.2.61", "192.0.2.70", "192.0.2.40", "192.0.2.41",
           "192.0.2.99", "app.example.org", "wiki.example.org"}


# ── the fakes ───────────────────────────────────────────────────────────────

@pytest.fixture
def net(monkeypatch):
    """`watch.probe` and `watch.peer_certificate` replaced: every Target asked
    is kept, and `answers[ckey]` is what a probe of it says (healthy in 4 ms
    otherwise)."""
    asked, answers = [], {}

    def probe(t):
        asked.append(t)
        return answers.get(t.ckey, ("healthy", 4, {}))

    monkeypatch.setattr(W, "probe", probe)
    monkeypatch.setattr(W, "peer_certificate", lambda t: {})
    monkeypatch.delenv("ATLAS_DIAGNOSE_OUTSIDE", raising=False)
    return type("Net", (), {"asked": asked, "answers": answers,
                            "ckeys": staticmethod(lambda: [t.ckey for t in asked])})


def _run(tmp_path, pid, data=LAB, hidden=frozenset(), now=None):
    return D.diagnose(data, pid, hidden=hidden, path=str(tmp_path / "checks.json"),
                      now=time.time() if now is None else now)


def _shape(answer):
    return [(s["step"], s["thing"], s["state"], s["why"]) for s in answer["steps"]]


def _stored(tmp_path):
    p = tmp_path / "checks.json"
    return json.loads(p.read_text(encoding="utf-8"))["checks"] if p.exists() else {}


# ── in order ────────────────────────────────────────────────────────────────

def test_the_chain_is_asked_from_the_head_down_then_the_place(tmp_path, net):
    outcome, answer = _run(tmp_path, "vm")
    assert outcome == "asked"
    assert (answer["id"], answer["name"], answer["asked"], answer["broke_at"]) == ("vm", "VM", True, None)
    assert _shape(answer) == [
        ("hop", "line", "skipped", "stub"),
        ("hop", "gate", "up", None),
        ("hop", "sw-1", "up", None),
        ("hop", "desk-sw", "skipped", "stub"),
        ("hop", "host", "skipped", "no-port"),
        ("hop", "app", "up", None),
        ("place", "vm", "up", None),
    ]
    assert net.ckeys() == ["p:gate", "d:sw-1", "p:app", "d:vm"], "nearest the head first"
    steps = answer["steps"]
    assert [s["asks"] for s in steps] == [None, "192.0.2.1 port 22", "192.0.2.2 port 8443", None, None,
                                          APP_HEALTH, "192.0.2.21 port 8080"]
    assert [s["name"] for s in steps] == ["LINE IN", "GATE", "SW 1", "DESK SWITCH", "HOST", "APP", "VM"]
    assert all(s["ms"] == 4 for s in steps if s["state"] == "up")
    assert all(set(s) == {"step", "thing", "name", "asks", "state", "why", "ms", "error"} for s in steps)
    # head first, the cables, then the parent tie the vm hangs by
    assert answer["path"] == {"things": ["line", "gate", "sw-1", "desk-sw", "host", "app", "vm"],
                              "links": ["w", "c1", "c2", "c3", "c4", "parent:vm"]}
    # a hop's own check is asked, never stored: the store is the round's
    assert _stored(tmp_path) == {}


def test_the_place_s_own_check_is_asked_as_check_now_and_stored(tmp_path, net):
    now = time.time()
    outcome, answer = _run(tmp_path, "app", now=now)
    assert outcome == "asked"
    assert _shape(answer)[-2:] == [("dns", "app", "up", None), ("place", "app", "up", None)]
    assert answer["steps"][-2]["asks"] == "the name app.example.org"
    assert net.ckeys() == ["p:gate", "d:sw-1", "d:dns:app", "p:app"]
    assert list(_stored(tmp_path)) == ["p:app"], "only the place's own check is stored"
    assert _stored(tmp_path)["p:app"]["asked"] == now


def test_a_head_has_no_hops_and_a_loose_place_has_no_path(tmp_path, net):
    _, answer = _run(tmp_path, "gate")
    assert _shape(answer) == [("hop", "line", "skipped", "stub"), ("place", "gate", "up", None)]
    _, answer = _run(tmp_path, "lonely")
    assert _shape(answer) == [("place", "lonely", "up", None)]
    assert answer["path"] == {"things": [], "links": []}
    head = {"nodes": [{"id": "gw", "kind": "network", "ip": "192.0.2.1", "check": "tcp", "check_port": 22},
                      {"id": "pc", "ip": "192.0.2.5"}],
            "cables": [{"a": "gw", "b": "pc"}]}
    _, answer = _run(tmp_path, "gw", data=head)
    assert _shape(answer) == [("place", "gw", "up", None)]
    assert answer["path"] == {"things": ["gw"], "links": []}


def test_dns_is_asked_only_for_a_charted_name(tmp_path, net):
    _, answer = _run(tmp_path, "named")
    assert _shape(answer)[-2:] == [("dns", "named", "up", None), ("place", "named", "skipped", "no-port")]
    assert "d:dns:named" in net.ckeys()
    assert [t.host for t in net.asked if t.type == "dns"] == ["wiki.example.org"]
    # an address only: no dns step at all, and a place's id or name is never a name
    _, answer = _run(tmp_path, "vm")
    assert "dns" not in [s["step"] for s in answer["steps"]]
    assert D.dns_name({"id": "app.example.org", "name": "box.example.org", "ip": "192.0.2.1"}) == ""
    assert D.dns_name({"check_host": "192.0.2.1"}) == ""
    assert D.dns_name({"check_host": "2852039166"}) == ""
    assert D.dns_name({"check_host": "nas.example.org"}) == "nas.example.org"
    assert D.dns_name({"links": [{"url": "http://192.0.2.9/"}, {"url": "https://u:p@git.example.org/x?k=1"}]}) \
        == "git.example.org"
    assert D.dns_name({"links": [{"url": "https://later.example.org/", "planned": True}]}) == ""


def test_a_place_with_no_address_is_not_asked_and_nothing_is_guessed(tmp_path, net):
    _, answer = _run(tmp_path, "nowhere")
    assert _shape(answer)[-1] == ("place", "nowhere", "skipped", "no-address")
    assert "d:nowhere" not in net.ckeys()


def test_a_port_is_borrowed_only_from_a_service_atlas_asks(tmp_path, net):
    """The plain probe's port comes from what the watch itself asks: a place
    whose check is off, or a service at its address that is off, watched by
    Kuma, or unmanaged, lends no port, and nothing at the address is asked."""
    places = {
        "quiet": {"check": "off", "check_port": 22},
        "kuma-link": {"links": [{"label": "Web", "url": "http://192.0.2.81:8080/", "kuma": "Web monitor"}]},
        "off-link": {"links": [{"label": "Web", "url": "http://192.0.2.82:8080/", "check": "off"}]},
        "quiet-link": {"links": [{"label": "Web", "url": "http://192.0.2.83:8080/", "unmanaged": True}]},
        "elsewhere": {"links": [{"label": "Web", "url": "http://198.51.100.9:8080/"}]},
        "lent": {"links": [{"label": "Db", "check": "tcp", "check_port": 5432}]},
    }
    data = {"nodes": [{"id": "gw", "kind": "network", "ip": "192.0.2.1"}], "cables": []}
    for i, (pid, extra) in enumerate(places.items()):
        data["nodes"].append({"id": pid, "ip": f"192.0.2.{80 + i}", **extra})
        data["cables"].append({"a": "gw", "b": pid})
    why = {}
    for i, pid in enumerate(places):
        _, answer = _run(tmp_path, pid, data=data, now=time.time() + i * (W.EVERY_MIN + 1))
        why[pid] = answer["steps"][-1]["why"]
    assert why == {"quiet": "off", "kuma-link": "no-port", "off-link": "no-port",
                   "quiet-link": "no-port", "elsewhere": "no-port", "lent": None}
    assert [(t.host, t.port) for t in net.asked] == [("192.0.2.85", 5432)], \
        "only the tcp check a service charts at the place's own address"


# ── stopped ─────────────────────────────────────────────────────────────────

def test_it_stops_at_the_first_step_that_fails_and_says_which(tmp_path, net):
    net.answers["d:sw-1"] = ("down", 3000, {"why": "timeout"})
    _, answer = _run(tmp_path, "vm")
    assert answer["broke_at"] == 2
    broke = answer["steps"][2]
    assert (broke["thing"], broke["state"], broke["error"], broke["ms"]) == \
        ("sw-1", "down", W.WHY["timeout"], 3000)
    assert _shape(answer)[3:] == [("hop", "desk-sw", "skipped", "stub"),
                                  ("hop", "host", "skipped", "no-port"),
                                  ("hop", "app", "skipped", "stopped"),
                                  ("place", "vm", "skipped", "stopped")]
    assert net.ckeys() == ["p:gate", "d:sw-1"], "nothing after the failure is asked"


def test_the_place_failing_is_where_it_broke(tmp_path, net):
    net.answers["p:app"] = ("degraded", 20, {"why": "server-error", "status": 502})
    _, answer = _run(tmp_path, "app")
    assert answer["broke_at"] == len(answer["steps"]) - 1
    assert (answer["steps"][-1]["state"], answer["steps"][-1]["error"]) == ("down", W.WHY["server-error"])


def test_a_step_that_could_not_be_asked_says_nothing_and_does_not_break(tmp_path, net):
    net.answers["p:gate"] = (None, 1, {})
    _, answer = _run(tmp_path, "vm")
    assert answer["steps"][1]["state"] == "skipped" and answer["steps"][1]["why"] == "not-asked"
    assert answer["broke_at"] is None


# ── the internet ────────────────────────────────────────────────────────────

def test_the_internet_step_is_absent_unless_an_outside_address_is_named(tmp_path, net, monkeypatch):
    _, answer = _run(tmp_path, "gate")
    assert "internet" not in [s["step"] for s in answer["steps"]]
    monkeypatch.setenv("ATLAS_DIAGNOSE_OUTSIDE", OUTSIDE)
    _, answer = _run(tmp_path, "sw-1")
    last = answer["steps"][-1]
    assert (last["step"], last["thing"], last["state"], last["asks"]) == \
        ("internet", None, "up", "198.51.100.1 port 443")
    assert net.asked[-1].host == "198.51.100.1" and net.asked[-1].port == 443


@pytest.mark.parametrize("raw", ["x", "198.51.100.1", "198.51.100.1:0", "198.51.100.1:70000",
                                 "169.254.169.254:80", "0.0.0.0:80", "http://198.51.100.1:80",
                                 "[::1:80", "[zz]:80", "2852039166:80", "198.51.100.1:80 extra"])
def test_an_outside_address_that_cannot_be_asked_leaves_the_step_off(monkeypatch, raw):
    monkeypatch.setenv("ATLAS_DIAGNOSE_OUTSIDE", raw)
    assert D.outside() is None


def test_an_outside_address_may_be_a_name_or_an_ipv6_address(monkeypatch):
    monkeypatch.setenv("ATLAS_DIAGNOSE_OUTSIDE", "probe.example.org:443")
    assert (D.outside().host, D.outside().port) == ("probe.example.org", 443)
    monkeypatch.setenv("ATLAS_DIAGNOSE_OUTSIDE", "[2001:db8::1]:53")
    assert (D.outside().host, D.outside().port) == ("2001:db8::1", 53)


# ── what may be asked ───────────────────────────────────────────────────────

def test_hidden_unmanaged_and_kuma_places_on_the_path_are_skipped_and_say_why(tmp_path, net):
    _, answer = _run(tmp_path, "deep", hidden={"back-room"})
    hop = answer["steps"][2]
    assert (hop["thing"], hop["name"], hop["asks"], hop["state"], hop["why"]) == \
        (None, None, None, "skipped", "hidden")
    assert answer["path"]["things"] == ["line", "gate", None, "deep"]
    assert answer["path"]["links"] == ["w", None, None], "a link that names a hidden place is not shown"
    assert "back-room" not in json.dumps(answer) and "BACK ROOM" not in json.dumps(answer)
    assert "p:back-room" not in net.ckeys()

    _, answer = _run(tmp_path, "under-old")
    assert _shape(answer)[2] == ("hop", "old", "skipped", "unmanaged")
    assert "p:old" not in net.ckeys()

    # a place Kuma watches: not asked while Check beside Kuma is off
    _, answer = _run(tmp_path, "watched")
    assert _shape(answer)[-1] == ("place", "watched", "skipped", "kuma")
    assert not any(t.place == "watched" for t in net.asked)


def test_beside_kuma_the_place_is_asked_as_its_shadow(tmp_path, net):
    data = json.loads(json.dumps(LAB))
    data["meta"]["shadow_kuma"] = True
    _, answer = _run(tmp_path, "watched", data=data)
    assert _shape(answer)[-1] == ("place", "watched", "up", None)
    assert net.ckeys()[-1] == "kp:watched"


def test_unknown_hidden_unmanaged_and_planned_ids_are_refused_before_anything_is_asked(tmp_path, net):
    assert _run(tmp_path, "nothing-here") == ("none", None)
    assert _run(tmp_path, "line") == ("none", None), "a stub is not a place"
    assert _run(tmp_path, "back-room", hidden={"back-room"}) == ("none", None)
    assert _run(tmp_path, "old") == ("unmanaged", None)
    assert _run(tmp_path, "future") == ("planned", None)
    assert _run(tmp_path, "192.0.2.1") == ("none", None)
    assert _run(tmp_path, "") == ("none", None)
    assert net.asked == []


def test_no_address_outside_the_chart_is_ever_asked(tmp_path, net, monkeypatch):
    monkeypatch.setenv("ATLAS_DIAGNOSE_OUTSIDE", OUTSIDE)
    now = time.time()
    for i, node in enumerate(LAB["nodes"]):
        _run(tmp_path, node["id"], now=now + i * (W.EVERY_MIN + 1))
    assert net.asked, "something was asked"
    for t in net.asked:
        where = W._parts(t.url)[0] if t.url else t.host
        assert where in CHARTED | {"198.51.100.1"}, t


# ── the budget ──────────────────────────────────────────────────────────────

def test_a_diagnose_costs_its_steps_and_is_refused_before_asking_when_the_minute_cannot_cover_it(
        tmp_path, net, monkeypatch):
    now = time.time()
    monkeypatch.setattr(W, "per_minute", lambda: 6)
    # vm costs 4 (gate, sw-1, app, vm); 3 asked in the last minute leave room for 3
    (tmp_path / "checks.json").write_text(json.dumps({"v": 2, "at": now, "checks": {
        f"s:x/{i}": {"asked": now - 50 + i} for i in range(3)}}), encoding="utf-8")
    outcome, wait = _run(tmp_path, "vm", now=now)
    assert outcome == "spent" and 1 <= wait <= 11
    assert net.asked == []
    # with room for 4 it runs, and its asks count against the next one
    monkeypatch.setattr(W, "per_minute", lambda: 7)
    assert _run(tmp_path, "vm", now=now)[0] == "asked"
    assert len(W.asked_by_hand(str(tmp_path / "checks.json"), now)) == 4, "two hops' own checks, sw-1, the vm"
    assert _stored(tmp_path).keys() == {f"s:x/{i}" for i in range(3)}, "none of them stored"
    # a minute on, the stored asks have aged out, the four by hand have not
    monkeypatch.setattr(W, "per_minute", lambda: 4)
    outcome, _ = _run(tmp_path, "gate", now=now + W.EVERY_MIN)
    assert outcome == "spent"


def test_the_by_hand_asks_spend_check_now_s_budget_too(tmp_path, net, monkeypatch):
    now = time.time()
    path = str(tmp_path / "checks.json")
    monkeypatch.setattr(W, "per_minute", lambda: 2)
    W.spend_by_hand(path, 2, now)
    t = W.find(LAB, "gate")
    assert W.manual_wait({"checks": {}}, t, now, path=path) > 0
    assert W.manual_wait({"checks": {}}, t, now) == 0, "another store's asks are its own"
    assert W.manual_wait({"checks": {}}, t, now + 61, path=path) == 0


def test_the_same_place_asked_a_moment_ago_waits(tmp_path, net):
    now = time.time()
    assert _run(tmp_path, "vm", now=now)[0] == "asked"
    outcome, wait = _run(tmp_path, "vm", now=now + 5)
    assert outcome == "soon" and 1 <= wait <= W.EVERY_MIN
    asked = len(net.asked)
    # its own check asked by hand a moment ago waits too
    (tmp_path / "checks.json").write_text(json.dumps({"v": 2, "at": now, "checks": {
        "p:gate": {"asked": now + 100}}}), encoding="utf-8")
    assert _run(tmp_path, "gate", now=now + 105)[0] == "soon"
    assert len(net.asked) == asked


# ── the route ───────────────────────────────────────────────────────────────

def _env(tmp_path, **extra):
    data = tmp_path / "lab-data.json"
    data.write_text(json.dumps(LAB), encoding="utf-8")
    env = {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file", "ATLAS_READONLY": "0",
           "ATLAS_DATA": str(data), "ATLAS_ACCOUNTS_DB": str(tmp_path / "accounts.db"),
           "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
           "ATLAS_BEATS": str(tmp_path / "heartbeats.json"),
           "ATLAS_BEATS_DIR": str(tmp_path / "beats"),
           "ATLAS_EVENTS": str(tmp_path / "events.json"),
           "ATLAS_SECRET_KEY": "test-signing-key", "ATLAS_INSECURE_COOKIES": "1",
           "ATLAS_SIGNALS_SOURCES": "checks", "ATLAS_AUTH_BACKENDS": "local",
           "ATLAS_MFA_REQUIRED": "", "ATLAS_ALLOW_INSECURE": "1"}
    env.update(extra)
    return env


def _boot(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ATLAS_AGENT_API", raising=False)
    import integrations
    integrations._cache["mtime"] = None
    handle = fresh_app()
    import accounts
    accounts.create_local_user("map-admin", PW, is_admin=True)
    accounts.create_local_user("map-viewer", PW)
    return handle


@pytest.fixture
def realm(net, tmp_path, monkeypatch):
    handle = _boot(monkeypatch, _env(tmp_path))
    yield handle
    monkeypatch.undo()
    fresh_app()


def _signed_in(realm, name):
    client = realm.app.test_client()
    r, _ = login_as(client, name, PW)
    assert r.status_code == 200 and r.get_json()["ok"]
    return client


def _post(client, body, headers=WRITE):
    return client.post("/api/v2/admin/diagnose", headers=headers, data=json.dumps(body),
                       content_type="application/json")


def test_an_admin_asks_where_it_breaks(realm, tmp_path, net):
    r = _post(_signed_in(realm, "map-admin"), {"id": "app"})
    assert r.status_code == 200, r.get_json()
    assert r.headers["Cache-Control"] == "no-store, private"
    body = r.get_json()
    assert set(body) == {"id", "name", "asked", "steps", "broke_at", "path"}
    assert [s["step"] for s in body["steps"]] == ["hop", "hop", "hop", "hop", "hop", "dns", "place"]
    assert body["broke_at"] is None
    assert "p:app" in _stored(tmp_path)


def test_a_viewer_and_a_missing_write_header_are_refused(realm, net):
    r = _post(_signed_in(realm, "map-viewer"), {"id": "app"})
    assert (r.status_code, r.get_json()["error"]) == (403, "admins only")
    assert _post(_signed_in(realm, "map-admin"), {"id": "app"}, headers={}).status_code == 403
    assert realm.app.test_client().post("/api/v2/admin/diagnose", json={"id": "app"},
                                        headers=WRITE).status_code == 401
    assert net.asked == []


def test_the_body_takes_an_id_and_never_an_address(realm, net):
    admin = _signed_in(realm, "map-admin")
    for body in (None, [], "app", {}, {"id": 7}, {"id": ""}, {"id": "x" * 513},
                 {"id": "app", "address": "198.51.100.7"}, {"id": "app", "host": "198.51.100.7"},
                 {"id": "app", "port": 22}, {"key": "app"}, {"address": "198.51.100.7"}):
        assert _post(admin, body).status_code == 400, body
    for pid in ("198.51.100.7", "http://198.51.100.7/", "nothing-here", "line"):
        r = _post(admin, {"id": pid})
        assert (r.status_code, r.get_json()) == (404, {"error": "no such place"}), pid
    assert net.asked == []


def test_unmanaged_planned_and_off_are_409(realm, net, tmp_path, monkeypatch):
    admin = _signed_in(realm, "map-admin")
    r = _post(admin, {"id": "old"})
    assert (r.status_code, r.get_json()["why"]) == (409, "unmanaged")
    r = _post(admin, {"id": "future"})
    assert (r.status_code, r.get_json()["why"]) == (409, "planned")
    assert net.asked == []


def test_with_the_checks_source_off_nothing_is_asked(net, tmp_path, monkeypatch):
    handle = _boot(monkeypatch, _env(tmp_path, ATLAS_SIGNALS_SOURCES=""))
    try:
        r = _post(_signed_in(handle, "map-admin"), {"id": "app"})
        assert (r.status_code, r.get_json()["why"]) == (409, "off")
        assert net.asked == []
    finally:
        monkeypatch.undo()
        fresh_app()


def test_the_budget_refused_is_429_with_a_retry_after(realm, tmp_path, net, monkeypatch):
    now = time.time()
    monkeypatch.setattr(W, "per_minute", lambda: 3)
    (tmp_path / "checks.json").write_text(json.dumps({"v": 2, "at": now, "checks": {
        f"s:x/{i}": {"asked": now - 50 + i} for i in range(3)}}), encoding="utf-8")
    r = _post(_signed_in(realm, "map-admin"), {"id": "app"})
    assert r.status_code == 429 and r.get_json()["why"] == "spent"
    assert r.get_json()["retry_after"] == int(r.headers["Retry-After"]) >= 1
    assert set(r.get_json()) == {"error", "why", "retry_after"}
    assert net.asked == []


# ── what a review found (2026-11-17) ────────────────────────────────────────

def test_two_diagnoses_at_once_cannot_ask_past_the_minute(tmp_path, monkeypatch):
    """Weighed and spent in one breath: each used to pass the weighing before
    either had spent anything."""
    import threading
    asked, gate = [], threading.Event()

    def probe(t):
        asked.append(t.ckey)
        gate.wait(2)                      # hold every probe until all have weighed
        return ("healthy", 4, {})

    monkeypatch.setattr(W, "probe", probe)
    monkeypatch.setattr(W, "peer_certificate", lambda t: {})
    monkeypatch.delenv("ATLAS_DIAGNOSE_OUTSIDE", raising=False)
    monkeypatch.setattr(W, "per_minute", lambda: 5)      # vm costs 4, named costs 3
    path = str(tmp_path / "checks.json")
    out = {}

    def go(pid):
        out[pid] = D.diagnose(LAB, pid, path=path)[0]

    threads = [threading.Thread(target=go, args=(pid,)) for pid in ("vm", "named")]
    for t in threads:
        t.start()
    for _ in range(100):                  # until both have been weighed
        if len(out) + (1 if asked else 0) >= 2:
            break
        time.sleep(0.02)
    gate.set()
    for t in threads:
        t.join(10)
    assert sorted(out.values()) == ["asked", "spent"], out
    assert len(asked) <= 5


def test_a_hop_asked_a_moment_ago_is_not_asked_again(tmp_path, net):
    """The places under one switch share it: its last answer stands for the
    shortest interval a check may have."""
    now = time.time()
    _, first = _run(tmp_path, "vm", now=now)
    assert net.ckeys() == ["p:gate", "d:sw-1", "p:app", "d:vm"]
    net.answers["p:gate"] = ("down", 9, {"why": "refused"})     # would be seen if it were asked
    _, second = _run(tmp_path, "named", now=now + 1)
    # named has no port of its own to ask: only its name is looked up
    assert net.ckeys()[4:] == ["d:dns:named"], "gate and sw-1 were not asked again"
    assert _shape(second)[:3] == [("hop", "line", "skipped", "stub"), ("hop", "gate", "up", None),
                                  ("hop", "sw-1", "up", None)]
    # past the interval it is asked, and what it says now is heard
    _, third = _run(tmp_path, "lonely", now=now + 2)             # another place, no hops
    _, later = _run(tmp_path, "vm", now=now + W.EVERY_MIN + 1)
    assert later["broke_at"] == 1 and _shape(later)[1] == ("hop", "gate", "down", None)


def test_a_chain_that_takes_too_long_stops_asking_and_says_so(tmp_path, net, monkeypatch):
    monkeypatch.setattr(D, "DEADLINE", -1.0)           # already late before the first step
    outcome, answer = D.diagnose(LAB, "vm", path=str(tmp_path / "checks.json"))
    assert outcome == "asked" and net.asked == []
    assert [s["why"] for s in answer["steps"] if s["step"] != "hop" or s["thing"] in ("gate", "sw-1", "app")] \
        == ["late", "late", "late", "late"]
    assert answer["broke_at"] is None
    assert "late" in D.WHY
