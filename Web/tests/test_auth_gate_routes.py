"""Accounts mode end to end: the gate, the login flow, MFA, admin routes,
redaction-by-session, and the promise that hub/standalone are untouched."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app  # noqa: E402

# Non-empty so conftest snapshots/restores the whole ATLAS_ENV list per test.
ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts"}

PW = "a-long-enough-password"
WRITE = {"X-Atlas-Write": "1"}


def _dataset(tmp_path):
    data = {
        "meta": {"title": "Test Realm"},
        "zones": [],
        "nodes": [
            {"id": "public-place", "name": "Public", "kind": "physical",
             "x": 10, "y": 10},
            {"id": "secret-place", "name": "Secret", "kind": "physical",
             "x": 20, "y": 20, "require_group": "HUB-decoy"},
        ],
        "routes": [],
    }
    path = tmp_path / "lab-data.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def realm(tmp_path):
    """An accounts-mode Atlas with one admin and one plain user."""
    handle = fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(_dataset(tmp_path)),
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


def _login(client, username, password=PW):
    r = client.post("/api/v2/auth/login", json={"username": username, "password": password},
                    headers=WRITE)
    return r, None


# ── The gate ─────────────────────────────────────────────────────────────────

def test_anonymous_is_gated(realm):
    c = realm.app.test_client()
    r = c.get("/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
    assert c.get("/api/v2/lab-data").status_code == 401
    assert c.get("/api/status").status_code == 200      # monitoring contract
    assert c.get("/auth/login").status_code == 200


def test_login_grants_and_logout_revokes(realm):
    c = realm.app.test_client()
    r, tok = _login(c, "ops")
    assert r.status_code == 200 and r.get_json()["ok"]
    assert c.get("/api/v2/lab-data").status_code == 200
    me = c.get("/api/v2/auth/me").get_json()
    assert me["authenticated"] and me["is_admin"] and me["source"] == "local"
    r = c.post("/api/v2/auth/logout", headers=WRITE)
    assert r.get_json()["ok"]
    assert c.get("/api/v2/lab-data").status_code == 401


def test_wrong_password_is_generic(realm):
    c = realm.app.test_client()
    r, _ = _login(c, "ops", "wrong-password-x")
    r2, _ = _login(c, "who-does-not-exist", "wrong-password-x")
    assert r.status_code == r2.status_code == 401
    assert r.get_json()["error"] == r2.get_json()["error"]


def test_same_origin_proof_required_on_login(realm):
    """No X-Atlas-Write header -> the same-origin gate refuses before creds."""
    c = realm.app.test_client()
    r = c.post("/api/v2/auth/login", json={"username": "ops", "password": PW})
    assert r.status_code == 403


def test_throttle_locks_after_failures(realm):
    import accounts
    c = realm.app.test_client()
    for _ in range(accounts.THROTTLE_USER_MAX):
        _login(c, "ops", "wrong-password-x")
    r, _ = _login(c, "ops", PW)                        # even the RIGHT password
    assert r.status_code == 429


def test_epoch_bump_kills_live_sessions(realm):
    import accounts
    c = realm.app.test_client()
    _login(c, "ops")
    assert c.get("/api/v2/lab-data").status_code == 200
    accounts.bump_session_epoch("ops")
    assert c.get("/api/v2/lab-data").status_code == 401


def test_deactivated_account_cannot_login_or_stay(realm):
    import accounts
    c = realm.app.test_client()
    _login(c, "alice")
    accounts.set_active("alice", False)                 # bumps epoch too
    assert c.get("/api/v2/lab-data").status_code == 401
    r, _ = _login(c, "alice")
    assert r.status_code == 401


# ── Authorisation: redaction + writes ────────────────────────────────────────

def test_redaction_follows_session_groups(realm):
    import accounts
    c = realm.app.test_client()
    _login(c, "alice")                                  # no groups, no admin
    ids = [n["id"] for n in c.get("/api/v2/lab-data").get_json()["nodes"]]
    assert "public-place" in ids and "secret-place" not in ids
    accounts.set_groups("alice", ["HUB-decoy"])
    ids = [n["id"] for n in c.get("/api/v2/lab-data").get_json()["nodes"]]
    assert "secret-place" in ids

    c2 = realm.app.test_client()
    _login(c2, "ops")                                  # admin sees everything
    ids = [n["id"] for n in c2.get("/api/v2/lab-data").get_json()["nodes"]]
    assert "secret-place" in ids


def test_named_admin_group_is_not_a_backdoor_local(realm):
    """the 2026-08-11 security review: 'atlas-admins' is the sees_everything sentinel. A local
    user must NOT gain admin by being assigned that string as a clearance
    group — admin is the is_admin flag alone."""
    import accounts
    # assigning the reserved group is refused at the source
    try:
        accounts.set_groups("alice", ["atlas-admins"])
        assert False, "expected ValueError assigning the reserved admin group"
    except ValueError:
        pass
    # and even if a row somehow carries it, authz strips it: force it in raw
    import sqlite3
    conn = sqlite3.connect(accounts.db_path())
    conn.execute("UPDATE users SET groups_csv = 'atlas-admins' WHERE username = 'alice'")
    conn.commit()
    conn.close()
    c = realm.app.test_client()
    _login(c, "alice")                                  # is_admin=0, group present
    r = c.post("/api/v2/positions", json={}, headers={"X-Atlas-Write": "1"})
    assert r.status_code == 403                         # NOT admin
    # and the map is still redacted for them
    ids = [n["id"] for n in c.get("/api/v2/lab-data").get_json()["nodes"]]
    assert "secret-place" not in ids


def test_named_admin_group_is_not_a_backdoor_ldap(realm, monkeypatch):
    """An LDAP member of AD 'atlas-admins' whose is_admin is False (operator
    configured a DIFFERENT admin group) must not inherit admin via the group
    name mirrored into the store."""
    import ldap_backend
    from test_ldap_backend import _Entry, _FakeConn
    monkeypatch.setenv("ATLAS_AUTH_BACKENDS", "local,ldap")
    monkeypatch.setenv("ATLAS_LDAP_URL", "ldaps://dc.home.example:636")
    monkeypatch.setenv("ATLAS_LDAP_BASE_DN", "DC=home,DC=example")
    monkeypatch.setenv("ATLAS_LDAP_ADMIN_GROUPS", "Lab-Operators")   # NOT atlas-admins
    ldap_backend._connect_fn = lambda url, upn, pw, t: _FakeConn(
        [_Entry(["CN=atlas-admins,DC=home,DC=example"])])   # member of atlas-admins only
    try:
        c = realm.app.test_client()
        r, _ = _login(c, "hero", "a-directory-password")
        assert r.get_json()["ok"] and not r.get_json()["is_admin"]
        import accounts
        assert not accounts.get_user("hero")["is_admin"]
        r = c.post("/api/v2/positions", json={}, headers={"X-Atlas-Write": "1"})
        assert r.status_code == 403                     # no backdoor admin
        ids = [n["id"] for n in c.get("/api/v2/lab-data").get_json()["nodes"]]
        assert "secret-place" not in ids                # redaction holds
    finally:
        ldap_backend._connect_fn = None


def test_writes_are_admin_only_and_enabled(realm):
    c = realm.app.test_client()
    _login(c, "alice")
    r = c.post("/api/v2/positions", json={}, headers={"X-Atlas-Write": "1"})
    assert r.status_code == 403                         # signed in ≠ admin
    c2 = realm.app.test_client()
    _login(c2, "ops")
    r = c2.post("/api/v2/positions", json={}, headers={"X-Atlas-Write": "1"})
    assert r.status_code != 403                         # accounts mode writes


# ── MFA ──────────────────────────────────────────────────────────────────────

def test_mfa_login_flow(realm):
    pyotp = pytest.importorskip("pyotp")
    import accounts
    secret, _, _ = accounts.start_mfa_enrollment("ops")
    accounts.confirm_mfa("ops", pyotp.TOTP(secret).now())

    c = realm.app.test_client()
    r, tok = _login(c, "ops")
    assert r.get_json()["mfa_required"]
    assert c.get("/api/v2/lab-data").status_code == 401    # password alone ≠ in
    r = c.post("/api/v2/auth/login/mfa", json={"code": "000000"},
               headers=WRITE)
    assert r.status_code == 401
    # the enrolment code is spent (2026-11-01): the next step signs in
    import time as _time
    r = c.post("/api/v2/auth/login/mfa",
               json={"code": pyotp.TOTP(secret).at(_time.time() + 30)}, headers=WRITE)
    assert r.get_json()["ok"]
    assert c.get("/api/v2/lab-data").status_code == 200


def test_forced_enrollment_fences_until_confirmed(realm, monkeypatch):
    pyotp = pytest.importorskip("pyotp")
    monkeypatch.setenv("ATLAS_MFA_REQUIRED", "all")
    c = realm.app.test_client()
    r, tok = _login(c, "alice")
    assert r.get_json()["mfa_setup_required"]
    assert c.get("/api/v2/lab-data").status_code == 401    # fenced to /auth
    r = c.post("/api/v2/auth/mfa/setup", headers=WRITE)
    secret = r.get_json()["secret"]
    r = c.post("/api/v2/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()},
               headers=WRITE)
    body = r.get_json()
    assert body["ok"] and len(body["backup_codes"]) == 10
    assert c.get("/api/v2/lab-data").status_code == 200
    # and disabling is refused while the policy stands
    r = c.post("/api/v2/auth/mfa/disable", headers=WRITE)
    assert r.status_code == 403


# ── The directory backend through the real login route ───────────────────────

def test_ldap_login_creates_mirror_and_admin(realm, monkeypatch):
    import ldap_backend
    from test_ldap_backend import _Entry, _FakeConn
    monkeypatch.setenv("ATLAS_AUTH_BACKENDS", "local,ldap")
    monkeypatch.setenv("ATLAS_LDAP_URL", "ldaps://dc.home.example:636")
    monkeypatch.setenv("ATLAS_LDAP_BASE_DN", "DC=home,DC=example")
    ldap_backend._connect_fn = lambda url, upn, pw, t: _FakeConn(
        [_Entry(["CN=atlas-admins,DC=home,DC=example", "CN=HUB-decoy,DC=home,DC=example"])])
    try:
        c = realm.app.test_client()
        r, _ = _login(c, "bob", "a-directory-password")
        assert r.get_json()["ok"] and r.get_json()["is_admin"]
        import accounts
        acc = accounts.get_user("bob")
        assert acc["source"] == "ldap" and acc["is_admin"]
        assert "HUB-decoy" in accounts.groups_of(acc)
        ids = [n["id"] for n in c.get("/api/v2/lab-data").get_json()["nodes"]]
        assert "secret-place" in ids                     # admin clearance
    finally:
        ldap_backend._connect_fn = None


# ── Admin user management ────────────────────────────────────────────────────

def test_admin_routes_guarded(realm):
    c = realm.app.test_client()
    _login(c, "alice")
    assert c.get("/api/v2/auth/users").status_code == 403
    c2 = realm.app.test_client()
    r, tok = _login(c2, "ops")
    users = c2.get("/api/v2/auth/users").get_json()["users"]
    assert {u["username"] for u in users} == {"ops", "alice"}
    # self-demote and last-admin are refused
    r = c2.post("/api/v2/auth/users/ops/admin", json={"on": False},
                headers=WRITE)
    assert r.status_code == 400
    # create, then the new admin may demote the first
    r = c2.post("/api/v2/auth/users", json={"username": "bob", "password": PW,
                                         "is_admin": True},
                headers=WRITE)
    assert r.get_json()["ok"]
    r = c2.post("/api/v2/auth/users/bob/admin", json={"on": False},
                headers=WRITE)
    assert r.get_json()["ok"]


def test_ldap_admin_flag_managed_by_directory(realm):
    import accounts
    accounts.upsert_ldap_user("bob", groups=["HUB-Atlas"])
    c = realm.app.test_client()
    r, tok = _login(c, "ops")
    r = c.post("/api/v2/auth/users/bob/admin", json={"on": True},
               headers=WRITE)
    assert r.status_code == 400
    assert "ATLAS_LDAP_ADMIN_GROUPS" in r.get_json()["error"]


# ── Bootstrap + other modes stay untouched ───────────────────────────────────

def test_bootstrap_admin_env(tmp_path):
    fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "boot.db"),
        ATLAS_SECRET_KEY="k", ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
        ATLAS_BOOTSTRAP_ADMIN_USER="ops",
        ATLAS_BOOTSTRAP_ADMIN_PASSWORD=PW,
    )
    import accounts
    acc = accounts.get_user("ops")
    assert acc and acc["is_admin"] and acc["source"] == "local"
    assert accounts.verify_password("ops", PW)


def test_bootstrap_password_alone_creates_admin(tmp_path):
    """A bare `docker run -e ATLAS_BOOTSTRAP_ADMIN_PASSWORD=…` (no user name)
    created nobody before 2026-10-18; it now creates the documented `admin`."""
    fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "pwonly.db"),
        ATLAS_SECRET_KEY="k", ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
        ATLAS_BOOTSTRAP_ADMIN_PASSWORD=PW,
    )
    import accounts
    acc = accounts.get_user("admin")
    assert acc and acc["is_admin"] and acc["source"] == "local"
    assert accounts.verify_password("admin", PW)


def test_no_admin_and_nothing_to_bootstrap_says_so(tmp_path, monkeypatch, caplog):
    """accounts mode with no admin and no bootstrap envs: the app starts, and
    the log says why nobody can sign in and how to fix it."""
    fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "noadmin.db"),
        ATLAS_SECRET_KEY="k", ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
    )
    import accounts
    import auth_routes
    for name in ("ATLAS_BOOTSTRAP_ADMIN_USER", "ATLAS_BOOTSTRAP_ADMIN_PASSWORD",
                 "ATLAS_BOOTSTRAP_ADMIN_PASSWORD_FILE"):
        monkeypatch.delenv(name, raising=False)
    with caplog.at_level("WARNING", logger="atlas.auth.routes"):
        auth_routes.ensure_bootstrap_admin()
    assert accounts.count_active_admins() == 0
    assert any("no admin account exists" in r.getMessage()
               and "ATLAS_BOOTSTRAP_ADMIN_PASSWORD" in r.getMessage()
               for r in caplog.records)


def test_bootstrap_admin_lost_race_is_not_fatal(tmp_path, monkeypatch):
    """Two gunicorn workers bootstrap a fresh install at once; the one whose
    INSERT loses must boot, not take the master down (atlas-public 2026-09-27)."""
    import sqlite3
    fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "race.db"),
        ATLAS_SECRET_KEY="k", ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
    )
    import accounts
    import auth_routes
    monkeypatch.setenv("ATLAS_BOOTSTRAP_ADMIN_USER", "ops")
    monkeypatch.setenv("ATLAS_BOOTSTRAP_ADMIN_PASSWORD", PW)
    real_create = accounts.create_local_user

    def other_worker_wins(username, password, **kw):
        real_create(username, password, **kw)          # the winner's row lands…
        raise sqlite3.IntegrityError("UNIQUE constraint failed: users.username")

    monkeypatch.setattr(accounts, "create_local_user", other_worker_wins)
    auth_routes.ensure_bootstrap_admin()                 # …and the loser must not raise
    assert accounts.get_user("ops")["is_admin"]

    # A failure with no row behind it is still an error, not swallowed.
    def just_fails(*a, **kw):
        raise sqlite3.IntegrityError("disk trouble")
    monkeypatch.setattr(accounts, "create_local_user", just_fails)
    monkeypatch.setattr(accounts, "count_active_admins", lambda: 0)
    monkeypatch.setenv("ATLAS_BOOTSTRAP_ADMIN_USER", "alice")   # no row for alice
    with pytest.raises(sqlite3.IntegrityError):
        auth_routes.ensure_bootstrap_admin()


def test_a_refused_bootstrap_password_boots_without_an_admin(tmp_path, monkeypatch, caplog):
    """The likeliest first-run mistake (a password under the length policy)
    must not stop every worker and restart-loop the container: the app starts
    with no admin and the log says exactly what to fix (v1.49.0)."""
    fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "short.db"),
        ATLAS_SECRET_KEY="k", ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
    )
    import accounts
    import auth_routes
    monkeypatch.setenv("ATLAS_BOOTSTRAP_ADMIN_USER", "owner")
    monkeypatch.setenv("ATLAS_BOOTSTRAP_ADMIN_PASSWORD", "short")
    with caplog.at_level("ERROR", logger="atlas.auth.routes"):
        auth_routes.ensure_bootstrap_admin()            # must not raise
    assert accounts.get_user("owner") is None
    assert accounts.count_active_admins() == 0
    assert any("NOT created" in r.getMessage() and "ATLAS_BOOTSTRAP_ADMIN_PASSWORD" in r.getMessage()
               for r in caplog.records)


def test_hub_mode_unchanged(tmp_path):
    """The framework resolves AUTH_MODE at ITS import, so a full-suite run must
    patch the module attribute the way every existing hub-mode test does."""
    import hub_auth.auth as auth
    handle = fresh_app(
        ATLAS_AUTH_MODE="hub",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_DATA_BACKEND="file",
    )
    original = auth.AUTH_MODE
    auth.AUTH_MODE = "hub"
    try:
        c = handle.app.test_client()
        assert c.get("/api/v2/lab-data").status_code == 403     # header required
        assert c.get("/api/status").status_code == 200
        r = c.get("/api/v2/lab-data", headers={"X-Remote-User": "ops"})
        assert r.status_code == 200                          # legacy no-secret path
        assert c.get("/auth/login").status_code == 403       # gate fronts routing
    finally:
        auth.AUTH_MODE = original


def test_standalone_mode_unchanged(tmp_path):
    import hub_auth.auth as auth
    handle = fresh_app(
        ATLAS_AUTH_MODE="standalone",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_DATA_BACKEND="file",
    )
    original = auth.AUTH_MODE
    auth.AUTH_MODE = "standalone"
    try:
        c = handle.app.test_client()
        assert c.get("/api/v2/lab-data").status_code == 200     # open, as documented
    finally:
        auth.AUTH_MODE = original


def test_the_login_page_ships_no_inline_script(realm):
    """The gate's own behaviour must survive the app's Content-Security-Policy.

    `app.py` sends `default-src 'self'` with no `script-src`, so `default-src`
    is the fallback for scripts and **every inline block is blocked**. The
    login flow lived in one until 2026-08-12, which meant that in a real
    browser no handler ever attached: the form fell back to a NATIVE GET
    submit and put the password in the URL — browser history, the gunicorn
    access log, every proxy log in front of it — while MFA verification and
    forced enrollment were simply dead.

    Nothing caught it, because the Flask test client does not enforce CSP: the
    whole flow passes over the wire and fails in every browser. This test pins
    the shape instead of the behaviour — a `<script>` may carry `src` (external,
    same-origin, allowed) or be a `type="application/json"` data block (not
    executable, so the policy has no opinion), and nothing else.
    """
    import re
    body = realm.app.test_client().get("/auth/login").get_data(as_text=True)
    for attrs, code in re.findall(r"<script([^>]*)>(.*?)</script>", body, re.S):
        external = "src=" in attrs
        data_block = "application/json" in attrs
        assert external or data_block, (
            f"inline <script{attrs}> on the login page — the CSP blocks it, so "
            f"the sign-in form would fall back to a native GET and leak the "
            f"password into the URL. Move it to static/ instead."
        )
        if data_block:
            assert "addEventListener" not in code and "fetch(" not in code, (
                "a data block is carrying behaviour; it will never execute"
            )


# ── hybrid: the Hub's identity when it is there, ours when it is not ─────────

def _hybrid(tmp_path, **over):
    env = dict(
        ATLAS_AUTH_MODE="hybrid",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
        ATLAS_SECRET_KEY="test-signing-key",
        ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
        ATLAS_AUTH_BACKENDS="local",
        ATLAS_MFA_REQUIRED="",
    )
    env.update(over)
    return fresh_app(**env)


def test_hybrid_takes_the_hub_identity_or_its_own_session(tmp_path):
    handle = _hybrid(tmp_path)
    import accounts
    accounts.create_local_user("ops", PW, is_admin=True)
    c = handle.app.test_client()

    # nobody: the gate is closed, and the page sends you to the login
    assert c.get("/api/v2/lab-data").status_code == 401
    assert c.get("/").status_code == 302

    # With NO secret configured there is no verifiable Hub identity, and hybrid
    # will not take an unverifiable one. This used to be the "documented legacy
    # posture" — trust the plaintext header the way hub mode does — but hub mode
    # can only afford that because the Hub's own gate has already 403'd anything
    # unauthenticated, and hybrid deliberately has no gate in front of it. So
    # the header WAS unauthenticated admin: the gate let it through and
    # is_admin() read atlas-admins straight out of it. Hub SSO simply switches off
    # until a secret exists; everyone signs in below instead.
    assert c.get("/api/v2/lab-data", headers={"X-Remote-User": "ops"}).status_code == 401
    assert c.get("/api/v2/lab-data", headers={"X-Remote-User": "ops",
                                           "X-Remote-Groups": "atlas-admins"}
                 ).status_code == 401

    # our own sign-in works too, on the same instance
    r = c.post("/api/v2/auth/login", json={"username": "ops", "password": PW},
               headers=WRITE)
    assert r.get_json()["ok"] is True
    assert c.get("/api/v2/lab-data").status_code == 200


def test_hybrid_clearance_never_collapses_open(tmp_path):
    """`redaction.viewer_groups()` returns None for "no gate applies", and None
    means SEES EVERYTHING. Hybrid must never reach that branch: a signed-out
    caller gets an empty set, not the run of the map. This is the §4.4.1b
    standalone-collapses-open failure one mode further along."""
    import redaction
    handle = _hybrid(tmp_path)
    with handle.app.test_request_context("/"):
        groups = redaction.viewer_groups()
    assert groups == set()
    assert redaction.sees_everything(groups) is False


def test_hybrid_refuses_a_forged_header_once_signing_is_on(tmp_path):
    """The trap hybrid is built around. `hub_auth.get_remote_user()` falls
    back to the plaintext header whenever the signed token is absent — safe in
    hub mode only because that mode's gate 403s first, which hybrid's does not.
    With a secret configured the signature must be the only identity there is."""
    import hub_auth.auth as ka
    handle = _hybrid(tmp_path)

    # Set the module global directly rather than reloading the module. A
    # reload rebinds AUTH_SECRET/AUTH_MODE from whatever the environment says
    # at that instant and leaves every other module holding the new object —
    # so a reload here (even in a finally) leaks a configured secret into every
    # test that runs afterwards. Verified the hard way: it turned one failure
    # into forty. Assign, then put it back exactly.
    original = ka.AUTH_SECRET
    ka.AUTH_SECRET = b"a-shared-secret"
    try:
        c = handle.app.test_client()
        forged = {"X-Remote-User": "mallory", "X-Remote-Groups": "atlas-admins"}
        assert c.get("/api/v2/lab-data", headers=forged).status_code == 401
        import redaction
        with handle.app.test_request_context("/", headers=forged):
            assert redaction.sees_everything(redaction.viewer_groups()) is False
    finally:
        ka.AUTH_SECRET = original


def _signed(secret, user, groups):
    """A valid X-Hub-Auth token, built the way hub_auth verifies it."""
    import base64
    import hashlib
    import hmac
    import json
    import time as _time
    now = _time.time()
    payload = json.dumps({"u": user, "g": groups,
                          "iat": now, "exp": now + 300}).encode()
    b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(secret, b64.encode(), hashlib.sha256).digest()
    return f"{b64}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def test_hybrid_accepts_the_hubs_signed_identity(tmp_path):
    """The other half of the rule above: refusing the forgeable header is only
    correct if the SIGNED identity still works, or hybrid would have no Hub SSO
    left at all. Same header names, a real signature, and the admin group in the
    token is admin."""
    import hub_auth.auth as ka
    handle = _hybrid(tmp_path)
    secret = b"a-shared-secret"
    original = ka.AUTH_SECRET
    ka.AUTH_SECRET = secret          # assign/restore, never reload — see above
    try:
        c = handle.app.test_client()
        token = _signed(secret, "ops", ["atlas-admins"])
        assert c.get("/api/v2/lab-data",
                     headers={"X-Hub-Auth": token}).status_code == 200
        import redaction
        with handle.app.test_request_context("/", headers={"X-Hub-Auth": token}):
            assert redaction.sees_everything(redaction.viewer_groups()) is True
    finally:
        ka.AUTH_SECRET = original


def _token(secret, **claims):
    """A signed token with whatever claims the test wants — the shape
    `_signed` builds, with the clock in the caller's hands."""
    import base64
    import hashlib
    import hmac
    import json
    b64 = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    sig = hmac.new(secret, b64.encode(), hashlib.sha256).digest()
    return f"{b64}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def test_a_signed_token_may_not_claim_a_long_life():
    """2026-11-01: the Atlas accepted whatever `exp` the Hub minted, so a Hub
    bug (or a captured token with a generous lifetime) set the replay window.
    Now `exp - iat` is capped server-side."""
    import time
    import hub_auth.auth as ka
    secret = b"a-shared-secret"
    original = ka.AUTH_SECRET
    ka.AUTH_SECRET = secret
    try:
        now = time.time()
        assert ka.verify_token(_token(secret, u="ops", iat=now, exp=now + 120))["u"] == "ops"
        assert ka.verify_token(_token(secret, u="ops", iat=now, exp=now + ka._MAX_TTL)) is not None
        # a second of slop is allowed (a minter reading the clock twice); two is not
        assert ka.verify_token(_token(secret, u="ops", iat=now, exp=now + ka._MAX_TTL + 2)) is None
        assert ka.verify_token(_token(secret, u="ops", iat=now - 7200, exp=now + 60)) is None
    finally:
        ka.AUTH_SECRET = original


