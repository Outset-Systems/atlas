"""ALERTS' rules and tick (2026-11-13): what matches, when it fires, when it
stays quiet.

Each test drives the annals and the tick by hand (`alertkit.Ticker`), the way
the annalist does after a feed build, with the sender captured. `now` is
handed in, so "stays for 5 minutes" is tested without waiting.
"""

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alertkit  # noqa: E402
import viewers  # noqa: E402
from alertkit import rule  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file"}

T0 = 1_800_000_000.0          # a fixed instant; the tick takes `now` from the test

DMZ = {**viewers._ZONE, "id": "dmz", "name": "DMZ", "vlan": 20, "subnet": "198.51.100.0/24"}


def realm_data():
    p = viewers.place
    return viewers.dataset(
        zones=[viewers._ZONE, DMZ],
        nodes=[p("gate", "Frontgate", role="the way in"),
               p("app", "App", depends_on=["gate"]),
               p("db", "Ledger", depends_on=["gate"]),
               p("alpha", "Alpha"),
               p("beta", "Beta"),
               p("edge", "Edge", zone="dmz")],
        sets=[{"id": "storage", "name": "Storage", "places": ["beta"]}],
    )


@pytest.fixture
def realm(tmp_path, monkeypatch):
    handle = alertkit.build(tmp_path, monkeypatch, realm_data())
    sent = alertkit.capture(monkeypatch)
    ticker = alertkit.Ticker(handle)
    healthy = {i: "healthy" for i in ("gate", "app", "db", "alpha", "beta", "edge")}
    ticker.step(healthy, T0 - 600)            # seeds the annals and the tick
    return {"handle": handle, "sent": sent, "tick": ticker, "ok": healthy, "tmp": tmp_path}


def _with(base, **states):
    return {**base, **states}


# ── matching ─────────────────────────────────────────────────────────────────
def test_a_place_rule_fires_for_that_place_only(realm):
    alertkit.store([rule("r-alpha", "place", "alpha")])
    realm["tick"].step(_with(realm["ok"], beta="down"), T0)
    assert realm["sent"].sent == []
    realm["tick"].step(_with(realm["ok"], alpha="down", beta="down"), T0 + 60)
    assert realm["sent"].titles == ["Alpha is down"]
    message = realm["sent"].sent[0][1]
    assert message["priority"] == "high" and message["tags"] == ["down"]
    assert message["link"] == alertkit.PUBLIC + "?place=alpha"
    assert "Nothing is declared to depend on it." in message["body"]


def test_a_set_rule_fires_for_its_members(realm):
    alertkit.store([rule("r-set", "set", "storage")])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].sent == []
    realm["tick"].step(_with(realm["ok"], alpha="down", beta="down"), T0 + 60)
    assert realm["sent"].titles == ["Beta is down"]


def test_a_network_rule_fires_for_the_places_in_it(realm):
    alertkit.store([rule("r-dmz", "network", "dmz")])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    realm["tick"].step(_with(realm["ok"], alpha="down", edge="down"), T0 + 60)
    assert realm["sent"].titles == ["Edge is down"]


def test_a_rule_reads_only_the_states_it_names(realm):
    alertkit.store([rule("r-alpha", "place", "alpha", to=("degraded",))])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].sent == []
    realm["tick"].step(_with(realm["ok"], alpha="degraded"), T0 + 60)
    assert realm["sent"].titles == ["Alpha is degraded"]
    assert realm["sent"].sent[0][1]["priority"] == "default"


def test_a_switched_off_rule_sends_nothing(realm):
    alertkit.store([rule("r-alpha", "place", "alpha", enabled=False)])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].sent == []


# ── "stays for" ──────────────────────────────────────────────────────────────
def test_stays_for_fires_once_the_time_has_passed(realm):
    alertkit.store([rule("r-alpha", "place", "alpha", minutes=5)])
    down = _with(realm["ok"], alpha="down")
    realm["tick"].step(down, T0)
    realm["tick"].step(down, T0 + 120)
    assert realm["sent"].sent == []
    realm["tick"].step(down, T0 + 301)
    assert realm["sent"].titles == ["Alpha is down"]
    realm["tick"].step(down, T0 + 600)                   # once, not every poll after
    assert len(realm["sent"].sent) == 1


def test_stays_for_cancels_when_the_place_recovers(realm):
    alertkit.store([rule("r-alpha", "place", "alpha", minutes=5)])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    realm["tick"].step(realm["ok"], T0 + 60)
    realm["tick"].step(realm["ok"], T0 + 400)
    assert realm["sent"].sent == []
    import alerts
    assert alerts._STATE.load()["timers"] == []


