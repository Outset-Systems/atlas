"""OpenID Connect sign-in against a fake identity provider.

Run from Web/: python -m pytest tests
"""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import accounts
import oidc_backend

ISSUER = "https://idp.test/realms/home"
CLIENT = "atlas"
KID = "k1"


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


SIGNING_KEY = _key()
OTHER_KEY = _key()


def _jwk(key, kid):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid=kid, use="sig", alg="RS256")
    return jwk


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeIdP:
    """Answers discovery, JWKS, token and userinfo like a provider would."""

    def __init__(self):
        self.claims = {}
        self.pending = {}
        self.userinfo = None
        self.sign_with = SIGNING_KEY
        self.header = {"kid": KID}
        self.alg = "RS256"
        self.token_calls = []

    def get(self, url, **kw):
        if url == ISSUER + "/.well-known/openid-configuration":
            return _Resp(200, {
                "issuer": ISSUER,
                "authorization_endpoint": ISSUER + "/auth",
                "token_endpoint": ISSUER + "/token",
                "jwks_uri": ISSUER + "/certs",
                "userinfo_endpoint": ISSUER + "/userinfo",
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            })
        if url == ISSUER + "/certs":
            return _Resp(200, {"keys": [_jwk(SIGNING_KEY, KID)]})
        if url == ISSUER + "/userinfo":
            return _Resp(200, self.userinfo or {})
        return _Resp(404, {})

    def post(self, url, data=None, headers=None, **kw):
        assert url == ISSUER + "/token"
        self.token_calls.append((data, headers))
        entry = self.pending.get(data["code"])
        if entry is None:
            return _Resp(400, {"error": "invalid_grant"})
        verifier = data["code_verifier"].encode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier).digest()).rstrip(b"=").decode()
        if challenge != entry["code_challenge"]:
            return _Resp(400, {"error": "invalid_grant"})
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT, "sub": "sub-1", "iat": now,
                  "exp": now + 300, "nonce": entry["nonce"],
                  "preferred_username": "Dana", "name": "Dana D", "email": "dana@home.test",
                  "groups": ["staff"]}
        claims.update(self.claims)
        claims = {k: v for k, v in claims.items() if v is not None}
        token = jwt.encode(claims, self.sign_with, algorithm=self.alg, headers=self.header)
        return _Resp(200, {"id_token": token, "access_token": "at-" + data["code"],
                           "token_type": "Bearer"})


