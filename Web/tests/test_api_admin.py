"""The editing API — and, mostly, the things that must refuse it.

`/api/admin/*` is the first surface in the Atlas that can rewrite the map, so
the interesting assertions here are negative: no write header, no write;
cross-site, no write; read-only instance, no write; not an admin, nothing at
all. The CSRF pair matters specifically because behind the Hub a cross-origin
page can borrow the session cookie and the Hub will sign the request for it.
"""

import json
import os
import shutil
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

BUNDLED = os.path.join(WEB, "default-lab-data.json")

# Declared for conftest so this module owns its environment (see conftest.py).
ATLAS_TEST_ENV = {
    "ATLAS_DATA_BACKEND": "file",
    "ATLAS_ALLOW_INSECURE": "1",
    "ATLAS_AUTH_MODE": "standalone",
}
os.environ.update(ATLAS_TEST_ENV)

WRITE = {"X-Atlas-Write": "1"}


@pytest.fixture
def client(tmp_path):
    """An app writing to a throwaway dataset, never the real one."""
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    atlas_app = fresh_app(
        ATLAS_DATA=str(data),
        ATLAS_POSITIONS=str(tmp_path / "positions.json"),
        ATLAS_RACK=str(tmp_path / "rack.json"),
        ATLAS_REVISIONS=str(tmp_path / "revisions"),
        ATLAS_OBSERVED=str(tmp_path / "observed.json"),
        ATLAS_READONLY="0",
    )
    return atlas_app.app.test_client()


@pytest.fixture
def readonly_client(tmp_path):
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    atlas_app = fresh_app(
        ATLAS_DATA=str(data),
        ATLAS_REVISIONS=str(tmp_path / "revisions"),
        ATLAS_READONLY="1",
    )
    return atlas_app.app.test_client()


def an_op(nid="testhold"):
    return {"op": "insert", "section": "nodes", "body": {
        "id": nid, "name": nid.upper(), "kind": "physical", "zone": "sky",
        "x": 10.0, "y": 10.0, "role": "a test", "lore": "a test"}}


# ── reads ───────────────────────────────────────────────────────────────────

def test_context_describes_the_deployment(client):
    body = client.get("/api/v2/admin/context").get_json()
    assert body["writable"] is True and body["backend"] == "file"
    assert body["seeded"] is True and body["stamp"]
    assert "nodes" in body["schema"]["sections"]


def test_dataset_is_the_raw_document(client):
    body = client.get("/api/v2/admin/dataset").get_json()
    assert body["data"]["nodes"] and body["stamp"]
    assert "overridden" in body


# ── the CSRF pair ───────────────────────────────────────────────────────────

def test_a_write_without_the_header_is_refused(client):
    r = client.post("/api/v2/admin/ops", json={"ops": [an_op()]})
    assert r.status_code == 403
    assert "write header" in r.get_json()["error"]


def test_a_cross_site_write_is_refused(client):
    r = client.post("/api/v2/admin/ops", headers={**WRITE, "Sec-Fetch-Site": "cross-site"},
                    json={"ops": [an_op()]})
    assert r.status_code == 403
    assert "cross-site" in r.get_json()["error"]


@pytest.mark.parametrize("site", ["same-origin", "same-site", "none"])
def test_same_origin_fetch_metadata_is_allowed(client, site):
    r = client.post("/api/v2/admin/ops", headers={**WRITE, "Sec-Fetch-Site": site},
                    json={"ops": [an_op(f"n-{site}")]})
    assert r.status_code == 200


def test_the_layout_writes_are_guarded_too(client):
    """positions/rack predate the editor and had no CSRF defence at all."""
    for path in ("/api/v2/positions", "/api/v2/rack"):
        assert client.post(path, json={}).status_code == 403
        assert client.post(path, headers=WRITE, json={}).status_code == 200


# ── read-only posture ───────────────────────────────────────────────────────

def test_a_read_only_instance_refuses_every_write(readonly_client):
    for path, payload in (("/api/v2/admin/ops", {"ops": [an_op()]}),
                          ("/api/v2/admin/import/csv", {"csv": "name,ip\nx,10.9.9.9\n"}),
                          ("/api/v2/admin/discovery/as-nodes", {"keys": ["x"]}),
                          ("/api/v2/positions", {}),
                          ("/api/v2/rack", {})):
        r = readonly_client.post(path, headers=WRITE, json=payload)
        assert r.status_code == 403, path
        assert r.get_json()["error"] in ("this Atlas is read-only", "admins only"), path


