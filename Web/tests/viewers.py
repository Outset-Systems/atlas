"""A small realm for the suites that ask "who sees what" (2026-11-13: sets,
certificates, the places table).

An accounts-mode Atlas on a file dataset, with an admin (`link`), a viewer
cleared for nothing (`alice`), agent access on so tokens can be issued, and a
dataset that validates clean, so a Desk write is judged on its own change and
not refused for an old problem elsewhere in the file.
"""

import copy
import json

from appfixture import fresh_app

PW = "correct-horse-battery-staple-9"
#: The same-origin write proof the Desk sends.
W = {"X-Atlas-Write": "1", "Origin": "http://localhost"}
GROUP = "HUB-decoy"

_ZONE = {"id": "core", "name": "Core", "vlan": 10, "subnet": "192.0.2.0/24", "hue": "#336699",
         "lore": "the middle", "label_x": 50, "label_y": 50}


def place(pid, name, **extra):
    """A place that validates: every required field filled in."""
    return {"id": pid, "name": name, "kind": "physical", "zone": "core",
            "x": 10, "y": 10, "role": "a box", **extra}


#: Two visible places and one behind a group. Each suite adds what it is about.
BASE = {
    "meta": {"title": "Test Realm"},
    "zones": [_ZONE],
    "nodes": [
        place("alpha", "Alpha", ip="192.0.2.5"),
        place("beta", "Beta", ip="192.0.2.6"),
        place("secret-place", "Secret", ip="192.0.2.99", require_group=GROUP),
    ],
    "routes": [],
}


def dataset(**sections):
    """BASE with sections replaced or added."""
    data = copy.deepcopy(BASE)
    data.update(copy.deepcopy(sections))
    return data


def build(tmp_path, monkeypatch, data, windows=None):
    """The realm's app handle. `windows` are repair windows to start with."""
    path = tmp_path / "lab-data.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    maint = tmp_path / "maintenance.json"
    maint.write_text(json.dumps({"nodes": [], "windows": windows or []}), encoding="utf-8")
    for name, value in {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file",
                        "ATLAS_DATA": str(path), "ATLAS_ACCOUNTS_DB": str(tmp_path / "a.db"),
                        "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
                        "ATLAS_MAINTENANCE": str(maint),
                        "ATLAS_EVENTS": str(tmp_path / "events.json"),
                        "ATLAS_REVISIONS": str(tmp_path / "rev"),
                        "ATLAS_SECRET_KEY": "test-signing-key", "ATLAS_INSECURE_COOKIES": "1",
                        "ATLAS_SIGNALS_SOURCES": "", "ATLAS_AUTH_BACKENDS": "local",
                        "ATLAS_MFA_REQUIRED": "", "ATLAS_ALLOW_INSECURE": "1",
                        "ATLAS_READONLY": "0", "ATLAS_AGENT_API": "1"}.items():
        monkeypatch.setenv(name, value)
    handle = fresh_app()
    import accounts
    accounts.create_local_user("ops", PW, display_name="Ops", is_admin=True)
    accounts.create_local_user("alice", PW, display_name="Alice", is_admin=False)
    return handle


def signed_in(handle, username):
    c = handle.app.test_client()
    r = c.post("/api/v2/auth/login", json={"username": username, "password": PW},
               headers={"X-Atlas-Write": "1"})
    assert r.get_json().get("ok") is True, f"{username} could not sign in"
    return c


def issue(handle, profile="full"):
    """A token's Authorization header, issued by the admin."""
    admin = signed_in(handle, "ops")
    r = admin.post("/api/v2/admin/tokens", headers=W,
                   json={"name": f"{profile} reader", "days": 30, "profile": profile})
    assert r.status_code == 200, r.get_json()
    return {"Authorization": f"Bearer {r.get_json()['secret']}"}
