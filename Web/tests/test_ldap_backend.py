"""The directory backend (ldap_backend.py) against a fake connection — no
real server, no ldap3 requirement beyond what's installed."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ldap_backend  # noqa: E402

ATLAS_TEST_ENV = {}


class _Attr:
    def __init__(self, values):
        self.values = values if isinstance(values, list) else [values]

    def __bool__(self):
        return bool(self.values)

    def __str__(self):
        return str(self.values[0]) if self.values else ""


class _Entry:
    def __init__(self, groups, mail="ops@home.example", display="Ops of the lab"):
        self.memberOf = _Attr(groups)
        self.mail = _Attr(mail)
        self.displayName = _Attr(display)


class _FakeConn:
    def __init__(self, entries):
        self.entries_to_return = entries
        self.entries = []
        self.searched = {}

    def search(self, **kw):
        self.searched = kw
        self.entries = self.entries_to_return

    def unbind(self):
        pass


@pytest.fixture
def ldap_env(monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH_BACKENDS", "ldap")
    monkeypatch.setenv("ATLAS_LDAP_URL", "ldaps://dc.home.example:636")
    monkeypatch.setenv("ATLAS_LDAP_BASE_DN", "DC=home,DC=example")
    yield
    ldap_backend._connect_fn = None


def _fake(groups, *, raise_on_bind=False, record=None):
    def connect(url, upn, password, timeout):
        if record is not None:
            record.update(url=url, upn=upn, password=password)
        if raise_on_bind:
            raise RuntimeError("invalid credentials")
        return _FakeConn([_Entry(groups)])
    return connect


def test_successful_bind_maps_groups_and_admin(ldap_env):
    record = {}
    ldap_backend._connect_fn = _fake(
        ["CN=atlas-admins,OU=Groups,DC=home,DC=example",
         "CN=HUB-Atlas,OU=Groups,DC=home,DC=example"], record=record)
    ok, info = ldap_backend.authenticate("Ops", "hunter2-hunter2")
    assert ok
    assert info["username"] == "ops"
    assert info["display_name"] == "Ops of the lab"
    assert set(info["groups"]) == {"atlas-admins", "HUB-Atlas"}
    assert info["is_admin"]                       # atlas-admins is the default
    assert record["upn"] == "Ops@home.example"     # UPN derived from BASE_DN


def test_failed_bind_is_generic(ldap_env):
    ldap_backend._connect_fn = _fake([], raise_on_bind=True)
    ok, info = ldap_backend.authenticate("ops", "wrong")
    assert (ok, info) == (False, {})


def test_empty_password_never_binds(ldap_env):
    """An empty password to an AD simple bind is an ANONYMOUS bind and it
    SUCCEEDS server-side — the check must refuse before ever connecting."""
    called = {}
    ldap_backend._connect_fn = _fake([], record=called)
    for pw in ("", "   ", None):
        ok, _ = ldap_backend.authenticate("ops", pw)
        assert not ok
    assert not called                              # never reached the server


def test_bad_username_shapes_refused(ldap_env):
    ldap_backend._connect_fn = _fake(["CN=HUB-Atlas,DC=home,DC=example"])
    for name in ("", "a b", "x(y)", "a" * 65, "*"):
        ok, _ = ldap_backend.authenticate(name, "some-password")
        assert not ok, name


def test_plaintext_ldap_refused_loudly(ldap_env, monkeypatch):
    monkeypatch.setenv("ATLAS_LDAP_URL", "ldap://dc.home.example:389")
    with pytest.raises(ValueError):
        ldap_backend.authenticate("ops", "some-password")


def test_access_groups_gate(ldap_env, monkeypatch):
    monkeypatch.setenv("ATLAS_LDAP_ACCESS_GROUPS", "HUB-Atlas")
    ldap_backend._connect_fn = _fake(["CN=HUB-Feed,OU=Groups,DC=home,DC=example"])
    ok, _ = ldap_backend.authenticate("ops", "some-password")
    assert not ok                                  # bound fine, not cleared
    ldap_backend._connect_fn = _fake(["CN=HUB-Atlas,OU=Groups,DC=home,DC=example"])
    ok, info = ldap_backend.authenticate("ops", "some-password")
    assert ok and not info["is_admin"]


def test_admin_groups_configurable(ldap_env, monkeypatch):
    monkeypatch.setenv("ATLAS_LDAP_ADMIN_GROUPS", "Cartographers")
    ldap_backend._connect_fn = _fake(["CN=Cartographers,DC=home,DC=example"])
    ok, info = ldap_backend.authenticate("ops", "some-password")
    assert ok and info["is_admin"]


def test_filter_escaping(ldap_env):
    assert ldap_backend._esc("a*b(c)d\\e") == "a\\2ab\\28c\\29d\\5ce"


def test_identity_is_resolved_by_the_upn_that_bound(ldap_env):
    """The bind proves control of a UPN, so the lookup must ask about that UPN.

    It used to search `(sAMAccountName=<username>)`. In AD those are unrelated
    attributes: bind as `bob@home.example` when your sAMAccountName is `alice`,
    and the search happily returned whichever OTHER account owned
    sAMAccountName=bob — with its groups, its mail, and its admin verdict.
    """
    record = {}
    ldap_backend._connect_fn = _fake(["CN=HUB-Atlas,OU=Groups,DC=home,DC=example"],
                                     record=record)
    captured = {}
    real_conn = _FakeConn([_Entry(["CN=HUB-Atlas,OU=Groups,DC=home,DC=example"])])

    def connect(url, upn, password, timeout):
        captured["upn"] = upn
        return real_conn
    ldap_backend._connect_fn = connect

    ok, _ = ldap_backend.authenticate("bob", "some-password")
    assert ok
    assert captured["upn"] == "bob@home.example"
    flt = real_conn.searched["search_filter"]
    assert "userPrincipalName=bob@home.example" in flt
    # The sAMAccountName arm survives only for accounts with NO UPN at all,
    # where AD synthesises one and no other account can collide with it.
    assert "(!(userPrincipalName=*))" in flt


def test_an_ambiguous_directory_answer_is_refused(ldap_env):
    """Two matches means the directory cannot say who bound. Picking entry[0]
    is the guess this filter exists to stop making."""
    def connect(url, upn, password, timeout):
        return _FakeConn([_Entry(["CN=HUB-Atlas,DC=home,DC=example"]),
                          _Entry(["CN=atlas-admins,DC=home,DC=example"])])
    ldap_backend._connect_fn = connect
    ok, info = ldap_backend.authenticate("ops", "some-password")
    assert (ok, info) == (False, {})


def test_admin_group_must_live_under_the_base_dn(ldap_env):
    """`_cn(dn)` reduced every memberOf to its CN, so a group named atlas-admins
    ANYWHERE — a delegated OU an ordinary user can create objects in, or a
    trusted domain — granted Atlas admin. Membership is honoured from under
    ATLAS_LDAP_BASE_DN only."""
    ldap_backend._connect_fn = _fake(
        ["CN=atlas-admins,OU=Rogue,DC=elsewhere,DC=example"])
    ok, info = ldap_backend.authenticate("mallory", "some-password")
    assert ok                                   # they can still sign in
    assert not info["is_admin"]                 # but that group is out of scope
    assert info["groups"] == []                 # and grants no clearance either


def test_group_scope_any_restores_forest_wide(ldap_env, monkeypatch):
    """The escape hatch for a directory whose groups genuinely live elsewhere.
    Opt-in, because it cannot be made safe — only chosen."""
    monkeypatch.setenv("ATLAS_LDAP_GROUP_SCOPE", "any")
    ldap_backend._connect_fn = _fake(
        ["CN=atlas-admins,OU=Rogue,DC=elsewhere,DC=example"])
    ok, info = ldap_backend.authenticate("mallory", "some-password")
    assert ok and info["is_admin"]


def test_an_admin_group_may_be_named_by_full_dn(ldap_env, monkeypatch):
    """Config accepts a DN so one specific group can be named when several
    share a CN."""
    monkeypatch.setenv("ATLAS_LDAP_ADMIN_GROUPS",
                       "CN=atlas-admins,OU=Real,DC=home,DC=example")
    ldap_backend._connect_fn = _fake(["CN=atlas-admins,OU=Decoy,DC=home,DC=example"])
    ok, info = ldap_backend.authenticate("mallory", "some-password")
    assert ok and not info["is_admin"]           # right CN, wrong group
    ldap_backend._connect_fn = _fake(["CN=atlas-admins,OU=Real,DC=home,DC=example"])
    ok, info = ldap_backend.authenticate("ops", "some-password")
    assert ok and info["is_admin"]


def test_overrides_never_touch_the_environment(ldap_env, monkeypatch):
    """The SETTINGS "test these values" path. It used to stage the proposal
    into os.environ for the length of the bind, so every other thread in the
    worker authorised against un-approved settings for up to the LDAP timeout."""
    monkeypatch.setenv("ATLAS_LDAP_ADMIN_GROUPS", "Cartographers")
    seen = {}

    def connect(url, upn, password, timeout):
        seen["url"] = url
        # ...and while the bind is in flight, the process-wide config must
        # still be the one that was actually approved.
        seen["env_during"] = os.environ["ATLAS_LDAP_ADMIN_GROUPS"]
        return _FakeConn([_Entry(["CN=atlas-admins,OU=Groups,DC=home,DC=example"])])
    ldap_backend._connect_fn = connect

    ok, info = ldap_backend.authenticate(
        "ops", "some-password",
        overrides={"ATLAS_LDAP_URL": "ldaps://other.home.example:636",
                   "ATLAS_LDAP_BASE_DN": "DC=home,DC=example",
                   "ATLAS_LDAP_ADMIN_GROUPS": "atlas-admins"})

    assert ok and info["is_admin"]               # judged by the PROPOSED groups
    assert seen["url"] == "ldaps://other.home.example:636"
    assert seen["env_during"] == "Cartographers"
    assert os.environ["ATLAS_LDAP_ADMIN_GROUPS"] == "Cartographers"


def test_backends_order_and_gating(ldap_env, monkeypatch):
    assert ldap_backend.backends() == ["ldap"]
    monkeypatch.setenv("ATLAS_AUTH_BACKENDS", "local,ldap")
    assert ldap_backend.backends() == ["local", "ldap"]
    monkeypatch.delenv("ATLAS_LDAP_URL")           # ldap configured off
    assert ldap_backend.backends() == ["local"]
    monkeypatch.setenv("ATLAS_AUTH_BACKENDS", "local")
    assert ldap_backend.backends() == ["local"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
