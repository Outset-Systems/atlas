"""ALERTS never names a hidden place (2026-11-13; security item 9).

One place, VAULTKEEP, is behind an access group, and it is put at every point
a message could reach it: as a rule's target, as a root cause, downstream of a
root, as a set member, as a certificate's place, in a rule's name and note, in
a monitor's name, and in a visible place's own words. Then every byte the
sender was handed, every delivery log line and the route answers that are not
the admin's own document (the deliveries, the test send's outcome, the
refusals) are searched for its id, its name and its address.

The admin's own document (`GET /api/v2/admin/alerts`) is not searched: it
echoes back what the admin typed, a rule's name and note included, and only
an admin reads it.
"""

import datetime
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alertkit  # noqa: E402
import viewers  # noqa: E402
from alertkit import rule  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file"}

T0 = 1_800_000_000.0
HIDDEN_ID, HIDDEN_NAME, HIDDEN_IP = "vault", "Vaultkeep", "192.0.2.99"
LEAK = re.compile(r"vault|192\.0\.2\.99", re.IGNORECASE)


def realm_data():
    p = viewers.place
    soon = (datetime.datetime.fromtimestamp(T0, datetime.timezone.utc)
            + datetime.timedelta(days=5)).strftime("%Y-%m-%d")
    return viewers.dataset(
        nodes=[p("gate", "Frontgate"),
               p("app", "App", depends_on=[HIDDEN_ID]),           # behind the hidden place
               p(HIDDEN_ID, HIDDEN_NAME, ip=HIDDEN_IP, depends_on=["gate"],
                 require_group=viewers.GROUP),                     # downstream of a visible one
               p("beta", "Beta"),
               p("talker", "Talker", role="mirrors Vaultkeep nightly")],
        sets=[{"id": "storage", "name": "Storage", "places": ["beta", HIDDEN_ID]}],
        certs=[{"name": "Inner cert", "place": HIDDEN_ID, "expires": soon},
               {"name": "Front cert", "place": "gate", "expires": soon}],
    )


@pytest.fixture
def realm(tmp_path, monkeypatch):
    handle = alertkit.build(tmp_path, monkeypatch, realm_data())
    sent = alertkit.capture(monkeypatch)
    ticker = alertkit.Ticker(handle)
    ok = {i: "healthy" for i in ("gate", "app", HIDDEN_ID, "beta", "talker")}
    ticker.step(ok, T0 - 600)
    return {"handle": handle, "sent": sent, "tick": ticker, "ok": ok, "tmp": tmp_path}


def _clean(realm, *texts):
    """Nothing the sender was handed, nothing in the delivery log, and none of
    `texts` names the hidden place."""
    assert not LEAK.search(realm["sent"].everything()), realm["sent"].everything()
    log = json.dumps(alertkit.log_lines(realm["tmp"]))
    assert not LEAK.search(log), log
    for text in texts:
        assert not LEAK.search(text), text


# ── at save ──────────────────────────────────────────────────────────────────
def test_a_rule_on_a_hidden_place_is_refused_at_save(realm):
    admin = viewers.signed_in(realm["handle"], "ops")
    doc = {"rules": [rule("r1", "place", HIDDEN_ID)], "digest": {},
           "destinations": [alertkit.DEST]}
    stamp = admin.get("/api/v2/admin/alerts").get_json()["stamp"]
    r = admin.post("/api/v2/admin/alerts", json={"doc": doc, "expect": stamp},
                   headers=viewers.W)
    assert r.status_code == 422
    assert any("cannot be alerted on" in p for p in r.get_json()["problems"])
    _clean(realm, r.get_data(as_text=True))


def test_a_set_with_a_hidden_member_may_be_named_and_the_member_never_matches(realm):
    alertkit.store([rule("r-set", "set", "storage")])
    realm["tick"].step({**realm["ok"], HIDDEN_ID: "down"}, T0)
    assert realm["sent"].sent == []
    realm["tick"].step({**realm["ok"], HIDDEN_ID: "down", "beta": "down"}, T0 + 60)
    assert realm["sent"].titles == ["Beta is down"]
    _clean(realm)


# ── in a cascade ─────────────────────────────────────────────────────────────
def test_a_hidden_root_cause_is_never_named(realm):
    alertkit.store([rule("r-core", "network", "core")])
    realm["tick"].step({**realm["ok"], HIDDEN_ID: "down", "app": "down"}, T0)
    # the visible consequence goes out as its own, with no "Behind"
    assert realm["sent"].titles == ["App is down"]
    assert "Behind" not in realm["sent"].sent[0][1]["body"]
    _clean(realm)


