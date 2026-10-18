"""The machine beat — `POST /api/v2/rites/<key>/beat`.

Every arm of the deliberately narrow gate: read-only 403 first, unconfigured
503, bad token 403, good token 200 — and in accounts mode the app gate's 401
before the token is ever read (pinned).
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

TOKEN = "a-test-beat-token"


def _app(tmp_path, **extra):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    return fresh_app(
        ATLAS_DATA=str(data),
        ATLAS_BEATS=str(tmp_path / "heartbeats.json"),
        ATLAS_BEATS_DIR=str(tmp_path / "beats"),
        **{**{"ATLAS_READONLY": "0"}, **extra},
    )


def test_beat_with_either_token_spelling(tmp_path):
    client = _app(tmp_path, ATLAS_BEAT_TOKEN=TOKEN).app.test_client()
    r = client.post("/api/v2/rites/backups/beat",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    json={"status": "ok", "note": "turned"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and body["key"] == "backups" and body["status"] == "ok"
    assert body["at"].endswith("Z")
    r = client.post("/api/v2/rites/sweep/beat", headers={"X-Atlas-Beat": TOKEN}, json={})
    assert r.status_code == 200 and r.get_json()["key"] == "sweep"


def test_bad_or_missing_token_is_403(tmp_path):
    client = _app(tmp_path, ATLAS_BEAT_TOKEN=TOKEN).app.test_client()
    r = client.post("/api/v2/rites/x/beat", headers={"Authorization": "Bearer wrong"}, json={})
    assert r.status_code == 403
    assert r.get_json() == {"error": "bad or missing beat token"}
    assert client.post("/api/v2/rites/x/beat", json={}).status_code == 403


def test_unconfigured_is_503_not_open(tmp_path):
    client = _app(tmp_path).app.test_client()          # no ATLAS_BEAT_TOKEN
    r = client.post("/api/v2/rites/x/beat", headers={"Authorization": f"Bearer {TOKEN}"}, json={})
    assert r.status_code == 503
    assert r.get_json()["error"] == "the beat endpoint is not configured"


def test_read_only_refuses_first(tmp_path):
    client = _app(tmp_path, ATLAS_BEAT_TOKEN=TOKEN, ATLAS_READONLY="1").app.test_client()
    r = client.post("/api/v2/rites/x/beat", headers={"Authorization": f"Bearer {TOKEN}"}, json={})
    assert r.status_code == 403
    assert r.get_json()["error"] == "this Atlas is read-only"


def test_accounts_mode_gate_swallows_the_beat(tmp_path):
    """Plan A6, pinned: the beat path is NOT gate-exempt, so a sessionless
    cron caller in accounts mode gets the gate's 401 before the token is ever
    read. The fleet reports through the beats drop-dir instead."""
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    client = fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(data),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
        ATLAS_SECRET_KEY="test-signing-key",
        ATLAS_INSECURE_COOKIES="1",
        ATLAS_AUTH_BACKENDS="local",
        ATLAS_MFA_REQUIRED="",
        ATLAS_BEAT_TOKEN=TOKEN,
        ATLAS_BEATS=str(tmp_path / "heartbeats.json"),
        ATLAS_BEATS_DIR=str(tmp_path / "beats"),
    ).app.test_client()
    r = client.post("/api/v2/rites/x/beat",
                    headers={"Authorization": f"Bearer {TOKEN}"}, json={})
    assert r.status_code == 401
