"""Accounts — `/api/v2/auth/*` (accounts/hybrid only).

The arms `test_auth_gate_routes.py` does not already drive end to end: the
signed-out `me`, the same-origin refusal on login, the password-change
refusals, MFA setup, the emblem, the admin surface's idempotent toggles and
traps, create/delete, the mode fence (standalone 404s), MFA disable under
policy, and the throttle's 429.
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app, login_as  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

PW = "a-long-enough-password"
WRITE = {"X-Atlas-Write": "1"}
AUTH = "/api/v2/auth"


@pytest.fixture
def realm(tmp_path):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    handle = fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(data),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
        ATLAS_SECRET_KEY="test-signing-key",
        ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
        ATLAS_AUTH_BACKENDS="local",
        ATLAS_MFA_REQUIRED="",
    )
    import accounts
    accounts.create_local_user("ops", PW, is_admin=True)
    accounts.create_local_user("alice", PW)
    return handle


# ── session & self-service ───────────────────────────────────────────────────

def test_me_signed_out(realm):
    r = realm.app.test_client().get(f"{AUTH}/me")
    assert r.status_code == 200
    assert r.get_json() == {"authenticated": False}


def test_login_refusals(realm):
    c = realm.app.test_client()
    # a cross-site POST (no same-origin proof) is refused before credentials
    r = c.post(f"{AUTH}/login", json={"username": "alice", "password": PW})
    assert r.status_code == 403
    r = c.post(f"{AUTH}/login", headers=WRITE, json={"username": "alice", "password": "wrong"})
    assert r.status_code == 401
    assert r.get_json() == {"ok": False, "error": "Invalid credentials."}


def test_login_then_me_then_logout(realm):
    c = realm.app.test_client()
    r, _ = login_as(c, "alice", PW)
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "mfa_required": False, "is_admin": False}
    me = c.get(f"{AUTH}/me").get_json()
    assert me["authenticated"] is True and me["username"] == "alice"
    assert me["source"] == "local" and me["groups"] == []
    assert c.get("/api/v2/lab-data").status_code == 200
    r = c.post(f"{AUTH}/logout", headers=WRITE)
    assert r.get_json() == {"ok": True}
    assert c.get(f"{AUTH}/me").get_json()["authenticated"] is False


def test_password_change(realm):
    c = realm.app.test_client()
    login_as(c, "alice", PW)
    r = c.post(f"{AUTH}/password", headers=WRITE, json={"current": "wrong", "new": "x" * 16})
    assert r.status_code == 401
    assert r.get_json() == {"ok": False, "error": "Current password is wrong."}
    r = c.post(f"{AUTH}/password", headers=WRITE, json={"current": PW, "new": PW + "-2"})
    assert r.status_code == 200 and r.get_json()["ok"]
    c2 = realm.app.test_client()
    assert login_as(c2, "alice", PW)[0].status_code == 401
    assert login_as(c2, "alice", PW + "-2")[0].status_code == 200


def test_mfa_setup_hands_back_a_fresh_secret(realm):
    c = realm.app.test_client()
    login_as(c, "alice", PW)
    r = c.post(f"{AUTH}/mfa/setup", headers=WRITE)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] and set(body) == {"ok", "secret", "uri", "qr_svg"}
    assert body["secret"] in body["uri"]
    again = c.post(f"{AUTH}/mfa/setup", headers=WRITE).get_json()
    assert again["secret"] != body["secret"]


def test_emblem(realm):
    c = realm.app.test_client()
    login_as(c, "alice", PW)
    r = c.post(f"{AUTH}/me/emblem", headers=WRITE, json={"emblem": "⚔"})
    assert r.get_json() == {"ok": True, "emblem": "⚔"}
    r = c.post(f"{AUTH}/me/emblem", headers=WRITE, json={"emblem": "x" * 9})
    assert r.status_code == 400 and "8 characters" in r.get_json()["error"]


# ── user administration ──────────────────────────────────────────────────────

def test_admin_surface(realm):
    c = realm.app.test_client()
    login_as(c, "ops", PW)
    users = c.get(f"{AUTH}/users").get_json()
    assert users["ok"] and {u["username"] for u in users["users"]} == {"ops", "alice"}
    audit = c.get(f"{AUTH}/audit", query_string={"limit": "5"}).get_json()
    assert audit["ok"] and 1 <= len(audit["events"]) <= 5
    # idempotent toggles
    assert c.post(f"{AUTH}/users/alice/active", headers=WRITE,
                  json={"on": True}).get_json() == {"ok": True}
    assert c.post(f"{AUTH}/users/alice/groups", headers=WRITE,
                  json={"groups": ["HL-Viewers"]}).get_json() == {"ok": True}
    assert c.post(f"{AUTH}/users/alice/reset-mfa", headers=WRITE).get_json() == {"ok": True}
    # the traps
    r = c.post(f"{AUTH}/users/ops/admin", headers=WRITE, json={"on": False})
    assert r.status_code == 400 and "own account" in r.get_json()["error"]
    r = c.post(f"{AUTH}/users/ghost/admin", headers=WRITE, json={"on": True})
    assert r.status_code == 404
    # a non-admin is refused
    login_as(c, "alice", PW)
    r = c.get(f"{AUTH}/users")
    assert r.status_code == 403
    assert r.get_json() == {"ok": False, "error": "Admin account required."}


def test_create_and_delete(realm):
    c = realm.app.test_client()
    login_as(c, "ops", PW)
    r = c.post(f"{AUTH}/users", headers=WRITE, json={"username": "u1", "password": PW})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "username": "u1"}
    r = c.post(f"{AUTH}/users", headers=WRITE, json={"username": "", "password": "x"})
    assert r.status_code == 400 and r.get_json()["ok"] is False
    assert c.delete(f"{AUTH}/users/u1", headers=WRITE).get_json() == {"ok": True}
    assert c.delete(f"{AUTH}/users/u1", headers=WRITE).status_code == 404


# ── The mode fence ───────────────────────────────────────────────────────────

def test_standalone_has_no_accounts_surface(tmp_path):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    c = fresh_app(ATLAS_AUTH_MODE="standalone", ATLAS_DATA=str(data),
                  ATLAS_DATA_BACKEND="file",
                  ATLAS_ALLOW_INSECURE="1").app.test_client()
    assert c.get(f"{AUTH}/me").status_code == 404
    assert c.post(f"{AUTH}/login", headers=WRITE,
                  json={"username": "x", "password": "y"}).status_code == 404


# ── The MFA flow, disable under policy, the throttle ─────────────────────────

def _enroll(username):
    import accounts
    import pyotp
    secret, _uri, _qr = accounts.start_mfa_enrollment(username)
    accounts.confirm_mfa(username, pyotp.TOTP(secret).now())
    return secret


def test_mfa_login_flow(realm):
    import pyotp
    secret = _enroll("alice")
    c = realm.app.test_client()
    r = c.post(f"{AUTH}/login", headers=WRITE, json={"username": "alice", "password": PW})
    assert r.get_json() == {"ok": True, "mfa_required": True}
    r = c.post(f"{AUTH}/login/mfa", headers=WRITE, json={"code": "000000"})
    assert r.status_code == 401 and r.get_json()["error"] == "Incorrect code."
    # the pending state survived the failure
    r = c.post(f"{AUTH}/login/mfa", headers=WRITE, json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "is_admin": False}
    assert c.get("/api/v2/lab-data").status_code == 200


def test_mfa_disable_under_policy(realm, monkeypatch):
    import settings
    c = realm.app.test_client()
    r, _ = login_as(c, "ops", PW)
    assert r.status_code == 200
    # policy off: disabling when not enrolled is idempotent
    assert c.post(f"{AUTH}/mfa/disable", headers=WRITE).get_json() == {"ok": True}
    # policy on (read live): refused
    monkeypatch.setattr(settings, "mfa_required", lambda: "1")
    r = c.post(f"{AUTH}/mfa/disable", headers=WRITE)
    assert r.status_code == 403 and "ATLAS_MFA_REQUIRED" in r.get_json()["error"]


def test_admins_policy_fences_the_surveyor_on_the_live_route(realm, monkeypatch):
    """The v1.41.0 regression: with ATLAS_MFA_REQUIRED=admins the admin's login
    must answer `mfa_setup_required` and stay fenced until a factor exists,
    while a plain viewer signs straight in."""
    import settings
    monkeypatch.setattr(settings, "mfa_required", lambda: "admins")
    c = realm.app.test_client()
    r = c.post(f"{AUTH}/login", headers=WRITE, json={"username": "ops", "password": PW})
    assert r.get_json() == {"ok": True, "mfa_setup_required": True}
    assert c.get("/api/v2/lab-data").status_code == 401           # fenced to /auth
    me = c.get(f"{AUTH}/me").get_json()
    assert me == {"authenticated": False, "mfa_setup_required": True, "username": "ops"}
    c2 = realm.app.test_client()
    r = c2.post(f"{AUTH}/login", headers=WRITE, json={"username": "alice", "password": PW})
    assert r.get_json()["mfa_required"] is False
    assert c2.get("/api/v2/lab-data").status_code == 200


def test_login_throttle(realm, monkeypatch):
    import accounts
    monkeypatch.setattr(accounts, "throttled", lambda u, ip: True)
    c = realm.app.test_client()
    r = c.post(f"{AUTH}/login", headers=WRITE, json={"username": "alice", "password": PW})
    assert r.status_code == 429
    assert r.get_json() == {"ok": False, "error": "Too many attempts. Try again later."}
