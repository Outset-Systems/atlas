"""Accounts — `/api/v2/auth/*` (accounts/hybrid only).

The sign-in API (the login PAGE stays a view: `auth_routes.py`). A nested
blueprint whose `before_request` 404s outside the modes that have sessions,
so in hub/standalone these paths simply do not exist. The admin half
(`/users*`, `/audit`) is `accounts_admin.py`, on the same blueprint.

These paths are exempt from the app gate (a signed-out user must be able to
reach the login flow), so every route here enforces its own requirements: the
same-origin write proof (`security.same_origin_refusal` — an `X-Atlas-Write`
header a cross-origin page cannot set, plus `Sec-Fetch-Site`) on anything
state-changing, explicit session checks on anything personal, the admin flag
on anything instance-wide, and the shared throttle on anything that takes a
guess at a credential.

Login tries the configured backends in ATLAS_AUTH_BACKENDS order (local
password store, and/or a direct LDAPS bind — ldap_backend.py). Every failure
is the same sentence with the same status: which backend, which step, and
whether the account even exists are all things an unauthenticated caller
does not get to learn.

`accounts` / `ldap_backend` are imported INSIDE handlers, not at module top:
this package is imported in every mode, and the accounts-mode dependency set
(pyotp, ldap3, cryptography) must stay unloaded in hub/standalone deployments
— the same contract `atlas_auth` and `app.py` keep.
"""

import logging
import time
from functools import wraps

from flask import Blueprint, abort, jsonify, request, session

import atlas_auth
import security

from . import bp

log = logging.getLogger("atlas.api.v2")

_GENERIC_FAIL = "Invalid credentials."
_MFA_PENDING_TTL = 300  # seconds a password-passed-but-no-code login may sit

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.before_request
def _modes_only():
    if not atlas_auth.sessions_enabled():
        abort(404)                    # no sessions in this mode: the surface does not exist
    return None


# ── The prologue — every state-changing route opens with these checks ────────

