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
        collections=[{"id": "storage", "name": "Storage", "places": ["beta"]}],
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


def test_a_collection_rule_fires_for_its_members(realm):
    alertkit.store([rule("r-col", "collection", "storage")])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].sent == []
    realm["tick"].step(_with(realm["ok"], alpha="down", beta="down"), T0 + 60)
    assert realm["sent"].titles == ["Beta is down"]


def test_a_rule_saved_when_collections_were_sets_still_fires_and_reads_as_today(realm):
    """A rule stored before 2026-11-14 says `set`: it matches as a collection,
    and it reads back (and is saved back) under today's name."""
    import json as _json
    import alerts
    import settings
    # written as an older Atlas wrote it: straight to the file, kind `set`
    with open(settings.ALERTS_PATH, "w", encoding="utf-8") as fh:
        _json.dump({"rules": [rule("r-old", "set", "storage")], "digest": {},
                    "destinations": [alertkit.DEST]}, fh)
    with open(settings.ALERTS_PATH, encoding="utf-8") as fh:
        assert '"set"' in fh.read()
    doc, _ = alerts.read()
    assert doc["rules"][0]["target"] == {"kind": "collection", "id": "storage"}
    assert alerts.normalize({"rules": [rule("r-old", "set", "storage")]})["rules"][0]["target"]["kind"] == "collection"
    realm["tick"].step(_with(realm["ok"], alpha="down", beta="down"), T0)
    assert realm["sent"].titles == ["Beta is down"]


def test_a_target_kind_that_is_not_text_is_named_not_a_crash(realm):
    """A list where the kind belongs (a hand edit, a bad POST): the store
    still loads, `normalize` does not raise, and `validate` says what is
    wrong (the 2026-11-14 review's second finding)."""
    import json as _json
    import alerts
    import settings
    with open(settings.ALERTS_PATH, "w", encoding="utf-8") as fh:
        _json.dump({"rules": [rule("r-odd", [], "x")], "digest": {}, "destinations": [alertkit.DEST]}, fh)
    doc, _ = alerts.read()
    assert doc["rules"][0]["target"]["kind"] == []
    normal = alerts.normalize(doc)
    problems = alerts.validate(normal, realm_data())
    assert any("its target must be a place, a collection, a network or a service" in p for p in problems)


def test_a_saved_rule_whose_collection_is_gone_does_not_block_other_saves(realm):
    """Removing a collection from the rail leaves its rules suspended; saving
    anything else in ALERTS must still work, while a NEW rule on a missing
    target is still refused (the review's sixth finding)."""
    import alerts
    alertkit.store([rule("r-col", "collection", "storage")])
    data = realm_data()
    data["collections"] = []
    doc = alerts.normalize(alerts.read()[0])
    doc["rules"][0]["name"] = "renamed, target unchanged"
    assert alerts.validate(doc, data) == []
    assert alerts.suspended(doc, data) == ["r-col"]
    doc["rules"].append(rule("r-new", "collection", "storage"))
    assert any("cannot be alerted on" in p for p in alerts.validate(doc, data))
    doc["rules"].pop()
    doc["rules"][0]["target"] = {"kind": "collection", "id": "gone-too"}
    assert any("cannot be alerted on" in p for p in alerts.validate(doc, data))


def test_a_target_id_that_is_not_text_matches_nothing_and_the_tick_goes_on(realm):
    """A hand edit's list where the target's id belongs must not stop every
    other rule (round 2 of the 2026-11-14 review)."""
    alertkit.store([rule("r-odd", "collection", ["storage"]), rule("r-alpha", "place", "alpha")])
    realm["tick"].step(_with(realm["ok"], alpha="down", beta="down"), T0)
    assert realm["sent"].titles == ["Alpha is down"]


@pytest.mark.parametrize("broken", [{"target": "storage"}, {"target": ["storage"]}, {"to": 5},
                                    {"for_minutes": "ten"}, {"target": None}])
