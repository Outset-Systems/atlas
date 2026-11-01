"""The accounts credential store (accounts.py) — no Flask app involved."""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ATLAS_TEST_ENV = {}  # per-test env comes from the fixture below instead


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_ACCOUNTS_DB", str(tmp_path / "accounts.db"))
    monkeypatch.setenv("ATLAS_DATA", str(tmp_path / "lab-data.json"))
    import accounts
    return accounts


PW = "correct-horse-battery"


def test_create_and_verify(store):
    store.create_local_user("ops", PW, display_name="Ops", is_admin=True)
    assert store.verify_password("ops", PW)["username"] == "ops"
    assert store.verify_password("ops", "wrong-password-here") is None
    assert store.verify_password("nobody", PW) is None
    # normalisation: usernames are case-insensitive
    assert store.verify_password("OPS", PW)["username"] == "ops"


def test_password_rules(store):
    with pytest.raises(ValueError):
        store.create_local_user("ops", "short")
    with pytest.raises(ValueError):
        store.create_local_user("bad name!", PW)
    store.create_local_user("ops", PW)
    with pytest.raises(ValueError):
        store.create_local_user("ops", PW)  # duplicate


def test_ldap_rows_never_pass_local_verify(store):
    """The directory is the only credential authority for its rows — a local
    password check against an ldap row must fail, whatever is supplied."""
    store.upsert_ldap_user("alice", groups=["HUB-Atlas"])
    assert store.verify_password("alice", "") is None
    assert store.verify_password("alice", PW) is None
    with pytest.raises(ValueError):
        store.set_password("alice", PW)


def test_a_directory_identity_never_overwrites_a_local_account(store):
    """`ON CONFLICT(username) DO UPDATE` used to convert a LOCAL row into an
    ldap one the first time an AD user of the same name signed in.

    Both directions were bad. The local admin `link` lost `is_admin` to the
    directory's verdict AND its password (verify_password requires
    source='local'), so if it was the only admin, user management was locked
    for good — the recovery account, removed by someone else logging in. The
    other way round, an AD user landing on an existing local name inherited
    that account's identity. A name collision across two authorities is an
    operator's problem to resolve, not a login's to decide silently.
    """
    store.create_local_user("ops", PW, is_admin=True)

    with pytest.raises(store.SourceConflict):
        store.upsert_ldap_user("ops", groups=["HUB-Atlas"], is_admin=False)

    acc = store.get_user("ops")
    assert acc["source"] == "local"
    assert acc["is_admin"] == 1                      # still the admin
    assert store.verify_password("ops", PW)         # still has its password


def test_ldap_upsert_mirrors_directory(store):
    store.upsert_ldap_user("alice", groups=["HUB-Atlas"], is_admin=False)
    store.upsert_ldap_user("alice", groups=["HUB-Atlas", "atlas-surveyors"], is_admin=True)
    acc = store.get_user("alice")
    assert acc["is_admin"] == 1
    assert store.groups_of(acc) == ["HUB-Atlas", "atlas-surveyors"]
    # revocation mirrors too
    store.upsert_ldap_user("alice", groups=[], is_admin=False)
    assert store.get_user("alice")["is_admin"] == 0


def test_session_epoch_bumps(store):
    store.create_local_user("ops", PW)
    e0 = store.session_epoch("ops")
    store.set_password("ops", PW + "-2")
    assert store.session_epoch("ops") == e0 + 1
    store.set_active("ops", False)
    assert store.session_epoch("ops") == e0 + 2


def test_local_groups_assignment(store):
    store.create_local_user("bob", PW, groups=["HUB-Atlas"])
    assert store.groups_of(store.get_user("bob")) == ["HUB-Atlas"]
    store.set_groups("bob", ["HUB-Atlas", "HUB-decoy"])
    assert "HUB-decoy" in store.groups_of(store.get_user("bob"))


