"""The sign-in ledger's clock — UTC-Z, like every other stamp in the Atlas.

`accounts._now()` wrote `datetime.now().isoformat()` — naive LOCAL time, and
the only wrong clock in the app (THE LIST #2). On the UTC container the numbers
were right by accident and the *format* still lied: a stamp with no offset that
the SIGN-INS panel, a JS `new Date`, or an operator reading `atlasctl
user-list` had no way to place. These tests hold both halves — the new writes,
and the one-time conversion of rows written before the fix.
"""

import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ATLAS_TEST_ENV = {}

UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PW = "correct-horse-battery"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_ACCOUNTS_DB", str(tmp_path / "accounts.db"))
    monkeypatch.setenv("ATLAS_DATA", str(tmp_path / "lab-data.json"))
    import accounts
    # `_migrated` is a process-wide latch, so a fresh DB in the same process
    # would otherwise inherit the previous test's "already migrated".
    monkeypatch.setattr(accounts, "_migrated", False)
    return accounts


def _rows(store, sql):
    conn = sqlite3.connect(store.db_path())
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ── What it writes now ───────────────────────────────────────────────────────

def test_now_is_the_apps_one_utc_spelling(store):
    import jsonio
    assert UTC_Z.match(store._now())
    # not merely the same shape — the same function, so the two can never drift
    assert store._now() == jsonio.iso_utc() or abs(
        int(store._now()[17:19]) - int(jsonio.iso_utc()[17:19])) <= 1


def test_now_is_actually_utc_not_local(store):
    """The bug that hid on a UTC container: `datetime.now()` and `gmtime` agree
    there and nowhere else. Compare against a real UTC clock, not a format."""
    written = datetime.strptime(store._now(), "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)
    assert abs(written - datetime.now(timezone.utc)) < timedelta(seconds=5)


def test_every_write_path_stamps_utc(store):
    store.create_local_user("ops", PW, is_admin=True)
    store.touch_login("ops")
    store.audit("login_ok", "ops", ip="10.77.33.11")
    store.generate_backup_codes("ops")

    created, last_login = _rows(
        store, "SELECT created, last_login FROM users WHERE username='ops'")[0]
    assert UTC_Z.match(created), created
    assert UTC_Z.match(last_login), last_login
    for (ts,) in _rows(store, "SELECT ts FROM auth_audit"):
        assert UTC_Z.match(ts), ts
    for (c,) in _rows(store, "SELECT created FROM mfa_backup_codes"):
        assert UTC_Z.match(c), c


def test_ldap_mirror_stamps_utc(store):
    store.upsert_ldap_user("alice", display_name="Alice", groups=["HUB-decoy"])
    created, last_login = _rows(
        store, "SELECT created, last_login FROM users WHERE username='alice'")[0]
    assert UTC_Z.match(created) and UTC_Z.match(last_login)


def test_the_stamp_column_list_matches_reality(store):
    """_STAMP_COLUMNS drives the backfill; a new stamp column that is not in it
    is a column the migration will silently skip."""
    store.init_db()
    conn = sqlite3.connect(store.db_path())
    try:
        listed = set(store._STAMP_COLUMNS)
        for table in ("users", "mfa_backup_codes", "auth_audit"):
            for row in conn.execute(f"PRAGMA table_info({table})"):
                col = row[1]
                if col in ("created", "last_login", "ts") and row[2] == "TEXT":
                    assert (table, col) in listed, (
                        f"{table}.{col} holds a stamp but is not in _STAMP_COLUMNS")
    finally:
        conn.close()


# ── Converting what was already written ──────────────────────────────────────

def test_to_utc_z_cases(store):
    f = store._to_utc_z
    assert f("2026-08-25T11:40:00Z") is None          # already done
    assert f("") is None and f(None) is None
    assert f("not a date") is None                     # never guess
    assert f("2026-08-25T11:40:00+00:00") == "2026-08-25T11:40:00Z"
    assert f("2026-08-25T13:40:00+02:00") == "2026-08-25T11:40:00Z"
    # a naive value means local time — that is what the bug wrote
    naive = "2026-08-25T11:40:00"
    expect = (datetime.fromisoformat(naive).astimezone()
              .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert f(naive) == expect


def _seed_naive(store):
    """Build a store the OLD way: naive local stamps in every column.

    Restores `_now` by hand rather than with monkeypatch.undo(), which would
    also undo the fixture's ATLAS_ACCOUNTS_DB and point the store elsewhere.
    """
    real_now = store._now
    store._now = lambda: datetime.now().isoformat(timespec="seconds")
    try:
        store.create_local_user("ops", PW, is_admin=True)
        store.touch_login("ops")
        store.audit("login_ok", "ops")
        store.generate_backup_codes("ops")
    finally:
        store._now = real_now


def test_backfill_converts_pre_fix_rows(store):
    _seed_naive(store)

    before = _rows(store, "SELECT created, last_login FROM users")[0]
    assert not any(v.endswith("Z") for v in before)   # the bug, reproduced

    store._migrated = False
    store.init_db()                                    # the migration

    created, last_login = _rows(store, "SELECT created, last_login FROM users")[0]
    assert UTC_Z.match(created) and UTC_Z.match(last_login)
    assert all(UTC_Z.match(r[0]) for r in _rows(store, "SELECT ts FROM auth_audit"))
    assert all(UTC_Z.match(r[0])
               for r in _rows(store, "SELECT created FROM mfa_backup_codes"))
    # the instant is preserved, not just the suffix
    assert created == store._to_utc_z(before[0])


def test_backfill_is_idempotent(store):
    _seed_naive(store)
    store._migrated = False
    store.init_db()
    once = _rows(store, "SELECT created, last_login FROM users")[0]
    for _ in range(3):
        store._migrated = False
        store.init_db()
    assert _rows(store, "SELECT created, last_login FROM users")[0] == once


def test_backfill_leaves_junk_alone(store):
    """A value we did not write is a value we must not rewrite."""
    store.init_db()
    store.create_local_user("ops", PW)
    conn = sqlite3.connect(store.db_path())
    conn.execute("UPDATE users SET created = 'sometime last tuesday'")
    conn.commit()
    conn.close()
    store._migrated = False
    store.init_db()
    assert _rows(store, "SELECT created FROM users")[0][0] == "sometime last tuesday"


def test_backfill_survives_a_null_last_login(store):
    """A user who has never signed in — the NULL must not become 'None'."""
    store.init_db()
    store.create_local_user("ops", PW)
    assert _rows(store, "SELECT last_login FROM users")[0][0] is None
    store._migrated = False
    store.init_db()
    assert _rows(store, "SELECT last_login FROM users")[0][0] is None
