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
            if AUTH_SECRET:
                if _claims() is None:
                    return _forbidden(path, f"valid {SIGNED_HEADER} token required")
                return None
            if SECRET_LOST:
                return jsonify({"error": "Server misconfigured",
                                "reason": "ATLAS_HUB_SECRET_FILE is missing or empty"}), 500
            if not request.headers.get("X-Remote-User"):
                return _forbidden(path, "X-Remote-User header required (hub mode)")
            return None

        return jsonify({"error": "Server misconfigured",
                        "reason": f"Unknown ATLAS_AUTH_MODE: {AUTH_MODE!r}"}), 500

    return _check


def get_remote_user() -> str:
    if AUTH_MODE == "hub":
        claims = _claims()
        if claims is not None:
            return str(claims.get("u", ""))
        return "" if SECRET_LOST else request.headers.get("X-Remote-User", "")
    return envnames.env("ATLAS_STANDALONE_USER", "local")


def get_remote_groups() -> list:
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

