import logging
import os
import re
import sqlite3

from flask import Blueprint, redirect, render_template, request

import accounts
import atlas_auth
import envnames

log = logging.getLogger("atlas.auth.routes")

bp = Blueprint("auth", __name__)

_SAFE_NEXT = re.compile(r"/(?![/\\])[^\x00-\x1f\x7f\\]*")


def _safe_next(raw):
    raw = (raw or "/").strip()
    if not _SAFE_NEXT.fullmatch(raw):
        return "/"
    return raw


@bp.route("/auth/login")
def login_page():
    if atlas_auth.current_account():
        return redirect(_safe_next(request.args.get("next", "/")))
    return render_template("login.html",
                           next=_safe_next(request.args.get("next", "/")))


def _say_nobody_can_sign_in():
    if atlas_auth.accounts_mode():
        log.warning("no admin account exists, so nobody can sign in. Set "
                    "ATLAS_ADMIN_PASSWORD in .env and run `up -d` again (without "
                    "the compose file: ATLAS_BOOTSTRAP_ADMIN_PASSWORD or _PASSWORD_FILE, "
                    "user name ATLAS_BOOTSTRAP_ADMIN_USER, default admin), or run "
                    "`python cli.py user-add <name> --admin`.")


def ensure_bootstrap_admin():
    if accounts.count_active_admins() > 0:
        return
    username = (os.environ.get("ATLAS_BOOTSTRAP_ADMIN_USER") or "").strip().lower()
    password = envnames.secret("ATLAS_BOOTSTRAP_ADMIN_PASSWORD")
    if password and not username:
        username = "admin"
    if not username:
        _say_nobody_can_sign_in()
        return
    existing = accounts.get_user(username)
    if existing:
        accounts.set_admin(username, True)
        accounts.set_active(username, True)
        accounts.audit("bootstrap_admin", username, detail="promoted existing account")
        if password:
            log.warning("bootstrap: %r already exists, so it was made an active admin with "
                        "its OWN password; ATLAS_BOOTSTRAP_ADMIN_PASSWORD was not applied. "
                        "To set a new one: python cli.py user-passwd %s", username, username)
        else:
            log.warning("bootstrap: no active admin, so %r was made an active admin again",
                        username)
        return
    if not password:
        _say_nobody_can_sign_in()
        return
    try:
        accounts.create_local_user(username, password, is_admin=True)
    except (sqlite3.IntegrityError, ValueError) as e:
        if accounts.get_user(username):
            return
        if isinstance(e, ValueError):
            log.error("bootstrap admin %r NOT created: %s Fix "
                      "ATLAS_BOOTSTRAP_ADMIN_USER / ATLAS_BOOTSTRAP_ADMIN_PASSWORD(_FILE) "
                      "and restart; the Atlas is running without an admin until then.",
                      username, e)
            return
        raise
    accounts.audit("bootstrap_admin", username, detail="created")