def test_a_rule_broken_by_hand_skips_itself_and_never_the_tick(realm, broken):
    """One hand-edited rule must not stop every alert: the tick would replay
    the same event and fail again for good (round 3 of the 2026-11-14 review)."""
    import json as _json
    import settings
    with open(settings.ALERTS_PATH, "w", encoding="utf-8") as fh:
        _json.dump({"rules": [{**rule("r-broken", "place", "beta"), **broken}, rule("r-alpha", "place", "alpha"),
                              rule("r-edge", "place", "edge")],
                    "digest": {}, "destinations": [alertkit.DEST]}, fh)
    realm["tick"].step(_with(realm["ok"], alpha="down", beta="down"), T0)
    assert realm["sent"].titles == ["Alpha is down"]
    # the next tick still runs and still sends
    realm["tick"].step(_with(realm["ok"], alpha="down", beta="down", edge="down"), T0 + 60)
    assert realm["sent"].titles == ["Alpha is down", "Edge is down"]


def test_a_list_as_a_rule_id_on_a_hidden_target_is_named_not_a_crash(realm):
    import alerts
    doc = {"rules": [{**rule("r-a", "collection", "no-such"), "id": ["x"]}],
           "digest": dict(alerts.DIGEST_DEFAULTS), "destinations": [dict(alertkit.DEST)]}
    problems = alerts.validate(alerts.normalize(doc), realm_data())
    assert any("its id must be" in p for p in problems)
    assert any("cannot be alerted on" in p for p in problems)


def test_a_waiting_timer_does_not_send_once_its_rule_no_longer_wants_that_state(realm):
    """"down for 5 minutes", then the rule is changed to degraded only while
    the place stays down: nothing is sent (round 4)."""
    import alerts
    alertkit.store([rule("r-a", "place", "alpha", minutes=5)])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    doc, _ = alerts.read()
    doc["rules"][0]["to"] = ["degraded"]
    alerts.save(doc)
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0 + 6 * 60)
    assert realm["sent"].sent == []


def test_a_broken_timer_or_digest_hour_in_the_state_never_stops_the_tick(realm):
    """A hand edit to the state file or the digest: dropped or skipped, and
    the tick still sends (round 4)."""
    import json as _json
    import alerts
    import settings
    alertkit.store([rule("r-a", "place", "alpha")],
                   digest={"enabled": True, "hour": 0, "destination": "pager"})
    with open(settings.ALERTS_PATH, encoding="utf-8") as fh:
        doc = _json.load(fh)
    doc["digest"]["hour"] = "seven"
    with open(settings.ALERTS_PATH, "w", encoding="utf-8") as fh:
        _json.dump(doc, fh)
    with open(settings.ALERTS_STATE_PATH, encoding="utf-8") as fh:
        state = _json.load(fh)
    state["timers"] = [{"rule": ["r-a"], "target": "alpha", "event": 1, "due": 0},
                       {"rule": "r-a", "target": {"x": 1}, "event": 1, "due": 0},
                       {"rule": "r-a", "target": "alpha", "event": [1], "due": 0}]
    with open(settings.ALERTS_STATE_PATH, "w", encoding="utf-8") as fh:
        _json.dump(state, fh)
    assert alerts._STATE.load()["timers"] == []
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].titles == ["Alpha is down"]


def _set_state(**changes):
    import json as _json
    import settings
    with open(settings.ALERTS_STATE_PATH, encoding="utf-8") as fh:
        state = _json.load(fh)
    state.update(changes)
    with open(settings.ALERTS_STATE_PATH, "w", encoding="utf-8") as fh:
        _json.dump(state, fh)


def test_a_rule_that_fails_on_an_event_costs_only_that_rule(realm, monkeypatch):
    """One rule raising on an event must not take the event from the other
    rules (round 6: the guard was per event)."""
    import alerts
    alertkit.store([rule("r-bad", "place", "edge"), rule("r-e", "place", "edge")])
    real = alerts._matches

    def bad(rule_, place_id, places, collections):
        if rule_.get("id") == "r-bad":
            raise RuntimeError("this rule only")
        return real(rule_, place_id, places, collections)
    monkeypatch.setattr(alerts, "_matches", bad)
    realm["tick"].step(_with(realm["ok"], edge="down"), T0)
    assert realm["sent"].titles == ["Edge is down"]