def test_a_look_only_standalone_atlas_keeps_its_admin_reads_to_itself(readonly_client):
    """Nobody signs in here, so "admin" would mean every visitor."""
    for path in ("context", "dataset", "revisions", "integrations", "tokens", "auth"):
        r = readonly_client.get(f"/api/v2/admin/{path}")
        assert r.status_code == 403, path
        assert r.get_json() == {"error": "admins only"}
    assert readonly_client.get("/api/v2/trust").status_code == 403
    # these only repeat the map, which this mode shows everyone, and the scene needs them
    for path in ("/api/v2/lab-data", "/api/v2/tripwires", "/api/v2/tripwires/setup"):
        assert readonly_client.get(path).status_code == 200, path


# ── writing ─────────────────────────────────────────────────────────────────

def test_a_good_write_lands_and_is_journalled(client):
    stamp = client.get("/api/v2/admin/context").get_json()["stamp"]
    r = client.post("/api/v2/admin/ops", headers=WRITE,
                    json={"ops": [an_op()], "expect": stamp, "note": "by hand"})
    assert r.status_code == 200
    assert r.get_json()["changed"] == ["added node testhold"]

    revisions = client.get("/api/v2/admin/revisions").get_json()["revisions"]
    assert revisions[0]["note"] == "by hand"

    r = client.post(f"/api/v2/admin/revisions/{revisions[0]['id']}/revert", headers=WRITE)
    assert r.status_code == 200
    data = client.get("/api/v2/admin/dataset").get_json()["data"]
    assert not any(n["id"] == "testhold" for n in data["nodes"])


def test_a_bad_write_is_422_with_per_field_reasons(client):
    bad = an_op()
    bad["body"]["zone"] = "nowhere"
    r = client.post("/api/v2/admin/ops", headers=WRITE, json={"ops": [bad]})
    assert r.status_code == 422
    assert any("unknown zone" in p for p in r.get_json()["problems"])


def test_a_stale_stamp_is_409(client):
    stamp = client.get("/api/v2/admin/context").get_json()["stamp"]
    client.post("/api/v2/admin/ops", headers=WRITE, json={"ops": [an_op("first")]})
    r = client.post("/api/v2/admin/ops", headers=WRITE,
                    json={"ops": [an_op("second")], "expect": stamp})
    assert r.status_code == 409


def test_dependents_are_queryable(client):
    body = client.get("/api/v2/admin/dependents?section=nodes&id=gateway").get_json()
    assert body["dependents"]
    assert client.get("/api/v2/admin/dependents?section=nope&id=x").status_code == 400


def test_editing_a_position_clears_the_saved_layout_override(client):
    """Otherwise the old override silently wins and the edit looks broken."""
    client.post("/api/v2/positions", headers=WRITE, json={"app-host": {"x": 1, "y": 2}})
    assert "app-host" in client.get("/api/v2/admin/dataset").get_json()["overridden"]["nodes"]

    r = client.post("/api/v2/admin/ops", headers=WRITE, json={
        "ops": [{"op": "upsert", "section": "nodes", "id": "app-host",
                 "body": {"x": 40.0, "y": 60.0}}]})
    assert r.get_json()["overlays_cleared"] == 1
    assert client.get("/api/v2/admin/dataset").get_json()["overridden"].get("nodes", []) == []


# ── discovery ───────────────────────────────────────────────────────────────

NMAP = """<?xml version="1.0"?><nmaprun>
  <host><status state="up"/><address addr="10.9.9.9" addrtype="ipv4"/>
    <hostnames><hostname name="stranger.example"/></hostnames></host>
  <host><status state="down"/><address addr="10.9.9.10" addrtype="ipv4"/></host>
</nmaprun>"""


