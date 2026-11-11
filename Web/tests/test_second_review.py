"""The 2026-11-01 security review: each finding, kept shut.

Most of these are one kind of bug: `redact_for_groups` was right, and a route
read the dataset some other way. The fixture hides one place and names it in
every way a place can be named, then each test asks a viewer cleared for nothing
for the thing that used to give it away.
"""

import json

import pytest

from appfixture import fresh_app

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts"}

PW = "correct-horse-battery"
WRITE = {"X-Atlas-Write": "1"}


def _dataset(tmp_path):
    (tmp_path / "lab-data.json").write_text(json.dumps({
        "meta": {"title": "T"}, "zones": [{"id": "z", "name": "Z"}],
        "nodes": [
            {"id": "pub", "name": "PUB", "kind": "physical", "zone": "z", "x": 1, "y": 1,
             "ip": "10.0.0.1", "links": [{"label": "p", "url": "http://pub.internal:80"}]},
            {"id": "secret-box", "name": "SECRETBOX", "kind": "physical", "zone": "z",
             "x": 2, "y": 2, "ip": "10.0.0.9", "require_group": "ops",
             "links": [{"label": "s", "url": "http://secret.internal:8443", "kuma": "secret-mon"}]},
        ],
        "routes": [], "rack": [], "vms": [], "signals": {"kuma": {}},
        "rites": [
            {"name": "pointed", "key": "a", "cadence": "daily", "when": "x", "host": "PUB",
             "asks": "secret-box"},
            {"name": "worded", "key": "b", "cadence": "daily", "when": "x", "host": "on SECRETBOX"},
            {"name": "open", "key": "c", "cadence": "daily", "when": "x", "host": "PUB"},
        ],
    }), encoding="utf-8")
    (tmp_path / "events.json").write_text(json.dumps({"seq": 2, "state": {}, "events": [
        {"id": 1, "at": "2026-11-01T00:00:00Z", "kind": "node", "target": "pub", "name": "PUB",
         "from": "healthy", "to": "down", "gravity": "consequence", "ack": None,
         "cause": "secret-box"},
        {"id": 2, "at": "2026-11-01T00:00:01Z", "kind": "service", "target": "secret-mon",
         "name": "secret-mon", "from": "healthy", "to": "down", "gravity": "grave", "ack": None},
    ]}), encoding="utf-8")
    (tmp_path / "maintenance.json").write_text(json.dumps({"nodes": [], "windows": [
        {"id": "w", "nodes": ["secret-box"], "starts": "2030-01-01T00:00:00Z",
         "ends": "2030-01-02T00:00:00Z", "reason": "patch SECRETBOX firmware"}]}), encoding="utf-8")
    return str(tmp_path / "lab-data.json")


def _common(tmp_path):
    return dict(ATLAS_DATA=_dataset(tmp_path), ATLAS_DATA_BACKEND="file",
                ATLAS_EVENTS=str(tmp_path / "events.json"),
                ATLAS_MAINTENANCE=str(tmp_path / "maintenance.json"),
                ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
                ATLAS_INSECURE_COOKIES="1", ATLAS_SIGNALS_SOURCES="")


@pytest.fixture
def realm(tmp_path):
    handle = fresh_app(ATLAS_AUTH_MODE="accounts", ATLAS_SECRET_KEY="test-signing-key",
                       **_common(tmp_path))
    import accounts
    accounts.create_local_user("viewer", PW)
    accounts.create_local_user("root1", PW, is_admin=True)
    return handle.app


@pytest.fixture
def viewer(realm):
    c = realm.test_client()
    assert c.post("/api/v2/auth/login", json={"username": "viewer", "password": PW},
                  headers=WRITE).status_code == 200
    return c


# ── the redirect after sign-in ───────────────────────────────────────────────
@pytest.mark.parametrize("raw", ["/\t/evil.example/", "/\n/evil.example/", "/\r/evil.example/",
                                 "/\\evil.example", "//evil.example", "/a\\b", "https://evil.example",
                                 "/x\x7f"])
def test_next_goes_nowhere_a_browser_would_read_as_elsewhere(realm, raw):
    import auth_routes
    assert auth_routes._safe_next(raw) == "/"


@pytest.mark.parametrize("raw", ["/", "/atlas/", "/a/b?c=d#e", "/map?x=1%2F2"])
def test_next_keeps_a_plain_path(realm, raw):
    import auth_routes
    assert auth_routes._safe_next(raw) == raw


# ── the sign-in throttle and its timing ──────────────────────────────────────
def test_signing_in_again_does_not_wipe_wrong_codes(realm):
    import accounts
    import pyotp
    accounts.create_local_user("mfau", PW)
    secret, _, _ = accounts.start_mfa_enrollment("mfau")
    accounts.confirm_mfa("mfau", pyotp.TOTP(secret).now())
    c = realm.test_client()
    hits = []
    for round_ in range(4):
        env = {"REMOTE_ADDR": f"203.0.113.{round_ + 1}"}
        r = c.post("/api/v2/auth/login", json={"username": "mfau", "password": PW},
                   headers=WRITE, environ_base=env)
        hits.append(r.status_code)
        for _ in range(4):
            hits.append(c.post("/api/v2/auth/login/mfa", json={"code": "000000"},
                               headers=WRITE, environ_base=env).status_code)
    assert 429 in hits, "the per-account cap has to bite across fresh password steps"