def test_two_workers_with_one_feed_send_once(realm):
    """Both workers poll and tick; the lock and the stored sequence make the
    second a no-op, in turn and at the same moment."""
    import alerts
    alertkit.store([rule("r-alpha", "place", "alpha")])
    data = alertkit.dataset(realm["handle"])
    feed = alertkit.feed_for(data, _with(realm["ok"], alpha="down"))
    import events
    with realm["handle"].app.app_context():
        events.record(feed)
        alerts.tick(feed, data, now=T0)
        alerts.tick(feed, data, now=T0)               # the second worker, later
    assert len(realm["sent"].sent) == 1

    # and at once: two threads, one barrier
    feed2 = alertkit.feed_for(data, _with(realm["ok"], alpha="healthy", beta="down"))
    alertkit.store([rule("r-beta", "place", "beta")])
    with realm["handle"].app.app_context():
        events.record(feed2)
    gate = threading.Barrier(2)

    def worker():
        with realm["handle"].app.app_context():
            gate.wait()
            alerts.tick(feed2, data, now=T0 + 60)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert realm["sent"].titles == ["Alpha is down", "Beta is down"]


# ── silence ──────────────────────────────────────────────────────────────────
def test_nothing_fires_inside_a_maintenance_window(realm):
    alertkit.store([rule("r-alpha", "place", "alpha", to=("down", "maintenance")),
                    rule("r-app", "place", "app")])
    realm["tick"].step(realm["ok"], T0, under=("alpha",))
    assert realm["sent"].sent == []
    # a place down behind one under repair is fallout from planned work
    realm["tick"].step(_with(realm["ok"], app="down"), T0 + 60, under=("alpha", "gate"))
    assert realm["sent"].sent == []


def test_an_acknowledged_event_sends_nothing_more(realm):
    import events
    alertkit.store([rule("r-alpha", "place", "alpha", minutes=5)])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    row = next(e for e in events.load()["events"] if e["target"] == "alpha")
    events.acknowledge(row["id"], "ops", "known, the disk is being swapped")
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0 + 400)
    assert realm["sent"].sent == []


# ── a cascade ────────────────────────────────────────────────────────────────
def test_a_cascade_is_one_message_naming_what_went_with_it(realm, tmp_path):
    import events
    alertkit.store([rule("r-core", "network", "core")])
    realm["tick"].step(_with(realm["ok"], gate="down", app="down", db="down"), T0)
    assert realm["sent"].titles == ["Frontgate is down"]
    body = realm["sent"].sent[0][1]["body"]
    assert "What it is for: the way in" in body
    assert "Went with it: App, Ledger" in body
    assert "Depends on it: App, Ledger" in body
    # the message's events are noted on the annals, for the ANNALS to show
    noted = [e for e in events.load()["events"] if e.get("sent")]
    assert {e["target"] for e in noted} == {"gate", "app", "db"}
    assert all(e["sent"][0]["to"] == "Pager" for e in noted)
    line = alertkit.log_lines(tmp_path)[-1]
    assert line["rule"] == "r-core" and line["outcome"] == "delivered" and len(line["events"]) == 3


def test_a_consequence_that_outlives_its_cause_is_sent_on_its_own(realm):
    alertkit.store([rule("r-core", "network", "core")])
    realm["tick"].step(_with(realm["ok"], gate="down", app="down"), T0)
    assert realm["sent"].titles == ["Frontgate is down"]
    realm["tick"].step(_with(realm["ok"], app="down"), T0 + 60)
    assert realm["sent"].titles == ["Frontgate is down", "App is down"]
    assert "still down on its own" in realm["sent"].sent[1][1]["body"]


def test_a_consequence_whose_root_no_rule_matches_names_it_as_behind(realm):
    alertkit.store([rule("r-app", "place", "app")])
    realm["tick"].step(_with(realm["ok"], gate="down", app="down"), T0)
    assert realm["sent"].titles == ["App is down"]
    assert "Behind: Frontgate" in realm["sent"].sent[0][1]["body"]


