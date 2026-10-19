"""Relay ingest tests — run directly, no pytest needed:

    python Web/tests/test_ingest.py

The token is the entire tenancy boundary here, so the rejection paths matter as
much as the happy ones: unknown/revoked token, missing scope, a payload naming
another site, oversize, malformed, and rate limiting. Also covers the `relay`
signals source and the staleness counter on /api/status.
"""

import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

TMP = tempfile.mkdtemp(prefix="atlas-ingest-test-")
DB_URL = "sqlite:///" + os.path.join(TMP, "ingest.db").replace("\\", "/")

# Declared once so conftest can re-apply it before every test in this
# module. pytest imports all test modules before running any of them, so
# without this the last module imported owns os.environ for the whole run.
ATLAS_TEST_ENV = {
    "ATLAS_DATA_BACKEND": "db",
    "ATLAS_DB_URL": DB_URL,
    "ATLAS_SITE": "lab",
    "ATLAS_INGEST_ENABLED": "1",
    "ATLAS_SIGNALS_SOURCES": "relay",
    "ATLAS_DATA": os.path.join(TMP, "no-such-lab-data.json"),
    "ATLAS_ALLOW_INSECURE": "1",
    # This module's own integrations file. Without it the path comes from
    # whichever module last reloaded `settings` (its DATA_DIR): if a file
    # existed there, the signals hub saw a new stamp mid-test and rebuilt its
    # adapters with that module's sources and site, so the stale-relay test
    # failed only after certain other modules (the 10-18 "flake").
    "ATLAS_INTEGRATIONS": os.path.join(TMP, "integrations-test-ingest.json"),
}
os.environ.update(ATLAS_TEST_ENV)

from store import init_db, load_labdata, session_scope  # noqa: E402
from store.labdata import get_site  # noqa: E402
from store.models import Node, ObservedNode, SignalSnapshot  # noqa: E402
from store.tokens import issue_token, revoke_token  # noqa: E402

init_db()

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as f:
    GOLDEN = json.load(f)
with open(os.path.join(FIX, "netbox", "devices-page1.json"), encoding="utf-8") as f:
    NETBOX_DEVICES = json.load(f)["results"]

with session_scope() as _s:
    load_labdata(_s, copy.deepcopy(GOLDEN), site_slug="lab", site_name="the lab")
    load_labdata(_s, copy.deepcopy(GOLDEN), site_slug="other", site_name="Other Site")
    LAB_TOKEN, _row = issue_token(_s, "lab", label="test relay")
    OTHER_TOKEN, _other_row = issue_token(_s, "other", label="other site relay")
    NOSCOPE_TOKEN, _ns = issue_token(_s, "lab", label="read only", scopes="read")
    REVOKED_TOKEN, _rev = issue_token(_s, "lab", label="old relay")
    revoke_token(_s, _rev.id)

import ingest  # noqa: E402
from api import v2 as api_v2  # noqa: E402
from appfixture import fresh_app  # noqa: E402

atlas_app = fresh_app()

CLIENT = atlas_app.app.test_client()

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _ingest_posture():
    """The ingest fence reads `settings` at request time, and other modules'
    `fresh_app` calls RELOAD the settings module between tests (wiping this
    module's import-time env). Pinned per test, restored after — the same
    guard test_relay.py carries, for the same reason."""
    import settings
    old = (settings.INGEST_ENABLED, settings.DATA_BACKEND, settings.SITE_SLUG)
    settings.INGEST_ENABLED = True
    settings.DATA_BACKEND = "db"
    # the relay adapter is built for settings.SITE_SLUG whenever the hub
    # rebuilds: pin it, so a rebuild can only ever point at this module's site
    settings.SITE_SLUG = "lab"
    yield
    settings.INGEST_ENABLED, settings.DATA_BACKEND, settings.SITE_SLUG = old
FEED = {"nodes": {"app-host": {"state": "healthy"}, "downloads": {"state": "down"}},
        "services": {"nextcloud": {"state": "healthy"}},
        "metrics": {"watchfires_up": 11}}


def _post(path, payload, token=LAB_TOKEN, raw=None, headers=None):
    ingest.limiter.reset()  # each test gets a fresh budget
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    h.update(headers or {})
    data = raw if raw is not None else json.dumps(payload)
    return CLIENT.post(api_v2.INGEST_URL_PREFIX + path, data=data, headers=h)


def _snapshots(site="lab"):
    with session_scope() as s:
        site_row = get_site(s, site)
        return list(s.query(SignalSnapshot)
                    .filter(SignalSnapshot.site_id == site_row.id)
                    .order_by(SignalSnapshot.id))


def test_ingest_is_registered_only_when_enabled():
    assert atlas_app.INGEST_ENABLED is True
    assert CLIENT.post(api_v2.INGEST_URL_PREFIX + "/signals").status_code != 404


def test_signals_push_is_stored_and_served_back():
    r = _post("/signals", FEED)
    assert r.status_code == 200, r.data[:300]
    body = r.get_json()
    assert body["ok"] and body["site"] == "lab" and body["nodes"] == 2

    stored = _snapshots()[-1].payload_json
    assert stored["nodes"]["app-host"]["state"] == "healthy"

    feed = CLIENT.get("/api/v2/signals").get_json()
    assert feed["sources"].get("relay") == "ok", feed.get("sources")
    assert feed["nodes"]["downloads"]["state"] == "down"
    assert feed["metrics"]["watchfires_up"] == 11


def test_snapshot_ring_is_pruned():
    for i in range(ingest.SNAPSHOT_RING + 4):
        assert _post("/signals", {**FEED, "metrics": {"watchfires_up": i}}).status_code == 200
    rows = _snapshots()
    assert len(rows) == ingest.SNAPSHOT_RING, f"ring not pruned: {len(rows)}"