def test_a_fold_whose_events_are_not_a_list_never_stops_the_tick(realm):
    alertkit.store([rule("r-a", "place", "alpha")])
    _set_state(folded={"pager": {"count": 1, "events": 5}})
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert "Alpha is down" in realm["sent"].titles


def test_an_annals_event_with_a_list_target_is_skipped_and_the_tick_goes_on(realm, monkeypatch):
    import events
    alertkit.store([rule("r-a", "place", "alpha")])
    real_since = events.since
    monkeypatch.setattr(events, "since", lambda seq: [{"id": 10 ** 6, "kind": "node", "target": ["alpha"],
                                                      "to": "down"}] + real_since(seq))
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].titles == ["Alpha is down"]


@pytest.mark.parametrize("node_edit", [{"depends_on": 5}, {"require_group": ["ops"]}, {"links": "oops"}])
def test_a_place_edited_by_hand_never_stops_the_tick(realm, monkeypatch, node_edit):
    """A visible place's `depends_on` that is a number, an access group that
    is a list, links that are text: the alerts still go (round 5)."""
    alertkit.store([rule("r-a", "place", "alpha")])
    handle = realm["handle"].app.extensions["atlas"]
    real = handle.dataset

    def edited():
        data, *rest = real()
        data = {**data, "nodes": [{**n, **node_edit} if n.get("id") == "beta" else n for n in data["nodes"]]}
        return (data, *rest)
    monkeypatch.setattr(handle, "dataset", edited)
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].titles == ["Alpha is down"]


def test_a_timer_whose_check_fails_is_kept_and_sent_once_the_fault_passes(realm, monkeypatch):
    """A fault while reading one timer skips it this tick, keeps it, and the
    other rules still send; the next tick sends it (round 6)."""
    import alerts
    alertkit.store([rule("r-a", "place", "alpha", minutes=5), rule("r-e", "place", "edge")])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    real = alerts._matches
    calls = {"n": 0}

    def flaky(rule_, place_id, places, collections):
        # alpha's state does not change in the second tick, so the first r-a /
        # alpha call is the due-timer check, not a new event
        if rule_.get("id") == "r-a" and place_id == "alpha" and calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("a passing fault")
        return real(rule_, place_id, places, collections)
    monkeypatch.setattr(alerts, "_matches", flaky)
    realm["tick"].step(_with(realm["ok"], alpha="down", edge="down"), T0 + 6 * 60)
    assert realm["sent"].titles == ["Edge is down"], "the other rule still sent"
    assert calls["n"] == 1
    realm["tick"].step(_with(realm["ok"], alpha="down", edge="down"), T0 + 7 * 60)
    assert realm["sent"].titles == ["Edge is down", "Alpha is down"], "the kept timer sent"


def test_one_fold_that_cannot_be_read_drops_only_itself(monkeypatch):
    """A bucket the sender cannot read goes with a log line; the other
    destination's overflow is still sent (round 6: the guard used to drop
    every bucket, against `fold`'s "never dropped")."""
    import alerts
    state = alerts._state_shape({})
    state["folded"] = {"pager": "not a bucket", "pager-2": {"count": 2, "events": [1]}}
    dests = {"pager": dict(alertkit.DEST), "pager-2": {**alertkit.DEST, "id": "pager-2", "name": "Pager 2"}}
    run = alerts._Run(state, dests, None, 0)
    sent = []
    sender = alerts._sender()
    monkeypatch.setattr(sender, "send", lambda dest, message: sent.append((dest["id"], message["title"]))
                        or {"outcome": "delivered"})
    run.send_folds()
    assert sent == [("pager-2", "Atlas: 2 more changes")]
    assert state["folded"] == {}


