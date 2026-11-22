import os


def post_worker_init(worker):
    try:
        import annalist
        annalist.start(worker.wsgi)
    except Exception:
        import logging
        logging.getLogger("atlas.live.annalist").exception(
            "annalist: could not start in worker %s; the annals will not advance "
            "with nobody watching", getattr(worker, "pid", "?"))
        log = getattr(worker, "log", None)
        if log is not None:
            try:
                log.error("annalist: could not start (see atlas.live.annalist)")
            except Exception:
                pass

    try:
        import watch
        watch.start(worker.wsgi)
    except Exception:
        import logging
        logging.getLogger("atlas.live.watch").exception(
            "watch: could not start in worker %s; the built-in checks ask only "
            "when the feed is read", getattr(worker, "pid", "?"))


def child_exit(server, worker):
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    try:
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
    except Exception:
        pass
