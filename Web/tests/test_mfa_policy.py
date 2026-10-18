"""ATLAS_MFA_REQUIRED=admins (2026-09-03): every surveyor must hold a
second factor; everyone else may, and is not fenced. The admin flag is what a
stolen password would buy, so that is where the factor is not optional.

ONE implementation — `atlas_auth.mfa_policy_applies` — and the login route the
browser actually posts to must use it. Until v1.41.0 the v2 login carried its
own copy WITHOUT the `admins` branch, so the policy was described in settings
and never enforced on the live path; the last test here pins the route to the
shared function so that cannot recur."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "standalone"}

ADMIN = {"username": "ops", "source": "local", "is_admin": 1}
VIEWER = {"username": "viewer", "source": "ldap", "is_admin": 0}


@pytest.mark.parametrize("policy, admin_fenced, viewer_fenced", [
    ("", False, False),
    ("all", True, True),
    ("admins", True, False),
    ("admin", True, False),
    ("ldap", False, True),
    ("local", True, False),
])
def test_who_is_fenced(monkeypatch, policy, admin_fenced, viewer_fenced):
    import atlas_auth
    monkeypatch.setenv("ATLAS_MFA_REQUIRED", policy)
    assert atlas_auth.mfa_policy_applies(ADMIN) is admin_fenced, policy
    assert atlas_auth.mfa_policy_applies(VIEWER) is viewer_fenced, policy


def test_admins_policy_reads_the_flag_not_a_group(monkeypatch):
    """A directory account that carries the admin flag is fenced exactly like
    a local one — the policy is about what the account can do, not where it
    came from."""
    import atlas_auth
    monkeypatch.setenv("ATLAS_MFA_REQUIRED", "admins")
    assert atlas_auth.mfa_policy_applies({"source": "ldap", "is_admin": True})
    assert not atlas_auth.mfa_policy_applies({"source": "local", "is_admin": False})
    assert not atlas_auth.mfa_policy_applies({"source": "local"})


def test_the_login_route_uses_the_one_implementation():
    """The regression this file exists for: the route the browser posts to
    must fence exactly what the policy says — no private copy."""
    import atlas_auth
    from api.v2 import accounts_v2
    assert accounts_v2._mfa_policy_applies is atlas_auth.mfa_policy_applies