def test_a_message_listing_two_visible_names_is_not_read_as_one_hidden_slug(realm):
    """"Went with it: Core, Switch" next to a hidden "Core Switch" is sent
    (round 6): the slug is read within one name, not across the list."""
    import alerts
    data = realm_data()
    data["nodes"].append(viewers.place("cs9", "Core Switch", require_group=viewers.GROUP))
    run = alerts._Run(alerts._state_shape({}), {}, alerts.hidden_pattern(data), 0,
                      alerts.hidden_slug_pattern(data))
    sent = []
    monkey_dest = {"id": "pager", "name": "Pager"}
    alerts_sender = alerts._sender()
    original = alerts_sender.send
    try:
        alerts_sender.send = lambda dest, message: sent.append(message) or {"outcome": "delivered"}
        out = run.deliver("r-a", monkey_dest, {"title": "Alpha is down",
                                               "body": "Went with it: Core, Switch\nat 2026-10-12 13:45 UTC"}, [1])
        assert out == "delivered" and sent
        blocked = run.deliver("r-a", monkey_dest, {"title": "Alpha is down", "body": "mirror of core-switch"}, [2])
        assert blocked == "blocked"
    finally:
        alerts_sender.send = original


def test_on_means_true_in_the_tick_and_in_suspended(realm):
    import json as _json
    import alerts
    import settings
    with open(settings.ALERTS_PATH, "w", encoding="utf-8") as fh:
        _json.dump({"rules": [{**rule("r-a", "place", "alpha"), "enabled": "false"},
                              {**rule("r-gone", "place", "no-such"), "enabled": "false"}],
                    "digest": {}, "destinations": [alertkit.DEST]}, fh)
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].sent == []
    assert alerts.suspended(alerts.read()[0], realm_data()) == []
    # missing is on (what normalize has always said); a save writes booleans
    assert alerts.rule_on({}) and alerts.rule_on({"enabled": True})
    assert not any(alerts.rule_on({"enabled": v}) for v in (False, 1, "true", "false"))
    # an incoming value that is not a boolean is refused (round 7) ...
    incoming = alerts.normalize({"rules": [{**rule("r-x", "place", "alpha"), "enabled": "yes"}],
                                 "destinations": [dict(alertkit.DEST)], "digest": dict(alerts.DIGEST_DEFAULTS)})
    assert any("enabled must be true or false" in p for p in alerts.validate(incoming, realm_data()))
    # ... but the stored, unchanged one does not block a save of something else
    stored = alerts.normalize(alerts.read()[0])
    stored["rules"][0]["name"] = "renamed"
    assert not any("enabled" in p for p in alerts.validate(stored, realm_data()))
    # a stored boolean changed to 1 or 0 by a client is refused (1 == True in Python)
    import json as _json
    import settings
    with open(settings.ALERTS_PATH, "w", encoding="utf-8") as fh:
        _json.dump({"rules": [rule("r-b", "place", "alpha")], "digest": {},
                    "destinations": [alertkit.DEST]}, fh)
    for sneaky in (1, 1.0):
        doc = alerts.normalize(alerts.read()[0])
        doc["rules"][0]["enabled"] = sneaky
        assert any("enabled must be true or false" in p for p in alerts.validate(doc, realm_data())), sneaky


@pytest.mark.parametrize("hidden_name,ip,body,blocked", [
    ("Vault Box", "", "What it is for: mirror of vault-box", True),
    ("Rack (A)", "", "What it is for: Rack(A) is the spare", True),
    ("Core Switch", "", "Went with it: Core, Switch", False),
    ("Box", "10.12.13.45", "Since 2026-10-12 13:45 UTC", False),
    ("東京 Alpha", "", "Alpha is down", False),
    ("NAS (Backup)", "", "What it is for: NAS Backup copy", True),
    ("客厅NAS", "", "书房NAS is down", False),
])
def test_the_send_check_reads_slugs_by_the_same_rules(hidden_name, ip, body, blocked):
    """The last check before a send uses the redaction's own slug rules, with
    the patterns the tick builds (rounds 5 to 7)."""
    import alerts
    data = realm_data()
    data["nodes"].append(viewers.place("h1", hidden_name, ip=ip or None, require_group=viewers.GROUP))
    run = alerts._Run(alerts._state_shape({}), {}, alerts.hidden_pattern(data), 0,
                      alerts.hidden_slug_pattern(data))
    sender = alerts._sender()
    original = sender.send
    try:
        sender.send = lambda dest, message: {"outcome": "delivered"}
        out = run.deliver("r-a", {"id": "pager", "name": "Pager"}, {"title": "Alpha is down", "body": body}, [1])
    finally:
        sender.send = original
    assert (out == "blocked") is blocked, (hidden_name, body, out)


