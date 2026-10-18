"""Key handling that used to fail silently.

Two of these are the same mistake in different places: something the deployment
asked for could not be honoured, and the app carried on as if it had been. A
key file that failed to mount became an auto-generated key in a directory
nobody backs up; a value that would not decrypt came back as its own
ciphertext. Both then surfaced far away from the cause — as an unopenable
accounts.db after a restore, or as "incorrect code" at an MFA prompt.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Non-empty on purpose — conftest only snapshots and restores the Atlas
#: environment for a module that declares one, and these tests repoint
#: ATLAS_DATA and the encryption keys.
ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "standalone"}


@pytest.fixture
def crypto(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA", str(tmp_path / "lab-data.json"))
    monkeypatch.delenv("ATLAS_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ATLAS_ENCRYPTION_KEY_FILE", raising=False)
    import crypto_at_rest
    crypto_at_rest._fernet = crypto_at_rest._fernet_key = None
    yield crypto_at_rest
    crypto_at_rest._fernet = crypto_at_rest._fernet_key = None


def test_round_trip(crypto):
    assert crypto.decrypt_text(crypto.encrypt_text("JBSWY3DPEB")) == "JBSWY3DPEB"
    assert crypto.encrypt_text("") == ""
    assert crypto.decrypt_text(None) is None


def test_a_value_that_was_never_encrypted_passes_through(crypto):
    """The migration affordance: rows written before this module existed hold a
    bare base32 TOTP secret. That must keep working — it is the reason the
    swallow was there in the first place."""
    assert crypto.decrypt_text("JBSWY3DPEHPK3PXP") == "JBSWY3DPEHPK3PXP"


def test_a_real_token_that_will_not_open_raises(crypto, monkeypatch):
    """...but a value that IS a Fernet token and still will not decrypt means
    the master key is not the one it was written with. Returning the ciphertext
    sent it on to pyotp, which raised a binascii error out of the MFA route as
    a 500 — or, on the enrollment path, was caught and shown to the user as
    "Incorrect code". Nothing said the key had changed."""
    token = crypto.encrypt_text("JBSWY3DPEB")
    assert token.startswith("gAAAAA")

    from cryptography.fernet import Fernet
    monkeypatch.setenv("ATLAS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto._fernet = crypto._fernet_key = None

    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_text(token)


def test_a_key_file_that_failed_to_mount_is_fatal(crypto, monkeypatch, tmp_path):
    """Set-but-unusable must not fall through to auto-generation. An empty file
    is exactly what a docker secret that failed to mount looks like, and the
    old fallthrough left the operator believing they had supplied their own key
    while the real one went to `<data-dir>/secrets/master.key` — a path that is
    in no backup, so the next restore produced an accounts.db nobody could open.
    """
    empty = tmp_path / "not-mounted"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("ATLAS_ENCRYPTION_KEY_FILE", str(empty))
    crypto._fernet = crypto._fernet_key = None
    with pytest.raises(crypto.KeyUnavailable):
        crypto.encrypt_text("anything")

    monkeypatch.setenv("ATLAS_ENCRYPTION_KEY_FILE", str(tmp_path / "absent"))
    crypto._fernet = crypto._fernet_key = None
    with pytest.raises(crypto.KeyUnavailable):
        crypto.encrypt_text("anything")

    assert not (tmp_path / "secrets" / "master.key").exists()


def test_an_unasked_deployment_still_generates_one(crypto):
    """The zero-ceremony path is untouched: ask for nothing, get a key."""
    assert crypto.decrypt_text(crypto.encrypt_text("secret")) == "secret"


# ── the session key ──────────────────────────────────────────────────────────

def test_concurrent_workers_agree_on_one_session_key(tmp_path):
    """Gunicorn forks its workers and each runs create_app() at import (there
    is no --preload). On a fresh install every worker found no key file, and
    the old read-or-generate wrote a DIFFERENT key from each — so the workers
    disagreed about every session cookie's signature and a signed-in user was
    logged out on roughly every other request.

    The create is O_CREAT|O_EXCL now, and losing the race means reading the
    winner's key. Simulated here by calling it repeatedly against one path,
    which is the same question: does the second caller adopt the first's key?
    """
    import app as app_module
    key_file = str(tmp_path / "secrets" / "session.key")
    keys = {app_module._generated_session_key(key_file) for _ in range(5)}
    assert len(keys) == 1
    with open(key_file, encoding="utf-8") as f:
        assert f.read().strip() == keys.pop()


def test_an_existing_session_key_is_reused(tmp_path):
    import app as app_module
    key_file = tmp_path / "secrets" / "session.key"
    key_file.parent.mkdir(parents=True)
    key_file.write_text("a-key-from-an-earlier-boot", encoding="utf-8")
    assert app_module._generated_session_key(str(key_file)) == \
        "a-key-from-an-earlier-boot"


# ── the master key (v1.47.1) ─────────────────────────────────────────────────

def test_concurrent_workers_agree_on_one_master_key(tmp_path):
    """The session-key race, on the key that matters more: two workers on a
    fresh install each wrote their own master key and kept it, so MFA secrets
    were encrypted under a key that was no longer on disk. Real threads, one
    barrier, one path — every caller must come back with the same key."""
    import threading

    import crypto_at_rest
    pytest.importorskip("cryptography")
    key_file = str(tmp_path / "secrets" / "master.key")
    barrier, keys = threading.Barrier(8), []

    def worker():
        barrier.wait()
        keys.append(crypto_at_rest._generated_master_key(key_file))
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(keys)) == 1
    with open(key_file, "rb") as f:
        assert f.read().strip() == keys[0]


def test_a_reader_waits_for_a_master_key_being_written(tmp_path):
    """The loser of the create race can find the file before the winner has
    written it — it must wait for the real key, not invent one."""
    import threading
    import time

    import crypto_at_rest
    key_file = tmp_path / "secrets" / "master.key"
    key_file.parent.mkdir(parents=True)
    key_file.write_bytes(b"")                       # created, not yet written

    def finish():
        time.sleep(0.3)
        key_file.write_bytes(b"the-winners-key")
    threading.Thread(target=finish).start()
    assert crypto_at_rest._generated_master_key(str(key_file)) == b"the-winners-key"


def test_a_master_key_that_stays_empty_is_fatal_not_replaced(tmp_path):
    import crypto_at_rest
    key_file = tmp_path / "secrets" / "master.key"
    key_file.parent.mkdir(parents=True)
    key_file.write_bytes(b"")
    with pytest.raises(crypto_at_rest.KeyUnavailable):
        crypto_at_rest._generated_master_key(str(key_file), wait_s=0.2)
    assert key_file.read_bytes() == b""             # nothing written over it


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
