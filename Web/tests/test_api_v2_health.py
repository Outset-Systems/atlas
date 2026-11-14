"""`/api/v2/health`: reachable like `/api/status`, gated like nothing else.

Three things are proven here and nowhere else:

* the v2 namespace — every `/api/v2/` rule belongs to the `api_v2` blueprint
  and no other blueprint's endpoint wears that name;
* the gate — v2 is fronted by the app-wide `before_request` in every mode,
  with `health` the one exempt path;
* parity — `/api/v2/health` answers byte-for-byte what `/api/status` (the
  fleet card contract, the one unversioned API path kept at the v1 removal)
  does, signed out and signed in, through the harness in `tests/parity.py`.
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app, login_as  # noqa: E402
from parity import Call, assert_parity  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

# Non-empty so conftest snapshots/restores ATLAS_ENV per test; each fixture
# below sets its own mode explicitly through fresh_app().
ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

PW = "a-long-enough-password"


def _dataset(tmp_path):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    return data


@pytest.fixture
def standalone(tmp_path):
    return fresh_app(
        ATLAS_AUTH_MODE="standalone",
        ATLAS_DATA_BACKEND="file",
        ATLAS_DATA=str(_dataset(tmp_path)),
    )


@pytest.fixture
def realm(tmp_path):
    """An accounts-mode Atlas with one admin and one plain user — the same
    shape `test_auth_gate_routes.realm` builds."""
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


# ── The namespace ────────────────────────────────────────────────────────────

def test_v2_rules_are_namespaced_and_nothing_else_is(standalone):
    rules = list(standalone.app.url_map.iter_rules())
    v2 = [r for r in rules if r.rule.startswith("/api/v2/")]
    assert v2, "v2 is mounted"
    assert all(r.endpoint.startswith("api_v2.") for r in v2), \
        [r.endpoint for r in v2]
    strays = [r.endpoint for r in rules
              if r.endpoint.startswith("api_v2.") and not r.rule.startswith("/api/v2/")]
    assert strays == []
    v1_names = {r.endpoint for r in rules if not r.rule.startswith("/api/v2/")}
    assert not any(n.startswith("api_v2.") for n in v1_names)
    assert standalone.app.config["API_V2_ENABLED"] is True


# ── Standalone: no gate, same body as /api/status ───────────────────────────

def test_health_answers_the_card_contract(standalone):
    c = standalone.app.test_client()
    r = c.get("/api/v2/health")
    assert r.status_code == 200
    body = r.get_json()
    # `annalist` (2026-11-13): whether this worker's background poll runs and
    # when it last finished, added beside the card contract's own keys
    assert set(body) == {"app", "name", "version", "healthy", "summary", "card", "annalist"}
    assert set(body["annalist"]) == {"running", "last_tick"}
    assert body["app"] == "atlas"
    assert body["healthy"] is True
    assert body["summary"]["headline_label"] == "Places Charted"
    assert body["summary"]["headline_metric"] > 0


def test_health_has_parity_with_status_standalone(standalone):
    c = standalone.app.test_client()
    assert_parity(c, "/api/status", "/api/v2/health",
                  headers=("Content-Type", "Cache-Control"))


# ── Accounts mode: anonymous and signed-in ───────────────────────────────────

def test_anonymous_reaches_health_but_not_the_rest_of_v2(realm):
    c = realm.app.test_client()
    assert c.get("/api/v2/health").status_code == 200        # monitoring contract
    assert c.get("/api/status").status_code == 200           # …same as v1's
    # The gate fronts routing: an unknown v2 path is 401, not 404, signed out.
    r = c.get("/api/v2/does-not-exist")
    assert r.status_code == 401
    assert r.get_json() == {"error": "Unauthorized", "reason": "Sign in required"}


def test_anonymous_health_has_parity_with_status(realm):
    c = realm.app.test_client()
    assert_parity(c, "/api/status", "/api/v2/health",
                  headers=("Content-Type", "Cache-Control"))


def test_signed_in_health_has_parity_with_status(realm):
    c = realm.app.test_client()
    r, _ = login_as(c, "alice", PW)
    assert r.status_code == 200 and r.get_json()["ok"]
    assert_parity(c, "/api/status", "/api/v2/health",
                  headers=("Content-Type", "Cache-Control"))
    # and once signed in the rest of the namespace routes normally
    assert c.get("/api/v2/does-not-exist").status_code == 404


def test_admin_required_refuses_like_api_admin(realm):
    from api.v2.auth import admin_required, write_required
    from flask import jsonify

    @admin_required
    def reads():
        return jsonify({"ok": True})

    @write_required
    def writes():
        return jsonify({"ok": True})

    c = realm.app.test_client()
    login_as(c, "alice", PW)
    cookie = c.get_cookie("atlas_session").value
    with realm.app.test_request_context("/api/v2/x", headers={"Cookie": f"atlas_session={cookie}"}):
        resp, status = reads()
        assert status == 403 and resp.get_json() == {"error": "admins only"}
        resp, status = writes()
        assert status == 403 and "write header" in resp.get_json()["error"]

    login_as(c, "ops", PW)
    cookie = c.get_cookie("atlas_session").value
    with realm.app.test_request_context("/api/v2/x", headers={"Cookie": f"atlas_session={cookie}"}):
        assert reads().get_json() == {"ok": True}
        resp, status = writes()
        assert status == 403                 # admin, but no X-Atlas-Write
    with realm.app.test_request_context(
            "/api/v2/x", headers={"Cookie": f"atlas_session={cookie}", "X-Atlas-Write": "1"}):
        assert writes().get_json() == {"ok": True}


# ── Hub mode: the framework gate fronts v2 too ───────────────────────────────

def test_hub_mode_gates_v2_with_the_same_rule(tmp_path):
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
        assert c.get("/api/v2/health").status_code == 200
        r = c.get("/api/v2/does-not-exist")
        assert r.status_code == 403                          # header required
        assert r.get_json()["error"] == "Forbidden"
        assert c.get("/api/v2/does-not-exist",
                     headers={"X-Remote-User": "ops"}).status_code == 404
        assert_parity(c, "/api/status", "/api/v2/health")
        assert_parity(c, "/api/status", "/api/v2/health",
                      Call(headers={"X-Remote-User": "ops"}))
    finally:
        auth.AUTH_MODE = original


def test_bearer_token_is_read_one_way(realm):
    """Every token-taking route shares `security.bearer_token`: the scheme
    without regard to case, the token stripped, "" for anything else."""
    import security
    cases = {"Bearer abc": "abc", "bearer  abc ": "abc", "BEARER abc": "abc",
             "Basic abc": "", "Bearer": "", "": ""}
    for header, want in cases.items():
        with realm.app.test_request_context("/api/v2/health",
                                            headers={"Authorization": header}):
            assert security.bearer_token() == want, header
    with realm.app.test_request_context("/api/v2/health"):
        assert security.bearer_token() == ""