@pytest.fixture
def idp(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_ACCOUNTS_DB", str(tmp_path / "accounts.db"))
    monkeypatch.setenv("ATLAS_AUTH_BACKENDS", "local,oidc")
    monkeypatch.setenv("ATLAS_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("ATLAS_OIDC_CLIENT_ID", CLIENT)
    monkeypatch.setenv("ATLAS_OIDC_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("ATLAS_OIDC_ADMIN_GROUPS", "atlas-admins")
    for name in ("ATLAS_OIDC_ACCESS_GROUPS", "ATLAS_MFA_REQUIRED",
                 "ATLAS_OIDC_TRUST_IDP_MFA", "ATLAS_OIDC_MFA_ACR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(accounts, "_migrated", False)
    fake = FakeIdP()
    monkeypatch.setattr(oidc_backend, "_http", fake)
    oidc_backend.reset_caches()
    yield fake
    oidc_backend.reset_caches()


@pytest.fixture
def client(idp):
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def _start(client, idp, next_path="/", code="code-1"):
    r = client.get("/auth/oidc/start", query_string={"next": next_path})
    assert r.status_code == 302, r.data
    loc = urlparse(r.headers["Location"])
    assert loc.netloc == "idp.test"
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    assert q["code_challenge_method"] == "S256"
    assert q["redirect_uri"] == "https://atlas.test/auth/oidc/callback"
    assert "openid" in q["scope"].split()
    idp.pending[code] = q
    return q


def _sign_in(client, idp, next_path="/", code="code-1"):
    q = _start(client, idp, next_path, code)
    return client.get("/auth/oidc/callback", query_string={"code": code, "state": q["state"]})


def _me(client):
    return client.get("/api/v2/auth/me").get_json()


def _error(resp):
    assert resp.status_code == 302
    return parse_qs(urlparse(resp.headers["Location"]).query).get("error", [""])[0]



def test_sign_in_creates_an_sso_account(client, idp):
    r = _sign_in(client, idp, next_path="/topology")
    assert r.status_code == 302 and r.headers["Location"].endswith("/topology")
    me = _me(client)
    assert me["authenticated"] and me["username"] == "dana"
    assert me["source"] == "oidc" and me["is_admin"] is False
    assert me["groups"] == ["staff"]
    data, headers = idp.token_calls[0]
    assert headers["Authorization"].startswith("Basic ")
    assert "client_secret" not in data


def test_admin_group_maps_to_admin(client, idp):
    idp.claims["groups"] = ["staff", "/atlas-admins"]
    _sign_in(client, idp)
    me = _me(client)
    assert me["is_admin"] is True
    assert "atlas-admins" not in me["groups"]


def test_admin_is_revoked_when_the_group_goes(client, idp):
    idp.claims["groups"] = ["atlas-admins"]
    _sign_in(client, idp)
    assert _me(client)["is_admin"]
    client.post("/api/v2/auth/logout", headers={"X-Atlas-Write": "1"})
    idp.claims["groups"] = ["staff"]
    _sign_in(client, idp, code="code-2")
    assert _me(client)["is_admin"] is False


def test_unknown_state_is_refused(client, idp):
    _start(client, idp)
    r = client.get("/auth/oidc/callback", query_string={"code": "code-1", "state": "forged"})
    assert _error(r) == "expired"
    assert not _me(client)["authenticated"]


def test_state_is_single_use(client, idp):
    q = _start(client, idp)
    _ = client.get("/auth/oidc/callback", query_string={"code": "code-1", "state": q["state"]})
    client.post("/api/v2/auth/logout", headers={"X-Atlas-Write": "1"})
    r = client.get("/auth/oidc/callback", query_string={"code": "code-1", "state": q["state"]})
    assert _error(r) == "expired"


def test_provider_error_is_reported(client, idp):
    q = _start(client, idp)
    r = client.get("/auth/oidc/callback",
                   query_string={"error": "access_denied", "state": q["state"]})
    assert _error(r) == "denied"


@pytest.mark.parametrize("tamper", [
    {"nonce": "replayed"},
    {"aud": "someone-else"},
    {"iss": "https://evil.test"},
    {"exp": int(time.time()) - 3600},
    {"aud": [CLIENT, "other"], "azp": "other"},
])
def test_bad_id_tokens_are_refused(client, idp, tamper):
    idp.claims.update(tamper)
    assert _error(_sign_in(client, idp)) == "refused"
    assert not _me(client)["authenticated"]


def test_unknown_signing_key_is_refused(client, idp):
    idp.sign_with = OTHER_KEY
    assert _error(_sign_in(client, idp)) == "refused"


def test_symmetric_alg_is_refused(client, idp):
    idp.sign_with, idp.alg = "s3cret-but-long-enough-for-hs256-xx", "HS256"
    assert _error(_sign_in(client, idp)) == "refused"


def test_wrong_pkce_verifier_is_refused(client, idp):
    q = _start(client, idp)
    idp.pending["code-1"] = dict(q, code_challenge="not-the-challenge")
    r = client.get("/auth/oidc/callback", query_string={"code": "code-1", "state": q["state"]})
    assert _error(r) == "refused"


def test_access_groups_gate_sign_in(client, idp, monkeypatch):
    monkeypatch.setenv("ATLAS_OIDC_ACCESS_GROUPS", "homelab")
    assert _error(_sign_in(client, idp)) == "refused"
    idp.claims["groups"] = ["homelab"]
    _sign_in(client, idp, code="code-2")
    assert _me(client)["authenticated"]


def test_group_overage_means_no_groups(client, idp):
    idp.claims.update(groups=None, _claim_names={"groups": "src1"})
    idp.userinfo = {"sub": "sub-1"}
    _sign_in(client, idp)
    me = _me(client)
    assert me["authenticated"] and me["groups"] == [] and not me["is_admin"]


def test_groups_from_userinfo_when_missing_from_id_token(client, idp):
    idp.claims["groups"] = None
    idp.userinfo = {"sub": "sub-1", "groups": ["atlas-admins"]}
    _sign_in(client, idp)
    assert _me(client)["is_admin"]


def test_userinfo_for_another_subject_is_ignored(client, idp):
    idp.claims["groups"] = None
    idp.userinfo = {"sub": "someone-else", "groups": ["atlas-admins"]}
    _sign_in(client, idp)
    assert not _me(client)["is_admin"]


def test_local_account_of_the_same_name_is_not_taken_over(client, idp):
    accounts.create_local_user("dana", "a-long-local-password", is_admin=True)
    assert _error(_sign_in(client, idp)) == "refused"
    assert accounts.get_user("dana")["source"] == "local"


def test_renamed_user_keeps_their_account(client, idp):
    _sign_in(client, idp)
    client.post("/api/v2/auth/logout", headers={"X-Atlas-Write": "1"})
    idp.claims["preferred_username"] = "dana.new"
    _sign_in(client, idp, code="code-2")
    assert _me(client)["username"] == "dana"
    assert accounts.get_user("dana.new") is None


def test_another_subject_cannot_claim_a_taken_name(client, idp):
    _sign_in(client, idp)
    client.post("/api/v2/auth/logout", headers={"X-Atlas-Write": "1"})
    idp.claims["sub"] = "sub-2"
    assert _error(_sign_in(client, idp, code="code-2")) == "refused"


def test_blocked_account_cannot_sign_in(client, idp):
    _sign_in(client, idp)
    client.post("/api/v2/auth/logout", headers={"X-Atlas-Write": "1"})
    accounts.set_active("dana", False)
    assert _error(_sign_in(client, idp, code="code-2")) == "refused"


def test_invalid_username_is_refused(client, idp):
    idp.claims["preferred_username"] = "Dana Smith!"
    assert _error(_sign_in(client, idp)) == "refused"



def test_mfa_policy_forces_enrollment(client, idp, monkeypatch):
    monkeypatch.setenv("ATLAS_MFA_REQUIRED", "oidc")
    r = _sign_in(client, idp)
    assert "step=enroll" in r.headers["Location"]
    me = _me(client)
    assert not me["authenticated"] and me["mfa_setup_required"]


def test_provider_mfa_is_trusted_only_when_asked(client, idp, monkeypatch):
    monkeypatch.setenv("ATLAS_MFA_REQUIRED", "all")
    idp.claims["amr"] = ["pwd", "mfa"]
    assert "step=enroll" in _sign_in(client, idp).headers["Location"]
    client.post("/api/v2/auth/logout", headers={"X-Atlas-Write": "1"})
    monkeypatch.setenv("ATLAS_OIDC_TRUST_IDP_MFA", "1")
    r = _sign_in(client, idp, code="code-2")
    assert r.headers["Location"].endswith("/")
    assert _me(client)["authenticated"]


def test_enrolled_totp_is_still_asked(client, idp):
    import pyotp
    _sign_in(client, idp)
    client.post("/api/v2/auth/logout", headers={"X-Atlas-Write": "1"})
    secret, _uri, _svg = accounts.start_mfa_enrollment("dana")
    accounts.confirm_mfa("dana", pyotp.TOTP(secret).now())
    r = _sign_in(client, idp, code="code-2")
    assert "step=mfa" in r.headers["Location"]
    assert not _me(client)["authenticated"]
    page = client.get(r.headers["Location"])
    assert b'"step": "mfa"' in page.data



def test_sso_reauth_needs_a_recent_sign_in(client, idp):
    _sign_in(client, idp)
    hdr = {"X-Atlas-Write": "1"}
    r = client.post("/api/v2/auth/mfa/setup", json={}, headers=hdr)
    assert r.status_code == 200 and r.get_json()["ok"]
    with client.session_transaction() as s:
        s["_start"] = time.time() - 3600
    r = client.post("/api/v2/auth/mfa/setup", json={}, headers=hdr)
    assert r.status_code == 401 and r.get_json()["reauth"]


def test_admin_flag_cannot_be_set_on_sso_accounts(client, idp):
    idp.claims["groups"] = ["atlas-admins"]
    _sign_in(client, idp)
    accounts.create_local_user("bob", "a-long-local-password")
    idp.claims.update(sub="sub-2", preferred_username="erin", groups=["staff"])
    client.post("/api/v2/auth/logout", headers={"X-Atlas-Write": "1"})
    _sign_in(client, idp, code="code-2")
    client.post("/api/v2/auth/logout", headers={"X-Atlas-Write": "1"})
    idp.claims.update(sub="sub-1", preferred_username="dana", groups=["atlas-admins"])
    _sign_in(client, idp, code="code-3")
    r = client.post("/api/v2/auth/users/erin/admin", json={"on": True},
                    headers={"X-Atlas-Write": "1"})
    assert r.status_code == 400 and "ATLAS_OIDC_ADMIN_GROUPS" in r.get_json()["error"]



def test_login_page_offers_sso_and_passwords(client, idp):
    page = client.get("/auth/login?next=/topology").data.decode()
    assert 'href="oidc/start?next=/topology"' in page
    assert 'id="f-login"' in page


def test_login_page_without_password_backends(client, idp, monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH_BACKENDS", "oidc")
    page = client.get("/auth/login").data.decode()
    assert "oidc/start" in page and 'id="f-login"' not in page


def test_sso_routes_are_off_unless_configured(client, idp, monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH_BACKENDS", "local")
    assert client.get("/auth/oidc/start").status_code == 404
    assert "oidc/start" not in client.get("/auth/login").data.decode()


def test_plain_http_issuer_is_refused(idp, monkeypatch):
    monkeypatch.setenv("ATLAS_OIDC_ISSUER", "http://idp.test")
    assert not oidc_backend.enabled()


def test_password_sign_in_still_works(client, idp):
    accounts.create_local_user("carol", "a-long-local-password")
    r = client.post("/api/v2/auth/login", headers={"X-Atlas-Write": "1"},
                    json={"username": "carol", "password": "a-long-local-password"})
    assert r.get_json()["ok"] and _me(client)["source"] == "local"


def test_open_redirect_is_refused(client, idp):
    r = _sign_in(client, idp, next_path="//evil.test/")
    assert r.headers["Location"] in ("/", "http://localhost/")
