"""SERVICES AS WATCHED THINGS (2026-11-15, stage 3b).

A service is known by its key, the one the feed files it under: a Kuma
monitor's name, or `<place id>/<label>` for a built-in check. A collection
may hold services (`services`), a repair window may name them, and a link
may be unmanaged. A service on a hidden place, or behind its own group,
never reaches a reader without the group, by key or otherwise.
"""

import json

import viewers

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file"}


def _data(**more):
    data = viewers.dataset(**more)
    data["nodes"][0]["links"] = [{"label": "UI", "url": "https://a.example", "kuma": "Alpha UI"},
                                 {"label": "SSH", "url": "ssh://a.example"},
                                 {"label": "Logs", "url": "https://l.example", "unmanaged": True}]
    data["nodes"][2]["links"] = [{"label": "Vault", "url": "https://v.example"}]   # secret-place
    return data


def test_every_service_has_a_key_and_its_place():
    import signals
    keys = signals.service_places(_data())
    assert keys == {"Alpha UI": "alpha", "alpha/SSH": "alpha", "alpha/Logs": "alpha",
                    "secret-place/Vault": "secret-place"}


def test_which_services_are_unmanaged_on_their_own():
    import signals
    data = _data(collections=[{"id": "c", "name": "C", "services": ["alpha/SSH"], "unmanaged": True},
                              {"id": "d", "name": "D", "services": ["Alpha UI"]}])
    assert signals.unmanaged_service_keys(data) == {"alpha/Logs", "alpha/SSH"}


def test_a_window_covers_the_services_it_names_and_its_collections_services():
    import maintenance
    data = _data(collections=[{"id": "c", "name": "C", "services": ["Alpha UI", 5], "places": ["beta"]}])
    w = {"services": ["alpha/SSH", ""], "collections": ["c", "gone"]}
    assert maintenance.window_services(w, data) == {"alpha/SSH", "Alpha UI"}
    assert maintenance.window_places(w, data) == {"beta"}
    assert maintenance.window_services(w, None) == {"alpha/SSH"}
    assert maintenance.problems([{"id": "w", "reason": "r", "services": ["alpha/SSH"],
                                  "starts": "2026-01-01T00:00:00Z", "ends": "2026-01-02T00:00:00Z"}]) == []


def test_the_feed_puts_a_named_service_in_maintenance_and_leaves_its_place(tmp_path, monkeypatch):
    handle = viewers.build(tmp_path, monkeypatch, _data(), windows=[
        {"id": "w", "reason": "r", "services": ["alpha/SSH", "alpha/Logs"],
         "starts": "2020-01-01T00:00:00Z", "ends": "2099-01-01T00:00:00Z"}])
    feed = viewers.signed_in(handle, "ops").get("/api/v2/signals").get_json()
    assert feed["services"]["alpha/SSH"]["state"] == "maintenance"
    assert feed["maintenance_services"] == ["alpha/SSH"], "unmanaged beats maintenance"
    assert "alpha/Logs" not in feed["services"]
    assert "alpha" not in feed["maintenance"]
    monkeypatch.undo()


def test_a_reader_without_the_group_never_gets_a_hidden_places_service_key(tmp_path, monkeypatch):
    data = _data(collections=[{"id": "c", "name": "Mixed", "places": ["alpha"],
                               "services": ["secret-place/Vault", "SECRET-PLACE/Vault", "alpha/SSH"]}])
    handle = viewers.build(tmp_path, monkeypatch, data, windows=[
        {"id": "w", "reason": "r", "services": ["secret-place/Vault", "alpha/SSH"],
         "starts": "2020-01-01T00:00:00Z", "ends": "2099-01-01T00:00:00Z"}])
    alice = viewers.signed_in(handle, "alice")
    lab = alice.get("/api/v2/lab-data").get_json()
    assert [c["services"] for c in lab["collections"]] == [["alpha/SSH"]]
    roster = alice.get("/api/v2/places/roster").get_json()
    assert roster["collections"][0]["services"] == ["alpha/SSH"]
    feed = alice.get("/api/v2/signals").get_json()
    assert feed["maintenance_services"] == ["alpha/SSH"]
    for body in (lab, roster, feed):
        assert "vault" not in json.dumps(body).lower()
    admin = viewers.signed_in(handle, "ops").get("/api/v2/signals").get_json()
    assert admin["maintenance_services"] == ["alpha/SSH", "secret-place/Vault"]
    monkeypatch.undo()