def test_a_root_that_fell_a_poll_earlier_is_one_message_when_its_dependents_follow(realm):
    alertkit.store([rule("r-core", "network", "core")])
    realm["tick"].step(_with(realm["ok"], gate="down"), T0)
    assert realm["sent"].titles == ["Frontgate is down"]
    realm["tick"].step(_with(realm["ok"], gate="down", app="down", db="down"), T0 + 60)
    assert realm["sent"].titles == ["Frontgate is down", "Frontgate is down"]
    assert "Went with it: App, Ledger" in realm["sent"].sent[1][1]["body"]
    realm["tick"].step(_with(realm["ok"], gate="down", app="down", db="down"), T0 + 120)
    assert len(realm["sent"].sent) == 2                  # and nothing more after


def test_a_root_whose_send_failed_is_sent_with_its_dependents(realm, monkeypatch):
    failing = alertkit.capture(monkeypatch, outcome="unreachable")
    alertkit.store([rule("r-core", "network", "core")])
    realm["tick"].step(_with(realm["ok"], gate="down"), T0)
    assert failing.titles == ["Frontgate is down"]
    realm["tick"].step(_with(realm["ok"], gate="down", app="down"), T0 + 60)
    assert failing.titles == ["Frontgate is down", "Frontgate is down"]


def test_dependents_wait_for_their_roots_stays_for(realm):
    alertkit.store([rule("r-gate", "place", "gate", minutes=5),
                    rule("r-app", "place", "app")])
    realm["tick"].step(_with(realm["ok"], gate="down"), T0)
    realm["tick"].step(_with(realm["ok"], gate="down", app="down"), T0 + 60)
    assert realm["sent"].sent == []
    realm["tick"].step(_with(realm["ok"], gate="down", app="down"), T0 + 301)
    assert realm["sent"].titles == ["Frontgate is down"]
    assert "Went with it: App" in realm["sent"].sent[0][1]["body"]


def test_an_acknowledged_root_takes_its_dependents_quietly(realm):
    import events
    alertkit.store([rule("r-core", "network", "core")])
    realm["tick"].step(_with(realm["ok"], gate="down"), T0)
    row = next(e for e in events.load()["events"] if e["target"] == "gate")
    events.acknowledge(row["id"], "ops", "on it")
    realm["tick"].step(_with(realm["ok"], gate="down", app="down"), T0 + 60)
    assert realm["sent"].titles == ["Frontgate is down"]


def test_where_a_send_went_never_reaches_a_viewer_or_a_token(realm):
    alertkit.store([rule("r-alpha", "place", "alpha")])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].titles == ["Alpha is down"]
    admin = viewers.signed_in(realm["handle"], "ops")
    assert admin.get("/api/v2/events").get_json()["events"][0]["sent"][0]["to"] == "Pager"
    token = viewers.issue(realm["handle"])
    viewer = viewers.signed_in(realm["handle"], "alice")
    anyone = realm["handle"].app.test_client()
    read = 0
    for path in ("/api/v2/events", "/api/v2/overview"):
        for client, headers in ((viewer, {}), (anyone, token)):
            r = client.get(path, headers=headers)
            if r.status_code != 200:
                continue
            read += 1
            text = r.get_data(as_text=True)
            assert '"sent"' not in text and "Pager" not in text, (path, text[:300])
    assert read == 4


def test_the_digest_names_places_nobody_has_reviewed(tmp_path, monkeypatch):
    data = realm_data()
    old, recent = "2026-01-01T00:00:00Z", "2027-01-10T00:00:00Z"
    for node in data["nodes"]:
        if node["id"] == "alpha":
            node["provenance"] = {"charted_at": old, "reviewed": True, "reviewed_at": old}
        if node["id"] == "beta":
            node["provenance"] = {"charted_at": old, "reviewed": True, "reviewed_at": recent}
        if node["id"] == "edge":
            node["provenance"] = {"charted_at": old, "reviewed": False}
    handle = alertkit.build(tmp_path, monkeypatch, data)
    sent = alertkit.capture(monkeypatch)
    alertkit.store([], digest={"enabled": True, "hour": 0, "destination": "pager"})
    alertkit.Ticker(handle).step({"alpha": "healthy"}, T0)
    assert sent.titles == ["Atlas daily digest"]
    assert "Not reviewed in 90 days: Alpha, Edge" in sent.sent[0][1]["body"]


# ── the rate limit ───────────────────────────────────────────────────────────
@pytest.fixture
def farm(tmp_path, monkeypatch):
    p = viewers.place
    data = viewers.dataset(nodes=[p(f"p{i}", f"Place {i}") for i in range(1, 10)])
    handle = alertkit.build(tmp_path, monkeypatch, data)
    sent = alertkit.capture(monkeypatch)
    ticker = alertkit.Ticker(handle)
    ok = {f"p{i}": "healthy" for i in range(1, 10)}
    ticker.step(ok, T0 - 600)
    return {"sent": sent, "tick": ticker, "ok": ok, "tmp": tmp_path}