def test_a_survey_files_hosts_and_flags_the_uncharted(client):
    r = client.post("/api/v2/admin/discovery/scan", headers=WRITE, json={"nmap_xml": NMAP})
    assert r.get_json() == {"ok": True, "seen": 1, "new": 1}, "a down host is not evidence"

    body = client.get("/api/v2/admin/discovery").get_json()
    assert body["undocumented"] == 1
    assert body["observed"][0]["ip"] == "10.9.9.9"

    drafts = client.post("/api/v2/admin/discovery/as-nodes", headers=WRITE,
                         json={"keys": ["10.9.9.9"]}).get_json()["nodes"]
    assert drafts[0]["kind"] == "unknown", "nothing about this stranger suggests a kind"
    assert drafts[0]["id"] == "stranger"


def test_a_silenced_device_stops_counting_as_drift(client):
    client.post("/api/v2/admin/discovery/scan", headers=WRITE, json={"nmap_xml": NMAP})
    client.post("/api/v2/admin/discovery/decide", headers=WRITE,
                json={"keys": ["10.9.9.9"], "action": "ignore"})
    assert client.get("/api/v2/admin/discovery").get_json()["undocumented"] == 0


def test_malformed_scans_are_refused(client):
    assert client.post("/api/v2/admin/discovery/scan", headers=WRITE,
                       json={"nmap_xml": "not xml"}).status_code == 422
    doctype = '<!DOCTYPE nmaprun><nmaprun></nmaprun>'
    assert client.post("/api/v2/admin/discovery/scan", headers=WRITE,
                       json={"nmap_xml": doctype}).status_code == 422
    assert client.post("/api/v2/admin/discovery/scan", headers=WRITE,
                       json={}).status_code == 400


# ── bulk import ─────────────────────────────────────────────────────────────

def test_a_device_list_becomes_drafts_never_a_write(client):
    csv = "name,ip,kind,zone,role,url\nFile Server,10.8.8.8,physical,sky,shares,http://x/\n"
    before = len(client.get("/api/v2/admin/dataset").get_json()["data"]["nodes"])
    body = client.post("/api/v2/admin/import/csv", headers=WRITE, json={"csv": csv}).get_json()
    assert body["count"] == 1 and body["nodes"][0]["name"] == "FILE SERVER"
    assert body["nodes"][0]["links"][0]["url"] == "http://x/"
    after = len(client.get("/api/v2/admin/dataset").get_json()["data"]["nodes"])
    assert before == after, "drafting must not write anything"


def test_drafted_places_are_spread_under_their_realm_not_piled(client):
    """Twenty scanned or listed devices used to all land at (50, 50). Drafts
    now grid under their realm's label, after the places already there."""
    rows = "".join(f"Box {i},10.8.8.{i + 10},physical,sky,,\n" for i in range(7))
    body = client.post("/api/v2/admin/import/csv", headers=WRITE,
                       json={"csv": "name,ip,kind,zone,role,url\n" + rows}).get_json()
    spots = [(n["x"], n["y"]) for n in body["nodes"]]
    assert len(set(spots)) == len(spots), "every draft gets its own spot"
    assert all(0 <= x <= 100 and -40 <= y <= 140 for x, y in spots)

    data = client.get("/api/v2/admin/dataset").get_json()["data"]
    sky = next(z for z in data["zones"] if z["id"] == "sky")
    residents = {(n["x"], n["y"]) for n in data["nodes"] if n.get("zone") == "sky"}
    assert not residents & set(spots), "drafts never sit on a place already charted"
    assert min(y for _, y in spots) >= sky["label_y"], "they start under the realm's label"
    again = client.post("/api/v2/admin/import/csv", headers=WRITE,
                        json={"csv": "name,ip,kind,zone,role,url\n" + rows}).get_json()
    assert [(n["x"], n["y"]) for n in again["nodes"]] == spots, "stable for the same input"


def test_place_drafts_handles_realms_without_a_label():
    import discovery
    data = {"zones": [{"id": "a"}], "nodes": []}
    drafts = discovery.place_drafts(data, [{"zone": "a"}, {"zone": "a"}, {"zone": "nowhere"}])
    assert len({(d["x"], d["y"]) for d in drafts}) == 3


def test_survey_sorts_addresses_as_numbers():
    import discovery
    order = sorted(["10.0.0.10", "10.0.0.2", "not-an-ip", "10.0.0.1", "fe80::1"],
                   key=discovery._address_order)
    assert order == ["10.0.0.1", "10.0.0.2", "10.0.0.10", "fe80::1", "not-an-ip"]