# ── alerts on a service (slice 2) ────────────────────────────────────────────
import alertkit   # noqa: E402

T0 = 1_800_000_000.0


def _alert_realm(tmp_path, monkeypatch, **more):
    p = viewers.place
    data = viewers.dataset(nodes=[
        p("alpha", "Alpha", links=[{"label": "UI", "url": "https://a.example", "kuma": "Alpha UI"},
                                   {"label": "Admin", "url": "https://a.example/x", "require_group": viewers.GROUP}]),
        p("beta", "Beta")], **more)
    handle = alertkit.build(tmp_path, monkeypatch, data)
    sent = alertkit.capture(monkeypatch)
    tick = alertkit.Ticker(handle)
    ok = {"alpha": "healthy", "beta": "healthy"}
    tick.step(ok, T0 - 600, extra={"services": {"Alpha UI": {"state": "healthy"}}})
    return {"handle": handle, "sent": sent, "tick": tick, "ok": ok}


def _svc(state):
    return {"services": {"Alpha UI": {"state": state}}}


def test_a_service_rule_sends_naming_the_service_and_its_place(tmp_path, monkeypatch):
    r = _alert_realm(tmp_path, monkeypatch)
    alertkit.store([alertkit.rule("r-s", "service", "Alpha UI")])
    r["tick"].step(r["ok"], T0, extra=_svc("down"))
    assert r["sent"].titles == ["UI on Alpha is down"]
    assert "Service: UI on Alpha" in r["sent"].sent[0][1]["body"]
    monkeypatch.undo()


def test_a_collection_holding_the_service_reaches_it(tmp_path, monkeypatch):
    r = _alert_realm(tmp_path, monkeypatch, collections=[{"id": "web", "name": "Web", "services": ["Alpha UI"]}])
    alertkit.store([alertkit.rule("r-c", "collection", "web")])
    r["tick"].step(r["ok"], T0, extra=_svc("down"))
    assert r["sent"].titles == ["UI on Alpha is down"]
    monkeypatch.undo()


def test_a_service_follows_its_place(tmp_path, monkeypatch):
    """While its place is down, the place's own alert speaks for it."""
    r = _alert_realm(tmp_path, monkeypatch)
    alertkit.store([alertkit.rule("r-s", "service", "Alpha UI")])
    r["tick"].step({**r["ok"], "alpha": "down"}, T0, extra=_svc("down"))
    assert r["sent"].titles == []
    monkeypatch.undo()


def test_a_service_under_a_window_is_quiet(tmp_path, monkeypatch):
    r = _alert_realm(tmp_path, monkeypatch)
    alertkit.store([alertkit.rule("r-s", "service", "Alpha UI")])
    r["tick"].step(r["ok"], T0, extra={**_svc("down"), "maintenance_services": ["Alpha UI"]})
    assert r["sent"].titles == []
    monkeypatch.undo()


def test_a_service_behind_its_own_group_cannot_be_alerted_on(tmp_path, monkeypatch):
    import alerts
    r = _alert_realm(tmp_path, monkeypatch)
    with r["handle"].app.app_context():
        data = alertkit.dataset(r["handle"])
        doc = {"rules": [alertkit.rule("r-h", "service", "alpha/Admin")], "digest": {}, "destinations": [alertkit.DEST]}
        problems = alerts.validate(alerts.normalize(doc), data)
    assert any("cannot be alerted on" in p for p in problems), problems
    monkeypatch.undo()