def same_origin_required(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        refusal = security.same_origin_refusal()
        if refusal:
            return refusal
        return view(*args, **kwargs)
    return guarded


def session_required(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        if not atlas_auth.current_account():
            return jsonify({"ok": False, "error": "Sign in required."}), 401
        return view(*args, **kwargs)
    return guarded


def admin_required(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        if not atlas_auth.current_account().get("is_admin"):
            return jsonify({"ok": False, "error": "Admin account required."}), 403
        return view(*args, **kwargs)
    return session_required(guarded)


def _too_many():
    """The throttle's answer, the same on every route that takes a guess."""
    return jsonify({"ok": False, "error": "Too many attempts. Try again later."}), 429


def _name(username):
    """A username as the store spells it."""
    return username.strip().lower()


def _enroll_pending_user():
    import accounts
    if not session.get("_mfa_enroll"):
        return None
    username = session.get("user")
    acc = accounts.get_user(username) if username else None
    if (acc and acc.get("active")
            and session.get("_epoch") == acc.get("session_epoch", 0)):
        return username
    return None


def _mfa_subject():
    acc = atlas_auth.current_account()
    if acc:
        return acc["username"]
    return _enroll_pending_user()


def _reauth_refusal(acc, data):
    """The proof a signed-in session owes before it touches its second factor
    (2026-11-01). A session cookie alone must not be enough to swap the
    owner's authenticator or switch it off — `/password` has always demanded
    the current password for the same reason, and this is the same check:

      current  the account's password, always. A local account is checked
               against the store; a directory account is re-bound the way
               login binds it.
      code     a fresh code from the LIVE factor, when one is enabled. It is
               consumed, so the same code cannot then open a login.

    Returns a (response, status) refusal or None. Shapes, not surprises: a
    missing field is a 400 with a plain `error`, a wrong one a 401/403 that
    also counts against the throttle."""
    import accounts
    import ldap_backend
    username = acc["username"]
    ip = atlas_auth.client_ip()
    if acc.get("mfa_enabled"):
        code = str(data.get("code") or "").strip()
        if not code:
            return jsonify({"ok": False, "error":
                            "A current authenticator code is required."}), 400
        if not accounts.verify_mfa_code(username, code):
            accounts.record_failure(username, ip)
            return jsonify({"ok": False, "error": "Incorrect code."}), 403
    current = data.get("current") or ""
    if not current:
        return jsonify({"ok": False, "error": "Current password is required."}), 400
    if acc.get("source") == "local":
        ok = bool(accounts.verify_password(username, current))
    else:
        ok, _info = ldap_backend.authenticate(username, current)
    if not ok:
        accounts.record_failure(username, ip)
        return jsonify({"ok": False, "error": "Current password is wrong."}), 401
    return None


def _try_backends(username, password):
    import accounts
    import ldap_backend
    for backend in ldap_backend.backends():
        if backend == "local":
            acc = accounts.verify_password(username, password)
            if acc:
                return acc, "local"
        elif backend == "ldap":
            ok, info = ldap_backend.authenticate(username, password)
            if ok:
                acc = accounts.upsert_ldap_user(
                    info["username"], display_name=info["display_name"],
                    email=info["email"], groups=info["groups"],
                    is_admin=info["is_admin"])
                return acc, "ldap"
    return None, None


# ── Sign in / out ────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
@same_origin_required
def api_login():
    import accounts
    data = request.get_json(silent=True) or {}
    username = _name(data.get("username") or "")
    password = data.get("password") or ""
    ip = atlas_auth.client_ip()
    if accounts.throttled(username, ip):
        accounts.audit("login_locked", username, ip)
        return _too_many()

    try:
        acc, source = _try_backends(username, password)
    except accounts.SourceConflict as exc:
        log.error("v2: auth backend misconfigured: %s", exc)
        accounts.record_failure(username, ip)
        accounts.audit("login_fail", username, ip, "source conflict")
        return jsonify({"ok": False, "error": _GENERIC_FAIL}), 401
    except ValueError as exc:
        log.error("v2: auth backend misconfigured: %s", exc)
        return jsonify({"ok": False, "error": "Sign-in is misconfigured — see the server log."}), 500

    if not acc or not acc.get("active"):
        accounts.record_failure(username, ip)
        accounts.audit("login_fail", username, ip,
                       "inactive" if acc else "bad credentials")
        return jsonify({"ok": False, "error": _GENERIC_FAIL}), 401

    # The failure count survives the password step when a code still has to be
    # given: wrong codes share it, and clearing it here let a stolen password
    # try codes forever by signing in again every few guesses.
    if acc.get("mfa_enabled"):
        session.clear()
        session["_mfa_user"] = acc["username"]
        session["_mfa_started"] = time.time()
        return jsonify({"ok": True, "mfa_required": True})
    accounts.clear_failures(username)
    # the ONE policy implementation — the copy that lived here until v1.41.0
    # lacked the `admins` branch, so the surveyor fence was never enforced
    if atlas_auth.mfa_policy_applies(acc):
        atlas_auth.establish_session(acc)
        session["_mfa_enroll"] = 1
        accounts.audit("login_ok", acc["username"], ip, source + " (enrollment forced)")
        return jsonify({"ok": True, "mfa_setup_required": True})
    atlas_auth.establish_session(acc)
    accounts.touch_login(acc["username"])
    accounts.audit("login_ok", acc["username"], ip, source)
    return jsonify({"ok": True, "mfa_required": False,
                    "is_admin": bool(acc.get("is_admin"))})


@auth_bp.route("/login/mfa", methods=["POST"])
@same_origin_required
def api_login_mfa():
    import accounts
    username = session.get("_mfa_user")
    ip = atlas_auth.client_ip()
    if accounts.throttled(username or "", ip):
        return _too_many()
    started = session.get("_mfa_started", 0)
    if not username or time.time() - started > _MFA_PENDING_TTL:
        session.pop("_mfa_user", None)
        session.pop("_mfa_started", None)
        return jsonify({"ok": False, "error": "Login expired — sign in again."}), 401
    code = (request.get_json(silent=True) or {}).get("code") or ""
    if not accounts.verify_mfa_or_backup(username, code):
        accounts.record_failure(username, ip)
        accounts.audit("login_mfa_fail", username, ip)
        return jsonify({"ok": False, "error": "Incorrect code."}), 401
    acc = accounts.get_user(username)
    if not acc or not acc.get("active"):
        session.clear()
        return jsonify({"ok": False, "error": _GENERIC_FAIL}), 401
    accounts.clear_failures(username)
    atlas_auth.establish_session(acc)
    accounts.touch_login(username)
    accounts.audit("login_ok", username, ip, "mfa")
    return jsonify({"ok": True, "is_admin": bool(acc.get("is_admin"))})


@auth_bp.route("/logout", methods=["POST"])
@same_origin_required
def api_logout():
    import accounts
    user = session.get("user", "")
    session.clear()
    if user:
        accounts.audit("logout", user, atlas_auth.client_ip())
    return jsonify({"ok": True})


@auth_bp.route("/me")
def api_me():
    import accounts
    acc = atlas_auth.current_account()
    if not acc:
        pending = _enroll_pending_user()
        if pending:
            return jsonify({"authenticated": False, "mfa_setup_required": True,
                            "username": pending})
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "username": acc["username"],
                    "display_name": acc.get("display_name") or acc["username"],
                    "source": acc.get("source"),
                    "is_admin": bool(acc.get("is_admin")),
                    "mfa_enabled": bool(acc.get("mfa_enabled")),
                    "groups": accounts.groups_of(acc)})


# ── MFA self-service ─────────────────────────────────────────────────────────

@auth_bp.route("/mfa/setup", methods=["POST"])
@same_origin_required
def api_mfa_setup():
    import accounts
    username = _mfa_subject()
    if not username:
        return jsonify({"ok": False, "error": "Sign in first."}), 401
    ip = atlas_auth.client_ip()
    if accounts.throttled(username, ip):
        return _too_many()
    acc = atlas_auth.current_account()
    if acc:
        # a full session proves itself; the forced-enrollment state is not
        # one (`_enroll_pending_user`) and was minted by the password login a
        # moment ago, which is the proof
        refusal = _reauth_refusal(acc, request.get_json(silent=True) or {})
        if refusal:
            return refusal
    try:
        secret, uri, qr_svg = accounts.start_mfa_enrollment(
            username, reauthenticated=bool(acc))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    return jsonify({"ok": True, "secret": secret, "uri": uri, "qr_svg": qr_svg})


@auth_bp.route("/mfa/confirm", methods=["POST"])
@same_origin_required
def api_mfa_confirm():
    import accounts
    username = _mfa_subject()
    ip = atlas_auth.client_ip()
    if not username:
        return jsonify({"ok": False, "error": "Sign in first."}), 401
    if accounts.throttled(username, ip):
        return _too_many()
    code = (request.get_json(silent=True) or {}).get("code") or ""
    try:
        backup_codes = accounts.confirm_mfa(username, code)
    except ValueError as exc:
        accounts.record_failure(username, ip)
        return jsonify({"ok": False, "error": str(exc)}), 400
    was_enrollment = bool(session.pop("_mfa_enroll", None))
    acc = accounts.get_user(username)
    atlas_auth.establish_session(acc)
    if was_enrollment:
        accounts.touch_login(username)
    accounts.audit("mfa_enrolled", username, ip)
    return jsonify({"ok": True, "backup_codes": backup_codes})


@auth_bp.route("/mfa/disable", methods=["POST"])
@same_origin_required
@session_required
def api_mfa_disable():
    import accounts
    acc = atlas_auth.current_account()
    if atlas_auth.mfa_policy_applies(acc):
        return jsonify({"ok": False, "error":
                        "MFA is required on this instance (ATLAS_MFA_REQUIRED)."}), 403
    ip = atlas_auth.client_ip()
    if accounts.throttled(acc["username"], ip):
        return _too_many()
    refusal = _reauth_refusal(acc, request.get_json(silent=True) or {})
    if refusal:
        return refusal
    accounts.disable_mfa(acc["username"])
    fresh = accounts.get_user(acc["username"])
    atlas_auth.establish_session(fresh)  # keep THIS session; others just died
    accounts.audit("mfa_disabled", acc["username"], atlas_auth.client_ip())
    return jsonify({"ok": True})


@auth_bp.route("/password", methods=["POST"])
@same_origin_required
@session_required
def api_change_password():
    import accounts
    acc = atlas_auth.current_account()
    if acc.get("source") != "local":
        return jsonify({"ok": False, "error":
                        "Directory accounts change their password in the directory."}), 400
    data = request.get_json(silent=True) or {}
    if not accounts.verify_password(acc["username"], data.get("current") or ""):
        accounts.record_failure(acc["username"], atlas_auth.client_ip())
        return jsonify({"ok": False, "error": "Current password is wrong."}), 401
    try:
        accounts.set_password(acc["username"], data.get("new") or "")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    fresh = accounts.get_user(acc["username"])
    atlas_auth.establish_session(fresh)
    accounts.audit("password_changed", acc["username"], atlas_auth.client_ip())
    return jsonify({"ok": True})


@auth_bp.route("/me/emblem", methods=["POST"])
@same_origin_required
@session_required
def api_me_emblem():
    import accounts
    acc = atlas_auth.current_account()
    emblem = str((request.get_json(silent=True) or {}).get("emblem") or "").strip()
    if len(emblem) > 8:
        return jsonify({"ok": False, "error": "An emblem is a mark, not a "
                        "sentence — 8 characters at most."}), 400
    accounts.set_emblem(acc["username"], emblem)
    return jsonify({"ok": True, "emblem": emblem})


# The admin half of this surface (`/users*`, `/audit`). It attaches to `auth_bp`,
# so it is imported here, after everything above exists and before the
# blueprint is registered.
from . import accounts_admin  # noqa: E402,F401

bp.register_blueprint(auth_bp)
