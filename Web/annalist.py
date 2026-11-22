import logging
import threading
import time

log = logging.getLogger("atlas.live.annalist")

_started = False
_lock = threading.Lock()
_thread = None
_last_tick = None


def interval():
    import settings
    return settings.env_int("ATLAS_ANNALS_POLL", 60, 15, zero_off=True)


def poll_once(app):
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
    except Exception as e:
        log.warning("annalist poll failed: %s", e)
        return False


def _alerts_tick(ctx, feed):
    try:
        import alerts
        data, _, _ = ctx.dataset()
        alerts.tick(feed, data, ctx=ctx)
    except Exception as e:
        log.warning("alerts tick failed: %s: %s", type(e).__name__, e)


def liveness():
    from jsonio import iso_utc
    return {"running": bool(_thread is not None and _thread.is_alive()),
            "last_tick": iso_utc(_last_tick) if _last_tick else None}


def start(app, stop=None):
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
            while not stop.wait(every):
                poll_once(app)

        t = threading.Thread(target=loop, name="atlas-annalist", daemon=True)
        t.start()
        _started, _thread = True, t
    log.info("annalist: polling the feed every %ss", every)
    return t
