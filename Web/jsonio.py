import itertools
import json
import logging
import os
import shutil
import threading
import time

log = logging.getLogger("atlas.io.jsonio")

_temp_counter = itertools.count()
_temp_guard = threading.Lock()


def _temp_path(path):
    with _temp_guard:
        n = next(_temp_counter)
    return f"{path}.{os.getpid()}.{n}.tmp"

_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF = 0.05


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def read_json_dict(path):
    value = read_json(path)
    return value if isinstance(value, dict) else {}


def iso_utc(epoch=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def write_json_atomic(path, obj, indent=2, keep_backup=True, newline=True):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = _temp_path(path)
    try:
        text = json.dumps(obj, indent=indent, ensure_ascii=False)
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text + "\n" if newline else text)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    if os.path.exists(path):
        try:
            shutil.copymode(path, tmp)
        except OSError as e:
            log.warning("could not carry %s's permissions onto the new file: %s", path, e)
        if keep_backup:
            try:
                shutil.copy2(path, path + ".bak")
            except OSError as e:
                log.warning("could not refresh %s.bak: %s", path, e)
    _replace_with_retry(tmp, path)


def write_bytes_atomic(path, blob):
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
    try:
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
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
