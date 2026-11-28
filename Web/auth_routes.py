import logging
import os
import re
import sqlite3

from urllib.parse import urlencode

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

import accounts
import atlas_auth
import envnames

log = logging.getLogger("atlas.auth.routes")

bp = Blueprint("auth", __name__)

_OIDC_PENDING = "_oidc_pending"

_SAFE_NEXT = re.compile(r"/(?![/\\])[^\x00-\x1f\x7f\\]*")


def _safe_next(raw):
    raw = (raw or "/").strip()
    if not _SAFE_NEXT.fullmatch(raw):
        return "/"
    return raw


_SSO_ERRORS = {
    "expired": "That sign-in took too long or was started in another browser. Try again.",
    "denied": "The identity provider did not sign you in.",
    "refused": "Your single sign-on account is not allowed into this Atlas. "
               "An admin can see why in the server log.",
    "provider": "The identity provider could not be reached. Try again, or "
                "use another way to sign in.",
}

_STEPS = ("mfa", "enroll")


@bp.route("/auth/login")
def login_page():
    import ldap_backend
    import oidc_backend
    nxt = _safe_next(request.args.get("next", "/"))
    step = request.args.get("step", "")
    if step == "mfa" and not session.get("_mfa_user"):
        step = ""
    if step == "enroll" and not session.get("_mfa_enroll"):
        step = ""
    if atlas_auth.current_account() and step not in _STEPS:
        return redirect(nxt)
    oidc_backend.warn_if_misconfigured()
    sso = oidc_backend.enabled()
    return render_template(
        "login.html", next=nxt, step=step if step in _STEPS else "",
        error=_SSO_ERRORS.get(request.args.get("error", ""), ""),
        sso=sso, sso_label=oidc_backend.label() if sso else "",
        passwords=bool(ldap_backend.backends()) or not sso)


def _sso_failed(code, next_path="/"):
    return redirect("/auth/login?" + urlencode({"error": code, "next": next_path}))


def _redirect_uri():
    import settings
    explicit = (envnames.env("ATLAS_OIDC_REDIRECT_URI") or "").strip()
    if explicit:
        return explicit
    if settings.PUBLIC_URL:
        return settings.PUBLIC_URL.rstrip("/") + "/auth/oidc/callback"
    return url_for("auth.oidc_callback", _external=True)


@bp.route("/auth/oidc/start")
def oidc_start():
    import oidc_backend
    if not oidc_backend.enabled():
        abort(404)
    nxt = _safe_next(request.args.get("next", "/"))
    reauth = request.args.get("reauth") == "1"
    entry, challenge = oidc_backend.new_pending(nxt, reauth=reauth)
    try:
        url = oidc_backend.authorization_url(_redirect_uri(), entry["state"],
                                             entry["nonce"], challenge, reauth=reauth)
    except oidc_backend.ProviderError as exc:
        log.error("oidc: cannot start a sign-in: %s", exc)
        return _sso_failed("provider", nxt)
    session[_OIDC_PENDING] = oidc_backend.remember_pending(session.get(_OIDC_PENDING), entry)
    resp = redirect(url)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/auth/oidc/callback")
def oidc_callback():
    import oidc_backend
    if not oidc_backend.enabled():
        abort(404)
    ip = atlas_auth.client_ip()
    entry, rest = oidc_backend.take_pending(session.get(_OIDC_PENDING),
                                            request.args.get("state", ""))
    session[_OIDC_PENDING] = rest
    if not entry:
        accounts.audit("login_fail", "", ip, "oidc: unknown or expired state")
        return _sso_failed("expired")
    nxt = _safe_next(entry.get("next"))
    if request.args.get("error"):
        detail = str(request.args.get("error"))[:60]
        accounts.audit("login_fail", "", ip, f"oidc: provider said {detail}")
        return _sso_failed("denied", nxt)
    try:
        ident = oidc_backend.complete(request.args.get("code", ""), entry, _redirect_uri())
    except oidc_backend.LoginRefused as exc:
        log.warning("oidc: sign-in refused: %s", exc)
        accounts.audit("login_fail", exc.username, ip, f"oidc: {exc}")
        return _sso_failed("refused", nxt)
    except oidc_backend.ProviderError as exc:
        log.error("oidc: provider error: %s", exc)
        accounts.audit("login_fail", "", ip, f"oidc: {exc}")
        return _sso_failed("provider", nxt)
    try:
        acc = accounts.upsert_oidc_user(
            ident["username"], external_id=ident["external_id"],
            display_name=ident["display_name"], email=ident["email"],
            groups=ident["groups"], is_admin=ident["is_admin"])
    except accounts.SourceConflict as exc:
        log.error("oidc: %s", exc)
        accounts.audit("login_fail", ident["username"], ip, "oidc: source conflict")
        return _sso_failed("refused", nxt)
    if not acc or not acc.get("active"):
        accounts.audit("login_fail", ident["username"], ip, "oidc: inactive")
        return _sso_failed("refused", nxt)
    outcome = atlas_auth.finish_primary_login(acc, "oidc", ip, idp_mfa=ident["idp_mfa"])
    if outcome in _STEPS:
        return redirect("/auth/login?" + urlencode({"step": outcome, "next": nxt}))
    return redirect(nxt)


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
