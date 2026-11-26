"""OpenID Connect sign-in: authorization code flow with PKCE (S256).

The Atlas is a confidential client when ATLAS_OIDC_CLIENT_SECRET is set and a
public client otherwise; PKCE is sent either way. Configuration is read from
the deployment (environment), never from the settings screen, so the client
secret is not stored in the data directory.

The identity provider's stable identity is (iss, sub). The Atlas user name is
taken from ATLAS_OIDC_USERNAME_CLAIM at first sign-in and then kept, so a
renamed or recycled preferred_username cannot take over someone else's account.
"""
import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from urllib.parse import quote, urlencode, urlparse

import envnames

log = logging.getLogger("atlas.auth.oidc")

STATE_TTL_S = 10 * 60
MAX_PENDING = 5
DISCOVERY_TTL_S = 60 * 60
JWKS_TTL_S = 60 * 60
JWKS_REFRESH_FLOOR_S = 60
CLOCK_LEEWAY_S = 60

ALLOWED_ALGS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512",
                "ES256", "ES384", "ES512", "EdDSA")


class ProviderError(Exception):
    """The identity provider could not be reached or answered something unusable."""


class LoginRefused(Exception):
    """The provider answered, but this sign-in must not proceed."""

    def __init__(self, message, username=""):
        super().__init__(message)
        self.username = username



def _cfg(name, default=""):
    return (str(envnames.env(name) or "").strip() or default)


def _backends():
    import ldap_backend
    return ldap_backend._order(ldap_backend._cfg("ATLAS_AUTH_BACKENDS", "local"))


def issuer():
    return _cfg("ATLAS_OIDC_ISSUER").rstrip("/")


def client_id():
    return _cfg("ATLAS_OIDC_CLIENT_ID")


def client_secret():
    return envnames.secret("ATLAS_OIDC_CLIENT_SECRET")


def label():
    return _cfg("ATLAS_OIDC_LABEL", "single sign-on")


def scopes():
    words = _cfg("ATLAS_OIDC_SCOPES", "openid profile email").replace(",", " ").split()
    if "openid" not in words:
        words.insert(0, "openid")
    return " ".join(dict.fromkeys(words))


def username_claim():
    return _cfg("ATLAS_OIDC_USERNAME_CLAIM", "preferred_username")


def groups_claim():
    return _cfg("ATLAS_OIDC_GROUPS_CLAIM", "groups")


def timeout():
    try:
        return max(1, int(_cfg("ATLAS_OIDC_TIMEOUT", "5")))
    except ValueError:
        return 5


def _verify():
    return _cfg("ATLAS_OIDC_CA_FILE") or True


def _is_secure_url(url):
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme == "https" and parsed.hostname:
        return True
    return parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")


def configured():
    return bool(issuer() and client_id())


def enabled():
    return "oidc" in _backends() and configured() and _is_secure_url(issuer())


_warned = set()


def warn_if_misconfigured():
    if "oidc" not in _backends():
        return
    problem = None
    if not configured():
        problem = ("ATLAS_AUTH_BACKENDS names oidc but ATLAS_OIDC_ISSUER or "
                   "ATLAS_OIDC_CLIENT_ID is unset: single sign-on is off")
    elif not _is_secure_url(issuer()):
        problem = ("ATLAS_OIDC_ISSUER must be https:// (http is accepted only for "
                   "localhost): single sign-on is off")
    if problem and problem not in _warned:
        _warned.add(problem)
        log.error(problem)



def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def new_pkce():
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge



_lock = threading.Lock()
_discovery = {"issuer": None, "at": 0.0, "doc": None}
_jwks = {"uri": None, "at": 0.0, "set": None}

_http = None


def _session():
    global _http
    if _http is None:
        import requests
        _http = requests.Session()
    return _http


