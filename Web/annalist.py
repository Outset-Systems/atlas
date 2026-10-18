"""THE ANNALIST — keeps the annals written when nobody is looking (v1.46.0).

The annals (events.py) and the rites sweep only advanced when something built
a fresh signals feed, and the only thing that did was a browser. So the map
remembered what it was *watched* doing: the 2026-09-17 power outage and the
2026-09-24 patch window — six hosts down, containers blind to their storage —
left no trace, because nobody had the Atlas open.

This is a daemon thread per gunicorn worker that builds the feed every
ATLAS_ANNALS_POLL seconds (default 60; 0 = off) through the same
`build_feed()` the route uses. Two workers polling is the case events.py was
already written for: the write lock plus the stored last-seen state make the
second writer's identical transition a no-op, and the SignalsHub's 30 s cache
keeps source load at what one open browser tab already costs.

Started from gunicorn.conf.py's `post_worker_init`, never at import, so the
test suite (and `flask run`) never grows a background thread.
"""

import logging
import os
import threading

log = logging.getLogger("atlas.live.annalist")

_started = False
_lock = threading.Lock()


def interval():
    """Seconds between polls; 0 disables. Garbage or negative -> default."""
    raw = os.environ.get("ATLAS_ANNALS_POLL", "60").strip()
    try:
        value = int(raw)
    except ValueError:
        return 60
    if value == 0:
        return 0
    return value if value >= 15 else 60        # never hammer the sources


def poll_once(app):
    """One fresh build of the feed inside an app context. Never raises."""
    try:
        with app.app_context():
            from api.v2.feeds import build_feed
            from context import atlas
            build_feed(atlas())
        return True
    except Exception as e:      # noqa: BLE001 — the annalist must never take a worker down
        log.warning("annalist poll failed: %s", e)
        return False


def start(app, stop=None):
    """Start the loop once per process. Returns the thread, or None if off."""
    global _started
    every = interval()
    if not every:
        log.info("annalist: off (ATLAS_ANNALS_POLL=0)")
        return None
    with _lock:
        if _started:
            return None
        _started = True
    stop = stop or threading.Event()

    def loop():
        # first poll after one interval: the worker has just booted and the
        # first sighting only seeds state anyway (events.py)
        while not stop.wait(every):
            poll_once(app)

    t = threading.Thread(target=loop, name="atlas-annalist", daemon=True)
    t.start()
    log.info("annalist: polling the feed every %ss", every)
    return t
