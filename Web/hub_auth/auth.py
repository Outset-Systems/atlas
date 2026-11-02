"""
Dual-mode authentication: standalone, or behind a single-sign-on Hub.

Reads the ATLAS_AUTH_MODE environment variable (see envnames.py for the names
this package used before v1.48.0):

- "standalone" (default): no auth gate. Useful for direct access in development
  or when shipping the app as a self-contained product without the Hub.
- "hub": the app trusts an identity injected by the Hub reverse proxy.
  Used when the app is deployed behind a Hub gateway.

The /api/status endpoint is exempt from the auth gate in both modes — Hub uses
it to discover apps, and external monitoring shouldn't require credentials.

── Signed identity (2026-07-16) ──────────────────────────────────────────────
Historically hub mode trusted a PLAINTEXT `X-Remote-User` header. That is only
safe if nothing can reach the app except through the Hub — an actor who can hit
the container directly on the docker network could forge the header and become
anyone. When a shared secret is configured (env `ATLAS_HUB_SECRET`, or a
file at `ATLAS_HUB_SECRET_FILE`), the app instead REQUIRES a short-lived
HMAC-signed token in the header `ATLAS_HUB_AUTH_HEADER` names (default
`X-Hub-Auth`), minted per-request by the Hub, and reads
the identity from the *verified* token — a forged plaintext header no longer
works. Behavior is backward-compatible: with no secret configured, the app
falls back to the legacy plaintext-header check, so un-migrated apps and
standalone mode are unaffected. Roll an app onto signing by giving it the
secret; nothing else changes.
"""

import base64
import hashlib
import hmac
import json
import os
import time

from flask import request, jsonify, g

import envnames

# Resolved at import time. Apps can re-read os.environ if they need runtime override.
AUTH_MODE = (envnames.env("ATLAS_AUTH_MODE") or "standalone").lower().strip()

# Default exempt paths (always reachable, regardless of mode)
DEFAULT_EXEMPT = frozenset([
    "/api/status",
    "/api/health",
    "/healthz",
    "/favicon.ico",
])

# ── Signed-token identity ─────────────────────────────────────────────────────
#: Which header carries the Hub's signed identity (envnames: ATLAS_HUB_AUTH_HEADER).
SIGNED_HEADER = envnames.env("ATLAS_HUB_AUTH_HEADER")
_CLOCK_SKEW = 30          # seconds of tolerance on iat/exp
#: The longest life a token may claim. The Hub mints per request with a
#: 120 s default; anything longer is a minting bug, and a captured token
#: should never stay good for longer than this whatever `exp` says.
_MAX_TTL = 300
_UNSET = object()


def _load_auth_secret() -> bytes | None:
    """Shared HMAC secret, from env or a mounted file. None → legacy mode."""
    val = envnames.env("ATLAS_HUB_SECRET")
    if val:
        return val.encode()
    path = envnames.env("ATLAS_HUB_SECRET_FILE")
    if path and os.path.exists(path):
        with open(path, "rb") as fh:
            data = fh.read().strip()
            return data or None
    return None