def test_a_timer_that_keeps_failing_is_dropped_after_three_polls(realm, monkeypatch):
    import alerts
    alertkit.store([rule("r-a", "place", "alpha", minutes=5)])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    real = alerts._matches
    monkeypatch.setattr(alerts, "_matches", lambda r, p, pl, c: (_ for _ in ()).throw(RuntimeError("always"))
                        if r.get("id") == "r-a" and p == "alpha" else real(r, p, pl, c))
    for i in range(1, 4):
        realm["tick"].step(_with(realm["ok"], alpha="down"), T0 + (5 + i) * 60)
        timers = alerts._STATE.load()["timers"]
        if i < alerts.TIMER_FAULTS:
            assert [t.get("faults") for t in timers] == [i], f"kept after fault {i}"
        else:
            assert timers == [], "dropped on the third fault"
    assert alerts.TIMER_FAULTS == 3
    assert realm["sent"].sent == []


def test_a_timer_with_no_state_is_dropped_on_load(realm):
    """A hand edit's timer without a state (round 10): dropped at load."""
    import alerts
    alertkit.store([rule("r-a", "place", "alpha")])
    _set_state(timers=[{"rule": "r-a", "target": "alpha", "event": 1, "due": 0}])
    assert alerts._STATE.load()["timers"] == []


def test_a_rule_with_a_state_that_is_not_text_is_skipped_by_the_tick(realm):
    """`to: [null, "down"]` on Edge: the tick skips the rule (it would start
    a timer, and a timer the tick cannot finish), the others still send
    (round 10; round 11 found the old test never reached it)."""
    import json as _json
    import settings
    with open(settings.ALERTS_PATH, "w", encoding="utf-8") as fh:
        _json.dump({"rules": [{**rule("r-n", "place", "edge"), "to": [None, "down"]},
                              rule("r-a", "place", "alpha")],
                    "digest": {}, "destinations": [alertkit.DEST]}, fh)
    realm["tick"].step(_with(realm["ok"], alpha="down", edge="down"), T0)
    assert realm["sent"].titles == ["Alpha is down"]


def test_a_collections_section_that_is_not_a_list_never_stops_the_tick(realm, monkeypatch):
    """Nothing hidden, so the redaction leaves `"collections": 5` as it is:
    the tick must not iterate it (round 11)."""
    import alerts
    alertkit.store([rule("r-a", "place", "alpha")])
    handle = realm["handle"].app.extensions["atlas"]
    real = handle.dataset
    for i, odd in enumerate((5, True, 2.5, {"id": "x"})):
        monkeypatch.setattr(handle, "dataset", lambda odd=odd: ({**real()[0], "collections": odd}, *real()[1:]))
        assert alerts.suspended(alerts.read()[0], {**realm_data(), "collections": odd}) == []
        # a tick with each shape (round 12: it ran once, after the loop)
        realm["tick"].step(_with(realm["ok"], alpha="down" if i % 2 == 0 else "healthy"), T0 + 60 * i)
    assert realm["sent"].titles == ["Alpha is down", "Alpha is down"]


def test_a_timer_with_no_event_id_is_dropped_on_load(realm):
    """Step 4 reads a due timer's event: a hand edit without one would raise
    on every poll (round 9)."""
    import alerts
    alertkit.store([rule("r-a", "place", "alpha")])
    _set_state(timers=[{"rule": "r-a", "target": "alpha", "state": "down", "due": 0}])
    assert alerts._STATE.load()["timers"] == []
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].titles == ["Alpha is down"]


