"""ALERTS' admin routes (2026-11-13): who may read and write them, what they
refuse, and what they never return.

`GET/POST /api/v2/admin/alerts`, `POST /api/v2/admin/alerts/destinations/<id>/test`,
`GET /api/v2/admin/alerts/deliveries`. Admin only (a token is refused), writes
behind `write_required`, off until the operator turns alerts on. The sender is
captured: nothing here sends anywhere.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alertkit  # noqa: E402
import viewers  # noqa: E402
from alertkit import rule  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file"}

SECRET_VALUE = "s3cr3t-never-shown-9f8e7d"
ALERTS = "/api/v2/admin/alerts"
TEST = "/api/v2/admin/alerts/destinations/pager/test"
DELIVERIES = "/api/v2/admin/alerts/deliveries"


def _saving(client, doc):
    """A save's body: the document and the stamp it was read with, as the page
    sends it (a save without `expect` is refused, 2026-11-13)."""
    return {"doc": doc, "expect": client.get(ALERTS).get_json()["stamp"]}


def _doc(**dest):
    return {"rules": [rule("r-alpha", "place", "alpha")],
            "digest": {"enabled": False, "hour": 7, "destination": None, "cert_days": 30,
                       "review_days": 90, "drift": False, "uncharted": False},
            "destinations": [{**alertkit.DEST, **dest}]}


@pytest.fixture
def realm(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_ALERT_SECRET_NTFY_LAB", SECRET_VALUE)
    handle = alertkit.build(tmp_path, monkeypatch, viewers.dataset())
    sent = alertkit.capture(monkeypatch)
    return {"handle": handle, "sent": sent, "tmp": tmp_path,
            "admin": viewers.signed_in(handle, "ops")}


@pytest.fixture
def off(tmp_path, monkeypatch):
    handle = alertkit.build(tmp_path, monkeypatch, viewers.dataset(), on=False)
    return {"handle": handle, "admin": viewers.signed_in(handle, "ops")}


# ── who ──────────────────────────────────────────────────────────────────────
def test_admin_only(realm):
    viewer = viewers.signed_in(realm["handle"], "alice")
    assert viewer.get(ALERTS).status_code == 403
    assert viewer.get(DELIVERIES).status_code == 403
    assert viewer.post(ALERTS, json={"doc": _doc()}, headers=viewers.W).status_code == 403
    assert viewer.post(TEST, headers=viewers.W).status_code == 403
    stranger = realm["handle"].app.test_client()
    assert stranger.get(ALERTS).status_code in (401, 403)


def test_a_token_is_refused_on_every_route(realm):
    token = viewers.issue(realm["handle"])
    client = realm["handle"].app.test_client()
    assert client.get(ALERTS, headers=token).status_code in (401, 403)
    assert client.get(DELIVERIES, headers=token).status_code in (401, 403)
    assert client.post(ALERTS, json={"doc": _doc()},
                       headers={**token, **viewers.W}).status_code in (401, 403)
    assert client.post(TEST, headers={**token, **viewers.W}).status_code in (401, 403)


def test_writes_need_the_write_proof(realm):
    admin = realm["admin"]
    assert admin.post(ALERTS, json={"doc": _doc()}).status_code == 403
    cross = {**viewers.W, "Sec-Fetch-Site": "cross-site"}
    assert admin.post(ALERTS, json={"doc": _doc()}, headers=cross).status_code == 403
    assert admin.post(TEST).status_code == 403
    assert admin.post(ALERTS, json=_saving(admin, _doc()), headers=viewers.W).status_code == 200


def test_every_answer_is_never_cached(realm):
    r = realm["admin"].get(ALERTS)
    assert "no-store" in r.headers["Cache-Control"]


def test_a_read_only_atlas_refuses_the_writes(tmp_path, monkeypatch):
    handle = alertkit.build(tmp_path, monkeypatch, viewers.dataset())
    admin = viewers.signed_in(handle, "ops")
    monkeypatch.setenv("ATLAS_READONLY", "1")
    from appfixture import fresh_app
    fresh_app()
    assert admin.get(ALERTS).status_code == 200
    r = admin.post(ALERTS, json={"doc": _doc()}, headers=viewers.W)
    assert r.status_code == 403 and "read-only" in r.get_json()["error"]
    assert admin.post(TEST, headers=viewers.W).status_code == 403


# ── off by default ───────────────────────────────────────────────────────────
def test_off_by_default_the_read_says_how_and_the_writes_refuse(off):
    body = off["admin"].get(ALERTS).get_json()
    assert body["status"]["enabled"] is False and body["status"]["on"] is False
    assert body["status"]["poll_running"] is False
    assert body["states"] == sorted(["healthy", "degraded", "down", "slumbering", "maintenance"])
    r = off["admin"].post(ALERTS, json={"doc": _doc()}, headers=viewers.W)
    assert r.status_code == 403 and "ATLAS_ALERTS=1" in r.get_json()["error"]
    assert off["admin"].post(TEST, headers=viewers.W).status_code == 403


def test_on_without_hosts_is_still_off(tmp_path, monkeypatch):
    handle = alertkit.build(tmp_path, monkeypatch, viewers.dataset(), hosts="")
    admin = viewers.signed_in(handle, "ops")
    assert admin.get(ALERTS).get_json()["status"]["on"] is False
    assert admin.post(ALERTS, json={"doc": _doc()}, headers=viewers.W).status_code == 403


def test_the_read_carries_the_status(realm):
    status = realm["admin"].get(ALERTS).get_json()["status"]
    assert status["enabled"] is True and status["on"] is True
    assert status["hosts"] == ["ntfy.example:443"]
    assert status["public_url_set"] is True
    assert status["poll_seconds"] == 60 and status["last_tick"] is None


# ── the save ─────────────────────────────────────────────────────────────────
def test_a_save_round_trips_and_a_stale_one_is_refused(realm):
    admin = realm["admin"]
    first = admin.get(ALERTS).get_json()
    r = admin.post(ALERTS, json={"doc": _doc(), "expect": first["stamp"]}, headers=viewers.W)
    assert r.status_code == 200, r.get_json()
    after = admin.get(ALERTS).get_json()
    assert after["doc"]["rules"][0]["target"] == {"kind": "place", "id": "alpha"}
    stale = admin.post(ALERTS, json={"doc": _doc(), "expect": first["stamp"]}, headers=viewers.W)
    assert stale.status_code == 409


@pytest.mark.parametrize("body", [{}, {"expect": ""}, {"expect": None}, {"expect": 7}])
def test_a_save_without_the_stamp_it_was_read_with_is_refused(realm, body):
    # without `expect` the stale check was skipped, and one admin's save wrote
    # over another's (2026-11-13)
    admin = realm["admin"]
    before = admin.get(ALERTS).get_json()["stamp"]
    doc = _doc()
    doc["rules"][0]["name"] = "written without a stamp"
    r = admin.post(ALERTS, json={"doc": doc, **body}, headers=viewers.W)
    assert r.status_code == 400 and "expect" in r.get_json()["error"]
    assert admin.get(ALERTS).get_json()["stamp"] == before


def test_a_bad_document_is_refused_with_its_problems(realm):
    doc = _doc()
    doc["rules"][0].update(to=["on fire"], for_minutes=5000, destination="nowhere")
    doc["digest"]["uncharted"] = True
    doc["destinations"][0]["url"] = "https://elsewhere.example/atlas?token=abc"
    r = realm["admin"].post(ALERTS, json=_saving(realm["admin"], doc), headers=viewers.W)
    assert r.status_code == 422
    problems = " | ".join(r.get_json()["problems"])
    for words in ("one or more states", "0 to 1440", "does not exist",
                  "cannot list uncharted devices", "query string"):
        assert words in problems, problems


def test_secrets_are_named_never_shown(realm):
    admin = realm["admin"]
    r = admin.post(ALERTS, json=_saving(admin, _doc(secret="NTFY_LAB")), headers=viewers.W)
    assert r.status_code == 200
    for answer in (r, admin.get(ALERTS)):
        text = answer.get_data(as_text=True)
        assert SECRET_VALUE not in text and "secret_origin" not in text
        dest = answer.get_json()["doc"]["destinations"][0]
        assert dest["secret"] == "NTFY_LAB" and dest["secret_bound"] is True
    import alerts
    assert SECRET_VALUE not in (realm["tmp"] / "alerts.json").read_text(encoding="utf-8")
    assert alerts.read()[0]["destinations"][0]["secret_origin"] == "https://ntfy.example:443"


def test_a_binding_is_never_taken_from_the_client_and_a_move_drops_it(realm, monkeypatch):
    admin = realm["admin"]
    # a client-sent origin is ignored: no secret named, nothing bound
    forged = _doc(secret_origin="https://ntfy.example:443")
    assert admin.post(ALERTS, json=_saving(admin, forged), headers=viewers.W).status_code == 200
    assert admin.get(ALERTS).get_json()["doc"]["destinations"][0]["secret_bound"] is False

    admin.post(ALERTS, json=_saving(admin, _doc(secret="NTFY_LAB")), headers=viewers.W)
    monkeypatch.setenv("ATLAS_ALERT_HOSTS", "ntfy.example:443,ntfy2.example:443")
    import importlib
    import settings
    importlib.reload(settings)
    moved = _doc(secret="NTFY_LAB", url="https://ntfy2.example/atlas")
    r = admin.post(ALERTS, json=_saving(admin, moved), headers=viewers.W)
    assert r.status_code == 200 and r.get_json()["notes"]
    assert r.get_json()["doc"]["destinations"][0]["secret_bound"] is False
    # saving it again as it is does not rebind it ...
    r = admin.post(ALERTS, json=_saving(admin, moved), headers=viewers.W)
    assert r.get_json()["doc"]["destinations"][0]["secret_bound"] is False
    # ... naming the secret again does
    rebind = _doc(secret="NTFY_LAB", url="https://ntfy2.example/atlas", bind=True)
    r = admin.post(ALERTS, json=_saving(admin, rebind), headers=viewers.W)
    assert r.get_json()["doc"]["destinations"][0]["secret_bound"] is True
    import alerts
    assert "bind" not in alerts.read()[0]["destinations"][0]


# ── the test send ────────────────────────────────────────────────────────────
def test_a_test_send_answers_its_outcome_only(realm):
    admin = realm["admin"]
    assert admin.post(ALERTS, json=_saving(admin, _doc()), headers=viewers.W).status_code == 200
    r = admin.post(TEST, headers=viewers.W)
    assert r.status_code == 200
    assert r.get_json() == {"outcome": "delivered", "status": 200, "why": None}
    dest, message = realm["sent"].sent[-1]
    assert message["title"] == "Atlas test from Test Realm" and dest["id"] == "pager"
    line = alertkit.log_lines(realm["tmp"])[-1]
    assert line["rule"] == "test" and line["destination"] == "Pager"
    assert admin.post("/api/v2/admin/alerts/destinations/nowhere/test",
                      headers=viewers.W).status_code == 404


def test_test_sends_share_the_probe_limiter(realm):
    from api.v2 import admin as admin_routes
    admin_routes._probe_log.clear()
    admin = realm["admin"]
    assert admin.post(ALERTS, json=_saving(admin, _doc()), headers=viewers.W).status_code == 200
    codes = [admin.post(TEST, headers=viewers.W).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429
    admin_routes._probe_log.clear()


# ── the delivery log ─────────────────────────────────────────────────────────
def test_deliveries_newest_first(realm):
    import alert_send
    for i, at in enumerate(("2026-11-13T10:00:00Z", "2026-11-13T10:05:00Z",
                            "2026-11-13T10:02:00Z")):
        alert_send.log_delivery({"at": at, "rule": f"r{i}", "destination": "Pager",
                                 "events": [i], "outcome": "delivered", "status": 200})
    rows = realm["admin"].get(DELIVERIES + "?limit=2").get_json()["deliveries"]
    assert [r["at"] for r in rows][0] >= [r["at"] for r in rows][-1]
    rows = realm["admin"].get(DELIVERIES).get_json()["deliveries"]
    assert [r["at"] for r in rows] == sorted((r["at"] for r in rows), reverse=True)