def test_stale_relay_goes_silent_and_status_says_so():
    _post("/signals", FEED)
    stale_at = datetime.now(timezone.utc) - timedelta(minutes=42)
    with session_scope() as s:
        # age out every snapshot: freshness is "the newest push", not "a push"
        for row in (s.query(SignalSnapshot)
                    .filter(SignalSnapshot.site_id == get_site(s, "lab").id)):
            row.received_at = stale_at
    atlas_app._signals._cache = None  # bypass the 30s feed cache

    feed = CLIENT.get("/api/v2/signals").get_json()
    assert feed["sources"].get("relay") == "silent", "a stale relay must not look live"
    assert not feed.get("nodes"), "stale health must not be served as current"

    metrics = CLIENT.get("/api/status").get_json()["summary"]["secondary_metrics"]
    stale = [m for m in metrics if m["label"].startswith("Relay Stale")]
    assert stale and stale[0]["value"] >= 42, metrics
    assert CLIENT.get("/api/status").get_json()["healthy"] is True, \
        "a dead relay must not flip the app unhealthy (live data is seasoning)"


def test_inventory_push_applies_a_netbox_snapshot():
    payload = {"vlans": [{"id": 1, "vid": 33, "name": "Upper Deck"}],
               "prefixes": [{"id": 1, "prefix": "10.77.33.0/24",
                             "vlan": {"id": 1, "vid": 33}}],
               "devices": NETBOX_DEVICES, "vms": []}
    r = _post("/inventory", payload)
    assert r.status_code == 200, r.data[:300]
    stats = r.get_json()["stats"]
    assert stats["nodes_adopted"] + stats["nodes_created"] >= 1, stats
    with session_scope() as s:
        node = {n.slug: n for n in s.query(Node)
                .filter(Node.site_id == get_site(s, "lab").id)}["nas"]
        assert node.external_source == "netbox"


def test_observed_push_reports_drift():
    hosts = [{"ip": "10.77.33.5", "hostname": "hypervisor.home.example"},
             {"ip": "10.77.33.222", "mac": "DE:AD:BE:EF:02:22", "hostname": "stranger"}]
    r = _post("/observed", {"hosts": hosts})
    assert r.status_code == 200, r.data[:300]
    stats = r.get_json()["stats"]
    assert stats["matched"] == 1 and stats["undocumented"] == 1, stats
    with session_scope() as s:
        rows = list(s.query(ObservedNode)
                    .filter(ObservedNode.site_id == get_site(s, "lab").id))
    assert any(o.ip == "10.77.33.222" and o.matched_node_id is None for o in rows)


def test_missing_unknown_and_revoked_tokens_are_401():
    assert _post("/signals", FEED, token=None).status_code == 401
    assert _post("/signals", FEED, token="atlas_not-a-real-token").status_code == 401
    assert _post("/signals", FEED, token=REVOKED_TOKEN).status_code == 401


def test_wrong_scope_is_403():
    r = _post("/signals", FEED, token=NOSCOPE_TOKEN)
    assert r.status_code == 403, r.status_code
    assert "scope" in r.get_json()["error"]


def test_token_cannot_write_another_site():
    """The tenancy invariant — negative control for cross-site writes."""
    r = _post("/signals", {**FEED, "site": "other"}, token=LAB_TOKEN)
    assert r.status_code == 403, r.data[:200]
    assert _snapshots("other") == [], "a cross-site write must leave no trace"
    ok = _post("/signals", {**FEED, "site": "other"}, token=OTHER_TOKEN)
    assert ok.status_code == 200, "the site's own token must still work"


def test_malformed_payloads_are_422():
    assert _post("/signals", None, raw="not json").status_code == 422
    assert _post("/signals", ["a", "list"]).status_code == 422
    assert _post("/signals", {"nodes": "not a dict"}).status_code == 422
    assert _post("/observed", {"hosts": [{"nothing": "useful"}]}).status_code == 422
    assert _post("/observed", {"hosts": "not a list"}).status_code == 422
    assert _post("/inventory", {"devices": [{"no": "id"}]}).status_code == 422
    assert _post("/inventory", {"vlans": [], "devices": [], "vms": []}).status_code == 422


def test_oversize_payload_is_413():
    big = json.dumps({"nodes": {f"n{i}": {"state": "healthy"} for i in range(60000)}})
    assert len(big) > ingest.MAX_BYTES
    assert _post("/signals", None, raw=big).status_code == 413


def test_rate_limit_is_429():
    ingest.limiter.reset()
    codes = [CLIENT.post(
        api_v2.INGEST_URL_PREFIX + "/signals", data=json.dumps(FEED),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {LAB_TOKEN}"}).status_code
        for _ in range(ingest.RATE_LIMIT + 3)]
    assert codes.count(429) == 3, f"expected 3 rate-limited, got {codes.count(429)}"
    assert codes[0] == 200
    ingest.limiter.reset()


def test_ingest_paths_bypass_only_the_session_gate():
    """Exempt from the Hub gate, never from the token check."""
    from hub_auth.auth import require_hub_or_standalone
    check = require_hub_or_standalone(exempt_prefixes=["/static/", api_v2.INGEST_URL_PREFIX + "/"])
    with atlas_app.app.test_request_context(api_v2.INGEST_URL_PREFIX + "/signals", method="POST"):
        assert check() is None, "ingest must not be blocked by the session gate"
    assert _post("/signals", FEED, token=None).status_code == 401


if __name__ == "__main__":
    failures = 0
    for name in sorted(n for n in globals() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"  ok   {name}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {name}: {e}")
    print("PASS" if not failures else f"{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)
