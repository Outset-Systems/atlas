import json
import logging
import os

import settings

log = logging.getLogger("atlas.data.favourite_opens")

FILE = "favourite-opens.json"

LOCK_WAIT = 1.0


def path_of(path=None):
    return path or os.path.join(settings.DATA_DIR, FILE)


def load(path=None):
    try:
        with open(path_of(path), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v > 0}


def bump(url, favourites, path=None):
    import filelock
    import jsonio

    where = path_of(path)
    keep = set(favourites)
    if url not in keep:
        return None
    try:
        with filelock.exclusive(filelock.lock_for(where), timeout=LOCK_WAIT):
            counts = {k: v for k, v in load(where).items() if k in keep}
            counts[url] = counts.get(url, 0) + 1
            jsonio.write_json_atomic(where, counts, keep_backup=False)
            return counts[url]
    except filelock.LockTimeout:
        log.info("favourite open not counted: %s is busy", where)
    except OSError as e:
        log.warning("favourite open not counted: %s", e)
    return None