def test_a_malformed_claim_is_a_refusal_not_a_crash():
    """A correctly signed token with `"exp": "soon"` raised inside
    verify_token and 500'd the request; only the secret holder can mint one,
    so this is robustness — it must read as a plain refusal."""
    import time
    import hub_auth.auth as ka
    secret = b"a-shared-secret"
    original = ka.AUTH_SECRET
    ka.AUTH_SECRET = secret
    try:
        now = time.time()
        assert ka.verify_token(_token(secret, u="ops", iat=now, exp="soon")) is None
        assert ka.verify_token(_token(secret, u="ops", iat=None, exp=now + 60)) is None
        assert ka.verify_token(_token(secret, u="ops", iat=[1], exp=now + 60)) is None
    finally:
        ka.AUTH_SECRET = original


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── The gate must work under a path prefix, not just at the origin root ──────
#
# Twice now this sign-in has been decorative in a browser while the suite was
# green, because both failures live in the part the Flask test client does not
# execute: the CSP blocked the inline handler (2026-08-12), and then every
# fetch used an ABSOLUTE path (2026-08-18). The Atlas is served at "/" directly
# AND at "/atlas/" behind the Hub, which strips its prefix before proxying — so
# the server sees an empty SCRIPT_ROOT and cannot help. `fetch('/api/v2/auth/...')`
# therefore escaped the prefix, posted to the Hub's root, and 404'd: the Atlas
# logged no POST at all while a correct password read as "Sign-in failed."
#
# There is no request we can make here that would catch it. A static assertion
# on the shipped file is the honest guard.