def test_a_stored_number_sent_back_as_the_same_number_passes(realm):
    import json as _json
    import alerts
    import settings
    with open(settings.ALERTS_PATH, "w", encoding="utf-8") as fh:
        _json.dump({"rules": [{**rule("r-n", "place", "alpha"), "enabled": 1.0}], "digest": {},
                    "destinations": [alertkit.DEST]}, fh)
    doc = alerts.normalize(alerts.read()[0])
    doc["rules"][0]["enabled"] = 1
    assert not any("enabled" in p for p in alerts.validate(doc, realm_data()))


def test_a_collection_whose_places_is_one_id_still_matches(realm):
    """A hand edit's `"places": "beta"`: the rail counts it, the rule fires."""
    import alerts
    data = realm_data()
    data["collections"][0]["places"] = "beta"
    places, collections, _ = alerts._visible_targets(data)
    assert alerts._matches(rule("r-c", "collection", "storage"), "beta", places, collections)


def test_the_atlas_own_address_never_blocks_an_alert(monkeypatch):
    import re
    import alerts
    import settings
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://atlas.example/")
    run = alerts._Run(alerts._state_shape({}), {}, re.compile(r"(?<![^\W_])atlas(?![^\W_])", re.I), 0)
    sender = alerts._sender()
    monkeypatch.setattr(sender, "send", lambda dest, message: {"outcome": "delivered"})
    out = run.deliver("r-a", {"id": "pager", "name": "Pager"},
                      {"title": "Alpha is down", "body": "Alpha", "ops": "https://atlas.example/?place=alpha"}, [1])
    assert out == "delivered"


def test_an_alerts_sequence_ahead_of_the_annals_catches_up(realm):
    """events.json restored or removed on its own leaves the alerts' sequence
    ahead: nothing would ever be new again (round 14)."""
    import alerts
    alertkit.store([rule("r-a", "place", "alpha")])
    _set_state(seq=10000)
    realm["tick"].step(_with(realm["ok"], alpha="healthy"), T0)
    assert alerts._STATE.load()["seq"] < 10000
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0 + 60)
    assert realm["sent"].titles == ["Alpha is down"]


def test_an_annals_file_that_cannot_be_read_resets_nothing(realm):
    """Round 15: a failed read says 0, and round 14's catch-up reset the
    alerts to it, so the next tick replayed the whole history. Only a file
    that is really gone, or really read, may move the sequence back."""
    import alerts
    import settings
    alertkit.store([rule("r-a", "place", "alpha")])
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0)
    assert realm["sent"].titles == ["Alpha is down"]
    before = alerts._STATE.load()["seq"]
    with open(settings.EVENTS_PATH, encoding="utf-8") as fh:
        good = fh.read()
    with open(settings.EVENTS_PATH, "w", encoding="utf-8") as fh:
        fh.write("{ not json")
    # the tick alone, as when the read fails between the annals' record and
    # the alerts' turn (the record would rewrite the file)
    with realm["handle"].app.app_context():
        data = alertkit.dataset(realm["handle"])
        alerts.tick(alertkit.feed_for(data, _with(realm["ok"], alpha="down"), ()), data, now=T0 + 60)
    assert alerts._STATE.load()["seq"] == before, "a failed read reset the sequence"
    with open(settings.EVENTS_PATH, "w", encoding="utf-8") as fh:
        fh.write(good)
    realm["tick"].step(_with(realm["ok"], alpha="down"), T0 + 120)
    assert realm["sent"].titles == ["Alpha is down"], "nothing was sent twice"


def test_a_fold_count_must_be_a_whole_number_above_zero():
    import alerts
    shaped = alerts._state_shape({"folded": {"a": {"count": True, "events": []}, "b": {"count": 0, "events": []},
                                             "c": {"count": 2, "events": [1, True]}}})
    assert shaped["folded"] == {"c": {"count": 2, "events": [1]}}


