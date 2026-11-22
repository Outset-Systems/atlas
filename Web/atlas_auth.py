import ipaddress
import logging
import time

from flask import g, jsonify, redirect, request, session

from hub_auth import require_hub_or_standalone
from hub_auth.auth import DEFAULT_EXEMPT

import settings

log = logging.getLogger("atlas.auth.gate")

import envnames

ADMIN_GROUP = envnames.env("ATLAS_ADMIN_GROUP")


def mode():
    return settings.auth_mode()


def accounts_mode():
    return mode() == "accounts"


def hybrid_mode():
    return mode() == "hybrid"


def sessions_enabled():
    return mode() in ("accounts", "hybrid")


def hub_claims():
    import hub_auth.auth as auth
    if not auth.AUTH_SECRET:
        _warn_unsigned_hub()
        return None
    return auth.verify_token(request.headers.get(auth.SIGNED_HEADER, "")) or None


_warned_unsigned = False


def _warn_unsigned_hub():
    global _warned_unsigned
    if not _warned_unsigned:
        _warned_unsigned = True
        log.error(
            "no ATLAS_HUB_SECRET is configured: Hub single-sign-on is "
            "DISABLED in hybrid mode and every visitor must use /auth/login. "
            "Unsigned X-Remote-* headers are not accepted — anyone able to "
            "reach this app could otherwise set them and be admin.")


def _hub_groups(claims):
    raw = (claims or {}).get("g", [])
    if not isinstance(raw, list):
        raw = str(raw).split(",")
    return {str(g).strip() for g in raw if str(g).strip()}


def session_source():
    if not sessions_enabled():
        return "hub" if mode() == "hub" else ""
    if _session_account() is not None:
        return "atlas"
    if hybrid_mode() and hub_claims():
        return "hub"
    return ""


def _is_trusted(host):
    if not settings.TRUSTED_PROXIES or not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in settings.TRUSTED_PROXIES)


def client_ip():
    peer = request.remote_addr or "?"
    if not _is_trusted(peer):
        return peer
    xff = request.headers.get("X-Forwarded-For", "")
    for hop in reversed([p.strip() for p in xff.split(",") if p.strip()]):
        if not _is_trusted(hop):
            return hop[:settings.MAX_IP_KEY]
    return peer


def _session_account():
    if "_atlas_acct" in g:
        return g._atlas_acct
    acct = None
    username = session.get("user")
    if username and not session.get("_mfa_enroll"):
        import accounts
        acc = accounts.get_user(username)
        if (acc and acc.get("active")
                and session.get("_epoch") == acc.get("session_epoch", 0)):
            now = time.time()
            if (now - session.get("_seen", 0) <= settings.SESSION_IDLE_S
                    and now - session.get("_start", 0) <= settings.SESSION_ABS_S):
                session["_seen"] = now
                acct = acc
    g._atlas_acct = acct
    return acct


def establish_session(acc):
    session.clear()
    session["user"] = acc["username"]
    session["_epoch"] = int(acc.get("session_epoch") or 0)
    now = time.time()
    session["_start"] = now
    session["_seen"] = now


MFA_SOURCES = ("local", "ldap")
_mfa_policy_warned = set()


def mfa_policy_applies(acc):
    policy = settings.mfa_required()
    said = envnames.yes_no(policy)
    if policy == "" or said is False:
        return False
    if said is True or policy == "all":
        return True
    if policy in ("admin", "admins"):
        return bool(acc.get("is_admin"))
    if policy in MFA_SOURCES:
        return policy == acc.get("source")
    if policy not in _mfa_policy_warned:
        _mfa_policy_warned.add(policy)
        log.warning("ATLAS_MFA_REQUIRED=%r names no policy (all, admins, %s, or a yes/no word): "
                    "requiring a second factor of everyone", policy[:40], ", ".join(MFA_SOURCES))
    return True


def require_atlas_auth(exempt_paths=None, exempt_prefixes=None):
    exact = set(DEFAULT_EXEMPT) | set(exempt_paths or []) | {"/auth/login"}
    prefixes = list(exempt_prefixes or ["/static/"])
    prefixes.append("/api/v2/auth/")
    base_check = require_hub_or_standalone(
        exempt_paths=exempt_paths, exempt_prefixes=exempt_prefixes)

    def _check():
        if not sessions_enabled():
            return base_check()
        path = request.path
        if path in exact or any(path.startswith(p) for p in prefixes):
            return None
        if _session_account() is not None:
            return None
        if hybrid_mode() and hub_claims():
            return None
        if session.get("user") and not session.get("_mfa_enroll"):
            session.clear()
        if path.startswith("/api/"):
            return jsonify({"error": "Unauthorized", "reason": "Sign in required"}), 401
        from urllib.parse import quote
        return redirect("/auth/login?next=" + quote(path))

    return _check



def current_user() -> str:
    acc = _session_account()
    if acc:
        return acc["username"]
    if hybrid_mode():
        claims = hub_claims()
        if claims:
            return str(claims.get("u", ""))
    return ""


def has_viewer():
    if mode() == "standalone":
        return True
    if mode() == "hub":
        import hub_auth.auth as hub
        if hub.AUTH_SECRET:
            claims = hub._claims()
            return bool(claims and claims.get("u"))
        return bool(hub.get_remote_user())
    return bool(current_user())


def current_account():
    return _session_account()


def current_groups():
    if not sessions_enabled():
        return None
    acc = _session_account()
    if not acc:
        if hybrid_mode():
            claims = hub_claims()
            if claims:
                return _hub_groups(claims)
        return set()
    import accounts
    grps = {g for g in accounts.groups_of(acc) if g != ADMIN_GROUP}
    if acc.get("is_admin"):
        grps.add(ADMIN_GROUP)
    return grps