def test_a_hidden_downstream_place_is_neither_listed_nor_counted(realm):
    alertkit.store([rule("r-core", "network", "core")])
    realm["tick"].step({**realm["ok"], "gate": "down", HIDDEN_ID: "down"}, T0)
    assert realm["sent"].titles == ["Frontgate is down"]
    body = realm["sent"].sent[0][1]["body"]
    # only the hidden place hangs on Frontgate, so the visible map declares nothing
    assert "Nothing is declared to depend on it." in body
    assert "more" not in body and "Went with it" not in body
    _clean(realm)


def test_a_hidden_place_in_the_middle_of_a_chain(realm):
    """Visible root, hidden middle, visible leaf, all down: the leaf's way to
    the root runs through the hidden place, so the no-group feed cuts its
    cause, and it goes out as its own. Two messages, neither naming it."""
    alertkit.store([rule("r-core", "network", "core")])
    realm["tick"].step({**realm["ok"], "gate": "down", HIDDEN_ID: "down", "app": "down"}, T0)
    assert sorted(realm["sent"].titles) == ["App is down", "Frontgate is down"]
    for _, message in realm["sent"].sent:
        assert "Behind" not in message["body"]
    _clean(realm)


def test_a_rule_whose_target_becomes_hidden_is_suspended(realm, tmp_path):
    alertkit.store([rule("r-beta", "place", "beta")])
    admin = viewers.signed_in(realm["handle"], "ops")
    assert admin.get("/api/v2/admin/alerts").get_json()["status"]["suspended"] == []
    path = tmp_path / "lab-data.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for node in data["nodes"]:
        if node["id"] == "beta":
            node["require_group"] = viewers.GROUP
    path.write_text(json.dumps(data), encoding="utf-8")
    realm["handle"].app.extensions["atlas"].invalidate()
    assert admin.get("/api/v2/admin/alerts").get_json()["status"]["suspended"] == ["r-beta"]
    realm["tick"].step({**realm["ok"], "beta": "down"}, T0)
    assert realm["sent"].sent == []


# ── in the rule's own words ──────────────────────────────────────────────────
def test_a_rule_naming_a_hidden_place_never_sends_its_name_or_note(realm):
    admin = viewers.signed_in(realm["handle"], "ops")
    alertkit.store([rule("r-beta", "place", "beta", name=f"{HIDDEN_NAME} watch",
                         note=f"if beta goes, {HIDDEN_ID} at {HIDDEN_IP} is next")])
    realm["tick"].step({**realm["ok"], "beta": "down"}, T0)
    assert realm["sent"].titles == ["Beta is down"]
    deliveries = admin.get("/api/v2/admin/alerts/deliveries").get_data(as_text=True)
    tested = admin.post("/api/v2/admin/alerts/destinations/pager/test", headers=viewers.W)
    assert tested.status_code == 200
    _clean(realm, deliveries, tested.get_data(as_text=True))


def test_a_message_that_would_name_a_hidden_place_is_blocked_and_logged(realm):
    alertkit.store([rule("r-talker", "place", "talker")])
    realm["tick"].step({**realm["ok"], "talker": "down"}, T0)
    assert realm["sent"].sent == []
    line = alertkit.log_lines(realm["tmp"])[-1]
    assert line["outcome"] == "blocked" and line["why"] == "would name a hidden place"
    _clean(realm)


# ── in the digest ────────────────────────────────────────────────────────────
def test_the_digest_leaves_out_a_hidden_places_certificate_and_monitor(realm):
    alertkit.store([], digest={"enabled": True, "hour": 0, "destination": "pager",
                               "drift": True})
    realm["tick"].step(realm["ok"], T0, extra={"drift": {"count": 3, "uncharted": [
        f"{HIDDEN_NAME} ping", "backup ping", "nas-https"]}})
    assert realm["sent"].titles == ["Atlas daily digest"]
    body = realm["sent"].sent[0][1]["body"]
    assert "Front cert (Frontgate)" in body and "Inner cert" not in body
    # while any place is hidden no uncharted monitor is named (2026-11-13): one
    # called something else ("nas-https") may be the hidden place's own
    assert "backup ping" not in body and "nas-https" not in body
    assert "Monitors the map has not charted: 3 (see Atlas)" in body
    assert "hidden" not in body.lower()
    _clean(realm)
