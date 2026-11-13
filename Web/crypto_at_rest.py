"""Symmetric at-rest encryption for the accounts store's TOTP secrets and the
saved source keys (`integrations.py`).

Protects a compromised disk/backup, not the running app — verifying a TOTP
code needs the plaintext secret, so this is not end-to-end encryption. Same
mechanism a sibling app uses for its provider keys and MFA secrets.

Key precedence: ATLAS_ENCRYPTION_KEY env, then ATLAS_ENCRYPTION_KEY_FILE
(a file-mounted docker secret), else a key auto-generated once into
`<data-dir>/secrets/master.key` (0600). The auto path keeps a fresh
self-hosted install working with zero ceremony; production mounts its own.

The auto path is only for a deployment that asked for NOTHING. If
ATLAS_ENCRYPTION_KEY_FILE is set but unreadable or empty, that is a failed
mount and it raises `KeyUnavailable` rather than quietly generating a
different key somewhere the operator is not backing up.

`cryptography` is imported lazily — a deployment needs it installed once an
account enrolls a second factor (accounts or hybrid mode) or a source key is
saved, in any mode.
"""

import logging
import os

log = logging.getLogger("atlas.auth.crypto")

_fernet = None
_fernet_key = None

#: Every Fernet token starts with the 0x80 version byte, which is `gAAAAA` once
#: urlsafe-base64'd. It is how a value that FAILED to decrypt can be told apart
#: from one that was never encrypted (see `decrypt_text`).
_FERNET_PREFIX = "gAAAAA"


class KeyUnavailable(RuntimeError):
    """The deployment named a key file that cannot be used."""


class DecryptionError(RuntimeError):
    """A real Fernet token would not open — almost always the wrong master key."""


def _key_file_path():
    import settings   # live: follows ATLAS_DATA, as the tests re-point it
    return os.path.join(settings.data_dir(), "secrets", "master.key")


def _load_key() -> bytes:
    env_key = (os.environ.get("ATLAS_ENCRYPTION_KEY") or "").strip()
    if env_key:
        return env_key.encode("utf-8")
    path = (os.environ.get("ATLAS_ENCRYPTION_KEY_FILE") or "").strip()
    if path:
        # Set-but-unusable must NOT fall through to auto-generation. A docker
        # secret that failed to mount, an empty file, or a path pointing at a
        # directory all look exactly like this, and the old fallthrough left the
        # deployment believing it had supplied its own key while the real one
        # was written to `<data-dir>/secrets/master.key` — a path that is in no
        # backup, so the next restore produced an accounts.db nobody could open.
        try:
            with open(path, "rb") as f:
                data = f.read().strip()
        except OSError as e:
            raise KeyUnavailable(
                f"ATLAS_ENCRYPTION_KEY_FILE={path!r} could not be read ({e}). "
                f"Refusing to auto-generate a different key over the top of a "
                f"deployment that supplied its own.") from e
        if not data:
            raise KeyUnavailable(
                f"ATLAS_ENCRYPTION_KEY_FILE={path!r} is empty — that is a "
                f"secret that failed to mount, not a key.")
        return data
    return _generated_master_key(_key_file_path())


def _generated_master_key(key_file, wait_s=2.5):
    """Read the generated master key, creating it if this process is first.

    v1.47.1: this was a plain exists-check-then-write — the race already fixed
    for session.key (app._generated_session_key). Gunicorn's two workers start
    together on a fresh install; both could find no file, both write, and each
    keep the key IT generated. A session key lost that way logs people out; a
    master key lost that way makes every MFA secret encrypted under it
    unrecoverable. So: `O_CREAT | O_EXCL` decides one winner, the loser reads
    the winner's key, and a reader that finds the file created but still empty
    (the winner mid-write) waits for it. It NEVER falls back to a key of its
    own — that would be the bug again — it raises instead.
    """
    import time
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    deadline = time.monotonic() + wait_s
    while True:
        try:
            with open(key_file, "rb") as f:
                data = f.read().strip()
            if data:
                return data
        except FileNotFoundError:
            from cryptography.fernet import Fernet
            key = Fernet.generate_key()
            try:
                fd = os.open(key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                continue                     # another worker won; read theirs
            with os.fdopen(fd, "wb") as f:
                f.write(key)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass
            # log, not print: under gunicorn a print bypasses the configured
            # format and every aggregator's level filter — and this is the one
            # line an operator must not miss (2026-08-21)
            log.warning("generated a new master key at %s -- back this up; losing it "
                        "makes encrypted MFA secrets unrecoverable. Set "
                        "ATLAS_ENCRYPTION_KEY(_FILE) to supply your own key instead.",
                        key_file)
            return key
        if time.monotonic() >= deadline:
            raise KeyUnavailable(
                f"{key_file} exists but stayed empty for {wait_s}s — refusing to "
                f"generate a second master key over it.")
        time.sleep(0.05)                     # created but not yet written


def _fernet_instance():
    """Rebuilds when the resolved key changes — tests point ATLAS_DATA at a
    fresh tmp dir per suite, and a cached Fernet from the previous suite's
    auto-generated key would silently fail to decrypt the new suite's rows."""
    global _fernet, _fernet_key
    key = _load_key()
    if _fernet is None or key != _fernet_key:
        from cryptography.fernet import Fernet
        _fernet = Fernet(key)
        _fernet_key = key
    return _fernet


def encrypt_text(plaintext):
    """None-safe; empty stays empty (nothing to protect)."""
    if not plaintext:
        return plaintext
    return _fernet_instance().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(ciphertext):
    """Decrypt a stored value.

    A value that was never encrypted (a row written before this module existed
    — a bare base32 TOTP secret) is returned unchanged, which is what makes the
    migration seamless. But a value that IS a Fernet token and still will not
    open means the master key is not the one it was written with, and returning
    the ciphertext for that case turned a key problem into a mystery: the
    ciphertext went on to `pyotp.TOTP(...)`, which raised a binascii error out
    of `/api/auth/login/mfa` as a 500, while `confirm_mfa`'s caller caught it
    and told the user "incorrect code". Nothing anywhere said the key changed.
    """
    if not ciphertext:
        return ciphertext
    from cryptography.fernet import InvalidToken
    try:
        return _fernet_instance().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as e:
        if str(ciphertext).startswith(_FERNET_PREFIX):
            log.error("could not decrypt a stored secret — the master key is "
                      "not the one it was encrypted with")
            raise DecryptionError(
                "a stored secret could not be decrypted with the current "
                "master key") from e
        return ciphertext      # never encrypted; pre-encryption row
