"""Accounts, the admin half — `/api/v2/auth/users*` and `/api/v2/auth/audit`.

Split out of `accounts_v2.py` (2026-11-12). The routes attach to the same
blueprint, so every endpoint keeps its name, and the `before_request` there
(404 outside the modes that have sessions) fronts them as before. Each route
still enforces its own requirements with the decorators that module defines.

`accounts` is imported INSIDE handlers, for the reason `accounts_v2.py` gives.
"""

from flask import jsonify, request

import atlas_auth

from .accounts_v2 import _name, admin_required, auth_bp, same_origin_required


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
    if (demoting or deactivating) and accounts.is_last_active_admin(acc):
        return jsonify({"ok": False, "error": "That is the last active admin."}), 400
    return None


@auth_bp.route("/users/<username>/admin", methods=["POST"])
@same_origin_required
@admin_required
def api_user_admin(username):
    import accounts
    username = _name(username)
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
    username = _name(username)
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
        accounts.set_groups(_name(username), groups)
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
    username = _name(username)
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
    username = _name(username)
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