def test_an_unknown_name_still_pays_for_a_hash(realm, monkeypatch):
    import accounts
    seen = []
    real = accounts.check_password_hash
    monkeypatch.setattr(accounts, "check_password_hash",
                        lambda h, p: seen.append(h) or real(h, p))
    assert accounts.verify_password("no-such-person", "anything-at-all") is None
    assert len(seen) == 1


# ── hidden places, everywhere they were named ────────────────────────────────
def test_rites_keep_to_what_the_viewer_can_see(viewer):
    assert [r["name"] for r in viewer.get("/api/v2/rites").get_json()["rites"]] == ["open"]


def test_the_calendar_and_manifest_do_not_name_a_hidden_place(viewer):
    for path in ("/api/v2/calendar", "/api/manifest"):
        r = viewer.get(path)
        assert r.status_code == 200, path
        body = r.get_data(as_text=True)
        assert "SECRETBOX" not in body and "secret-box" not in body, path


def test_an_admin_still_sees_every_rite(realm):
    c = realm.test_client()
    c.post("/api/v2/auth/login", json={"username": "root1", "password": PW}, headers=WRITE)
    assert len(c.get("/api/v2/rites").get_json()["rites"]) == 3


def test_the_signals_feed_keeps_no_repair_summary_of_hidden_work(viewer):
    assert "SECRETBOX" not in viewer.get("/api/v2/signals").get_data(as_text=True)


def test_an_event_does_not_name_a_hidden_cause(viewer):
    rows = viewer.get("/api/v2/events").get_json()["events"]
    assert [e["target"] for e in rows] == ["pub"]
    assert "cause" not in rows[0]


def test_the_csp_lists_only_what_this_viewer_can_see(viewer):
    csp = viewer.get("/api/v2/lab-data").headers["Content-Security-Policy"]
    assert "pub.internal" in csp and "secret.internal" not in csp


def test_a_signed_out_caller_gets_no_origins_at_all(realm):
    csp = realm.test_client().get("/auth/login").headers["Content-Security-Policy"]
    assert "pub.internal" not in csp and "secret.internal" not in csp


def test_a_chart_legend_drops_a_hidden_place(realm, viewer):
    from api.v2 import charts
    answer = {"key": "k", "kind": "line", "series": [
        {"name": "SECRETBOX", "points": [[1, 5.0]]}, {"name": "10.0.0.9:9100", "points": []},
        {"name": "10.0.0.91:9100", "points": []}, {"name": "PUB", "points": []}]}
    table = {"key": "k", "kind": "table", "rows": [
        {"name": "anon", "labels": {"instance": "10.0.0.9:9100"}, "value": 1}]}
    with realm.test_request_context("/"):
        from flask import session
        from redaction import viewer_groups
        import redaction
        redaction.viewer_groups, keep = (lambda: []), viewer_groups
        charts.viewer_groups, keep_c = (lambda: []), charts.viewer_groups
        try:
            names = [s["name"] for s in charts._for_viewer(answer)["series"]]
            assert names == ["10.0.0.91:9100", "PUB"]
            assert charts._for_viewer(table)["rows"] == []
        finally:
            redaction.viewer_groups = keep
            charts.viewer_groups = keep_c


def test_mcp_events_take_the_monitor_gate(realm, monkeypatch):
    import api_tokens
    monkeypatch.setenv("ATLAS_AGENT_API", "1")      # agent access starts off
    _, raw = api_tokens.issue("t", 30, "x")
    r = realm.test_client().post(
        "/api/v2/mcp", headers={"Authorization": "Bearer " + raw},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "atlas_events", "arguments": {}}})
    text = r.get_json()["result"]["content"][0]["text"]
    assert "secret-mon" not in text and "secret-box" not in text


# ── hub mode ─────────────────────────────────────────────────────────────────
def test_hub_mode_keeps_the_schedule_from_an_unproved_caller(tmp_path):
    app = fresh_app(ATLAS_AUTH_MODE="hub", ATLAS_HUB_SECRET="s" * 32, **_common(tmp_path)).app
    c = app.test_client()
    r = c.get("/api/manifest")
    assert r.status_code == 200 and r.get_json().get("gated")
    assert "pointed" not in r.get_data(as_text=True)
    assert "pub.internal" not in c.get("/api/status").headers["Content-Security-Policy"]


def test_hub_mode_with_a_lost_secret_file_trusts_no_header(tmp_path):
    app = fresh_app(ATLAS_AUTH_MODE="hub", ATLAS_HUB_SECRET_FILE=str(tmp_path / "gone"),
                    **_common(tmp_path)).app
    forged = {"X-Remote-User": "mallory", "X-Remote-Groups": "atlas-admins"}
    c = app.test_client()
    for path in ("/api/v2/lab-data", "/api/v2/admin/context", "/api/v2/rites"):
        r = c.get(path, headers=forged)
        assert r.status_code >= 400, path
        assert "SECRETBOX" not in r.get_data(as_text=True), path
    assert c.post("/api/v2/positions", json={}, headers={**forged, **WRITE}).status_code >= 400
