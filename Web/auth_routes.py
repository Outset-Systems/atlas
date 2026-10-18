"""Accounts-mode pages: the sign-in page, and the first-run bootstrap.

Only registered when sessions exist (`atlas_auth.sessions_enabled()`,
app.py) — every other mode is cookie-less and gains no new workstation. The API
half that lived here (`/api/auth/*`) is `api/v2/accounts_v2.py` since the
2026-08-25 cutover and was removed from this file at the v1 removal
(v1.41.0); the page is not an API and stays a view (the API migration plan G15).

`/auth/login` is exempt from the gate (a signed-out user must be able to reach
the login flow); the page itself does nothing but render, and the sign-in it
posts to carries its own same-origin proof and throttle.
"""

import logging
import os
import sqlite3

from flask import Blueprint, redirect, render_template, request

import accounts
import atlas_auth

log = logging.getLogger("atlas.auth.routes")

bp = Blueprint("auth", __name__)


def _safe_next(raw):
    """Same-origin relative path only — the value becomes a redirect after
    login, so anything but a plain '/path' is an open-redirect/XSS vector."""
    raw = (raw or "/").strip()
    if raw.startswith("/") and not raw.startswith("//") and not raw.startswith("/\\"):
        return raw
    return "/"


@bp.route("/auth/login")
def login_page():
    if atlas_auth.current_account():
        return redirect(_safe_next(request.args.get("next", "/")))
    return render_template("login.html",
                           next=_safe_next(request.args.get("next", "/")))


def ensure_bootstrap_admin():
    """First-run only: while the instance has NO active admin, the bootstrap
    envs may create (or promote) one. The moment an admin exists this is
    inert, so the envs can stay in the compose without becoming a backdoor."""
    if accounts.count_active_admins() > 0:
        return
    username = (os.environ.get("ATLAS_BOOTSTRAP_ADMIN_USER") or "").strip().lower()
    if not username:
        return
    password = (os.environ.get("ATLAS_BOOTSTRAP_ADMIN_PASSWORD") or "").strip()
    path = (os.environ.get("ATLAS_BOOTSTRAP_ADMIN_PASSWORD_FILE") or "").strip()
    if not password and path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            password = f.read().strip()
    existing = accounts.get_user(username)
    if existing:
        accounts.set_admin(username, True)
        accounts.set_active(username, True)
        accounts.audit("bootstrap_admin", username, detail="promoted existing account")
        return
    if not password:
        return
    try:
        accounts.create_local_user(username, password, is_admin=True)
    except (sqlite3.IntegrityError, ValueError) as e:
        # Gunicorn forks its workers and each runs create_app() at import, so
        # on a fresh install every worker reaches this line at once and all but
        # one lose the INSERT. The loser used to raise, gunicorn took the whole
        # master down, and the container only came up on Docker's restart
        # (atlas-public's first boot, 2026-09-27). Losing the race is success
        # as long as the winner's row is there.
        if accounts.get_user(username):
            return
        if isinstance(e, ValueError):
            # A bootstrap password the policy refuses (too short, a bad
            # username) is the likeliest first-run mistake. Raising here
            # stopped every worker and the container restart-looped with the
            # reason buried in the log. Start WITHOUT the admin instead and say
            # exactly what to fix: the instance is reachable and nothing is
            # created that the operator did not ask for. (v1.49.0)
            log.error("bootstrap admin %r NOT created: %s Fix "
                      "ATLAS_BOOTSTRAP_ADMIN_USER / ATLAS_BOOTSTRAP_ADMIN_PASSWORD(_FILE) "
                      "and restart; the Atlas is running without an admin until then.",
                      username, e)
            return
        raise
    accounts.audit("bootstrap_admin", username, detail="created")
