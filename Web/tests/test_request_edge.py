"""The request edge: a body is what the route expects, or the route never runs.

`_body()` used to hand back whatever JSON arrived. `[1]`, `"x"` and `7` are
truthy, so `or {}` kept them, the route's first `.get` raised, and seventeen
admin routes, the beat and the sign-in answered 500 to a body anyone could
send (audit 2026-11-12, API 9 and Auth 13). The readers in `api/v2/__init__.py`
refuse those with a 422, once, for every route that uses them.
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from appfixture import fresh_app, login_as  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: The bundled map: every tree has one (the public export swaps in its own seed;
#: the contract record's copy is private and stays out of the export).
MAP = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_AUTH_MODE": "standalone",
                  "ATLAS_ALLOW_INSECURE": "1", "ATLAS_SIGNALS_SOURCES": ""}

WRITE = {"X-Atlas-Write": "1", "Origin": "http://localhost"}
PW = "a-long-enough-password"

#: Bodies that are JSON, not empty, and not an object.
NOT_OBJECTS = [[1], "x", 7, [{"settings": {}}], True]


@pytest.fixture(autouse=True)
def _probe_limit_left_as_found():
    """These tests post to the source and connection tests many times a
    minute. Their limiter is a module-level log, so without this the next
    suite to ask for a test is refused with a 429."""
    from api.v2 import admin as adm
    adm._probe_log.clear()
    yield
    adm._probe_log.clear()


def _paths(tmp_path):
    data = tmp_path / "lab-data.json"
    shutil.copy(MAP, data)
    return {"ATLAS_DATA": str(data), "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
            "ATLAS_MAPS": str(tmp_path / "maps")}


@pytest.fixture
def admin(tmp_path):
    """The admin of a standalone Atlas that may write."""
    handle = fresh_app(ATLAS_AUTH_MODE="standalone", ATLAS_ALLOW_INSECURE="1",
                       ATLAS_READONLY="0", ATLAS_DATA_BACKEND="file",
                       ATLAS_SIGNALS_SOURCES="", **_paths(tmp_path))
    return handle.app.test_client()


@pytest.fixture
def realm(tmp_path):
    """An accounts-mode Atlas with one admin (`link`) and one plain user."""
    handle = fresh_app(ATLAS_AUTH_MODE="accounts", ATLAS_ALLOW_INSECURE="",
                       ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
                       ATLAS_SECRET_KEY="test-signing-key", ATLAS_INSECURE_COOKIES="1",
                       ATLAS_DATA_BACKEND="file", ATLAS_AUTH_BACKENDS="local",
                       ATLAS_MFA_REQUIRED="", ATLAS_SIGNALS_SOURCES="", **_paths(tmp_path))
    import accounts
    accounts.create_local_user("ops", PW, is_admin=True)
    accounts.create_local_user("alice", PW)
    return handle


# ── the readers themselves ───────────────────────────────────────────────────

def _read(app, json_body, reader):
    from flask import jsonify
    from werkzeug.exceptions import HTTPException
    with app.test_request_context("/x", method="POST", json=json_body):
        try:
            return jsonify(reader()).get_json(), 200
        except HTTPException as refused:
            return refused.response.get_json(), refused.response.status_code


def test_the_body_is_an_object_or_nothing(admin):
    from api import v2
    app = admin.application
    assert _read(app, {"a": 1}, v2._body) == ({"a": 1}, 200)
    for empty in (None, [], 0, "", False, {}):
        assert _read(app, empty, v2._body) == ({}, 200)
    for body in NOT_OBJECTS:
        answer, status = _read(app, body, v2._body)
        assert status == 422 and answer["ok"] is False and "JSON object" in answer["error"]


def test_a_part_of_the_body_is_an_object_or_nothing(admin):
    from api import v2
    app = admin.application
    assert _read(app, {"settings": {"k": "v"}}, lambda: v2._part(v2._body(), "settings")) == ({"k": "v"}, 200)
    for empty in ({}, {"settings": None}, {"settings": {}}, {"settings": ""}):
        assert _read(app, empty, lambda: v2._part(v2._body(), "settings")) == ({}, 200)
    for wrong in ("x", [1], 7, True):
        answer, status = _read(app, {"settings": wrong}, lambda: v2._part(v2._body(), "settings"))
        assert status == 422 and "`settings`" in answer["error"]


def test_text_is_text_a_number_is_its_digits_and_the_rest_is_refused(admin):
    from api import v2
    app = admin.application

    def text(body, limit=v2.TEXT_LIMIT):
        return _read(app, body, lambda: {"v": v2._text(v2._body(), "v", limit)})
    assert text({"v": "abc"}) == ({"v": "abc"}, 200)
    assert text({"v": 123456}) == ({"v": "123456"}, 200)
    assert text({"other": 1}) == ({"v": ""}, 200)
    assert text({"v": None}) == ({"v": ""}, 200)
    for wrong in ([1], {"a": 1}, True, False):
        answer, status = text({"v": wrong})
        assert status == 422 and "must be text" in answer["error"]
    answer, status = text({"v": "x" * 11}, limit=10)
    assert status == 422 and "too long" in answer["error"]
    assert text({"v": "x" * 10}, limit=10)[1] == 200


def test_a_list_of_text_is_never_a_string_walked_letter_by_letter(admin):
    from api import v2
    app = admin.application

    def texts(body):
        return _read(app, body, lambda: {"v": v2._texts(v2._body(), "v")})
    assert texts({"v": ["ops", "net"]}) == ({"v": ["ops", "net"]}, 200)
    assert texts({}) == ({"v": []}, 200)
    assert texts({"v": []}) == ({"v": []}, 200)
    for wrong in ("ops", {"a": 1}, 7, [["ops"]], [{"a": 1}], [True]):
        answer, status = texts({"v": wrong})
        assert status == 422, wrong


# ── the admin routes (audit: API 9) ──────────────────────────────────────────

ADMIN_WRITES = [
    "/api/v2/admin/revisions/1/revert",
    "/api/v2/admin/events/1/ack",
    "/api/v2/admin/tokens",
    "/api/v2/admin/connections/test",
    "/api/v2/admin/connections/review",
    "/api/v2/admin/connections/import",
    "/api/v2/admin/auth/test",
    "/api/v2/admin/auth",
    "/api/v2/admin/discovery/connection",
    "/api/v2/admin/discovery/decide",
    "/api/v2/admin/discovery/as-nodes",
    "/api/v2/admin/import/csv",
    "/api/v2/admin/map-art/survey",
    "/api/v2/admin/integrations/test",
    "/api/v2/admin/integrations",
]


@pytest.mark.parametrize("path", ADMIN_WRITES)
def test_an_admin_route_refuses_a_body_that_is_not_an_object(admin, path):
    for body in NOT_OBJECTS:
        r = admin.post(path, json=body, headers=WRITE)
        assert r.status_code != 500, (path, body, r.get_data(as_text=True)[:200])
        assert r.status_code < 500, (path, body)


@pytest.mark.parametrize("path", [
    "/api/v2/admin/connections/test", "/api/v2/admin/auth/test", "/api/v2/admin/auth",
    "/api/v2/admin/integrations/test", "/api/v2/admin/integrations",
])
def test_settings_that_are_not_an_object_are_refused(admin, path):
    for wrong in ("x", [1], 7):
        body = {"settings": wrong, "key": "kuma", "kind": "kuma",
                "username": "ops", "password": "pw"}
        r = admin.post(path, json=body, headers=WRITE)
        assert r.status_code < 500, (path, wrong, r.get_data(as_text=True)[:200])


def test_the_beat_refuses_a_body_that_is_not_an_object(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_BEAT_TOKEN", "beat-token")
    handle = fresh_app(ATLAS_AUTH_MODE="standalone", ATLAS_ALLOW_INSECURE="1",
                       ATLAS_READONLY="0", ATLAS_DATA_BACKEND="file",
                       ATLAS_BEAT_TOKEN="beat-token",
                       ATLAS_BEATS=str(tmp_path / "heartbeats.json"), **_paths(tmp_path))
    client = handle.app.test_client()
    for body in NOT_OBJECTS:
        r = client.post("/api/v2/rites/backup/beat", json=body,
                        headers={"Authorization": "Bearer beat-token", "X-Beat-Token": "beat-token"})
        assert r.status_code < 500, (body, r.get_data(as_text=True)[:200])


# ── the sign-in and the accounts routes (audit: Auth 13, and the name's length) ──

def test_the_sign_in_refuses_what_is_not_a_name_and_a_password(realm):
    client = realm.app.test_client()
    for body in NOT_OBJECTS:
        r = client.post("/api/v2/auth/login", json=body, headers=WRITE)
        assert r.status_code == 422, (body, r.status_code)
    for body in ({"username": ["ops"], "password": PW}, {"username": {"a": 1}, "password": PW},
                 {"username": "ops", "password": ["x"]}, {"username": True, "password": PW}):
        r = client.post("/api/v2/auth/login", json=body, headers=WRITE)
        assert r.status_code == 422 and r.get_json()["ok"] is False, body
    # a number where a name belongs is its digits, and is simply nobody
    r = client.post("/api/v2/auth/login", json={"username": 7, "password": PW}, headers=WRITE)
    assert r.status_code == 401


def test_a_name_too_long_to_be_one_never_reaches_the_sign_in_log(realm):
    import accounts
    client = realm.app.test_client()
    before = len(accounts.audit_tail(500))
    r = client.post("/api/v2/auth/login", headers=WRITE,
                    json={"username": "a" * 5000, "password": "x"})
    assert r.status_code == 422
    assert len(accounts.audit_tail(500)) == before
    # one that fits is recorded as before
    r = client.post("/api/v2/auth/login", headers=WRITE,
                    json={"username": "nobody", "password": "x"})
    assert r.status_code == 401
    assert len(accounts.audit_tail(500)) == before + 1


def test_the_sign_in_still_works(realm):
    client = realm.app.test_client()
    r, _ = login_as(client, "ops", PW)
    assert r.status_code == 200 and r.get_json()["ok"] is True


ACCOUNT_WRITES = [
    "/api/v2/auth/login/mfa", "/api/v2/auth/mfa/setup", "/api/v2/auth/mfa/confirm",
    "/api/v2/auth/mfa/disable", "/api/v2/auth/password", "/api/v2/auth/me/emblem",
    "/api/v2/auth/users", "/api/v2/auth/users/alice/admin", "/api/v2/auth/users/alice/active",
    "/api/v2/auth/users/alice/groups",
]


@pytest.mark.parametrize("path", ACCOUNT_WRITES)
def test_an_accounts_route_refuses_a_body_that_is_not_an_object(realm, path):
    client = realm.app.test_client()
    login_as(client, "ops", PW)
    for body in NOT_OBJECTS:
        r = client.post(path, json=body, headers=WRITE)
        assert r.status_code < 500, (path, body, r.get_data(as_text=True)[:200])


def test_groups_sent_as_one_string_are_refused_not_stored_letter_by_letter(realm):
    import accounts
    client = realm.app.test_client()
    login_as(client, "ops", PW)
    r = client.post("/api/v2/auth/users/alice/groups", json={"groups": "ops"}, headers=WRITE)
    assert r.status_code == 422
    assert accounts.get_user("alice")["groups_csv"] == ""
    r = client.post("/api/v2/auth/users/alice/groups", json={"groups": ["ops", "net"]}, headers=WRITE)
    assert r.status_code == 200
    assert accounts.get_user("alice")["groups_csv"] == "ops,net"
    r = client.post("/api/v2/auth/users", headers=WRITE,
                    json={"username": "saria", "password": PW, "groups": "ops"})
    assert r.status_code == 422 and accounts.get_user("saria") is None


# ── a count from the query string (audit: API 14) ────────────────────────────

def test_a_count_is_at_least_one_and_at_most_the_cap(admin):
    from api import v2
    app = admin.application
    for query, expected in (("", 25), ("limit=10", 10), ("limit=999", 200), ("limit=0", 25),
                            ("limit=-5", 25), ("limit=abc", 25), ("limit=1.5", 25)):
        with app.test_request_context("/x?" + query):
            assert v2._count("limit", 25, 200) == expected, query


@pytest.mark.parametrize("path", ["/api/v2/events", "/api/v2/admin/revisions"])
def test_a_negative_limit_is_the_default_not_a_slice_from_the_end(admin, path):
    for limit in ("-1", "-500", "0", "abc"):
        assert admin.get(f"{path}?limit={limit}").status_code == 200