def _get_json(url, **kwargs):
    import requests
    try:
        resp = _session().get(url, timeout=timeout(), verify=_verify(), **kwargs)
    except requests.RequestException as e:
        raise ProviderError(f"could not reach {urlparse(url).netloc}: {e.__class__.__name__}") from e
    if resp.status_code != 200:
        raise ProviderError(f"{urlparse(url).netloc} answered HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as e:
        raise ProviderError(f"{urlparse(url).netloc} did not answer JSON") from e
    if not isinstance(body, dict):
        raise ProviderError(f"{urlparse(url).netloc} did not answer a JSON object")
    return body


def discovery(force=False):
    iss = issuer()
    with _lock:
        fresh = (_discovery["issuer"] == iss and _discovery["doc"] is not None
                 and time.time() - _discovery["at"] < DISCOVERY_TTL_S)
        if fresh and not force:
            return _discovery["doc"]
    doc = _get_json(iss + "/.well-known/openid-configuration")
    if str(doc.get("issuer", "")).rstrip("/") != iss:
        raise ProviderError("the discovery document names a different issuer "
                            f"({str(doc.get('issuer'))[:120]!r}) than ATLAS_OIDC_ISSUER")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not _is_secure_url(str(doc.get(key, ""))):
            raise ProviderError(f"the discovery document has no usable {key}")
    methods = doc.get("code_challenge_methods_supported")
    if isinstance(methods, list) and methods and "S256" not in methods:
        raise ProviderError("the provider does not support PKCE with S256")
    with _lock:
        _discovery.update(issuer=iss, at=time.time(), doc=doc)
    return doc


def _key_set(force=False):
    import jwt
    uri = discovery()["jwks_uri"]
    with _lock:
        age = time.time() - _jwks["at"]
        if _jwks["uri"] == uri and _jwks["set"] is not None:
            if not force and age < JWKS_TTL_S:
                return _jwks["set"]
            if force and age < JWKS_REFRESH_FLOOR_S:
                return _jwks["set"]
    raw = _get_json(uri)
    try:
        keys = jwt.PyJWKSet.from_dict(raw)
    except jwt.PyJWTError as e:
        raise ProviderError(f"the provider's signing keys are unusable: {e}") from e
    with _lock:
        _jwks.update(uri=uri, at=time.time(), set=keys)
    return keys


def _signing_key(token):
    import jwt
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise LoginRefused(f"the ID token is malformed: {e}") from e
    alg = header.get("alg")
    if alg not in ALLOWED_ALGS:
        raise LoginRefused(f"the ID token is signed with {str(alg)[:20]!r}, which is not accepted")
    kid = header.get("kid")
    for force in (False, True):
        keys = _key_set(force=force)
        matches = [k for k in keys.keys
                   if (kid is None or k.key_id == kid)
                   and (k.public_key_use in (None, "sig"))]
        if len(matches) == 1 or (matches and kid is not None):
            return matches[0], alg
    raise LoginRefused("the ID token was signed by a key the provider does not publish")



def authorization_url(redirect_uri, state, nonce, challenge, reauth=False):
    doc = discovery()
    params = {
        "response_type": "code",
        "client_id": client_id(),
        "redirect_uri": redirect_uri,
        "scope": scopes(),
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if reauth:
        params["prompt"] = "login"
        params["max_age"] = "0"
    endpoint = doc["authorization_endpoint"]
    joiner = "&" if "?" in endpoint else "?"
    return endpoint + joiner + urlencode(params)


def new_pending(next_path, reauth=False):
    verifier, challenge = new_pkce()
    entry = {
        "state": secrets.token_urlsafe(32),
        "nonce": secrets.token_urlsafe(32),
        "verifier": verifier,
        "next": next_path,
        "reauth": bool(reauth),
        "at": time.time(),
    }
    return entry, challenge


def remember_pending(stash, entry):
    """Keep at most MAX_PENDING unexpired sign-ins (one per open tab)."""
    now = time.time()
    kept = [e for e in (stash or []) if isinstance(e, dict)
            and now - float(e.get("at", 0)) <= STATE_TTL_S]
    kept.append(entry)
    return kept[-MAX_PENDING:]


def take_pending(stash, state):
    """Return (entry, remaining stash). The entry is consumed whatever happens next."""
    state = state or ""
    now = time.time()
    found, rest = None, []
    for e in stash or []:
        if not isinstance(e, dict):
            continue
        if found is None and hmac.compare_digest(str(e.get("state", "")), state):
            found = e
            continue
        rest.append(e)
    if found and now - float(found.get("at", 0)) > STATE_TTL_S:
        found = None
    return found, rest



def _token_request(code, redirect_uri, verifier):
    import requests
    doc = discovery()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }
    headers = {"Accept": "application/json"}
    secret = client_secret()
    methods = doc.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    if secret and "client_secret_basic" in methods:
        pair = f"{quote(client_id(), safe='')}:{quote(secret, safe='')}"
        headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
    elif secret:
        data["client_id"] = client_id()
        data["client_secret"] = secret
    else:
        data["client_id"] = client_id()
    try:
        resp = _session().post(doc["token_endpoint"], data=data, headers=headers,
                               timeout=timeout(), verify=_verify(), allow_redirects=False)
    except requests.RequestException as e:
        raise ProviderError(f"the token endpoint could not be reached: {e.__class__.__name__}") from e
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code != 200:
        err = str((body or {}).get("error", ""))[:60] if isinstance(body, dict) else ""
        raise LoginRefused(f"the token endpoint refused the code (HTTP {resp.status_code}"
                           f"{', ' + err if err else ''})")
    if not isinstance(body, dict) or not body.get("id_token"):
        raise ProviderError("the token endpoint answered without an ID token")
    return body


def validate_id_token(id_token, nonce):
    import jwt
    doc = discovery()
    key, alg = _signing_key(id_token)
    try:
        claims = jwt.decode(
            id_token, key=key.key, algorithms=[alg],
            audience=client_id(), issuer=doc["issuer"], leeway=CLOCK_LEEWAY_S,
            options={"require": ["iss", "sub", "aud", "exp", "iat"]})
    except jwt.PyJWTError as e:
        raise LoginRefused(f"the ID token did not validate: {e}") from e
    aud = claims.get("aud")
    many = isinstance(aud, list) and len(aud) > 1
    azp = claims.get("azp")
    if (many or azp is not None) and azp != client_id():
        raise LoginRefused("the ID token was issued to another client (azp)")
    if not hmac.compare_digest(str(claims.get("nonce", "")), str(nonce or "")):
        raise LoginRefused("the ID token's nonce does not match this sign-in")
    return claims


def _userinfo(access_token, sub):
    doc = discovery()
    url = doc.get("userinfo_endpoint")
    if not access_token or not url or not _is_secure_url(str(url)):
        return {}
    try:
        info = _get_json(url, headers={"Authorization": f"Bearer {access_token}",
                                       "Accept": "application/json"})
    except ProviderError as e:
        log.warning("oidc: userinfo unavailable, using the ID token alone: %s", e)
        return {}
    if info.get("sub") != sub:
        log.warning("oidc: userinfo answered for a different subject; ignored")
        return {}
    return info



def _claim(claims, path):
    node = claims
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        sep = "," if "," in value else " "
        return [p.strip() for p in value.split(sep) if p.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def _norm_group(name):
    return name.strip().lstrip("/").lower()


def _matches(groups, configured):
    wanted = {_norm_group(c) for c in configured if c.strip()}
    return any(_norm_group(g) in wanted for g in groups)


def _group_list(value):
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def access_groups():
    return _group_list(_cfg("ATLAS_OIDC_ACCESS_GROUPS"))


def admin_groups():
    return _group_list(_cfg("ATLAS_OIDC_ADMIN_GROUPS", envnames.env("ATLAS_ADMIN_GROUP") or ""))


def idp_mfa(claims):
    """True when the provider says this sign-in used more than one factor."""
    if envnames.yes_no(_cfg("ATLAS_OIDC_TRUST_IDP_MFA")) is not True:
        return False
    amr = [a.lower() for a in _as_list(claims.get("amr"))]
    if "mfa" in amr:
        return True
    acr_ok = {a.strip() for a in _cfg("ATLAS_OIDC_MFA_ACR").split(",") if a.strip()}
    return bool(acr_ok) and str(claims.get("acr", "")) in acr_ok


def identity_from_claims(claims):
    import accounts
    gclaim = groups_claim()
    raw = _claim(claims, gclaim)
    overage = (raw is None and isinstance(claims.get("_claim_names"), dict)
               and gclaim in claims["_claim_names"])
    if overage:
        log.warning("oidc: the provider left the %r claim out because the user is in too many "
                    "groups (group overage); treating them as in no groups. Emit only the "
                    "groups assigned to the application.", gclaim)
    groups = _as_list(raw)

    uclaim = username_claim()
    username = str(_claim(claims, uclaim) or "").strip().lower()
    if uclaim == "email" and claims.get("email_verified") is False:
        raise LoginRefused("the provider says this email address is not verified", username)
    if not username:
        raise LoginRefused(f"the ID token has no {uclaim!r} claim to use as a user name")
    if not accounts.valid_username(username):
        raise LoginRefused(f"{username[:64]!r} is not a valid Atlas user name "
                           "(lowercase letters, digits, . _ @ -)", username)

    access = access_groups()
    if access and not _matches(groups, access):
        raise LoginRefused("not in any of ATLAS_OIDC_ACCESS_GROUPS", username)

    reserved = (envnames.env("ATLAS_ADMIN_GROUP") or "").lower()
    return {
        "username": username,
        "external_id": f"{claims['iss']}|{claims['sub']}",
        "display_name": str(claims.get("name") or username)[:200],
        "email": str(claims.get("email") or "")[:320],
        "groups": [g for g in dict.fromkeys(g.lstrip("/") for g in groups)
                   if g and g.lower() != reserved and "," not in g],
        "is_admin": _matches(groups, admin_groups()),
        "idp_mfa": idp_mfa(claims),
    }


def complete(code, entry, redirect_uri):
    """Exchange the code, validate the ID token and return the Atlas identity."""
    if not code:
        raise LoginRefused("the provider returned no authorization code")
    tokens = _token_request(code, redirect_uri, entry["verifier"])
    claims = validate_id_token(tokens["id_token"], entry["nonce"])
    if _claim(claims, groups_claim()) is None or not _claim(claims, username_claim()):
        extra = _userinfo(tokens.get("access_token"), claims["sub"])
        for key, value in extra.items():
            claims.setdefault(key, value)
    return identity_from_claims(claims)


def reset_caches():
    with _lock:
        _discovery.update(issuer=None, at=0.0, doc=None)
        _jwks.update(uri=None, at=0.0, set=None)
