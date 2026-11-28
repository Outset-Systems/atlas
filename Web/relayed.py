"""The last inventory snapshot a relay pushed for a system that Atlas cannot reach
itself (Hyper-V over WinRM). Kept for review; nothing here writes to the map."""
import os
import time

import settings
from jsonio import iso_utc
from jsonstore import JsonStore


def _normal(raw):
    return raw if isinstance(raw, dict) else {}


_STORE = JsonStore(lambda: os.path.join(settings.DATA_DIR, "relayed.json"), _normal)


def _slot(system, site):
    return f"{system}:{site}"


def put(system, site, snapshot, *, now=None):
    now = time.time() if now is None else now
    with _STORE.locked():
        state = _STORE.load()
        state[_slot(system, site)] = {"received": iso_utc(now), "epoch": int(now),
                                      "snapshot": snapshot}
        _STORE.save(state)


def get(system, site):
    held = _STORE.load().get(_slot(system, site))
    return held if isinstance(held, dict) and isinstance(held.get("snapshot"), dict) else None


def age_words(held, *, now=None):
    seconds = max(0, int((time.time() if now is None else now) - (held.get("epoch") or 0)))
    for size, word in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = seconds // size
            return f"{n} {word}{'' if n == 1 else 's'} ago"
    return "just now"