AUTH_SECRET = _load_auth_secret()
#: A secret file was named and gave nothing. Unsigned hub mode trusts plain
#: headers, so it has to be chosen by naming no secret at all, never reached
#: because a mount went missing.
SECRET_LOST = AUTH_SECRET is None and bool(envnames.env("ATLAS_HUB_SECRET_FILE"))


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_token(token: str):
    """Return the claims dict for a valid signed-identity token, else None.

    Token = base64url(payload_json) + "." + base64url(hmac_sha256(secret, b64)).
    Constant-time signature check; iat/exp windowed with a small skew.
    """
    if not AUTH_SECRET or not token or "." not in token:
        return None
    payload_b64, _, sig_b64 = token.rpartition(".")
    expected = hmac.new(AUTH_SECRET, payload_b64.encode(), hashlib.sha256).digest()
    try:
        got = _b64d(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(expected, got):
        return None
    try:
        claims = json.loads(_b64d(payload_b64))
    except Exception:
        return None
    now = time.time()
    try:
        exp = float(claims.get("exp", 0))
        iat = float(claims.get("iat", now))
    except (TypeError, ValueError):
        return None               # a signed but malformed claim is a refusal, not a 500
    if exp < now - _CLOCK_SKEW:
        return None
    if iat > now + _CLOCK_SKEW:
        return None
    if exp - iat > _MAX_TTL + 1:
        return None               # server-side cap: the Hub does not set our replay window
        # (+1: a minter that reads the clock twice claims 300.000004 s, not 300)
    return claims


def mint_token(user: str, email: str = "", groups=(), ttl: int = 120, now=None):
    """The signing half of `verify_token` — the same shape the Hub mints.

    For app→Hub reads (the Atlas asking the Hub's calendar, the Ledger asking
    its providers), an app names itself as a MACHINE subject, `svc:<app>`,
    with no groups; the Hub grants such a subject read-only surfaces and
    nothing else. Returns "" when no secret is configured or the subject is
    blank — an empty subject signed by a fleet secret would be a forgery
    every app has reason to trust.
    """
    if not AUTH_SECRET or not user:
        return ""
    now = int(time.time() if now is None else now)
    payload = {"u": user, "e": email or "", "g": list(groups or []), "iat": now, "exp": now + int(ttl)}
    pb = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(
        hmac.new(AUTH_SECRET, pb.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{pb}.{sig}"


def _claims():
    """Verified claims for this request (cached on flask.g), or None."""
    if not AUTH_SECRET:
        return None
    cached = getattr(g, "_hub_claims", _UNSET)
    if cached is not _UNSET:
        return cached
    claims = verify_token(request.headers.get(SIGNED_HEADER, ""))
    try:
        g._hub_claims = claims
    except Exception:
        pass
    return claims


def require_hub_or_standalone(exempt_paths=None, exempt_prefixes=None):
    """
    Returns a Flask before_request handler enforcing the dual-mode contract.

    Usage:
        from hub_auth import require_hub_or_standalone
        app.before_request(require_hub_or_standalone())

    Args:
        exempt_paths: iterable of exact paths to allow without auth.
            Defaults to DEFAULT_EXEMPT (status, health, favicon).
        exempt_prefixes: iterable of path prefixes to allow without auth.
            Defaults to ["/static/"] so static assets always serve.
    """
    exact = set(DEFAULT_EXEMPT) | set(exempt_paths or [])
    prefixes = list(exempt_prefixes or ["/static/"])

    def _forbidden(path, reason):
        if path.startswith("/api/"):
            return jsonify({"error": "Forbidden", "reason": reason}), 403
        return ("Forbidden — this app is in hub mode and must be accessed "
                "through the Hub gateway."), 403

    def _check():
        path = request.path

        # Always-exempt paths
        if path in exact:
            return None
        for prefix in prefixes:
            if path.startswith(prefix):
                return None

        # Standalone mode: no further enforcement
        if AUTH_MODE == "standalone":
            return None

        # Hub mode
        if AUTH_MODE == "hub":
            if AUTH_SECRET:
                # Signed identity required — a forged plaintext header is useless.
                if _claims() is None:
                    return _forbidden(path, f"valid {SIGNED_HEADER} token required")
                return None
            if SECRET_LOST:
                return jsonify({"error": "Server misconfigured",
                                "reason": "ATLAS_HUB_SECRET_FILE is missing or empty"}), 500
            # Legacy: trust the plaintext header (no secret configured).
            if not request.headers.get("X-Remote-User"):
                return _forbidden(path, "X-Remote-User header required (hub mode)")
            return None

        # Unknown mode — fail closed
        return jsonify({"error": "Server misconfigured",
                        "reason": f"Unknown ATLAS_AUTH_MODE: {AUTH_MODE!r}"}), 500

    return _check


def get_remote_user() -> str:
    """
    Get the current effective user.

    In hub mode with signing on, from the verified token; else the plaintext
    X-Remote-User header. In standalone mode, ATLAS_STANDALONE_USER (default
    "local").
    """
    if AUTH_MODE == "hub":
        claims = _claims()
        if claims is not None:
            return str(claims.get("u", ""))
        return "" if SECRET_LOST else request.headers.get("X-Remote-User", "")
    return envnames.env("ATLAS_STANDALONE_USER", "local")


def get_remote_groups() -> list:
    """Get the current user's groups as a list (hub mode) or empty list (standalone)."""
    if AUTH_MODE == "hub":
        claims = _claims()
        if claims is not None:
            g_claim = claims.get("g", [])
            if isinstance(g_claim, list):
                return [str(x).strip() for x in g_claim if str(x).strip()]
            g_claim = str(g_claim)
        else:
            g_claim = "" if SECRET_LOST else request.headers.get("X-Remote-Groups", "")
        return [g.strip() for g in g_claim.split(",") if g.strip()]
    raw = envnames.env("ATLAS_STANDALONE_GROUPS", "")
    return [g.strip() for g in raw.split(",") if g.strip()]

