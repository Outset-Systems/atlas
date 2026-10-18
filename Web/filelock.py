"""An exclusive lock that holds across gunicorn workers *and* threads.

The Atlas serves 2 worker processes × 4 threads. Every write it does is a
read-modify-write — load the dataset, apply operations, save it — and until
this existed nothing serialized them. Reproduced with 8 concurrent writers
against one dataset: edits were silently lost, and `os.replace` raised
FileNotFoundError because both writers had built the same `.tmp` file and the
first rename consumed it. The second failure is a 500, not a lost edit.

The `If-Match` stamp in `dataset.apply` does not help here. It detects a client
working from a *stale* copy; it cannot detect two clients who both read the
same fresh copy a microsecond apart. That is a lock's job.

Two layers, because one is not enough on either platform:

- a per-path `threading.Lock`, because an OS file lock is held by the process
  (Windows) or the open file description (POSIX) and will not reliably
  serialize two threads inside one gunicorn worker;
- an OS lock on a sidecar `.lock` file — `fcntl.flock` on POSIX,
  `msvcrt.locking` on Windows — because threads are only half the problem.

Locks are advisory: they work because every writer takes them. Readers do not,
and must not — `os.replace` is atomic, so a reader sees the whole old file or
the whole new one, never a torn one, and making the map wait on an editor
would be a bad trade.
"""

import errno
import logging
import os
import threading
import time
from contextlib import contextmanager

log = logging.getLogger("atlas.io.filelock")

#: How long to wait for another writer before giving up. Long enough that a
#: normal save (tens of milliseconds) never collides, short enough that a
#: wedged holder frees the worker rather than hanging the request forever.
LOCK_TIMEOUT = 10.0
_POLL = 0.02

_registry_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}
_warned_unsupported = set()

try:                                    # POSIX
    import fcntl

    def _try_lock(fd):
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd):
        fcntl.flock(fd, fcntl.LOCK_UN)

    _BUSY = (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK)
except ImportError:                     # Windows
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
    """Another writer held the lock for longer than we were willing to wait."""


def lock_for(path):
    """The sidecar a writer of `path` takes: `<path>.lock`.

    Five modules spelled this concatenation for themselves (2026-08-21); the
    dataset writer alone uses a different scheme (`<site>-write.lock` under
    revisions/, dataset.py) and keeps it — its lock guards a directory of
    files, not one file.
    """
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
    """Hold an exclusive lock on `path` (a sidecar `.lock` file).

    Raises `LockTimeout` if another writer will not let go. Never nest two of
    these — nothing in the Atlas does, and the locks are not reentrant.
    """
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
                        # The filesystem does not support locking at all (some
                        # network mounts). Degrade to the thread lock rather
                        # than refusing every write, but say so once — on a
                        # multi-worker deployment that is a real gap.
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