def test_a_message_naming_a_hidden_place_as_a_slug_is_not_sent():
    """The last check before a send reads slugs too: "mirror of vault-box"
    names a hidden "Vault Box" (round 5). The pattern is the one the tick
    builds (`hidden_slug_pattern`), not one written for the test."""
    import alerts
    data = realm_data()
    data["nodes"].append(viewers.place("nas01", "Vault Box", require_group=viewers.GROUP))
    run = alerts._Run(alerts._state_shape({}), {}, alerts.hidden_pattern(data), 0,
                      alerts.hidden_slug_pattern(data))
    out = run.deliver("r-a", {"id": "pager", "name": "Pager"},
                      {"title": "Alpha is down", "body": "Alpha: mirror of vault-box"}, [1])
    assert out == "blocked" and run.logs[0]["why"] == "would name a hidden place"


def test_a_state_that_is_not_text_is_named_not_a_crash(realm):
    import alerts
    doc = {"rules": [{**rule("r-a", "place", "alpha"), "to": [["down"]]}],
           "digest": dict(alerts.DIGEST_DEFAULTS), "destinations": [dict(alertkit.DEST)]}
    problems = alerts.validate(alerts.normalize(doc), realm_data())
    assert any("it needs one or more states" in p for p in problems)


def test_ids_that_are_not_text_are_named_not_a_crash(realm):
    import alerts
    doc = {"rules": [{**rule("r-a", "place", "alpha"), "id": ["x"], "destination": ["pager"]}],
           "digest": {"enabled": True, "hour": 7, "destination": ["pager"], "cert_days": 30,
                      "review_days": 90, "drift": False, "uncharted": False},
           "destinations": [{**alertkit.DEST, "id": ["pager"]}]}
    problems = alerts.validate(alerts.normalize(doc), realm_data())
    assert any("its id must be" in p for p in problems)
    assert any("destination that does not exist" in p for p in problems)
    assert any(p.startswith("digest: it sends to a destination") for p in problems)


def test_a_waiting_timer_does_not_send_once_its_collection_no_longer_holds_the_place(realm, monkeypatch):
    """"Stays for five minutes", and in the meantime the place left the
    collection (or the collection was removed): nothing is sent."""
    import alerts
    alertkit.store([rule("r-col", "collection", "storage", minutes=5)])
    realm["tick"].step(_with(realm["ok"], beta="down"), T0)
    assert realm["sent"].sent == []
    emptied = realm_data()
    emptied["collections"][0]["places"] = []
    realm_now = realm["handle"].app.extensions["atlas"]
    real_dataset = realm_now.dataset
    monkeypatch.setattr(realm_now, "dataset", lambda: (emptied, *real_dataset()[1:]))
    realm["tick"].step(_with(realm["ok"], beta="down"), T0 + 6 * 60)
    assert realm["sent"].sent == []


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


def test_the_digest_names_what_was_left_in_maintenance_mode(tmp_path, monkeypatch):
    """Maintenance mode has no end (2026-11-14, the owner's Q4); its guard is
    the digest, naming what has been in it more than a week, by the places
    and collections it covers (never its free-text reason)."""
    data = realm_data()
    data["nodes"].append(viewers.place("vault", "Vault", require_group=viewers.GROUP))
    windows = [
        {"id": "old", "reason": "vault work", "open": True, "starts": "2027-01-01T00:00:00Z",
         "nodes": ["alpha", "vault"]},
        {"id": "old-col", "reason": "x", "open": True, "starts": "2027-01-02T00:00:00Z",
         "collections": ["storage"]},
        {"id": "recent", "reason": "x", "open": True, "starts": "2027-01-14T00:00:00Z", "nodes": ["gate"]},
        {"id": "sched", "reason": "x", "starts": "2026-01-01T00:00:00Z", "ends": "2099-01-01T00:00:00Z",
         "nodes": ["db"]},
    ]
    handle = alertkit.build(tmp_path, monkeypatch, data, windows=windows)
    sent = alertkit.capture(monkeypatch)
    alertkit.store([], digest={"enabled": True, "hour": 0, "destination": "pager"})
    alertkit.Ticker(handle).step({"alpha": "healthy"}, T0)
    body = sent.sent[0][1]["body"]
    assert ("In maintenance mode more than 7 days: Alpha (since 2027-01-01), "
            "the collection Storage (since 2027-01-02)") in body
    for never in ("Frontgate", "Ledger", "Vault", "vault work", "Beta"):
        assert never not in body, never


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