def test_over_the_limit_folds_into_one_message_at_the_next_tick(farm):
    alertkit.store([rule("r-all", "network", "core")])
    down = {k: "down" for k in farm["ok"]}
    farm["tick"].step(down, T0)
    assert len(farm["sent"].sent) == 6                  # six a minute to one destination
    farm["tick"].step(down, T0 + 61)
    assert len(farm["sent"].sent) == 7
    fold = farm["sent"].sent[-1][1]
    assert fold["title"] == "Atlas: 3 more changes"
    assert fold["body"] == "and 3 more changes, see Atlas"
    line = alertkit.log_lines(farm["tmp"])[-1]
    assert line["rule"] == "fold" and line["folded"] == 3 and line["outcome"] == "delivered"


def test_thirty_an_hour_across_every_destination(farm, monkeypatch):
    import alerts
    monkeypatch.setattr(alerts, "PER_DESTINATION_PER_MINUTE", 100)
    with farm["tick"].handle.app.app_context():
        state = alerts._STATE.load()
        state["all"] = [T0 - 100] * 29
        alerts._STATE.save(state)
    alertkit.store([rule("r-all", "network", "core")])
    farm["tick"].step({k: "down" for k in farm["ok"]}, T0)
    assert len(farm["sent"].sent) == 1


