"""Atlas-local auth gate: adds ATLAS_AUTH_MODE=accounts (real sign-in) over
the framework's dual-mode gate, the way a sibling app does — hub_auth stays
untouched, so `hub` deployments and `standalone` dev behave byte-for-byte as
before. Additive by design.

In accounts mode a request is authenticated by a Flask session that:
  * names a user that still EXISTS and is still ACTIVE (re-checked every
    request — sessions are stateless cookies, the DB is where revocation lives),
  * carries the account's CURRENT session epoch (bumped on credential change),
  * is inside both the idle and absolute lifetimes,
  * is not a half-finished login (pending MFA code, pending forced enrollment).

Mode is read from the environment PER REQUEST, not at import: the test suite
builds apps for several modes in one process (appfixture.fresh_app), and an
import-time constant here would hand every later suite the first suite's mode.
"""

import ipaddress
import logging
import time

from flask import g, jsonify, redirect, request, session

from hub_auth import require_hub_or_standalone
from hub_auth.auth import DEFAULT_EXEMPT

import settings

log = logging.getLogger("atlas.auth.gate")

import envnames  # noqa: E402

#: The group that makes a viewer an Atlas admin (ATLAS_ADMIN_GROUP).
ADMIN_GROUP = envnames.env("ATLAS_ADMIN_GROUP")


def mode():
    return settings.auth_mode()


def accounts_mode():
    return mode() == "accounts"


def hybrid_mode():
    """`hybrid` — the Hub's identity when it is there, our own sign-in when it
    is not. The Feed's shape (score-worker), and the only mode that lets one
    instance sit behind the Hub *and* be reached directly with a real login."""
    return mode() == "hybrid"


def sessions_enabled():
    """True where an Atlas session can exist at all."""
    return mode() in ("accounts", "hybrid")


def hub_claims():
    """The Hub's VERIFIED identity for this request, or None.

    ⚠ Deliberately NOT `hub_auth.get_remote_user()`/`get_remote_groups()`.
    Both fall back to the plaintext `X-Remote-*` headers whenever the signed
    token is absent or invalid — a kindness for hubs not yet signing, and safe
    in *hub* mode only because that mode's gate has already 403'd the request
    before any handler can ask. Hybrid has no such gate in front of it: the
    whole point is that a request without a Hub identity is allowed through to
    the login. So a fallback here would mean anyone could forge
    `X-Remote-User: link` + `X-Remote-Groups: atlas-admins` and be admin.
    Worse, those helpers return the *standalone default* when AUTH_MODE is not
    "hub", which in hybrid would silently name every caller "local".

    Once a secret is configured the signature is the only thing that counts.

    ⚠ And with NO secret configured there is no Hub identity here at all. This
    used to fall back to the plaintext header "the same documented legacy
    posture hub mode itself takes" — but that posture is only safe because hub
    mode has the Hub's own gate in front of it, which is precisely what the
    paragraph above says hybrid does not. The fallback therefore made the
    forged `X-Remote-User: link` + `X-Remote-Groups: atlas-admins` request that
    this docstring describes as the thing to prevent into unauthenticated
    admin: `require_atlas_auth` lets any request with hub claims straight
    through, and `is_admin()` reads atlas-admins out of them.

    It fails closed instead. A hybrid instance whose secret is missing loses
    Hub SSO and everyone signs in through `/auth/login` — visibly degraded
    rather than silently open. That distinction matters because
    `hub_auth.auth._load_auth_secret()` returns None *without an error*
    when ATLAS_HUB_SECRET_FILE names a path that does not exist or is empty,
    which is what a renamed or failed docker secret looks like.
    """
    import hub_auth.auth as auth
    if not auth.AUTH_SECRET:
        _warn_unsigned_hub()
        return None
    return auth.verify_token(request.headers.get(auth.SIGNED_HEADER, "")) or None


_warned_unsigned = False


def _warn_unsigned_hub():
    """Say once, loudly, that Hub SSO is off — a silent degrade reads as a bug
    in the Hub rather than a missing secret in this deployment."""
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
    """Where this request's identity came from: 'atlas' (our own session, and
    the only one we can end), 'hub' (the gateway named them), or '' (nobody).
    The account surface reads this — offering a sign-out for a session we do
    not own would be a button that cannot work."""
    if not sessions_enabled():
        return "hub" if mode() == "hub" else ""
    if _session_account() is not None:
        return "atlas"
    if hybrid_mode() and hub_claims():
        return "hub"
    return ""


def _idle_seconds():
    return settings.SESSION_IDLE_S


def _abs_seconds():
    return settings.SESSION_ABS_S


def _is_trusted(host):
    if not settings.TRUSTED_PROXIES or not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False        # '?', 'testclient', junk: never a proxy
    return any(addr in net for net in settings.TRUSTED_PROXIES)


def client_ip():
    """Client IP — the trust rule. Believe X-Forwarded-For only when the SOCKET
PEER is a proxy we have named, then walk the header from the RIGHT, skipping
trusted hops: the first address that is NOT one of ours is the client, the
address the outermost proxy we trust actually observed. Everything left of it
is text the caller supplied. An untrusted peer's header is ignored outright.

This was a HOP COUNT until 2026-09-09, and a count believes the header from
ANY peer that can open a socket — which on the `suite` network is all 14
containers, not just tls-proxy and the Hub. Measured, not theorised: an
arbitrary peer sending `X-Forwarded-For: 1.2.3.4` resolved to 1.2.3.4, so a
compromised sibling could rotate the header and walk past the login throttle.
The two proxies now have PINNED addresses (the internal host's compose) precisely
so they can be named here.

Unset / empty = trust nobody, key on the socket peer. A bare integer (the old
hop count) is REFUSED rather than reinterpreted: it warns and trusts nobody,
because silently trusting the wrong thing is the failure this closes."""
    peer = request.remote_addr or "?"
    if not _is_trusted(peer):
        return peer
    xff = request.headers.get("X-Forwarded-For", "")
    for hop in reversed([p.strip() for p in xff.split(",") if p.strip()]):
        if not _is_trusted(hop):
            return hop[:settings.MAX_IP_KEY]
    # Empty header, or every entry is a proxy we named — the peer is the
    # nearest thing to a client we can vouch for.
    return peer