def test_a_scanned_device_charts_under_its_short_name():
    import discovery
    data = {"zones": [{"id": "main", "subnet": "10.0.0.0/24"}], "nodes": []}
    nas = discovery.as_node({"ip": "10.0.0.20", "hostname": "nas.home.example"}, data)
    assert nas["name"] == "NAS" and nas["id"] == "nas" and nas["zone"] == "main"
    bare = discovery.as_node({"ip": "10.0.0.77"}, data)
    assert bare["name"] == "10.0.0.77"


def test_a_bad_device_list_reports_line_numbers(client):
    csv = "name,ip\nGood,10.0.0.1\nBad,not-an-ip\n"
    r = client.post("/api/v2/admin/import/csv", headers=WRITE, json={"csv": csv})
    assert r.status_code == 422
    assert any("line 3" in p for p in r.get_json()["problems"])


# ── the 2026-07-27 security review regressions ─────────────────────────────────────────────

def test_admin_responses_are_never_cacheable(client):
    """Finding 2. /dataset is deliberately unredacted and /revisions names
    people; neither may be stored by a proxy that appears later."""
    for path in ("/api/v2/admin/dataset", "/api/v2/admin/context", "/api/v2/admin/revisions"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "no-store" in r.headers.get("Cache-Control", ""), path
        assert r.headers.get("Vary") == "X-Hub-Auth", path


def test_standalone_defaults_to_read_only(tmp_path):
    """Finding 1. Standalone has no auth at all, so every admin check passes
    for anyone who can reach the port. It must not also be writable by
    default — the editor turned that from a read exposure into a write one."""
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)

    # neither ATLAS_READONLY nor ATLAS_ALLOW_INSECURE set
    os.environ.pop("ATLAS_READONLY", None)
    os.environ.pop("ATLAS_ALLOW_INSECURE", None)
    app = fresh_app(ATLAS_AUTH_MODE="standalone", ATLAS_DATA=str(data),
                    ATLAS_REVISIONS=str(tmp_path / "rev"))
    c = app.app.test_client()
    r = c.post("/api/v2/admin/ops", headers=WRITE, json={"ops": [an_op()]})
    assert r.status_code == 403, "an unauthenticated standalone instance must not accept writes"
    assert 'data-editable="0"' in c.get("/").get_data(as_text=True)

    # ...and the acknowledgement flag opts back in, for loopback dev
    app2 = fresh_app(ATLAS_AUTH_MODE="standalone", ATLAS_ALLOW_INSECURE="1",
                     ATLAS_DATA=str(data), ATLAS_REVISIONS=str(tmp_path / "rev"))
    r2 = app2.app.test_client().post("/api/v2/admin/ops", headers=WRITE,
                                     json={"ops": [an_op("acknowledged")]})
    assert r2.status_code == 200, "ATLAS_ALLOW_INSECURE=1 should still allow local editing"


# ── the directory test route ────────────────────────────────────────────────

def test_the_directory_test_is_a_guarded_write(client):
    """It binds outward with caller-supplied settings and issues the receipt
    that unlocks an ldap-only save. It was the one state-changing admin route
    with no `write_refusal()` in front of it — saved from being reachable
    cross-origin only by the preflight its JSON content type happens to force.
    """
    body = {"settings": {"ATLAS_LDAP_URL": "ldaps://dc.test:636"},
            "username": "ops", "password": "x"}
    assert client.post("/api/v2/admin/auth/test", json=body).status_code == 403
    r = client.post("/api/v2/admin/auth/test",
                    headers={**WRITE, "Sec-Fetch-Site": "cross-site"}, json=body)
    assert r.status_code == 403


