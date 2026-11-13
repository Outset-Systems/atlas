"""What it takes to change something — the gate in front of every write route.

Before this, `POST /api/positions` and `POST /api/rack` checked the caller's
groups and nothing else. Behind the Hub that is not sufficient: the Hub injects
the signed identity from *its own session cookie*, so a page on another origin
could point a request at the Hub's `/atlas/` path, the cookie would ride along,
the Hub would helpfully sign it, and the app would see a fully authorised
admin. Classic CSRF, and the editor turns it from "moves some dots" into
"rewrites the map".

Two checks, cheap and independent:

1. **A custom request header.** A cross-origin page cannot set one without a
   CORS preflight, and this app answers no preflight, so the request never
   arrives. This is the actual protection.
2. **`Sec-Fetch-Site`.** Every current browser sends it and it cannot be
   forged from script. Defence in depth, and it costs a dict lookup.

Neither is a substitute for the group check, which stays exactly as it was.
"""

import logging

from flask import request

import settings
from errors import fail
from redaction import sees_everything, viewer_groups

log = logging.getLogger("atlas.auth.security")

#: The header a same-origin caller must send on any write.
WRITE_HEADER = "X-Atlas-Write"

#: `Sec-Fetch-Site` values that are not cross-origin. "none" is a direct
#: navigation or a non-browser client (curl, the CLI, a test harness).
SAFE_FETCH_SITES = frozenset({"same-origin", "same-site", "none"})


def same_origin_refusal():
    """The reason this request is not from the Atlas's own page, or None.

    The two browser-side checks above, and nothing about who is asking: the
    accounts surface (`api/v2/accounts_v2.py`) needs exactly this much on routes
    that run BEFORE there is an identity (the login POST itself), and the editor
    needs it in front of its admin check. One implementation, so the app has
    one answer to "what proves a request came from us" — it used to have two
    (a per-session token on the sign-in routes, this header everywhere else).
    """
    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site and fetch_site not in SAFE_FETCH_SITES:
        log.warning("refused a %s write to %s", fetch_site, request.path)
        return fail(403, "cross-site writes are refused",
                    reason=f"Sec-Fetch-Site: {fetch_site}")

    if request.headers.get(WRITE_HEADER) != "1":
        return fail(403, "this request is missing its write header",
                    reason=f"send {WRITE_HEADER}: 1 — it is what proves the request "
                           f"came from the Atlas itself and not another site")
    return None


def sees_whole_map():
    """True when the caller may see the whole map."""
    return sees_everything(viewer_groups())


def admins_only():
    """The refusal an admins-only surface answers, as `(json, status)`."""
    return fail(403, "admins only")


def write_refusal():
    """The reason this write must not proceed, or None if it may.

    Returns a ready-to-return `(json, status)` tuple so route bodies stay one
    `if` long.
    """
    if settings.READ_ONLY:
        return fail(403, "this Atlas is read-only",
                    reason="ATLAS_READONLY=1 — the dataset is managed elsewhere")

    refusal = same_origin_refusal()
    if refusal:
        return refusal

    if not sees_whole_map():
        return admins_only()

    return None


def bearer_token(req=None):
    """The token in `Authorization: Bearer <token>`, or "" when the header is
    absent or carries another scheme. Scheme matched without regard to case,
    the token stripped — the one reading every token-taking route shares
    (api_tokens, ingest, tripwires, the beat endpoint, /metrics)."""
    header = (req or request).headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def actor():
    """Who is making this change, for the change log.

    Standalone mode has no identity to report, and saying so plainly beats
    recording every edit as an anonymous "local".
    """
    import api_tokens
    token = api_tokens.current()
    if token:
        return f"token:{token['name']}"
    import atlas_auth
    # hybrid resolves through atlas_auth too — it knows both identity sources
    # and, unlike the hub_auth helpers below, never falls back to a
    # plaintext header once signing is configured.
    if atlas_auth.sessions_enabled():
        return atlas_auth.current_user() or "unknown"
    import hub_auth.auth as auth   # read through the module, never a copy
    if auth.AUTH_MODE != "hub":
        return "standalone"
    return auth.get_remote_user() or "unknown"


def is_admin():
    """True when the caller may see and use the editing surfaces.

    A look-only standalone Atlas has no admin. Nobody signs in, so `groups` is
    None for every visitor, and with writes refused no editor is served to need
    these surfaces. Standalone with writes on keeps them: that is what
    ATLAS_ALLOW_INSECURE acknowledges.
    """
    groups = viewer_groups()
    if groups is None and settings.READ_ONLY:
        return False
    return sees_everything(groups)