def _login_js():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "static", "js", "login.js"), encoding="utf-8") as f:
        return f.read()


def test_login_js_derives_the_app_root_from_the_page_url():
    src = _login_js()
    assert "window.location.pathname.replace(" in src, (
        "login.js must derive the app root from the page URL — the server "
        "cannot tell it, because the Hub strips its prefix before proxying")


def _strip_js_comments(src):
    """Comments quote the very bug this guards against, so scan CODE only."""
    import re
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def test_login_js_never_fetches_an_absolute_api_path():
    """Absolute paths escape the /atlas/ prefix and hit the Hub instead."""
    import re
    src = _strip_js_comments(_login_js())
    bad = re.findall(r"fetch\(\s*['\"]/", src)
    assert not bad, (
        "login.js calls fetch() with an absolute path; under the Hub that "
        "leaves the app and 404s. Hang it off ROOT instead.")


def test_login_js_sends_every_call_through_the_prefixed_helper():
    src = _login_js()
    assert "fetch(ROOT + path" in src, (
        "every API call must go through the one ROOT-prefixed fetch")
    assert "NEXT = ROOT + NEXT" in src, (
        "the post-sign-in landing is Atlas-relative too — unprefixed it drops "
        "the surveyor on the Hub's root instead of the map")


# ── The same-origin write proof (replaced the per-session CSRF token) ───────
#
# `security.same_origin_refusal` is the one thing the whole app now uses to know
# a request came from its own page: a custom `X-Atlas-Write` header a
# cross-origin page cannot set without a preflight this app never answers, plus
# `Sec-Fetch-Site` as a cheap second signal. No token to mint or rotate, and
# nothing compares Origin against host_url — the bug that 403'd every direct
# sign-in behind the TLS front (v1.21.5) cannot recur because the value it got
# wrong is no longer read.

