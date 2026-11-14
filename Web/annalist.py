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

ALERTS (2026-11-13) ride this loop and add no thread of their own: after each
build, `alerts.tick` reads the annals by sequence and sends what is due. So
alerts fire only while this poll runs, and `/api/v2/health` says whether it
does (`liveness()`: per worker, since each worker polls for itself).
"""

import logging
import os
import threading
import time

log = logging.getLogger("atlas.live.annalist")

_started = False
_lock = threading.Lock()
_thread = None
#: When this worker last finished a poll (epoch seconds), or None.
_last_tick = None


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
    """One fresh build of the feed inside an app context, then ALERTS' tick.
    Never raises; a failed tick never fails the poll."""
    global _last_tick
    try:
        with app.app_context():
            from api.v2.feeds import build_feed
            from context import atlas
            ctx = atlas()
            feed = build_feed(ctx)
            _alerts_tick(ctx, feed)
        _last_tick = time.time()
        return True
    except Exception as e:      # noqa: BLE001 — the annalist must never take a worker down
        log.warning("annalist poll failed: %s", e)
        return False


def _alerts_tick(ctx, feed):
    """ALERTS: after the build, never instead of it. The tick is called from
    here and not from `build_feed`, so a browser's request never sends."""
    try:
        import alerts
        data, _, _ = ctx.dataset()
        alerts.tick(feed, data, ctx=ctx)
    except Exception as e:      # noqa: BLE001 — an alert that fails must not stop the annals
        log.warning("alerts tick failed: %s: %s", type(e).__name__, e)


def liveness():
    """{running, last_tick} for this worker: whether its poll thread is alive,
    and when it last finished a poll (UTC, or None). Nothing else."""
    from jsonio import iso_utc
    return {"running": bool(_thread is not None and _thread.is_alive()),
            "last_tick": iso_utc(_last_tick) if _last_tick else None}


def start(app, stop=None):
    """Start the loop once per process. Returns the thread, or None if off."""
    global _started, _thread
    every = interval()
    if not every:
        log.info("annalist: off (ATLAS_ANNALS_POLL=0)")
        return None
    with _lock:
        if _started:
            return None
        stop = stop or threading.Event()

        def loop():
            # first poll after one interval: the worker has just booted and the
            # first sighting only seeds state anyway (events.py)
            while not stop.wait(every):
                poll_once(app)

        t = threading.Thread(target=loop, name="atlas-annalist", daemon=True)
        t.start()                 # raises before `_started` is set: a retry may still start it
        _started, _thread = True, t
    log.info("annalist: polling the feed every %ss", every)
    return t