def test_reserved_admin_group_refused(store):
    """The sees_everything sentinel must never be assignable as a clearance
    group (the 2026-08-11 security review)."""
    with pytest.raises(ValueError):
        store.create_local_user("x", PW, groups=["atlas-admins"])
    store.create_local_user("bob", PW)
    with pytest.raises(ValueError):
        store.set_groups("bob", ["HUB-Atlas", "atlas-admins"])
    # a benign group still assigns fine
    store.set_groups("bob", ["HUB-Atlas"])
    assert store.groups_of(store.get_user("bob")) == ["HUB-Atlas"]


def test_throttle_per_user_and_ip(store):
    for _ in range(store.THROTTLE_USER_MAX):
        store.record_failure("ops", "10.0.0.1")
    assert store.throttled("ops", "10.0.0.9")          # user bucket, any IP
    assert not store.throttled("alice", "10.0.0.9")     # other user fine
    store.clear_failures("ops")
    assert not store.throttled("ops", "10.0.0.9")
    # ip bucket: spray many usernames from one address
    for i in range(store.THROTTLE_IP_MAX):
        store.record_failure(f"user{i}", "10.9.9.9")
    assert store.throttled("fresh-user", "10.9.9.9")


def test_mfa_roundtrip_and_backup_codes(store):
    pyotp = pytest.importorskip("pyotp")
    pytest.importorskip("cryptography")
    store.create_local_user("ops", PW)
    secret, uri, qr_svg = store.start_mfa_enrollment("ops")
    assert "svg" in qr_svg
    with pytest.raises(ValueError):
        store.confirm_mfa("ops", "000000")
    codes = store.confirm_mfa("ops", pyotp.TOTP(secret).now())
    assert len(codes) == store.BACKUP_CODE_COUNT
    acc = store.get_user("ops")
    assert acc["mfa_enabled"] == 1
    assert secret not in (acc["mfa_secret"] or "")      # encrypted at rest
    # the enrolment code is spent (2026-11-01); the next step signs in
    assert store.verify_mfa_or_backup("ops", pyotp.TOTP(secret).at(time.time() + 30))
    # a backup code works exactly once
    assert store.verify_mfa_or_backup("ops", codes[0])
    assert not store.consume_backup_code("ops", codes[0])
    # disable clears everything and bumps the epoch
    e = store.session_epoch("ops")
    store.disable_mfa("ops")
    assert store.session_epoch("ops") == e + 1
    assert not store.verify_mfa_code("ops", pyotp.TOTP(secret).now())


def test_a_totp_code_is_good_once(store):
    """v1.47.1: valid_window=1 accepted the same code for ~90 s and nothing
    recorded it — a code seen over a shoulder could be replayed."""
    pyotp = pytest.importorskip("pyotp")
    pytest.importorskip("cryptography")
    store.create_local_user("ops", PW)
    secret, _, _ = store.start_mfa_enrollment("ops")
    totp = pyotp.TOTP(secret)
    t0 = 1_800_000_000                                    # a fixed instant
    store.confirm_mfa("ops", totp.now())             # enrolment uses the real clock
    code = totp.at(t0)
    assert store.verify_mfa_code("ops", code, now=t0)
    assert not store.verify_mfa_code("ops", code, now=t0)          # replay
    assert not store.verify_mfa_code("ops", code, now=t0 + 25)     # still in window
    assert not store.verify_mfa_code("ops", totp.at(t0 - 30), now=t0)  # an older step
    assert store.verify_mfa_code("ops", totp.at(t0 + 30), now=t0 + 30)  # the next one is fine
    assert not store.verify_mfa_code("ops", "12a456", now=t0 + 60)     # junk
    # re-enrolment starts clean
    store.disable_mfa("ops")
    secret2, _, _ = store.start_mfa_enrollment("ops")
    store.confirm_mfa("ops", pyotp.TOTP(secret2).now())
    assert store.verify_mfa_code("ops", pyotp.TOTP(secret2).at(t0), now=t0)


def test_audit_appends(store):
    store.audit("login_ok", "ops", "10.0.0.1", "local")
    store.audit("logout", "ops", "10.0.0.1")
    tail = store.audit_tail()
    assert tail[0]["event"] == "logout"
    assert tail[1]["event"] == "login_ok"


