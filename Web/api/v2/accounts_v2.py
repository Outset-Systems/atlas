"""Accounts — `/api/v2/auth/*` (accounts/hybrid only).

The sign-in API (the login PAGE stays a view: `auth_routes.py`). A nested
blueprint whose `before_request` 404s outside the modes that have sessions,
so in hub/standalone these paths simply do not exist.

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
        acc = atlas_auth.current_account()
        if not acc:
            return jsonify({"ok": False, "error": "Sign in required."}), 401
        if not acc.get("is_admin"):
            return jsonify({"ok": False, "error": "Admin account required."}), 403
        return view(*args, **kwargs)
    return guarded


#: Who MUST hold a second factor — `atlas_auth.mfa_policy_applies`, the one
#: implementation. (The copy that lived here until v1.41.0 lacked the `admins`
#: branch, so the surveyor fence was never enforced on the live path.)
_mfa_policy_applies = atlas_auth.mfa_policy_applies


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
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    ip = atlas_auth.client_ip()
    if accounts.throttled(username, ip):
        accounts.audit("login_locked", username, ip)
        return jsonify({"ok": False, "error": "Too many attempts. Try again later."}), 429

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

    accounts.clear_failures(username)
    if acc.get("mfa_enabled"):
        session.clear()
        session["_mfa_user"] = acc["username"]
        session["_mfa_started"] = time.time()
        return jsonify({"ok": True, "mfa_required": True})
    if _mfa_policy_applies(acc):
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
        return jsonify({"ok": False, "error": "Too many attempts. Try again later."}), 429
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
    secret, uri, qr_svg = accounts.start_mfa_enrollment(username)
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
        return jsonify({"ok": False, "error": "Too many attempts. Try again later."}), 429
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
    if _mfa_policy_applies(acc):
        return jsonify({"ok": False, "error":
                        "MFA is required on this instance (ATLAS_MFA_REQUIRED)."}), 403
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


# ── Admin: user management (G14) ─────────────────────────────────────────────

@auth_bp.route("/users")
@admin_required
def api_users():
    import accounts
    return jsonify({"ok": True, "users": accounts.list_users()})


@auth_bp.route("/users", methods=["POST"])
@same_origin_required
@admin_required
def api_users_create():
    import accounts
    data = request.get_json(silent=True) or {}
    try:
        acc = accounts.create_local_user(
            data.get("username") or "", data.get("password") or "",
            display_name=data.get("display_name") or "",
            email=data.get("email") or "",
            groups=data.get("groups") or (),
            is_admin=bool(data.get("is_admin")))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    accounts.audit("user_created", acc["username"], atlas_auth.client_ip(),
                   "by " + atlas_auth.current_user())
    return jsonify({"ok": True, "username": acc["username"]})


def _admin_target_guard(username, *, demoting=False, deactivating=False):
    import accounts
    me = atlas_auth.current_user()
    acc = accounts.get_user(username)
    if not acc:
        return jsonify({"ok": False, "error": "No such account."}), 404
    if username == me and (demoting or deactivating):
        return jsonify({"ok": False, "error": "You can't do that to your own account."}), 400
    if ((demoting or deactivating) and acc.get("is_admin") and acc.get("active")
            and accounts.count_active_admins() <= 1):
        return jsonify({"ok": False, "error": "That is the last active admin."}), 400
    return None


@auth_bp.route("/users/<username>/admin", methods=["POST"])
@same_origin_required
@admin_required
def api_user_admin(username):
    import accounts
    username = username.strip().lower()
    on = bool((request.get_json(silent=True) or {}).get("on"))
    acc = accounts.get_user(username)
    if acc and acc.get("source") == "ldap":
        return jsonify({"ok": False, "error":
                        "Directory accounts get admin from ATLAS_LDAP_ADMIN_GROUPS — "
                        "change the AD group, not this flag."}), 400
    blocked = _admin_target_guard(username, demoting=not on)
    if blocked:
        return blocked
    accounts.set_admin(username, on)
    accounts.audit("user_admin", username, atlas_auth.client_ip(),
                   f"{'granted' if on else 'revoked'} by {atlas_auth.current_user()}")
    return jsonify({"ok": True})


@auth_bp.route("/users/<username>/active", methods=["POST"])
@same_origin_required
@admin_required
def api_user_active(username):
    import accounts
    username = username.strip().lower()
    on = bool((request.get_json(silent=True) or {}).get("on"))
    blocked = _admin_target_guard(username, deactivating=not on)
    if blocked:
        return blocked
    accounts.set_active(username, on)
    accounts.audit("user_active", username, atlas_auth.client_ip(),
                   f"{'activated' if on else 'deactivated'} by {atlas_auth.current_user()}")
    return jsonify({"ok": True})


@auth_bp.route("/users/<username>/groups", methods=["POST"])
@same_origin_required
@admin_required
def api_user_groups(username):
    import accounts
    groups = (request.get_json(silent=True) or {}).get("groups") or []
    try:
        accounts.set_groups(username.strip().lower(), groups)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    accounts.audit("user_groups", username, atlas_auth.client_ip(),
                   "by " + atlas_auth.current_user())
    return jsonify({"ok": True})


@auth_bp.route("/users/<username>/reset-mfa", methods=["POST"])
@same_origin_required
@admin_required
def api_user_reset_mfa(username):
    import accounts
    username = username.strip().lower()
    if not accounts.get_user(username):
        return jsonify({"ok": False, "error": "No such account."}), 404
    accounts.disable_mfa(username)
    accounts.audit("mfa_reset", username, atlas_auth.client_ip(),
                   "by " + atlas_auth.current_user())
    return jsonify({"ok": True})


@auth_bp.route("/users/<username>", methods=["DELETE"])
@same_origin_required
@admin_required
def api_user_delete(username):
    import accounts
    username = username.strip().lower()
    blocked = _admin_target_guard(username, deactivating=True)
    if blocked:
        return blocked
    accounts.delete_user(username)
    accounts.audit("user_deleted", username, atlas_auth.client_ip(),
                   "by " + atlas_auth.current_user())
    return jsonify({"ok": True})


@auth_bp.route("/audit")
@admin_required
def api_audit():
    import accounts
    try:
        limit = min(max(int(request.args.get("limit", 200)), 1), 500)
    except ValueError:
        limit = 200
    return jsonify({"ok": True, "events": accounts.audit_tail(limit)})


bp.register_blueprint(auth_bp)