def test_same_origin_proof_accepts_a_same_origin_or_direct_request(realm):
    """same-origin (a fetch from the app's own page) and none (a direct
    navigation or a non-browser client) both pass with the header — wrong creds
    so 401, never the same-origin gate's 403."""
    c = realm.app.test_client()
    for site in ("same-origin", "none"):
        r = c.post("/api/v2/auth/login",
                   json={"username": "nobody", "password": "wrong"},
                   headers={**WRITE, "Sec-Fetch-Site": site})
        assert r.status_code == 401, site


def test_same_origin_proof_refuses_cross_site_or_a_missing_header(realm):
    """A cross-site fetch is refused even carrying the header, and a request
    with no write header at all is refused."""
    c = realm.app.test_client()
    r = c.post("/api/v2/auth/login", json={"username": "nobody", "password": "wrong"},
               headers={**WRITE, "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = c.post("/api/v2/auth/login", json={"username": "nobody", "password": "wrong"})
    assert r.status_code == 403


# ── The CSP must not describe the realm to a stranger (2026-08-19) ──────────
#
# `frame-src` is derived from the dataset, so it enumerates the internal
# service origins the map links to. Found live hours after the Atlas first
# answered on the public internet: an anonymous GET of the login page returned
# 36 origins, 8 of them internal hosts with their ports. The login wall was
# protecting the map's BODY while a response HEADER on the login page handed
# out the topology.
#
# These three assert the whole shape: withheld from strangers, still delivered
# to members, and untouched where the Atlas does not gate itself.

EMBED_SENTINEL = "https://chronicle.example.test"


@pytest.fixture
def embed_realm(tmp_path):
    """An accounts-mode realm whose CSP has something to leak."""
    handle = fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
        ATLAS_SECRET_KEY="test-signing-key",
        ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
        ATLAS_AUTH_BACKENDS="local",
        ATLAS_MFA_REQUIRED="",
        ATLAS_EMBED_HOSTS=EMBED_SENTINEL,
    )
    import accounts
    accounts.create_local_user("ops", PW, is_admin=True)
    return handle


def _frame_src_of(resp):
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "frame-src" in csp, "no frame-src in the CSP at all"
    return csp.split("frame-src", 1)[1].strip().rstrip(";")


def test_anonymous_csp_does_not_enumerate_the_realm(embed_realm):
    """The login page must describe nothing but itself.

    Asserted on the SHIPPED header rather than on a helper, because every way
    this gate has broken was invisible one layer up.
    """
    c = embed_realm.app.test_client()
    r = c.get("/auth/login")
    assert r.status_code == 200
    frame_src = _frame_src_of(r)
    assert frame_src == "'self'", (
        "an anonymous caller was handed the embed allowlist: " + frame_src)
    assert EMBED_SENTINEL not in r.headers.get("Content-Security-Policy", "")


def test_csp_carries_the_directives_default_src_does_not_govern(embed_realm):
    """`default-src` is no fallback for `base-uri`, `form-action` or
    `object-src` (2026-11-01 review): without them a stray <base> rewrites
    every relative URL and a form may post anywhere. Asserted on both sides
    of the gate, since the anonymous CSP is built separately."""
    c = embed_realm.app.test_client()
    for resp in (c.get("/auth/login"), c.get("/", follow_redirects=True)):
        csp = resp.headers.get("Content-Security-Policy", "")
        for directive in ("base-uri 'none'", "form-action 'self'", "object-src 'none'"):
            assert directive in csp, f"{directive!r} missing from {csp!r}"


def test_authenticated_csp_still_carries_the_embed_hosts(embed_realm):
    """...and the fix must not quietly neuter the panes it protects."""
    c = embed_realm.app.test_client()
    r, _ = _login(c, "ops")
    assert r.status_code == 200
    assert EMBED_SENTINEL in c.get("/").headers.get("Content-Security-Policy", ""), (
        "a signed-in viewer lost the embed allowlist — THE VIEWING GLASS "
        "would show a blank pane")


def test_hub_mode_gives_the_embed_list_only_to_a_known_caller(tmp_path):
    """The Hub is the gate, so a request it sent has an identity and gets the
    list. An unpublished port is the operator's promise, not this app's, so a
    request that reaches it directly does not (the 2026-11-01 review)."""
    handle = fresh_app(
        ATLAS_AUTH_MODE="hub",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_DATA_BACKEND="file",
        ATLAS_EMBED_HOSTS=EMBED_SENTINEL,
    )
    c = handle.app.test_client()
    r = c.get("/", headers={"X-Remote-User": "ops", "X-Remote-Groups": "atlas-admins"})
    assert EMBED_SENTINEL in r.headers.get("Content-Security-Policy", ""), (
        "a caller the Hub sent lost its embed allowlist")
    assert EMBED_SENTINEL not in c.get("/").headers.get("Content-Security-Policy", "")


# ── A name collision must not be distinguishable from a wrong password ──────
#
# `SourceConflict` (a directory identity and a local account claiming one name)
# is deliberately a ValueError so the login route refuses and logs loudly. That
# part was right. What was wrong was the STATUS CODE: it fell through to the
# "misconfigured" arm and answered 500, while a bad password answered 401.
#
# The body was already generic; the status code was not.
#
# NOT an anonymous enumeration oracle, though it was first written up as one:
# SourceConflict comes from upsert_ldap_user, which _try_backends only reaches
# AFTER the directory has accepted the password. A stranger probing usernames
# gets 401 for all of them. The 500 reached only a caller who had just proven
# they hold that account's AD credentials. Low severity - but a server-fault
# status for something that is not a server fault, so the tests below pin the
# refusal to look like every other refusal.

def test_source_conflict_is_indistinguishable_from_a_bad_password(realm, monkeypatch):
    import accounts as accounts_mod
    from api.v2 import accounts_v2 as auth_routes

    c = realm.app.test_client()

    # baseline: what a genuinely wrong password looks like, byte for byte
    r_bad, _ = _login(c, "ops", "definitely-not-the-password")
    bad_code, bad_body = r_bad.status_code, r_bad.get_data(as_text=True)
    assert bad_code == 401

    # now force the collision on the very next attempt
    def _boom(*_a, **_kw):
        raise accounts_mod.SourceConflict(
            "'ops' already exists as a local account; the directory identity "
            "of the same name was refused.")
    monkeypatch.setattr(auth_routes, "_try_backends", _boom)

    r_conf, _ = _login(c, "ops")
    assert r_conf.status_code == bad_code, (
        f"a source conflict answered {r_conf.status_code} where a wrong password "
        f"answers {bad_code} - the status code is an enumeration oracle")
    assert r_conf.get_data(as_text=True) == bad_body, (
        "the body differs from a wrong-password refusal, which leaks the same way")


def test_source_conflict_still_refuses_and_is_recorded(realm, monkeypatch):
    """Closing the oracle must not make the misconfiguration invisible."""
    import accounts as accounts_mod
    from api.v2 import accounts_v2 as auth_routes

    c = realm.app.test_client()

    def _boom(*_a, **_kw):
        raise accounts_mod.SourceConflict("collision")
    monkeypatch.setattr(auth_routes, "_try_backends", _boom)

    r, _ = _login(c, "ops")
    assert r.status_code == 401
    # no session was established - the whole point is that it REFUSES
    with c.session_transaction() as s:
        assert "user" not in s
    # and the operator can still see why, in the ledger the admin UI renders
    rows = accounts_mod.recent_audit(20) if hasattr(accounts_mod, "recent_audit") else []
    if rows:
        assert any("source conflict" in str(row) for row in rows), \
            "the audit trail should name the cause even though the caller is not told"


# ── The six routes on the most dangerous screen that had no test ────────────
# Each one is a write to an account or the ledger that
# records writes to accounts; every one must refuse a non-admin, a missing
# CSRF token, and the classic self/last-admin traps before it does anything.

def _users(client):
    return {u["username"]: u for u in client.get("/api/v2/auth/users").get_json()["users"]}


def test_change_password_rotates_the_credential_and_keeps_this_session(realm):
    c = realm.app.test_client()
    r, tok = _login(c, "alice")
    assert r.get_json()["ok"]

    def post(body):
        return c.post("/api/v2/auth/password", json=body, headers=WRITE)

    assert c.post("/api/v2/auth/password", json={}).status_code == 403     # no CSRF
    assert post({"current": "wrong", "new": "another-long-password"}).status_code == 401
    r = post({"current": PW, "new": "short"})
    assert r.status_code == 400 and "at least" in r.get_json()["error"]

    r = post({"current": PW, "new": "another-long-password"})
    assert r.status_code == 200 and r.get_json()["ok"]
    # the credential changed, the epoch bumped, and THIS session survived it
    assert c.get("/api/v2/auth/me").get_json()["authenticated"]
    other = realm.app.test_client()
    assert _login(other, "alice")[0].status_code == 401                 # old password
    assert _login(other, "alice", "another-long-password")[0].status_code == 200

    anon = realm.app.test_client()
    r = anon.post("/api/v2/auth/password", json={"current": PW, "new": "x" * 20},
                  headers=WRITE)
    assert r.status_code == 401


def test_deactivating_an_account_kills_its_sessions_and_its_logins(realm):
    admin = realm.app.test_client()
    _, tok = _login(admin, "ops")
    alice = realm.app.test_client()
    _login(alice, "alice")
    assert alice.get("/api/v2/auth/me").get_json()["authenticated"]

    r = admin.post("/api/v2/auth/users/alice/active", json={"on": False},
                   headers=WRITE)
    assert r.status_code == 200 and r.get_json()["ok"]
    assert _users(admin)["alice"]["active"] == 0
    assert not alice.get("/api/v2/auth/me").get_json()["authenticated"]    # epoch bumped
    assert _login(realm.app.test_client(), "alice")[0].status_code == 401

    r = admin.post("/api/v2/auth/users/alice/active", json={"on": True},
                   headers=WRITE)
    assert r.get_json()["ok"]
    assert _login(realm.app.test_client(), "alice")[0].status_code == 200

    # the traps: yourself, and nobody at all
    r = admin.post("/api/v2/auth/users/ops/active", json={"on": False},
                   headers=WRITE)
    assert r.status_code == 400 and "own account" in r.get_json()["error"]
    assert admin.post("/api/v2/auth/users/ganon/active", json={"on": False},
                      headers=WRITE).status_code == 404
    # and the gates: admin only, CSRF always
    plain = realm.app.test_client()
    _, ptok = _login(plain, "alice")
    assert plain.post("/api/v2/auth/users/ops/active", json={"on": False},
                      headers=WRITE).status_code == 403
    assert admin.post("/api/v2/auth/users/alice/active", json={"on": False}).status_code == 403


def test_assigning_groups_changes_what_a_viewer_sees_and_never_grants_admin(realm):
    admin = realm.app.test_client()
    _, tok = _login(admin, "ops")
    alice = realm.app.test_client()
    _login(alice, "alice")

    def ids():
        return {n["id"] for n in alice.get("/api/v2/lab-data").get_json()["nodes"]}

    assert "secret-place" not in ids()

    r = admin.post("/api/v2/auth/users/alice/groups", json={"groups": ["HUB-decoy"]},
                   headers=WRITE)
    assert r.status_code == 200 and r.get_json()["ok"]
    assert "secret-place" in ids()                       # clearance is live, no re-login
    assert _users(admin)["alice"]["groups_csv"] == "HUB-decoy"

    # the sentinel: atlas-admins is not a clearance group and must be refused
    r = admin.post("/api/v2/auth/users/alice/groups", json={"groups": ["atlas-admins"]},
                   headers=WRITE)
    assert r.status_code == 400 and "is_admin" in r.get_json()["error"]
    assert _users(admin)["alice"]["groups_csv"] == "HUB-decoy"       # unchanged
    assert not alice.get("/api/v2/auth/me").get_json()["is_admin"]
    assert alice.post("/api/v2/positions", json={}, headers={"X-Atlas-Write": "1"}).status_code == 403

    # directory accounts mirror the directory; their groups are not set here
    import accounts
    accounts.upsert_ldap_user("bob", groups=["HUB-Atlas"])
    r = admin.post("/api/v2/auth/users/bob/groups", json={"groups": ["HUB-decoy"]},
                   headers=WRITE)
    assert r.status_code == 400 and "local" in r.get_json()["error"]

    plain = realm.app.test_client()
    _, ptok = _login(plain, "alice")
    assert plain.post("/api/v2/auth/users/alice/groups", json={"groups": []},
                      headers=WRITE).status_code == 403
    assert admin.post("/api/v2/auth/users/alice/groups", json={"groups": []}).status_code == 403


def test_resetting_mfa_removes_the_factor_and_ends_the_sessions(realm):
    pyotp = pytest.importorskip("pyotp")
    import accounts
    secret, _, _ = accounts.start_mfa_enrollment("alice")
    accounts.confirm_mfa("alice", pyotp.TOTP(secret).now())

    alice = realm.app.test_client()
    r, ztok = _login(alice, "alice")
    assert r.get_json()["mfa_required"]
    import time as _time
    alice.post("/api/v2/auth/login/mfa",      # the next step: enrolment spent this one
               json={"code": pyotp.TOTP(secret).at(_time.time() + 30)}, headers=WRITE)
    assert alice.get("/api/v2/auth/me").get_json()["mfa_enabled"] is True

    admin = realm.app.test_client()
    _, tok = _login(admin, "ops")
    assert admin.post("/api/v2/auth/users/alice/reset-mfa").status_code == 403   # CSRF
    r = admin.post("/api/v2/auth/users/alice/reset-mfa", headers=WRITE)
    assert r.status_code == 200 and r.get_json()["ok"]
    assert _users(admin)["alice"]["mfa_enabled"] == 0
    assert not alice.get("/api/v2/auth/me").get_json()["authenticated"]   # a downgrade ends sessions
    r, _ = _login(realm.app.test_client(), "alice")
    assert r.status_code == 200 and r.get_json()["mfa_required"] is False

    assert admin.post("/api/v2/auth/users/ganon/reset-mfa",
                      headers=WRITE).status_code == 404
    plain = realm.app.test_client()
    _, ptok = _login(plain, "alice")
    assert plain.post("/api/v2/auth/users/ops/reset-mfa",
                      headers=WRITE).status_code == 403


def test_deleting_an_account_is_final_and_refuses_the_self_trap(realm):
    admin = realm.app.test_client()
    _, tok = _login(admin, "ops")
    alice = realm.app.test_client()
    _login(alice, "alice")

    assert admin.delete("/api/v2/auth/users/alice").status_code == 403          # CSRF
    r = admin.delete("/api/v2/auth/users/alice", headers=WRITE)
    assert r.status_code == 200 and r.get_json()["ok"]
    assert "alice" not in _users(admin)
    assert not alice.get("/api/v2/auth/me").get_json()["authenticated"]
    assert _login(realm.app.test_client(), "alice")[0].status_code == 401
    assert admin.delete("/api/v2/auth/users/alice", headers=WRITE).status_code == 404

    r = admin.delete("/api/v2/auth/users/ops", headers=WRITE)
    assert r.status_code == 400 and "own account" in r.get_json()["error"]
    assert "ops" in _users(admin)

    # a second admin may remove the first — the last-admin trap is about the
    # count, not the order of creation
    admin.post("/api/v2/auth/users", json={"username": "bob", "password": PW, "is_admin": True},
               headers=WRITE)
    bob = realm.app.test_client()
    _, itok = _login(bob, "bob")
    assert bob.delete("/api/v2/auth/users/ops", headers=WRITE).get_json()["ok"]
    # ...and then cannot remove itself, being the last
    r = bob.delete("/api/v2/auth/users/bob", headers=WRITE)
    assert r.status_code == 400


def test_the_sign_in_ledger_is_admin_only_and_clamps_its_limit(realm):
    anon = realm.app.test_client()
    assert anon.get("/api/v2/auth/audit").status_code == 401
    plain = realm.app.test_client()
    _login(plain, "alice")
    assert plain.get("/api/v2/auth/audit").status_code == 403

    admin = realm.app.test_client()
    _login(admin, "ops")
    r = admin.get("/api/v2/auth/audit")
    assert r.status_code == 200
    events = r.get_json()["events"]
    assert events and set(events[0]) == {"ts", "event", "username", "ip", "detail"}
    assert events[0]["event"] == "login_ok" and events[0]["username"] == "ops"   # newest first
    assert any(e["username"] == "alice" for e in events)

    assert len(admin.get("/api/v2/auth/audit?limit=1").get_json()["events"]) == 1
    assert len(admin.get("/api/v2/auth/audit?limit=0").get_json()["events"]) == 1      # clamped up
    assert len(admin.get("/api/v2/auth/audit?limit=abc").get_json()["events"]) == len(events)
    assert len(admin.get("/api/v2/auth/audit?limit=99999").get_json()["events"]) <= 500


def test_a_named_user_with_no_password_says_so_too(tmp_path, monkeypatch, caplog):
    """The compose file always names a user, so a blank password arrives here."""
    fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(_dataset(tmp_path)),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "nopass.db"),
        ATLAS_SECRET_KEY="k", ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
    )
    import accounts
    import auth_routes
    monkeypatch.setenv("ATLAS_BOOTSTRAP_ADMIN_USER", "admin")
    monkeypatch.setenv("ATLAS_BOOTSTRAP_ADMIN_PASSWORD", "")
    monkeypatch.delenv("ATLAS_BOOTSTRAP_ADMIN_PASSWORD_FILE", raising=False)
    with caplog.at_level("WARNING", logger="atlas.auth.routes"):
        auth_routes.ensure_bootstrap_admin()
    assert accounts.count_active_admins() == 0
    assert any("no admin account exists" in r.getMessage() for r in caplog.records)
