"""gunicorn hooks for the Atlas (v1.42.0).

One job: tell prometheus_client's multiprocess registry when a worker dies,
so its per-process files stop counting. Without this a worker that was
replaced (a boot failure, a `--max-requests` recycle, an OOM kill) keeps its
last gauge values in the scrape forever — `atlas_signals_source_ok` stays 1
for a source nobody is polling, and the `live*` gauge modes metrics.py uses
have no way to know the process is gone. (review, 2026-09-03)

Loaded by the Dockerfile's CMD (`-c gunicorn.conf.py`); harmless when
PROMETHEUS_MULTIPROC_DIR is unset (nothing to mark).
"""

import os


def post_worker_init(worker):
    """THE ANNALIST (v1.46.0): keep the annals and the rites sweep advancing with
    nobody watching — see annalist.py. A failure here must never stop a worker."""
    try:
        import annalist
        annalist.start(worker.wsgi)
    except Exception:  # noqa: BLE001
        pass


def child_exit(server, worker):  # noqa: ARG001 — gunicorn's signature
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    try:
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
    except Exception:  # noqa: BLE001 — a bookkeeping miss must never stop a reap
        pass
