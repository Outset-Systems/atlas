import logging
import os

log = logging.getLogger("atlas.auth.crypto")

_fernet = None
_fernet_key = None

_FERNET_PREFIX = "gAAAAA"


class KeyUnavailable(RuntimeError):
    pass


class DecryptionError(RuntimeError):
    pass


def _key_file_path():
    import settings
    return os.path.join(settings.data_dir(), "secrets", "master.key")


def _load_key() -> bytes:
    env_key = (os.environ.get("ATLAS_ENCRYPTION_KEY") or "").strip()
    if env_key:
        return env_key.encode("utf-8")
    path = (os.environ.get("ATLAS_ENCRYPTION_KEY_FILE") or "").strip()
    if path:
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
                continue
            with os.fdopen(fd, "wb") as f:
                f.write(key)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass
            log.warning("generated a new master key at %s -- back this up; losing it "
                        "makes encrypted MFA secrets unrecoverable. Set "
                        "ATLAS_ENCRYPTION_KEY(_FILE) to supply your own key instead.",
                        key_file)
            return key
        if time.monotonic() >= deadline:
            raise KeyUnavailable(
                f"{key_file} exists but stayed empty for {wait_s}s — refusing to "
                f"generate a second master key over it.")
        time.sleep(0.05)


def _fernet_instance():
    global _fernet, _fernet_key
    key = _load_key()
    if _fernet is None or key != _fernet_key:
        from cryptography.fernet import Fernet
        _fernet = Fernet(key)
        _fernet_key = key
    return _fernet


def encrypt_text(plaintext):
    if not plaintext:
        return plaintext
    return _fernet_instance().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(ciphertext):
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
        return ciphertext
