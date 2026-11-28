import logging
import os

from flask import jsonify

import settings
from security import actor, write_refusal


log = logging.getLogger("atlas.api.v2")
from . import NAME_LIMIT, _body, _part, _text
from .admin import (
    _has_ldap_admin_proof, _local_admin_exists, _remember_ldap_admin_proof, admin_bp,
)


@admin_bp.route("/auth")
def auth_settings():
    import auth_config
    import ldap_backend
    import oidc_backend
    return jsonify({
        "settings": auth_config.effective(),
        "sources": auth_config.sources(),
        "allowed": list(auth_config.ALLOWED),
        "mode": settings.auth_mode(),
        "ldap_ready": ldap_backend.enabled(),
        "oidc_ready": oidc_backend.enabled(),
        "backends": ldap_backend.backends() + (["oidc"] if oidc_backend.enabled() else []),
        "local_admin_exists": _local_admin_exists(),
    })


@admin_bp.route("/auth/test", methods=["POST"])
def auth_settings_test():
    refusal = write_refusal()
    if refusal:
        return refusal
    body = _body()
    proposed = _part(body, "settings")
    username = _text(body, "username", NAME_LIMIT).strip()
    password = _text(body, "password")
    if not username or not password:
        return jsonify({"ok": False, "error": "A name and password are needed to test a bind."}), 400
    import auth_config
    unknown = [k for k in proposed if k not in auth_config.ALLOWED]
    if unknown:
        return jsonify({"ok": False, "error": f"not a directory setting: {unknown[0]}"}), 400

    import ldap_backend
    overrides = {k: (str(proposed.get(k, "") or "").strip() or os.environ.get(k, "").strip())
                 for k in auth_config.ALLOWED}
    overrides["ATLAS_LDAP_GROUP_SCOPE"] = ldap_backend._cfg("ATLAS_LDAP_GROUP_SCOPE", "base")
    try:
        ok, info = ldap_backend.authenticate(username, password, overrides=overrides)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        log.warning("v2: directory test failed: %s", e)
        return jsonify({"ok": False, "error": f"The directory did not answer: {e}"}), 200

    info = info or {}
    is_admin_result = bool(info.get("is_admin"))
    if ok and is_admin_result:
        _remember_ldap_admin_proof()
    log.info("v2: directory test by %s: ok=%s admin=%s", actor(), bool(ok), is_admin_result)
    return jsonify({"ok": bool(ok), "is_admin": is_admin_result,
                    "groups": info.get("groups") or [],
                    "display_name": info.get("display_name") or "",
                    "error": "" if ok else "That account could not sign in."})


@admin_bp.route("/auth", methods=["POST"])
def auth_settings_save():
    refusal = write_refusal()
    if refusal:
        return refusal
    import auth_config
    import ldap_backend
    proposed = _part(_body(), "settings")
    unknown = [k for k in proposed if k not in auth_config.ALLOWED]
    if unknown:
        return jsonify({"error": f"not a directory setting: {unknown[0]}"}), 400

    def in_force(key):
        return (str(proposed.get(key, "") or "").strip()
                or os.environ.get(key, "") or "").strip()

    backends = ldap_backend._order(in_force("ATLAS_AUTH_BACKENDS") or "local")
    if not any(b in ("local", "ldap", "oidc") for b in backends):
        return jsonify({"error": "At least one sign-in backend (local, ldap or oidc) must stay enabled."}), 422
    if not any(b in ("local", "ldap") for b in backends):
        import atlas_auth
        import oidc_backend
        me = atlas_auth.current_account() or {}
        if not (oidc_backend.configured() and me.get("source") == "oidc" and me.get("is_admin")):
            return jsonify({"error": "Single sign-on can be the only way in once you are "
                                     "signed in through it as an admin. Sign in with single "
                                     "sign-on first, so an admin is proven to get back in."}), 422
    url = in_force("ATLAS_LDAP_URL")
    if "ldap" in backends:
        if not url or not in_force("ATLAS_LDAP_BASE_DN"):
            return jsonify({"error": "The directory needs both a URL and a base DN."}), 422
        if not ldap_backend.is_ldaps(url):
            return jsonify({"error": "Only ldaps:// is accepted — a plaintext bind "
                                     "would put every password on the wire."}), 422

    if "local" not in backends and "ldap" in backends and not _has_ldap_admin_proof():
        return jsonify({
            "error": "Test the directory with an admin account first. Saving a "
                     "directory-only sign-in without proving an admin can get "
                     "back in would lock this Atlas for everyone.",
            "needs_proof": True,
        }), 422
    if "local" in backends and not _local_admin_exists() and not _has_ldap_admin_proof():
        log.warning("v2: directory settings saved with no local admin present")

    try:
        effective = auth_config.save(proposed)
    except (ValueError, OSError) as e:
        return jsonify({"error": f"could not save: {e}"}), 500
    log.info("v2: directory settings changed by %s", actor())
    return jsonify({"ok": True, "settings": effective,
                    "sources": auth_config.sources(),
                    "backends": ldap_backend.backends(),
                    "ldap_ready": ldap_backend.enabled()})