def test_a_node_timer_and_a_service_timer_with_the_same_name_never_cancel_each_other(tmp_path, monkeypatch):
    """A monitor may be named like a place id: the timers carry their kind."""
    r = _alert_realm(tmp_path, monkeypatch)
    alertkit.store([alertkit.rule("r-p", "place", "beta", minutes=5),
                    alertkit.rule("r-s", "service", "Alpha UI", minutes=5)])
    r["tick"].step({**r["ok"], "beta": "down"}, T0, extra=_svc("down"))
    import alerts
    with r["handle"].app.app_context():
        kinds = sorted((t.get("kind") or "node", t["target"]) for t in alerts._STATE.load()["timers"])
    assert kinds == [("node", "beta"), ("service", "Alpha UI")]
    monkeypatch.undo()


# ── the stage 3b review ──────────────────────────────────────────────────────
def test_a_collection_never_names_a_group_gated_link_or_a_hidden_places_monitor(tmp_path, monkeypatch):
    """B1: the allowlist was built before a gated link and `signals.kuma`
    on a hidden place were cut."""
    data = _data(collections=[{"id": "c", "name": "C", "services": ["alpha/Admin", "Secret Kuma", "alpha/SSH"]}])
    data["nodes"][0]["links"].append({"label": "Admin", "url": "https://a.example/admin",
                                      "require_group": viewers.GROUP})
    data["signals"] = {"kuma": {"Secret Kuma": "secret-place"}}
    handle = viewers.build(tmp_path, monkeypatch, data)
    alice = viewers.signed_in(handle, "alice")
    assert alice.get("/api/v2/lab-data").get_json()["collections"][0]["services"] == ["alpha/SSH"]
    assert alice.get("/api/v2/places/roster").get_json()["collections"][0]["services"] == ["alpha/SSH"]
    monkeypatch.undo()


def test_a_service_still_down_when_its_place_comes_back_is_sent(tmp_path, monkeypatch):
    """A2: the timer due while its place was down was dropped, and nothing
    restarted it (the service's state never changed)."""
    r = _alert_realm(tmp_path, monkeypatch)
    alertkit.store([alertkit.rule("r-s", "service", "Alpha UI")])
    r["tick"].step({**r["ok"], "alpha": "down"}, T0, extra=_svc("down"))
    assert r["sent"].titles == []
    r["tick"].step({**r["ok"], "alpha": "healthy"}, T0 + 120, extra=_svc("down"))
    assert r["sent"].titles == ["UI on Alpha is down"]
    monkeypatch.undo()


def test_a_window_naming_a_gone_service_makes_nothing_up(tmp_path, monkeypatch):
    """A4: it put a made-up service in maintenance (read as uncharted drift)."""
    handle = viewers.build(tmp_path, monkeypatch, _data(), windows=[
        {"id": "w", "reason": "r", "services": ["gone/Thing", "alpha/SSH"],
         "starts": "2020-01-01T00:00:00Z", "ends": "2099-01-01T00:00:00Z"}])
    feed = viewers.signed_in(handle, "ops").get("/api/v2/signals").get_json()
    assert feed["maintenance_services"] == ["alpha/SSH"]
    assert "gone/Thing" not in feed["services"]
    monkeypatch.undo()


def test_the_digest_names_a_service_left_in_maintenance_mode(tmp_path, monkeypatch):
    p = viewers.place
    data = viewers.dataset(nodes=[p("alpha", "Alpha", links=[{"label": "UI", "url": "https://a.example"}])])
    handle = alertkit.build(tmp_path, monkeypatch, data, windows=[
        {"id": "m", "reason": "x", "open": True, "starts": "2027-01-01T00:00:00Z", "services": ["alpha/UI"]}])
    sent = alertkit.capture(monkeypatch)
    alertkit.store([], digest={"enabled": True, "hour": 0, "destination": "pager"})
    alertkit.Ticker(handle).step({"alpha": "healthy"}, T0)
    assert "In maintenance mode more than 7 days: UI on Alpha (since 2027-01-01)" in sent.sent[0][1]["body"]
    monkeypatch.undo()
