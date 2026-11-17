"""SHADOW (2026-11-15): Atlas's own checks asked beside Kuma, and counted.

What is held here:

* OFF UNLESS ASKED: only the map's `meta.shadow_kuma` makes Atlas ask what a
  Kuma monitor watches, and those answers never reach the live feed.
* COUNTED ONCE: each answer Atlas heard is set beside Kuma's state once, up
  against not-up; maintenance, silence and an answer not yet believed are
  not counted.
* AN ADMIN'S: the comparison is read on the admin surface only.

Every name and address is invented (RFC 5737 and private ranges).
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shadow  # noqa: E402
import watch as W  # noqa: E402
from appfixture import fresh_app, login_as  # noqa: E402

PW = "a-long-enough-password"


def _map(on=True):
    return {"meta": {"title": "Test map", "shadow_kuma": on}, "zones": [], "routes": [],
            "signals": {"kuma": {"Gate monitor": "gate"}},
            "nodes": [
                {"id": "app", "name": "APP", "ip": "192.0.2.10", "kind": "physical", "x": 10, "y": 10,
                 "links": [{"label": "Wiki", "url": "http://192.0.2.10/", "kuma": "Wiki monitor"},
                           {"label": "Files", "url": "http://192.0.2.10:81/"}]},
                {"id": "gate", "name": "GATE", "ip": "192.0.2.1", "kind": "network", "x": 20, "y": 20,
                 "check": "tcp", "check_port": 22},
            ]}


def test_shadow_asks_what_kuma_watches_only_when_the_map_says_so():
    on = [(t.ckey, t.kind) for t in W.targets(_map(True))]
    assert on == [("k:Wiki monitor", "shadow"), ("s:app/Files", "service"), ("kp:gate", "shadow-place")]
    assert [(t.ckey, t.kind) for t in W.targets(_map(False))] == [("s:app/Files", "service")]


def test_a_shadow_answer_never_reaches_the_feed():
    ts = W.targets(_map(True))
    store = {"checks": {t.ckey: {"state": "down", "heard": 1000, "asked": 1000, "ms": 3} for t in ts}}
    feed = W.as_feed(store, ts, now=1001, factor=1.0)
    assert feed == {"services": {"app/Files": {"state": "down", "ms": 3}}, "nodes": {"app": {"state": "down"}}}


def _heard(tmp_path, states, heard=1000):
    body = {"v": 2, "at": heard, "checks": {k: {"state": s, "said": s, "heard": heard, "asked": heard}
                                            for k, s in states.items()}}
    (tmp_path / "checks.json").write_text(json.dumps(body), encoding="utf-8")


def _observe(tmp_path, feed, data=None, now=2000):
    return shadow.observe(feed, data or _map(True), path=str(tmp_path / "shadow.json"),
                          watch_path=str(tmp_path / "checks.json"), now=now)


KUMA = {"services": {"Wiki monitor": {"state": "healthy"}},
        "nodes": {"gate": {"state": "down"}}, "confirmed_by": {"gate": "kuma"}}


def test_each_answer_is_counted_once_up_against_not_up(tmp_path):
    _heard(tmp_path, {"k:Wiki monitor": "healthy", "kp:gate": "healthy"})
    assert _observe(tmp_path, KUMA) == 2
    assert _observe(tmp_path, KUMA) == 0, "the same answer is not counted twice"
    _heard(tmp_path, {"k:Wiki monitor": "degraded", "kp:gate": "down"}, heard=1060)
    assert _observe(tmp_path, KUMA, now=2060) == 2
    s = shadow.summary(_map(True), path=str(tmp_path / "shadow.json"))
    assert (s["on"], s["agree"], s["differ"], s["since"]) == (True, 2, 2, 2000)
    by = {t["key"]: t for t in s["things"]}
    assert (by["Wiki monitor"]["agree"], by["Wiki monitor"]["differ"]) == (1, 1)
    assert by["Wiki monitor"]["last"] == [{"at": 1060, "atlas": "degraded", "kuma": "healthy"}]
    assert (by["Wiki monitor"]["name"], by["Wiki monitor"]["of"], by["Wiki monitor"]["place"]) == ("Wiki", "APP", "app")
    assert (by["gate"]["agree"], by["gate"]["differ"], by["gate"]["name"]) == (1, 1, "GATE")


def test_maintenance_silence_and_a_belief_not_yet_formed_are_not_counted(tmp_path):
    _heard(tmp_path, {"k:Wiki monitor": "healthy", "kp:gate": "healthy"})
    feed = {"services": {"Wiki monitor": {"state": "maintenance"}}, "nodes": {"gate": {"state": "down"}},
            "confirmed_by": {"gate": "checks"}}
    assert _observe(tmp_path, feed) == 0, "Kuma in maintenance, and a place Kuma did not decide"
    body = json.loads((tmp_path / "checks.json").read_text(encoding="utf-8"))
    del body["checks"]["k:Wiki monitor"]["state"]           # a failure still inside its retries
    (tmp_path / "checks.json").write_text(json.dumps(body), encoding="utf-8")
    assert _observe(tmp_path, KUMA) == 1, "only the place this time"


def test_off_is_silent_and_what_is_no_longer_shadowed_is_dropped(tmp_path):
    _heard(tmp_path, {"k:Wiki monitor": "healthy", "kp:gate": "down"})
    assert _observe(tmp_path, KUMA, data=_map(False)) is None
    assert not (tmp_path / "shadow.json").exists()
    _observe(tmp_path, KUMA)
    smaller = _map(True)
    smaller["nodes"][0]["links"][0].pop("kuma")
    _observe(tmp_path, KUMA, data=smaller, now=2100)
    assert [t["key"] for t in shadow.summary(smaller, path=str(tmp_path / "shadow.json"))["things"]] == ["gate"]


def test_a_broken_comparison_never_breaks_the_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow, "_observe", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert shadow.observe(KUMA, _map(True)) is None


# ── an admin's ──────────────────────────────────────────────────────────────

@pytest.fixture
def realm(tmp_path, monkeypatch):
    data = tmp_path / "lab-data.json"
    data.write_text(json.dumps(_map(True)), encoding="utf-8")
    for name, value in {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file",
                        "ATLAS_DATA": str(data), "ATLAS_ACCOUNTS_DB": str(tmp_path / "accounts.db"),
                        "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
                        "ATLAS_BEATS": str(tmp_path / "heartbeats.json"),
                        "ATLAS_BEATS_DIR": str(tmp_path / "beats"),
                        "ATLAS_EVENTS": str(tmp_path / "events.json"),
                        "ATLAS_SECRET_KEY": "test-signing-key", "ATLAS_INSECURE_COOKIES": "1",
                        "ATLAS_SIGNALS_SOURCES": "", "ATLAS_AUTH_BACKENDS": "local",
                        "ATLAS_MFA_REQUIRED": "", "ATLAS_ALLOW_INSECURE": "1"}.items():
        monkeypatch.setenv(name, value)
    import integrations
    integrations._cache["mtime"] = None
    handle = fresh_app()
    import accounts
    accounts.create_local_user("map-admin", PW, is_admin=True)
    accounts.create_local_user("map-viewer", PW)
    yield handle
    monkeypatch.undo()
    fresh_app()


def _signed_in(realm, name):
    client = realm.app.test_client()
    r, _ = login_as(client, name, PW)
    assert r.status_code == 200 and r.get_json()["ok"]
    return client


def test_the_comparison_is_an_admins_to_read(realm):
    r = _signed_in(realm, "map-admin").get("/api/v2/admin/shadow")
    assert r.status_code == 200
    body = r.get_json()
    assert body["on"] is True and body["agree"] == 0 and body["things"] == []
    assert _signed_in(realm, "map-viewer").get("/api/v2/admin/shadow").status_code in (401, 403, 404)
    assert realm.app.test_client().get("/api/v2/admin/shadow").status_code in (401, 403, 404)


def test_nodes_shows_who_watches_and_the_comparison():
    web = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = os.path.join(web, "static", "js")
    nodes = ""
    for name in sorted(n for n in os.listdir(js) if n.startswith("nodes") and n.endswith(".js")):   # nodes.js and its parts (2026-11-16)
        with open(os.path.join(js, name), encoding="utf-8") as fh:
            nodes += fh.read()
    for piece in ("nodes_col_confirmed: 'Watched by'", "`<td>${watchedCell(row)}</td>`",
                  "fetch('api/v2/admin/shadow'", "if (!mayWrite()) { S.shadow = null; return null; }",
                  'class="nv-recent nv-shadow"', "serviceWatcher(svc)"):
        assert piece in nodes, piece



# ── what the review of A5 found (2026-11-15) ─────────────────────────────────

def test_a_failure_still_inside_its_retries_is_not_counted(tmp_path):
    t = [x for x in W.targets(_map(True)) if x.ckey == "k:Wiki monitor"][0]
    entry = W.judge(None, t, ("healthy", 1, {}), 1000)
    entry = W.judge(entry, t, ("down", 1, {}), 1060)            # retries 1: not believed yet
    assert entry["state"] == "healthy" and entry["said"] == "down"
    body = {"v": 2, "at": 1060, "checks": {"k:Wiki monitor": entry}}
    (tmp_path / "checks.json").write_text(json.dumps(body), encoding="utf-8")
    feed = {"services": {"Wiki monitor": {"state": "down"}}, "nodes": {}, "confirmed_by": {}}
    assert _observe(tmp_path, feed) == 0
    entry = W.judge(entry, t, ("down", 1, {}), 1080)            # now believed
    (tmp_path / "checks.json").write_text(json.dumps({**body, "checks": {"k:Wiki monitor": entry}}), encoding="utf-8")
    assert _observe(tmp_path, feed) == 1
    s = shadow.summary(_map(True), path=str(tmp_path / "shadow.json"))
    assert (s["agree"], s["differ"]) == (1, 0)


def test_a_link_whose_monitor_kuma_folds_into_a_place_is_not_shadowed():
    data = _map(True)
    data["signals"]["kuma"]["Wiki monitor"] = "app"
    assert "k:Wiki monitor" not in [t.ckey for t in W.targets(data)]


def test_a_hand_edited_record_never_stops_the_counting(tmp_path):
    (tmp_path / "shadow.json").write_text(json.dumps({"since": 1e30, "things": {
        "k:Wiki monitor": {"agree": "x", "differ": -3, "last": 5, "counted": "soon"},
        "kp:gate": "nonsense"}}), encoding="utf-8")
    _heard(tmp_path, {"k:Wiki monitor": "healthy", "kp:gate": "down"})
    assert _observe(tmp_path, KUMA) == 2
    s = shadow.summary(_map(True), path=str(tmp_path / "shadow.json"))
    assert (s["agree"], s["differ"]) == (2, 0) and s["since"] == 2000
    assert all(isinstance(x["last"], list) for x in s["things"])


def test_shadow_goes_after_what_the_map_shows_in_a_round(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(W, "probe", lambda t: order.append(t.ckey) or ("healthy", 1, {}))
    monkeypatch.setattr(W, "WORKERS", 1)
    W.tick(_map(True), str(tmp_path / "checks.json"), now=1000)
    assert order == ["s:app/Files", "k:Wiki monitor", "kp:gate"]


def test_the_comparison_says_when_nothing_is_being_asked(tmp_path, monkeypatch):
    import integrations
    monkeypatch.setattr(integrations, "enabled_sources", lambda: ["kuma"])
    assert shadow.summary(_map(True), path=str(tmp_path / "shadow.json"))["asking"] is False