def test_the_directory_test_never_stages_settings_globally(client, monkeypatch):
    """The proposal must not become process-wide config for the length of the
    bind: gunicorn runs several threads per worker, so every other request in
    flight read it too, and a login authorised against un-approved settings
    wrote its admin verdict to the database, where it outlived the window."""
    monkeypatch.setenv("ATLAS_LDAP_ADMIN_GROUPS", "Cartographers")
    import ldap_backend
    seen = {}

    def fake_authenticate(username, password, overrides=None):
        seen["overrides"] = overrides
        seen["env"] = os.environ.get("ATLAS_LDAP_ADMIN_GROUPS")
        return False, {}
    monkeypatch.setattr(ldap_backend, "authenticate", fake_authenticate)

    r = client.post("/api/v2/admin/auth/test", headers=WRITE, json={
        "settings": {"ATLAS_LDAP_ADMIN_GROUPS": "Everyone"},
        "username": "ops", "password": "x"})

    assert r.status_code == 200
    assert seen["overrides"]["ATLAS_LDAP_ADMIN_GROUPS"] == "Everyone"
    assert seen["env"] == "Cartographers"          # untouched during the bind
    assert os.environ["ATLAS_LDAP_ADMIN_GROUPS"] == "Cartographers"


def test_the_admin_proof_expires(client, monkeypatch):
    """The receipt used to be a bare `True` that was never cleared, so one
    successful test at any point unlocked every later ldap-only save for the
    life of the session — including saves of settings it never covered."""
    from api.v2 import admin as api_admin
    import ldap_backend
    monkeypatch.setattr(ldap_backend, "authenticate",
                        lambda u, p, overrides=None: (True, {"is_admin": True}))
    r = client.post("/api/v2/admin/auth/test", headers=WRITE, json={
        "settings": {}, "username": "ops", "password": "x"})
    assert r.get_json()["is_admin"] is True

    with client.application.test_request_context("/"):
        assert api_admin._has_ldap_admin_proof() is True

    monkeypatch.setattr(api_admin, "_PROOF_TTL_SECONDS", -1)
    with client.application.test_request_context("/"):
        assert api_admin._has_ldap_admin_proof() is False


def test_hub_mode_is_unaffected_by_the_standalone_default(tmp_path):
    """The app host deployment must keep writing exactly as it did."""
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    os.environ.pop("ATLAS_READONLY", None)
    os.environ.pop("ATLAS_ALLOW_INSECURE", None)
    app = fresh_app(ATLAS_AUTH_MODE="hub", ATLAS_DATA=str(data),
                    ATLAS_REVISIONS=str(tmp_path / "rev"))
    assert app.app.extensions["atlas"].config.READ_ONLY is False


def test_status_does_not_name_the_realm(tmp_path):
    """/api/status is gate-exempt, so it answers ANONYMOUSLY on the public door.

    It must therefore wear the brand, not the realm - the same decision the
    sign-in page took in v1.21.3. Found live 2026-08-21: the login page said
    "The Atlas" while /api/status beside it told every passer-by "the lab
    Atlas". No dataset is needed; status answers even when the map is
    unreadable, which is the point of a health route.
    """
    import settings
    from appfixture import fresh_app

    handle = fresh_app(ATLAS_DATA=str(tmp_path / "absent.json"),
                       ATLAS_DATA_BACKEND="file")
    body = handle.app.test_client().get("/api/status").get_json()

    assert body["name"] == settings.APP_BRAND
    assert "the lab" not in body["name"], (
        "/api/status leaks the realm name to anonymous callers: %r" % body["name"])


# ── first run: the demo is not an empty realm (W8) ──────────────────────────

def test_the_page_says_when_it_is_showing_the_bundled_demo(tmp_path):
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"          # never written: an unseeded instance
    demo = fresh_app(ATLAS_FALLBACK="bundled", ATLAS_DATA=str(data),
                     ATLAS_REVISIONS=str(tmp_path / "rev"))
    page = demo.app.test_client().get("/").get_data(as_text=True)
    assert 'data-seeded="0"' in page and 'data-demo="1"' in page

    empty = fresh_app(ATLAS_FALLBACK="empty", ATLAS_DATA=str(data),
                      ATLAS_REVISIONS=str(tmp_path / "rev"))
    assert 'data-demo="0"' in empty.app.test_client().get("/").get_data(as_text=True)

    shutil.copy(BUNDLED, data)                 # seeded: the operator's own map
    seeded = fresh_app(ATLAS_FALLBACK="bundled", ATLAS_DATA=str(data),
                       ATLAS_REVISIONS=str(tmp_path / "rev"))
    assert 'data-demo="0"' in seeded.app.test_client().get("/").get_data(as_text=True)
