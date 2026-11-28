"""Hub and hybrid modes need ATLAS_HUB_SECRET; a plain X-Remote-User is never believed."""

import pytest

import hub_auth.auth as hub

SECRET = "s3cret-for-tests"

BOOT_AND_REPORT = """
from app import app
print("BOOTED")
"""


@pytest.mark.parametrize("mode", ["hub", "hybrid", "HUB", " Hybrid "])
def test_signed_modes_refuse_to_start_without_a_secret(run_app, mode):
    r = run_app(BOOT_AND_REPORT, ATLAS_AUTH_MODE=mode)
    assert r.returncode != 0
    assert "BOOTED" not in r.stdout
    assert "HubSecretMissing" in r.stderr
    assert "ATLAS_HUB_SECRET" in r.stderr


def test_a_missing_secret_file_refuses_to_start(run_app, tmp_path):
    r = run_app(BOOT_AND_REPORT, ATLAS_AUTH_MODE="hub",
                ATLAS_HUB_SECRET_FILE=str(tmp_path / "nope"))
    assert r.returncode != 0
    assert "ATLAS_HUB_SECRET_FILE is missing or empty" in r.stderr


def test_an_empty_secret_file_refuses_to_start(run_app, tmp_path):
    empty = tmp_path / "empty"
    empty.write_text("\n")
    r = run_app(BOOT_AND_REPORT, ATLAS_AUTH_MODE="hybrid", ATLAS_HUB_SECRET_FILE=str(empty))
    assert r.returncode != 0
    assert "HubSecretMissing" in r.stderr


@pytest.mark.parametrize("mode", ["hub", "hybrid"])
def test_signed_modes_start_with_a_secret(run_app, mode):
    r = run_app(BOOT_AND_REPORT, ATLAS_AUTH_MODE=mode, ATLAS_HUB_SECRET=SECRET)
    assert r.returncode == 0, r.stderr
    assert "BOOTED" in r.stdout


def test_a_secret_file_is_enough(run_app, tmp_path):
    f = tmp_path / "hub.secret"
    f.write_text(SECRET + "\n")
    r = run_app(BOOT_AND_REPORT, ATLAS_AUTH_MODE="hub", ATLAS_HUB_SECRET_FILE=str(f))
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("mode", ["standalone", "accounts"])
def test_other_modes_do_not_need_a_secret(run_app, mode):
    r = run_app(BOOT_AND_REPORT, ATLAS_AUTH_MODE=mode)
    assert r.returncode == 0, r.stderr


def test_hub_mode_ignores_plain_headers_and_takes_a_signed_token(run_app):
    r = run_app(f"""
        import hub_auth.auth as hub
        from app import app
        c = app.test_client()
        forged = {{"X-Remote-User": "admin", "X-Remote-Groups": "atlas-admins"}}
        assert c.get("/api/v2/lab-data", headers=forged).status_code == 403
        assert c.get("/api/v2/lab-data").status_code == 403
        token = hub.mint_token("alice", groups=["viewers"])
        signed = {{hub.SIGNED_HEADER: token}}
        assert c.get("/api/v2/lab-data", headers=signed).status_code == 200
        bad = {{hub.SIGNED_HEADER: token[:-2] + "AA"}}
        assert c.get("/api/v2/lab-data", headers=bad).status_code == 403
        print("OK")
    """, ATLAS_AUTH_MODE="hub", ATLAS_HUB_SECRET=SECRET)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout


def test_hybrid_mode_ignores_plain_headers_and_takes_a_signed_token(run_app):
    r = run_app(f"""
        import hub_auth.auth as hub
        from app import app
        c = app.test_client()
        forged = {{"X-Remote-User": "admin", "X-Remote-Groups": "atlas-admins"}}
        assert c.get("/api/v2/lab-data", headers=forged).status_code == 401
        token = hub.mint_token("alice")
        assert c.get("/api/v2/lab-data", headers={{hub.SIGNED_HEADER: token}}).status_code == 200
        print("OK")
    """, ATLAS_AUTH_MODE="hybrid", ATLAS_HUB_SECRET=SECRET)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout


# The pieces, without booting the app.

def test_secret_problem_names_the_mode():
    assert hub.secret_problem("hub", secret=None, lost=False).startswith("ATLAS_AUTH_MODE=hub ")
    assert hub.secret_problem("hybrid", secret=b"x", lost=False) is None
    assert hub.secret_problem("accounts", secret=None, lost=False) is None
    assert hub.secret_problem("standalone", secret=None, lost=True) is None
    assert "SECRET_FILE" in hub.secret_problem("hub", secret=None, lost=True)


def test_remote_user_comes_only_from_a_verified_token(monkeypatch):
    from flask import Flask
    monkeypatch.setattr(hub, "AUTH_MODE", "hub")
    monkeypatch.setattr(hub, "AUTH_SECRET", SECRET.encode())
    app = Flask(__name__)
    forged = {"X-Remote-User": "admin", "X-Remote-Groups": "atlas-admins"}
    with app.test_request_context("/", headers=forged):
        assert hub.get_remote_user() == ""
        assert hub.get_remote_groups() == []
    token = hub.mint_token("alice", groups=["a", " b "])
    with app.test_request_context("/", headers={hub.SIGNED_HEADER: token, **forged}):
        assert hub.get_remote_user() == "alice"
        assert hub.get_remote_groups() == ["a", "b"]


def test_the_gate_fails_closed_if_reached_without_a_secret(monkeypatch):
    from flask import Flask
    monkeypatch.setattr(hub, "AUTH_MODE", "hub")
    monkeypatch.setattr(hub, "AUTH_SECRET", None)
    monkeypatch.setattr(hub, "SECRET_LOST", False)
    app = Flask(__name__)
    app.before_request(hub.require_hub_or_standalone())
    app.add_url_rule("/x", "x", lambda: "in")
    r = app.test_client().get("/x", headers={"X-Remote-User": "admin"})
    assert r.status_code == 500
    with app.test_request_context("/x", headers={"X-Remote-User": "admin"}):
        assert hub.get_remote_user() == ""
