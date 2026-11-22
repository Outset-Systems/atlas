from flask import jsonify, request

import atlas_auth

from . import NAME_LIMIT, _body, _text, _texts
from .accounts_v2 import (_name, _reauth_refusal, _too_many, admin_required, auth_bp,
                          same_origin_required)



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
    data = _body()
    try:
        acc = accounts.create_local_user(
            _text(data, "username", NAME_LIMIT), _text(data, "password"),
            display_name=_text(data, "display_name"),
            email=_text(data, "email"),
            groups=_texts(data, "groups"),
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
    on = bool(_body().get("on"))
    acc = accounts.get_user(username)
    if acc and acc.get("source") == "ldap":
        return jsonify({"ok": False, "error":
                        "Directory accounts get admin from ATLAS_LDAP_ADMIN_GROUPS — "
                        "change the AD group, not this flag."}), 400
    blocked = _admin_target_guard(username, demoting=not on)
    if blocked:
        return blocked
    try:
        accounts.set_admin(username, on)
    except accounts.LastAdminError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    accounts.audit("user_admin", username, atlas_auth.client_ip(),
                   f"{'granted' if on else 'revoked'} by {atlas_auth.current_user()}")
    return jsonify({"ok": True})


@auth_bp.route("/users/<username>/active", methods=["POST"])
@same_origin_required
@admin_required
def api_user_active(username):
    import accounts
    username = _name(username)
    on = bool(_body().get("on"))
    blocked = _admin_target_guard(username, deactivating=not on)
    if blocked:
        return blocked
    try:
        accounts.set_active(username, on)
    except accounts.LastAdminError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    accounts.audit("user_active", username, atlas_auth.client_ip(),
                   f"{'activated' if on else 'deactivated'} by {atlas_auth.current_user()}")
    return jsonify({"ok": True})


@auth_bp.route("/users/<username>/groups", methods=["POST"])
@same_origin_required
@admin_required
def api_user_groups(username):
    import accounts
    groups = _texts(_body(), "groups")
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
    me = atlas_auth.current_account()
    if username == me["username"]:
        if atlas_auth.mfa_policy_applies(me):
            return jsonify({"ok": False, "error":
                            "MFA is required on this instance (ATLAS_MFA_REQUIRED)."}), 403
        if accounts.throttled(username, atlas_auth.client_ip()):
            return _too_many()
        refusal = _reauth_refusal(me, _body())
        if refusal:
            return refusal
    accounts.disable_mfa(username)
    if username == me["username"]:
        atlas_auth.establish_session(accounts.get_user(username))
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
    try:
        accounts.delete_user(username)
    except accounts.LastAdminError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
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
