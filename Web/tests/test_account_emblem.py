"""The emblem — the mark an account wears beside its name (2026-08-16).

Cosmetic, but it crosses two boundaries worth pinning: it is stored ON the
account (so it needs a real Atlas session and CSRF, like every self-service
route), and it must survive the accounts.db migration — every live database
predates the column.
"""

import json
import os
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

from appfixture import fresh_app  # noqa: E402

PW = "correct-horse-battery"
WRITE = {"X-Atlas-Write": "1"}

ATLAS_TEST_ENV = {
    "ATLAS_DATA_BACKEND": "file",
    "ATLAS_AUTH_MODE": "accounts",
}
os.environ.update(ATLAS_TEST_ENV)


@pytest.fixture
def realm(tmp_path):
    data = {"meta": {"title": "t"}, "zones": [], "nodes": [], "routes": []}
    path = tmp_path / "lab-data.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    handle = fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(path),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
        ATLAS_SECRET_KEY="test-signing-key",
        ATLAS_INSECURE_COOKIES="1",
        ATLAS_AUTH_BACKENDS="local",
        ATLAS_MFA_REQUIRED="",
    )
    import accounts
    accounts.create_local_user("ops", PW, is_admin=True)
    return handle


def _login(client, username="ops"):
    from appfixture import login_as
    return login_as(client, username, PW)[1]


def test_the_column_migrates_onto_an_old_database(tmp_path, monkeypatch):
    """init_db must ALTER an existing users table — CREATE IF NOT EXISTS never
    revisits, and every live accounts.db predates the emblem. This builds a
    REAL pre-emblem schema first; a fresh DB only exercises CREATE."""
    import sqlite3
    import accounts
    old_db = tmp_path / "pre-emblem.db"
    with sqlite3.connect(old_db) as conn:
        conn.execute("""CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'local',
            password_hash TEXT, groups_csv TEXT NOT NULL DEFAULT '',
            is_admin INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
            mfa_enabled INTEGER NOT NULL DEFAULT 0, mfa_secret TEXT,
            mfa_pending_secret TEXT, session_epoch INTEGER NOT NULL DEFAULT 0,
            created TEXT NOT NULL, last_login TEXT)""")
        conn.execute("INSERT INTO users (username, created) VALUES ('old-soul', 'then')")
    monkeypatch.setenv("ATLAS_ACCOUNTS_DB", str(old_db))
    monkeypatch.setattr(accounts, "_migrated", False)   # once-per-process gate
    accounts.init_db()
    row = accounts.get_user("old-soul")
    assert row is not None and row.get("emblem") == ""


def test_an_account_wears_and_sheds_its_mark(realm):
    c = realm.app.test_client()
    tok = _login(c)
    r = c.post("/api/v2/auth/me/emblem", json={"emblem": "🗡"},
               headers=WRITE)
    assert r.status_code == 200 and r.get_json()["ok"]
    import accounts
    assert accounts.get_user("ops")["emblem"] == "🗡"
    # the roster carries it too — the admin panel renders from list_users
    assert any(u["username"] == "ops" and u.get("emblem") == "🗡"
               for u in accounts.list_users())
    # shed it
    r = c.post("/api/v2/auth/me/emblem", json={"emblem": ""},
               headers=WRITE)
    assert r.status_code == 200
    assert accounts.get_user("ops")["emblem"] == ""


def test_a_mark_is_not_a_sentence(realm):
    c = realm.app.test_client()
    tok = _login(c)
    r = c.post("/api/v2/auth/me/emblem", json={"emblem": "x" * 9},
               headers=WRITE)
    assert r.status_code == 400


def test_no_session_no_mark(realm):
    c = realm.app.test_client()
    r = c.post("/api/v2/auth/me/emblem", json={"emblem": "🗡"}, headers=WRITE)
    assert r.status_code == 401


def test_no_write_header_no_mark(realm):
    """The same-origin proof is required: signed in, but no X-Atlas-Write."""
    c = realm.app.test_client()
    _login(c)
    r = c.post("/api/v2/auth/me/emblem", json={"emblem": "🗡"})
    assert r.status_code == 403


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
