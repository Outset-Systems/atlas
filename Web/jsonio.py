"""Reading and writing the JSON files the Atlas owns, without losing them.

Extracted from `app.py`, where `_write_json_atomic` was already carrying the
hard-won rule below for `positions.json` / `rack.json`. The dataset writer
needs exactly the same guarantee, and a second copy of it would be a second
chance to get it wrong.

    positions.json, rack.json and (once the editor can write) lab-data.json
    are the only copy of what they hold. A plain `open(path, "w")` truncates
    *before* writing, and the readers swallow a ValueError into {} — so a
    crash, an OOM kill or a full disk mid-write silently discarded the lot,
    with no error anywhere.

temp file + fsync + `os.replace()` is atomic on POSIX and on NTFS; one `.bak`
generation is kept so even a bad *successful* write stays recoverable.
"""

import itertools
import json
import logging
import os
import shutil
import threading
import time

log = logging.getLogger("atlas.io.jsonio")

# Every in-flight write gets its own temp file. It used to be a fixed
# `<path>.tmp`, which meant two concurrent writers built the *same* temp file
# and the first `os.replace` consumed it — the second then died with
# FileNotFoundError, i.e. a 500 rather than a merely-lost edit. Reproduced with
# 8 concurrent writers. Writers are serialized by `filelock` now; this makes the
# collision impossible rather than merely unlikely, and covers anything that
# writes without taking the lock.
_temp_counter = itertools.count()
_temp_guard = threading.Lock()


def _temp_path(path):
    with _temp_guard:
        n = next(_temp_counter)
    return f"{path}.{os.getpid()}.{n}.tmp"

#: `os.replace` is atomic, but on Windows over SMB it can transiently fail with
#: "Access is denied" when something still holds a handle on the target — an
#: indexer, a virus scanner, or the `.bak` copy a moment earlier. The rename is
#: the last step, so failing here means the edit is lost even though the new
#: contents are safely on disk. A few short retries turn a lost save into a
#: slightly slow one; a real permissions problem still raises, just later.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF = 0.05


def read_json(path, default=None):
    """Parse `path`, or return `default` if it is missing or unreadable.

    Deliberately forgiving: a missing overlay is the normal case on a fresh
    deploy, and a corrupt one must not take the whole map down with it.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def read_json_dict(path):
    """`read_json` narrowed to a dict — anything else reads as empty."""
    value = read_json(path)
    return value if isinstance(value, dict) else {}


def iso_utc(epoch=None):
    """The one spelling of a UTC stamp — `2026-08-21T12:00:00Z` — for every
    file the Atlas writes and every feed it serves. `epoch` defaults to now.

    It was `time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(...))` written out
    seven times across six modules (2026-08-21 survey), and `_now()` had come
    to mean four different things — a string here, a float in heartbeats, an
    aware datetime in maintenance, naive LOCAL time in accounts. This is the
    string one; the others keep their names and their meanings.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def write_json_atomic(path, obj, indent=2, keep_backup=True, newline=True):
    """Write JSON so an interrupted write can never destroy the old file.

    `indent` and `newline` matter because all three of these files are tracked
    in git: the dataset is 2-space and ends with a newline, the two overlays
    are 1-space and end without one. Writing them back in a different shape
    would turn every save into a whole-file diff.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = _temp_path(path)
    try:
        # newline="" disables Python's newline translation. Without it, writing
        # on Windows turns every "\n" into "\r\n" — and since these files are LF
        # in git (.gitattributes: eol=lf), changing one field would rewrite all
        # 1285 lines and bury the real change in a whole-file diff.
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            json.dump(obj, fh, indent=indent, ensure_ascii=False)
            if newline:
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        # don't leave a half-written temp file behind on the way out
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    if os.path.exists(path):
        # os.replace takes the *temp* file's permissions, so a save would
        # quietly re-mode the target: on the app host lab-data.json went 664
        # link:link -> 644 link:docker-admins the first time the Desk wrote to
        # it. The file's ownership is deliberate (the deployment notes) and a writer has
        # no business changing it.
        try:
            shutil.copystat(path, tmp)
        except OSError as e:
            log.warning("could not carry %s's permissions onto the new file: %s", path, e)
        if keep_backup:
            try:
                shutil.copy2(path, path + ".bak")
            except OSError as e:  # a stale .bak must never block a good save
                log.warning("could not refresh %s.bak: %s", path, e)
    _replace_with_retry(tmp, path)


def write_bytes_atomic(path, blob):
    """`write_json_atomic`'s guarantee for a binary file (an uploaded render).

    `mapart.store` hand-rolled this with a FIXED `<path>.part` temp name and a
    bare `os.replace` — exactly the two things this module exists to fix: two
    admins uploading renders of the same name at once built the same temp file
    (the 8-concurrent-writers failure above), and a transient sharing
    violation lost the upload outright instead of retrying. No `.bak` and no
    `copystat`: a render is overwritten only by an upload under its own name,
    and that is the operator's stated intent.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = _temp_path(path)
    try:
        with open(tmp, "wb") as fh:
            fh.write(blob)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    _replace_with_retry(tmp, path)


def _replace_with_retry(tmp, path):
    """`os.replace`, retried briefly through a transient sharing violation."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF * (attempt + 1))
            log.warning("%s was locked; retrying the save (%d/%d)",
                        path, attempt + 2, _REPLACE_ATTEMPTS)
