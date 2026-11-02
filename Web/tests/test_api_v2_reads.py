"""Map reads — `/api/v2/lab-data`, `/api/v2/maps`.

The two reads the map lives on: body shape, the cache-safety headers
(`Cache-Control: private, no-cache` + the viewer `Vary`), the ETag/304, and
the gate in front of them — signed out, signed in as a plain user and as an
admin, and in hub mode.
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


def _assert_private_read(r):
    assert r.status_code == 200
    assert r.mimetype == "application/json"
    assert r.headers["Cache-Control"] == "private, no-cache"
    vary = r.headers.get("Vary", "")
    for header in ("Cookie", "X-Hub-Auth", "X-Remote-User", "X-Remote-Groups"):
        assert header in vary, vary


# ── Standalone: no gate ──────────────────────────────────────────────────────

def test_lab_data_is_the_map(standalone):
    r = standalone.app.test_client().get("/api/v2/lab-data")
    _assert_private_read(r)
    body = r.get_json()
    assert body["nodes"] and body["zones"]
    assert {n["id"] for n in body["nodes"]} >= {"app-host", "nas"}


def test_maps_lists_the_renders(standalone):
    r = standalone.app.test_client().get("/api/v2/maps")
    _assert_private_read(r)
    maps = r.get_json()["maps"]
    assert maps and set(maps[0]) == {"name", "label", "url", "default", "theme", "regions", "bright", "words", "tripwire", "places", "zones", "zoom"}
    assert sum(1 for m in maps if m["default"]) == 1


def test_lab_data_etag_drives_304(standalone):
    c = standalone.app.test_client()
    r = c.get("/api/v2/lab-data")
    etag = r.headers.get("ETag")
    assert etag, "lab-data must carry an ETag"
    r2 = c.get("/api/v2/lab-data", headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.get_data() == b""
    assert "Cookie" in r2.headers.get("Vary", "")     # the conditional path keeps it


# ── Accounts: anonymous, plain user, admin ───────────────────────────────────

def test_lab_data_is_gated_when_signed_out(realm):
    c = realm.app.test_client()
    r = c.get("/api/v2/lab-data")
    assert r.status_code == 401
    assert r.get_json() == {"error": "Unauthorized", "reason": "Sign in required"}
    assert c.get("/api/v2/maps").status_code == 401


def test_plain_user_and_admin_read_with_different_etags(realm):
    c = realm.app.test_client()
    r, _ = login_as(c, "alice", PW)
    assert r.status_code == 200 and r.get_json()["ok"]
    plain = c.get("/api/v2/lab-data")
    _assert_private_read(plain)
    _assert_private_read(c.get("/api/v2/maps"))

    c2 = realm.app.test_client()
    login_as(c2, "ops", PW)
    admin = c2.get("/api/v2/lab-data")
    _assert_private_read(admin)
    # clearance is part of the tag: the two viewers never share a cache entry
    assert plain.headers["ETag"] != admin.headers["ETag"]


# ── Hub mode: the framework gate fronts the reads ────────────────────────────

def test_hub_mode_reads(tmp_path):
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
        assert c.get("/api/v2/lab-data").status_code == 403       # header required
        hdrs = {"X-Remote-User": "ops"}
        _assert_private_read(c.get("/api/v2/lab-data", headers=hdrs))
        _assert_private_read(c.get("/api/v2/maps", headers=hdrs))
    finally:
        auth.AUTH_MODE = original