def test_admin_counting(store):
    store.create_local_user("ops", PW, is_admin=True)
    store.create_local_user("alice", PW)
    assert store.count_active_admins() == 1
    store.set_active("ops", False)
    assert store.count_active_admins() == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── 2026-11-01 security review ───────────────────────────────────────────────

def test_schema_is_ensured_once_per_path(store, tmp_path, monkeypatch):
    """init_db ran four CREATE TABLEs and an index on EVERY accounts call —
    get_user is on the per-request auth path. Now a path is ensured once per
    process, keyed on the resolved path so a fresh DB still gets its schema."""
    store.create_local_user("ops", PW)
    with store._connect() as conn:                      # a later call must not rebuild it
        conn.execute("DROP TABLE login_throttle")
        conn.commit()
    assert store.get_user("ops")["username"] == "ops"
    with store._connect() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "login_throttle" not in tables
    # a different path is a different database and is born whole
    monkeypatch.setenv("ATLAS_ACCOUNTS_DB", str(tmp_path / "other.db"))
    assert store.get_user("ops") is None
    assert store.throttled("ops", "127.0.0.1") is False       # login_throttle exists here


def test_the_reserved_admin_group_never_lands_in_a_directory_row(store):
    """`_clean_groups` refuses the admin group on a local account; a directory
    row took whatever the directory said. The flag is the only admin path, so
    the name is dropped at the mirror — not raised, since a login is not the
    place to blow up."""
    reserved = store.RESERVED_ADMIN_GROUP
    acc = store.upsert_ldap_user("alice", groups=["HUB-Atlas", reserved, " "], is_admin=True)
    assert store.groups_of(acc) == ["HUB-Atlas"]
    assert acc["is_admin"] == 1


def test_the_enrollment_code_is_spent_at_the_next_login(store):
    """confirm_mfa used to clear mfa_last_step, so the very code just typed to
    enrol still opened a login for the rest of its window."""
    pyotp = pytest.importorskip("pyotp")
    pytest.importorskip("cryptography")
    import time
    store.create_local_user("ops", PW)
    secret, _, _ = store.start_mfa_enrollment("ops")
    totp = pyotp.TOTP(secret)
    t0 = time.time()
    store.confirm_mfa("ops", totp.at(t0))
    assert store.get_user("ops")["mfa_last_step"] == int(t0 // 30)
    assert not store.verify_mfa_code("ops", totp.at(t0), now=t0)           # replayed
    assert store.verify_mfa_code("ops", totp.at(t0 + 30), now=t0 + 30)     # the next one


def test_re_enrolment_over_a_live_factor_needs_proof(store):
    pyotp = pytest.importorskip("pyotp")
    pytest.importorskip("cryptography")
    store.create_local_user("ops", PW)
    secret, _, _ = store.start_mfa_enrollment("ops")
    store.confirm_mfa("ops", pyotp.TOTP(secret).now())
    with pytest.raises(ValueError, match="already enabled"):
        store.start_mfa_enrollment("ops")
    assert store.get_user("ops")["mfa_pending_secret"] is None       # nothing was overwritten
    secret2, _, _ = store.start_mfa_enrollment("ops", reauthenticated=True)
    assert secret2 != secret


def test_a_backup_code_burns_in_the_statement_that_checks_it(store, monkeypatch):
    """Check-then-update let two workers both accept one code. The UPDATE now
    carries `AND used = 0` and only a changed row is a sign-in: here another
    worker burns the row between the match and the update."""
    pytest.importorskip("pyotp")
    pytest.importorskip("cryptography")
    store.create_local_user("ops", PW)
    codes = store.generate_backup_codes("ops")
    real = store.check_password_hash

    def other_worker_wins(code_hash, code):
        ok = real(code_hash, code)
        if ok:
            with store._connect() as conn:
                conn.execute("UPDATE mfa_backup_codes SET used = 1 WHERE username = 'ops'")
                conn.commit()
        return ok

    monkeypatch.setattr(store, "check_password_hash", other_worker_wins)
    assert not store.consume_backup_code("ops", codes[0])
    monkeypatch.setattr(store, "check_password_hash", real)
    assert store.consume_backup_code("ops", codes[1]) is False     # burnt above too