# ── the digest ───────────────────────────────────────────────────────────────
def test_the_digest_fires_once_a_day(tmp_path, monkeypatch):
    import datetime
    soon = (datetime.datetime.fromtimestamp(T0, datetime.timezone.utc)
            + datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    data = realm_data()
    data["certs"] = [{"name": "Front door", "place": "gate", "expires": soon},
                     {"name": "Far off", "place": "gate", "expires": "2099-01-01"}]
    handle = alertkit.build(tmp_path, monkeypatch, data)
    sent = alertkit.capture(monkeypatch)
    ticker = alertkit.Ticker(handle)
    alertkit.store([], digest={"enabled": True, "hour": 0, "destination": "pager",
                               "drift": True})
    ok = {"gate": "healthy"}
    drift = {"drift": {"count": 1, "uncharted": ["backup ping"]}}
    ticker.step(ok, T0, extra=drift)
    assert sent.titles == ["Atlas daily digest"]
    body = sent.sent[0][1]["body"]
    assert "Front door (Frontgate): lapses in 10 days" in body and "Far off" not in body
    assert "Monitors the map has not charted: backup ping" in body
    ticker.step(ok, T0 + 3600, extra=drift)
    assert len(sent.sent) == 1                          # once a day
    ticker.step(ok, T0 + 86400, extra=drift)
    assert len(sent.sent) == 2                          # and again the next


def test_the_digest_waits_for_its_hour(tmp_path, monkeypatch):
    handle = alertkit.build(tmp_path, monkeypatch, realm_data())
    sent = alertkit.capture(monkeypatch)
    local = time.localtime(T0)
    if local.tm_hour == 23:
        pytest.skip("the fixed instant is the last hour of the local day here")
    alertkit.store([], digest={"enabled": True, "hour": local.tm_hour + 1,
                               "destination": "pager", "drift": True})
    alertkit.Ticker(handle).step({"gate": "healthy"}, T0,
                                 extra={"drift": {"count": 1, "uncharted": ["x"]}})
    assert sent.sent == []


# ── off ──────────────────────────────────────────────────────────────────────
def test_nothing_sends_while_alerts_are_off(tmp_path, monkeypatch):
    handle = alertkit.build(tmp_path, monkeypatch, realm_data(), on=False)
    sent = alertkit.capture(monkeypatch)
    alertkit.store([rule("r-alpha", "place", "alpha")])
    ticker = alertkit.Ticker(handle)
    assert ticker.step({"alpha": "healthy"}, T0) == {"skipped": "off"}
    ticker.step({"alpha": "down"}, T0 + 60)
    assert sent.sent == [] and not (tmp_path / "alerts-state.json").exists()


def test_the_first_tick_never_replays_the_annals(tmp_path, monkeypatch):
    handle = alertkit.build(tmp_path, monkeypatch, realm_data(), on=False)
    sent = alertkit.capture(monkeypatch)
    alertkit.store([rule("r-alpha", "place", "alpha")])
    ticker = alertkit.Ticker(handle)
    ticker.step({"alpha": "healthy"}, T0)
    ticker.step({"alpha": "down"}, T0 + 60)              # recorded while alerts were off
    alertkit.switch(tmp_path, monkeypatch, on=True)
    import settings
    import importlib
    importlib.reload(settings)
    ticker.step({"alpha": "down"}, T0 + 120)
    assert sent.sent == []


def test_the_annalist_ticks_after_its_build(tmp_path, monkeypatch):
    """The seam: `annalist.poll_once` builds the feed, then ticks."""
    import json
    signals = tmp_path / "signals.json"
    signals.write_text(json.dumps({"nodes": {"alpha": {"state": "healthy"}}}), encoding="utf-8")
    alertkit.build(tmp_path, monkeypatch, realm_data())
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", "static")
    monkeypatch.setenv("ATLAS_SIGNALS_FILE", str(signals))
    from appfixture import fresh_app
    handle = fresh_app()
    sent = alertkit.capture(monkeypatch)
    alertkit.store([rule("r-alpha", "place", "alpha")])
    import annalist
    assert annalist.poll_once(handle.app)                # seeds
    signals.write_text(json.dumps({"nodes": {"alpha": {"state": "down"}}}), encoding="utf-8")
    handle.app.extensions["atlas"].signals._cache = None
    assert annalist.poll_once(handle.app)
    assert sent.titles == ["Alpha is down"]
    # a browser's build never sends
    signals.write_text(json.dumps({"nodes": {"alpha": {"state": "healthy"}}}), encoding="utf-8")
    handle.app.extensions["atlas"].signals._cache = None
    alertkit.store([rule("r-alpha", "place", "alpha", to=("healthy",))])
    viewers.signed_in(handle, "ops").get("/api/v2/signals")
    assert sent.titles == ["Alpha is down"]


# ── a fault after a send never sends it again (2026-11-13) ───────────────────
def test_a_digest_that_raises_after_a_send_sends_nothing_twice(realm, monkeypatch):
    # the state was saved only when the whole tick finished: a digest that
    # raised after the rule's send left it unsaved, and every poll after sent
    # the same message again with no log line
    import alerts

    def broken(*a, **kw):
        raise RuntimeError("the digest broke")

    monkeypatch.setattr(alerts, "compose_digest", broken)
    alertkit.store([rule("r-alpha", "place", "alpha")],
                   digest={"enabled": True, "hour": 0, "destination": "pager"})
    down = _with(realm["ok"], alpha="down")
    for k in range(3):
        realm["tick"].step(down, T0 + 60 * (k + 1))
    assert realm["sent"].titles == ["Alpha is down"]
    lines = alertkit.log_lines(realm["tmp"])
    assert [(l["rule"], l["outcome"]) for l in lines] == [("r-alpha", "delivered"),
                                                         ("digest", "blocked")]
    assert lines[1]["why"] == "the digest could not be put together"


def test_a_message_that_cannot_be_put_together_is_logged_and_the_rest_go(realm, monkeypatch):
    import alerts
    real = alerts.compose

    def picky(subject, *a, **kw):
        if subject == "alpha":
            raise RuntimeError("no")
        return real(subject, *a, **kw)

    monkeypatch.setattr(alerts, "compose", picky)
    alertkit.store([rule("r-alpha", "place", "alpha"), rule("r-beta", "place", "beta")])
    down = _with(realm["ok"], alpha="down", beta="down")
    realm["tick"].step(down, T0)
    realm["tick"].step(down, T0 + 60)
    assert realm["sent"].titles == ["Beta is down"]
    lines = alertkit.log_lines(realm["tmp"])
    assert [(l["rule"], l["outcome"]) for l in lines] == [("r-alpha", "blocked"),
                                                         ("r-beta", "delivered")]


def test_a_tick_that_raises_still_keeps_what_it_sent(realm, monkeypatch):
    # a fault anywhere after a send: the state is saved on the way out and the
    # log line is written, so the next poll does not send it again
    import alerts
    calls = []

    def once_broken(*a, **kw):
        calls.append(1)
        raise RuntimeError("the digest broke")

    alertkit.store([rule("r-alpha", "place", "alpha")],
                   digest={"enabled": True, "hour": 0, "destination": "pager"})

    class Broken(alerts._Run):
        def failed(self, *a, **kw):
            raise KeyError("a fault after the send")

    monkeypatch.setattr(alerts, "_Run", Broken)
    monkeypatch.setattr(alerts, "compose_digest", once_broken)
    down = _with(realm["ok"], alpha="down")
    with pytest.raises(KeyError):
        realm["tick"].step(down, T0)
    for k in range(2):
        realm["tick"].step(down, T0 + 60 * (k + 1))
    assert realm["sent"].titles == ["Alpha is down"]
    assert [l["rule"] for l in alertkit.log_lines(realm["tmp"])] == ["r-alpha"]
    assert len(calls) == 1                             # the digest's day was kept too


def test_a_fault_before_the_sends_keeps_the_due_alert_for_the_next_tick(realm, monkeypatch):
    # the state is saved however a tick ends, so a timer taken out before a
    # fault would be an alert lost with no log line
    import dependencies
    real, calls = dependencies.declared_edges, []

    def once_broken(view):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the edges broke")
        return real(view)

    monkeypatch.setattr(dependencies, "declared_edges", once_broken)
    alertkit.store([rule("r-alpha", "place", "alpha")])
    down = _with(realm["ok"], alpha="down")
    with pytest.raises(RuntimeError):
        realm["tick"].step(down, T0)
    assert realm["sent"].sent == []
    realm["tick"].step(down, T0 + 60)
    assert realm["sent"].titles == ["Alpha is down"]
    realm["tick"].step(down, T0 + 120)
    assert realm["sent"].titles == ["Alpha is down"]
    assert [l["rule"] for l in alertkit.log_lines(realm["tmp"])] == ["r-alpha"]

def test_a_certificate_whose_place_is_a_list_does_not_stop_the_tick(tmp_path, monkeypatch):
    # written before validation refused it (2026-11-13): the digest raised on it
    import datetime
    soon = (datetime.datetime.fromtimestamp(T0, datetime.timezone.utc)
            + datetime.timedelta(days=5)).strftime("%Y-%m-%d")
    data = realm_data()
    data["certs"] = [{"name": "Listed", "place": ["alpha"], "expires": soon},
                     {"name": "Boxed", "place": {"id": "alpha"}, "expires": soon}]
    handle = alertkit.build(tmp_path, monkeypatch, data)
    sent = alertkit.capture(monkeypatch)
    ticker = alertkit.Ticker(handle)
    ok = {i: "healthy" for i in ("gate", "app", "db", "alpha", "beta", "edge")}
    ticker.step(ok, T0 - 600)
    alertkit.store([rule("r-alpha", "place", "alpha")],
                   digest={"enabled": True, "hour": 0, "destination": "pager"})
    ticker.step(_with(ok, alpha="down"), T0)
    ticker.step(_with(ok, alpha="down"), T0 + 60)
    assert sent.titles == ["Alpha is down", "Atlas daily digest"]
    body = sent.sent[1][1]["body"]
    assert "Boxed: lapses in 5 days" in body and "Listed: lapses in 5 days" in body
    assert [l["outcome"] for l in alertkit.log_lines(tmp_path)] == ["delivered", "delivered"]


# ── validate: limits first, the visible targets once (2026-11-13) ────────────
def test_over_a_count_limit_nothing_else_is_checked(realm, monkeypatch):
    import alerts
    real, calls = alerts._visible_targets, []
    monkeypatch.setattr(alerts, "_visible_targets", lambda view: calls.append(1) or real(view))
    with realm["handle"].app.app_context():
        data = alertkit.dataset(realm["handle"])
        many = alerts.normalize({
            "rules": [rule(f"r{i}", "place", "nowhere") for i in range(alerts.MAX_RULES + 1)],
            "destinations": [alertkit.DEST], "digest": {}})
        assert alerts.validate(many, data) == [f"at most {alerts.MAX_RULES} rules"]
        assert calls == []
        crowd = alerts.normalize({"rules": [], "digest": {}, "destinations": [
            {**alertkit.DEST, "id": f"d{i}"} for i in range(alerts.MAX_DESTINATIONS + 1)]})
        assert alerts.validate(crowd, data) == [
            f"at most {alerts.MAX_DESTINATIONS} destinations"]
        few = alerts.normalize({
            "rules": [rule(f"r{i}", "place", pid) for i, pid in
                      enumerate(("alpha", "beta", "gate", "app", "db"))],
            "destinations": [alertkit.DEST], "digest": {}})
        assert alerts.validate(few, data) == []
        assert len(calls) == 1                         # once per call, not per rule
        assert alerts.suspended(few, data) == []
        assert len(calls) == 2
