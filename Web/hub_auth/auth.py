import base64
import hashlib
import hmac
import json
import os
import time

from flask import request, jsonify, g

import envnames

AUTH_MODE = (envnames.env("ATLAS_AUTH_MODE") or "standalone").lower().strip()

DEFAULT_EXEMPT = frozenset([
    "/api/status",
    "/api/health",
    "/healthz",
    "/favicon.ico",
])

SIGNED_HEADER = envnames.env("ATLAS_HUB_AUTH_HEADER")
_CLOCK_SKEW = 30
_MAX_TTL = 300
_UNSET = object()


def _load_auth_secret() -> bytes | None:
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
SECRET_LOST = AUTH_SECRET is None and bool(envnames.env("ATLAS_HUB_SECRET_FILE"))

SIGNED_MODES = ("hub", "hybrid")


class HubSecretMissing(RuntimeError):
    """Raised at startup when a mode that trusts the hub has no secret to check it with."""


def secret_problem(mode, secret=_UNSET, lost=_UNSET):
    """Why `mode` cannot run with the configured hub secret, or None if it can."""
    mode = (mode or "").lower().strip()
    if mode not in SIGNED_MODES:
        return None
    secret = AUTH_SECRET if secret is _UNSET else secret
    lost = SECRET_LOST if lost is _UNSET else lost
    if secret:
        return None
    if lost:
        return (f"ATLAS_AUTH_MODE={mode} but ATLAS_HUB_SECRET_FILE is missing or empty. "
                "Fix the file, or set ATLAS_HUB_SECRET.")
    return (f"ATLAS_AUTH_MODE={mode} needs ATLAS_HUB_SECRET (or ATLAS_HUB_SECRET_FILE) so the "
            "Hub's signed identity can be checked. Atlas no longer trusts a plain "
            "X-Remote-User header. Set the secret, or use ATLAS_AUTH_MODE=accounts.")


def require_secret(mode):
    """Refuse to start a hub or hybrid Atlas that has no hub secret."""
    problem = secret_problem(mode)
    if problem:
        raise HubSecretMissing(problem)


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_token(token: str):
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
        return None
    if exp < now - _CLOCK_SKEW:
        return None
    if iat > now + _CLOCK_SKEW:
        return None
    if exp - iat > _MAX_TTL + 1:
        return None
    return claims


def mint_token(user: str, email: str = "", groups=(), ttl: int = 120, now=None):
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
    exact = set(DEFAULT_EXEMPT) | set(exempt_paths or [])
    prefixes = list(exempt_prefixes or ["/static/"])

    def _forbidden(path, reason):
        if path.startswith("/api/"):
            return jsonify({"error": "Forbidden", "reason": reason}), 403
        return ("Forbidden — this app is in hub mode and must be accessed "
                "through the Hub gateway."), 403

    def _check():
        path = request.path

        if path in exact:
            return None
        for prefix in prefixes:
            if path.startswith(prefix):
                return None

        if AUTH_MODE == "standalone":
            return None

        if AUTH_MODE == "hub":
            if not AUTH_SECRET:
                # create_app refuses to start like this; fail closed if something
                # imported the gate without going through it.
                return jsonify({"error": "Server misconfigured",
                                "reason": secret_problem("hub")}), 500
            if _claims() is None:
                return _forbidden(path, f"valid {SIGNED_HEADER} token required")
            return None

        return jsonify({"error": "Server misconfigured",
                        "reason": f"Unknown ATLAS_AUTH_MODE: {AUTH_MODE!r}"}), 500

    return _check


def get_remote_user() -> str:
    if AUTH_MODE == "hub":
        claims = _claims()
        if claims is not None:
            return str(claims.get("u", ""))
        return ""
    return envnames.env("ATLAS_STANDALONE_USER", "local")


def get_remote_groups() -> list:
    if AUTH_MODE == "hub":
        claims = _claims()
        if claims is None:
            return []
        g_claim = claims.get("g", [])
        if isinstance(g_claim, list):
            return [str(x).strip() for x in g_claim if str(x).strip()]
        g_claim = str(g_claim)
        return [g.strip() for g in g_claim.split(",") if g.strip()]
    raw = envnames.env("ATLAS_STANDALONE_GROUPS", "")
    return [g.strip() for g in raw.split(",") if g.strip()]

