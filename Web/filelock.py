import errno
import logging
import os
import threading
import time
from contextlib import contextmanager

log = logging.getLogger("atlas.io.filelock")

LOCK_TIMEOUT = 10.0
_POLL = 0.02

_registry_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}
_warned_unsupported = set()

try:
    import fcntl

    def _try_lock(fd):
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd):
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass

    _BUSY = (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK)
except ImportError:
    import msvcrt

    def _try_lock(fd):
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd):
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

    _BUSY = (errno.EACCES, errno.EDEADLOCK, errno.EAGAIN)


class LockTimeout(RuntimeError):
    pass


def lock_for(path):
    return path + ".lock"


def _thread_lock_for(path):
    key = os.path.abspath(path)
    with _registry_guard:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = _thread_locks[key] = threading.Lock()
        return lock


@contextmanager
def exclusive(path, timeout=LOCK_TIMEOUT):
    deadline = time.monotonic() + timeout
    thread_lock = _thread_lock_for(path)

    if not thread_lock.acquire(timeout=timeout):
        raise LockTimeout(f"another save has held {os.path.basename(path)} for "
                          f"more than {timeout:g}s")
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            while True:
                try:
                    _try_lock(fd)
                    break
                except OSError as e:
                    if e.errno not in _BUSY:
                        if path not in _warned_unsupported:
                            _warned_unsupported.add(path)
                            log.warning(
                                "%s does not support file locking (%s) — concurrent "
                                "writes from separate workers are NOT serialized here",
                                path, e)
                        break
                    if time.monotonic() >= deadline:
                        raise LockTimeout(
                            f"another save has held {os.path.basename(path)} for "
                            f"more than {timeout:g}s")
                    time.sleep(_POLL)
            yield
        finally:
            _unlock(fd)
            os.close(fd)
    finally:
        thread_lock.release()


@contextmanager
def writing_now(path):
    import jsonio

    with exclusive(lock_for(path), timeout=0):
        yield lambda obj: jsonio.write_json_atomic(path, obj, keep_backup=False)
