import logging

from flask import request

import settings
from errors import fail
from redaction import sees_everything, viewer_groups

log = logging.getLogger("atlas.auth.security")

WRITE_HEADER = "X-Atlas-Write"

SAFE_FETCH_SITES = frozenset({"same-origin", "same-site", "none"})


def same_origin_refusal():
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
    return sees_everything(viewer_groups())


def admins_only():
    return fail(403, "admins only")


def write_refusal():
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
    header = (req or request).headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def actor():
    import api_tokens
    token = api_tokens.current()
    if token:
        return f"token:{token['name']}"
    import atlas_auth
    if atlas_auth.sessions_enabled():
        return atlas_auth.current_user() or "unknown"
    import hub_auth.auth as auth
    if auth.AUTH_MODE != "hub":
        return "standalone"
    return auth.get_remote_user() or "unknown"


def is_admin():
    groups = viewer_groups()
    if groups is None and settings.READ_ONLY:
        return False
    return sees_everything(groups)
