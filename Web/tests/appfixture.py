"""Build an Atlas configured by the environment as it is *right now*.

Every db-mode suite sets `ATLAS_DATA_BACKEND` and friends at import time and
then imports `app`. That worked when each file was run on its own and failed
whenever the suite ran as a whole: `settings` reads the environment once per
process, so whichever module imported first chose the backend for every module
after it. The documented "expect 26 failed / 50 passed" baseline was this, not
real breakage — but a suite whose failures you have to memorise is a suite
nobody reads.

`create_app()` made the fix possible; this makes it one line per module.
Reloading `settings` re-reads the environment, and the freshly built app picks
it up, so two suites with different backends can share a process.

The historic module-level names on `app` are gone. The handle `fresh_app`
returns carries the ones the existing tests assert on
(`atlas_app.DATA_BACKEND`, `INGEST_ENABLED`, `_signals`).
"""

import importlib
import os
import sys
from types import SimpleNamespace

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WEB not in sys.path:
    sys.path.insert(0, WEB)


def fresh_app(**env):
    """Re-read the environment and build an app from it.

    Returns a handle carrying the names the suites already use
    (`.app`, `.DATA_BACKEND`, `.INGEST_ENABLED`, `._signals`, …) rather than
    the `app` module itself. Mutating the module's globals would look
    convenient and would mean the last suite to build an app decided what
    every earlier suite's `atlas_app.INGEST_ENABLED` said — the same
    shared-state trap one level up from the one this file exists to fix.
    """
    os.environ.update({k: str(v) for k, v in env.items()})

    import settings
    importlib.reload(settings)

    # 🔴 `settings` is not the only module that reads the environment ONCE.
    # `hub_auth/auth.py` binds `AUTH_MODE` at import ("Resolved at import
    # time", line 38) and its gate branches on that copy — so whichever test
    # module imported it first decided the auth mode for the whole process, and
    # a later module declaring a different one got a **500 "Unknown
    # ATLAS_AUTH_MODE"** from the gate rather than its own configuration.
    #
    # That is the same class of bug this file was written to fix, one layer
    # deeper: reloading `settings` alone left the *framework's* idea of the mode
    # frozen. It stayed invisible because pytest collects alphabetically, and
    # `test_api_admin` happens to sort before `test_auth_gate_routes` — so the
    # full suite is green while the pair, run in the other order, loses 24 tests.
    # (Found 2026-08-21.)
    #
    # `app.py` took a FROM-import of that name until 2026-11-12 (`from
    # hub_auth.auth import AUTH_MODE`), a copy that a reload of the source
    # module could not reach — hence reloading `app` too, and in this order.
    # It asks `settings.auth_mode()` now. The reload of `app` stays: it re-runs
    # the module's import-time work (the logger levels, the module-level `app`)
    # against the settings reloaded above.
    from hub_auth import auth as hub_auth_mod
    importlib.reload(hub_auth_mod)

    # store caches an engine keyed on the URL and rebuilds when it changes, so
    # A suite pointing at a different sqlite file gets a different engine.
    if settings.DATA_BACKEND == "db":
        import store
        store.reset_engine_for_tests()

    import app as app_module
    importlib.reload(app_module)          # re-runs its import-time work (see above)
    flask_app = app_module.create_app()
    context = flask_app.extensions["atlas"]
    return SimpleNamespace(
        app=flask_app,
        DATA_BACKEND=settings.DATA_BACKEND,
        _lab=context.reader,
        _signals=context.signals,
        INGEST_ENABLED=flask_app.config["INGEST_ENABLED"],
    )


def login_as(client, username, password):
    """The accounts-mode sign-in, for tests. The same-origin write proof is a
    custom header (`X-Atlas-Write`) the server checks in place of the old
    per-session CSRF token; the test client sends no `Sec-Fetch-Site`, so the
    header alone carries it through `security.same_origin_refusal`. Returns
    `(response, None)` — the second slot was the rotated token, now gone.
    """
    r = client.post("/api/v2/auth/login",
                    json={"username": username, "password": password},
                    headers={"X-Atlas-Write": "1"})
    return r, None
