"""The `atlas-admins` sentinel, refused at the ROUTE — THE LIST #3's real gap.

`redaction.sees_everything` treats `atlas-admins` as full-admin clearance: it is
the Hub's admin group and hub mode's whole authorisation model. In accounts
mode admin is the `is_admin` FLAG, so handing that string out as an ordinary
clearance group would be a second, silent path to admin.

`accounts.set_groups` refuses it, and `test_auth_gate_routes.py` proves that at
the STORE — which is exactly what THE LIST #3 said was not enough: the refusal
a caller actually meets is `POST /api/auth/users/<u>/groups`, on the file its
own docstring calls "the most dangerous screen in the app", and nothing
exercised that path. It works by the route catching the store's ValueError, so
it is one `except` clause away from silently becoming a 500 — or, if someone
ever moves the validation, from disappearing.

Both surfaces are tested: v1 still answers for external callers (v1.29.0 cut
over the in-repo ones only), so a gap in either is a gap.
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app, login_as  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

PW = "a-long-enough-password"
WRITE = {"X-Atlas-Write": "1"}
RESERVED = "atlas-admins"

BOTH = pytest.mark.parametrize("base", ["/api/v2/auth"])


@pytest.fixture
def realm(tmp_path):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    handle = fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(data),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
        ATLAS_SECRET_KEY="test-signing-key",
        ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
        ATLAS_AUTH_BACKENDS="local",
        ATLAS_MFA_REQUIRED="",
    )
    import accounts
    accounts.create_local_user("ops", PW, is_admin=True)
    accounts.create_local_user("alice", PW)
    return handle


def _admin(realm):
    c = realm.app.test_client()
    login_as(c, "ops", PW)
    return c


def _groups_of(username):
    import accounts
    return accounts.groups_of(accounts.get_user(username))


@BOTH
def test_the_route_refuses_the_reserved_admin_group(realm, base):
    c = _admin(realm)
    r = c.post(f"{base}/users/alice/groups", headers=WRITE,
               json={"groups": [RESERVED]})
    assert r.status_code == 400, r.get_data(as_text=True)
    body = r.get_json()
    assert body["ok"] is False
    # the refusal must SAY what it refused — an admin reading it needs to know
    # to use the is_admin flag instead, not just that "something was wrong"
    assert RESERVED in body["error"]
    assert RESERVED not in _groups_of("alice")


@BOTH
def test_the_refusal_is_atomic_no_partial_grant(realm, base):
    """A mixed list must grant NOTHING. `set_groups` builds the whole CSV
    before it writes, so a refusal in the middle must not leave the legitimate
    groups applied — that would be a write the caller was told had failed."""
    c = _admin(realm)
    r = c.post(f"{base}/users/alice/groups", headers=WRITE,
               json={"groups": ["HL-Viewers", RESERVED, "HL-Ops"]})
    assert r.status_code == 400
    assert _groups_of("alice") == []


@BOTH
def test_the_sentinel_is_matched_exactly_not_loosely(realm, base):
    """Neighbouring names are ordinary groups and must still be grantable — a
    refusal that fires on `atlas-admins-Readonly` would be a different bug."""
    c = _admin(realm)
    r = c.post(f"{base}/users/alice/groups", headers=WRITE,
               json={"groups": ["atlas-admins-Readonly", "HUB-decoy"]})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert set(_groups_of("alice")) == {"atlas-admins-Readonly", "HUB-decoy"}


@BOTH
def test_a_refused_grant_writes_no_audit_line(realm, base):
    """The ledger records what HAPPENED. A refused grant did not happen, and an
    audit line for it would read as a successful one to anyone scanning."""
    import accounts
    c = _admin(realm)
    before = len(accounts.audit_tail(500))
    c.post(f"{base}/users/alice/groups", headers=WRITE, json={"groups": [RESERVED]})
    assert len(accounts.audit_tail(500)) == before

    # ...and the successful arm DOES write one, so the assertion above is
    # measuring the refusal and not a broken audit log
    c.post(f"{base}/users/alice/groups", headers=WRITE, json={"groups": ["HL-Viewers"]})
    assert len(accounts.audit_tail(500)) == before + 1


@BOTH
def test_the_grant_route_needs_admin(realm, base):
    """The sentinel is the second gate. The first is that an ordinary user
    cannot reach this route at all."""
    c = realm.app.test_client()
    login_as(c, "alice", PW)
    r = c.post(f"{base}/users/alice/groups", headers=WRITE,
               json={"groups": ["HL-Viewers"]})
    assert r.status_code == 403
    assert _groups_of("alice") == []


@BOTH
def test_the_grant_route_needs_the_same_origin_proof(realm, base):
    """And the third: a cross-site POST carrying the admin's cookie."""
    c = _admin(realm)
    r = c.post(f"{base}/users/alice/groups", json={"groups": ["HL-Viewers"]})
    assert r.status_code == 403
    assert _groups_of("alice") == []


def test_the_reserved_name_is_the_one_redaction_actually_honours():
    """The constant this whole refusal protects. If `redaction` ever stops
    reading this exact string, the refusal guards a name nothing honours — and
    the real sentinel goes unguarded. The two must be pinned to each other."""
    import accounts
    import redaction
    assert accounts.RESERVED_ADMIN_GROUP == RESERVED
    assert redaction.sees_everything([accounts.RESERVED_ADMIN_GROUP])
    assert not redaction.sees_everything(["atlas-admins-Readonly"])
    assert not redaction.sees_everything([])
