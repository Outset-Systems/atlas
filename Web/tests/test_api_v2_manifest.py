"""The Atlas's app manifest and its Calendar day (the calendar build plan):
the rites become schedule blocks in the contract's cadence vocabulary, the
document validates, anonymous callers get the card + auth shape only, and
the day is the Atlas's own rites standalone or the Hub's fleet view when
one is configured and answers."""
import json
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

RITES = [
    {"name": "The Patch Survey", "cadence": "weekly", "when": "Sun 04:15", "host": "all guests", "note": "apt on every guest"},
    {"name": "SSH Cert Renewal", "cadence": "weekly", "when": "Sun 03:00 UTC", "host": "4 guests"},
    {"name": "Media Maintenance", "cadence": "daily", "when": "daily 07:15", "host": "MEDIA"},
    {"name": "Feed scoring", "cadence": "daily", "at": "13:00", "days": "Mon-Fri", "host": "APP HOST",
     "asks": "gpu-box", "model": "qwen3:14b · 32k", "hold": 30},
    {"name": "Ledger research", "cadence": "daily", "at": "13:45", "host": "INTERNAL HOST", "asks": "gpu-box", "model": "qwen3:14b", "hold": 20},
    {"name": "Hourly signal", "cadence": "continuous", "at": ":35", "between": "13:00–01:00", "host": "MONITOR"},
    {"name": "Old thing", "cadence": "parked", "when": "never", "host": "nowhere"},
    {"name": "Unclocked", "cadence": "daily", "when": "sometime", "host": "x"},
]


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    d = json.loads(data.read_text(encoding="utf-8"))
    d["rites"] = RITES
    data.write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.delenv("ATLAS_HUB_URL", raising=False)
    return {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1", "ATLAS_DATA": str(data),
            "ATLAS_AUTH_MODE": "standalone",
            "ATLAS_EVENTS": str(tmp_path / "events.json"), "ATLAS_BEATS": str(tmp_path / "heartbeats.json"),
            "ATLAS_BEATS_DIR": str(tmp_path / "beats"), "ATLAS_SIGNALS_SOURCES": "static",
            "ATLAS_SIGNALS_FILE": str(tmp_path / "signals.json")}


def test_manifest_validates_and_maps_every_rite(app_env):
    import outset_manifest as om
    h = fresh_app(**app_env)
    c = h.app.test_client()
    for path in ("/api/manifest", "/api/v2/manifest"):
        d = c.get(path).get_json()
        assert om.validate(d) == [], (path, om.validate(d))
        assert d["app"] == "atlas" and d["lanes"] == [] and d["usage"]["endpoint"] is None
        assert d["schedule"]["run_endpoint"] is None                 # the rites are other hosts' timers
        by = {b["key"]: b for b in d["schedule"]["blocks"]}
        assert len(by) == len(RITES)
        cad = {k: b["cadence"] for k, b in by.items()}
        assert cad["the-patch-survey"] == om.cadence("weekly", day="Sun", at="04:15", tz="UTC")
        assert cad["ssh-cert-renewal"]["day"] == "Sun" and cad["ssh-cert-renewal"]["at"] == "03:00"
        assert cad["media-maintenance"] == om.cadence("daily", at="07:15", tz="UTC")
        assert cad["feed-scoring"] == om.cadence("daily", at="13:00", tz="UTC", days="Mon-Fri")
        assert by["feed-scoring"]["hold_min"] == 30 and "asks gpu-box for qwen3:14b" in by["feed-scoring"]["what"]
        assert cad["hourly-signal"]["kind"] == "cron" and cad["hourly-signal"]["expr"] == "35 * * * *"
        assert cad["old-thing"]["kind"] == "parked" and by["old-thing"]["enabled"] is False
        assert cad["unclocked"]["kind"] == "on-request"
        assert d["auth"]["mode"] == "own-login"                       # standalone: no directory in front


def test_anonymous_gets_card_and_auth_only_in_session_modes(app_env, tmp_path):
    h = fresh_app(**{**app_env, "ATLAS_AUTH_MODE": "accounts", "ATLAS_ACCOUNTS_DB": str(tmp_path / "accounts.db")})
    c = h.app.test_client()
    r = c.get("/api/manifest")
    assert r.status_code == 200
    d = r.get_json()
    assert d["gated"] == ["schedule", "lanes", "usage"] and "schedule" not in d
    assert d["auth"]["mode"] == "own-login"                 # no directory configured


def test_accounts_mode_reports_the_directory_when_ldap_is_on(app_env, tmp_path):
    """v1.47.1: the manifest read ATLAS_LDAP_SERVER, a knob that never existed,
    so accounts mode said "own-login" even with AD sign-in working."""
    h = fresh_app(**{**app_env, "ATLAS_AUTH_MODE": "accounts",
                     "ATLAS_ACCOUNTS_DB": str(tmp_path / "accounts.db"),
                     "ATLAS_AUTH_BACKENDS": "local,ldap",
                     "ATLAS_LDAP_URL": "ldaps://dc.home.example:636",
                     "ATLAS_LDAP_BASE_DN": "DC=example,DC=lan"})
    d = h.app.test_client().get("/api/manifest").get_json()
    assert d["auth"]["mode"] == "ad-builtin"


def test_calendar_day_standalone_is_the_atlas_own_rites(app_env):
    h = fresh_app(**app_env)
    c = h.app.test_client()
    v = c.get("/api/v2/calendar?day=2026-09-07").get_json()          # a Monday
    assert v["fleet"] is False and v["hub"] is None
    blocks = {(p["app"], p["block"]): p for p in v["planned"]}
    assert ("atlas", "feed-scoring") in blocks and blocks[("atlas", "feed-scoring")]["start"] == "2026-09-07T13:00+00:00"
    assert ("atlas", "the-patch-survey") not in blocks                # Sunday only
    assert v["overlaps"] == []                                        # no lanes → no model blocks
    assert {l["block"] for l in v["listed"]} == {"hourly-signal", "old-thing", "unclocked"}
    assert c.get("/api/v2/calendar?day=junk").status_code == 400


def test_calendar_day_uses_the_hub_when_configured(app_env, monkeypatch):
    import requests
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers)

        class R:
            def raise_for_status(self): pass
            def json(self): return {"day": params["day"], "zones": ["UTC"], "planned": [{"app": "feed"}],
                                    "overlaps": [], "listed": [], "actual": []}
        return R()
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setenv("ATLAS_HUB_SECRET", "fleet-secret")
    h = fresh_app(**{**app_env, "ATLAS_HUB_URL": "http://hub:5000/"})
    import hub_auth.auth as ka
    monkeypatch.setattr(ka, "AUTH_SECRET", b"fleet-secret")
    v = h.app.test_client().get("/api/v2/calendar?day=2026-09-07").get_json()
    assert v["fleet"] is True and v["hub"] == "http://hub:5000" and v["planned"] == [{"app": "feed"}]
    assert seen["url"] == "http://hub:5000/api/calendar" and seen["params"]["actual"] == "0"
    assert ka.verify_token(seen["headers"]["X-Hub-Auth"])["u"] == "svc:atlas"
    # the Hub goes away: fall back to our own rites, honestly labelled
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    v = h.app.test_client().get("/api/v2/calendar?day=2026-09-07").get_json()
    assert v["fleet"] is False and v["hub_error"] and any(p["app"] == "atlas" for p in v["planned"])