def _session_account():
    """The live, revalidated account for this request's session, or None.
    Cached on g so the gate and every helper hit the DB once per request."""
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
            if (now - session.get("_seen", 0) <= _idle_seconds()
                    and now - session.get("_start", 0) <= _abs_seconds()):
                session["_seen"] = now
                acct = acc
    g._atlas_acct = acct
    return acct


def establish_session(acc):
    """Called by the login routes once every factor has passed."""
    session.clear()
    session["user"] = acc["username"]
    session["_epoch"] = int(acc.get("session_epoch") or 0)
    now = time.time()
    session["_start"] = now
    session["_seen"] = now


def mfa_policy_applies(acc):
    """Who MUST hold a second factor (ATLAS_MFA_REQUIRED, read live).

    `admins` (2026-09-03): every surveyor is fenced to enrollment,
    everyone else may enroll but is not made to — the admin flag is what a
    stolen password would buy, so that is where the second factor is not
    optional. `all`/`1` fences everyone; `local`/`ldap` fences one source.

    ONE implementation, here, since v1.41.0. Until then the v1 login route
    carried the `admins` branch and its v2 twin — the one the browser actually
    posts to since the 2026-08-25 cutover — did not, so the policy the settings
    described was never enforced on the live path (found at the v1 removal).
    """
    policy = settings.mfa_required()
    if policy in ("", "0", "off", "no"):
        return False
    if policy in ("1", "all", "yes", "on"):
        return True
    if policy in ("admin", "admins"):
        return bool(acc.get("is_admin"))
    return policy == acc.get("source")


def require_atlas_auth(exempt_paths=None, exempt_prefixes=None):
    """Drop-in replacement for hub_auth.require_hub_or_standalone()."""
    exact = set(DEFAULT_EXEMPT) | set(exempt_paths or []) | {"/auth/login"}
    prefixes = list(exempt_prefixes or ["/static/"])
    # The login flow itself must be reachable signed-out; each /api/v2/auth
    # route (api/v2/accounts_v2.py) enforces its own same-origin + session-
    # state requirements, so the prefix is exempt here and gated there.
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
        # Hybrid: the Hub's verified identity is a way in too. Checked AFTER the
        # session so a viewer who signed in here explicitly keeps that identity
        # rather than being silently re-labelled by a passing gateway header.
        if hybrid_mode() and hub_claims():
            return None
        # Drop a FULL session that no longer validates (revoked, expired,
        # epoch-bumped) — but never a half-finished login: a pending-MFA or
        # forced-enrollment session hitting a gated URL (the SPA polls) must
        # keep its state, or the login flow dies under it mid-step.
        if session.get("user") and not session.get("_mfa_enroll"):
            session.clear()
        if path.startswith("/api/"):
            return jsonify({"error": "Unauthorized", "reason": "Sign in required"}), 401
        from urllib.parse import quote
        return redirect("/auth/login?next=" + quote(path))

    return _check


# ── Identity helpers (the seam redaction and the Desk read) ─────────────────

def current_user() -> str:
    acc = _session_account()
    if acc:
        return acc["username"]
    if hybrid_mode():
        claims = hub_claims()
        if claims:
            return str(claims.get("u", ""))
    return ""


def current_account():
    return _session_account()


def current_groups():
    """The viewer's clearance groups, or None when the caller is not in
    accounts mode (callers then fall through to their existing logic).

    ⚠ ADMIN_GROUP ("atlas-admins") is a magic sentinel: `redaction.sees_everything`
    treats its presence in the set as full clearance + write authority. In
    accounts mode admin authority is the `is_admin` FLAG (settable on its own,
    mapped from the configurable ATLAS_LDAP_ADMIN_GROUPS) — NOT membership of a
    group that happens to be named "atlas-admins". So the sentinel is stripped
    from the account's assigned/mirrored groups and re-added ONLY from the flag.
    Without the strip, an LDAP member of AD `atlas-admins` whose is_admin is False
    (because the operator configured a different admin group), or a local user
    handed "atlas-admins" as a view-clearance group, would silently gain full
    editor + unredacted access — the escalation the 2026-08-11 security review caught.
    Assigning the group is also refused at the source (accounts.set_groups /
    create_local_user); this is the second line."""
    if not sessions_enabled():
        return None
    acc = _session_account()
    if not acc:
        # Hybrid, no Atlas session: clearance is whatever the Hub SIGNED. Note
        # ADMIN_GROUP is NOT stripped here — on a Hub identity that group IS
        # what admin means (hub mode's own rule), and there is no separate
        # is_admin flag behind it to conflate with. The strip below exists only
        # for accounts rows, where such a flag does exist.
        if hybrid_mode():
            claims = hub_claims()
            if claims:
                return _hub_groups(claims)
        return set()      # signed out ⇒ no clearance, never None
    import accounts
    grps = {g for g in accounts.groups_of(acc) if g != ADMIN_GROUP}
    if acc.get("is_admin"):
        grps.add(ADMIN_GROUP)
    return grps


def is_admin() -> bool:
    acc = _session_account()
    if acc:
        return bool(acc.get("is_admin"))
    if hybrid_mode():
        claims = hub_claims()
        if claims:
            return ADMIN_GROUP in _hub_groups(claims)
    return False
