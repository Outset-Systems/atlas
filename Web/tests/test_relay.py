"""atlas-relay tests — run directly, no pytest needed:

    python Web/tests/test_relay.py

The headline test is the integration one: the real relay code pushing to the
real ingest endpoints. The rest guard the promises the relay makes about
never crashing (dead sources, missing nmap, unreachable server) and never
leaking (token from a file, https enforced).
"""

import copy
import json
import os
import subprocess
import sys
import tempfile

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELAY = os.path.join(os.path.dirname(WEB), "relay")
sys.path.insert(0, WEB)
sys.path.insert(0, RELAY)

TMP = tempfile.mkdtemp(prefix="atlas-relay-test-")
DB_URL = "sqlite:///" + os.path.join(TMP, "relay.db").replace("\\", "/")
# Declared once so conftest can re-apply it before every test in this
# module. pytest imports all test modules before running any of them, so
# without this the last module imported owns os.environ for the whole run.
ATLAS_TEST_ENV = {
    "ATLAS_DB_URL": DB_URL,
}
os.environ.update(ATLAS_TEST_ENV)

import atlas_relay  # noqa: E402
from flask import Flask  # noqa: E402

import ingest  # noqa: E402
from store import init_db, load_labdata, session_scope  # noqa: E402
from store.labdata import get_site  # noqa: E402
from store.models import Node, ObservedNode, SignalSnapshot  # noqa: E402
from store.tokens import issue_token  # noqa: E402

init_db()

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as f:
    GOLDEN = json.load(f)
with open(os.path.join(FIX, "nmap", "scan.xml"), encoding="utf-8") as f:
    SCAN_XML = f.read()

with session_scope() as _s:
    load_labdata(_s, copy.deepcopy(GOLDEN), site_slug="lab", site_name="the lab")
    TOKEN, _row = issue_token(_s, "lab", label="relay test")

# The real ingest blueprints on a bare app: this exercises the actual server
# endpoints without inheriting app.py's module-level env (kept order-independent
# so the suite can run in any sequence). Since the 2026-08-25 cutover the relay
# CLIENT speaks /api/v2/ingest/*, so the v2 surface must answer here too; its
# per-request fence reads settings at call time, so the flags are set directly
# (module attributes — import order under pytest collection makes env timing
# unreliable, which is the exact trap this module's docstring warns about).
from api import v2 as api_v2

SERVER = Flask(__name__)
SERVER.register_blueprint(api_v2.bp)
CLIENT = SERVER.test_client()

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _v2_ingest_flags():
    """The v2 ingest fence reads `settings` attributes at request time, and
    other modules' `fresh_app` calls RELOAD the settings module between tests
    (wiping any import-time set). Applied per test, restored after."""
    import settings
    old = (settings.INGEST_ENABLED, settings.DATA_BACKEND)
    settings.INGEST_ENABLED = True
    settings.DATA_BACKEND = "db"
    yield
    settings.INGEST_ENABLED, settings.DATA_BACKEND = old

SIGNALS_FILE = os.path.join(TMP, "signals.json")
with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
    json.dump({"nodes": {"app-host": {"state": "healthy"}, "downloads": {"state": "down"}},
               "metrics": {"watchfires_up": 9}}, f)

ATLAS = atlas_relay.load_atlas_modules(WEB)


class ClientTransport:
    """Speaks the relay's transport contract, delivers to the real endpoints."""

    def __init__(self, token=TOKEN):
        self.token = token
        self.sent = []

    def post(self, path, payload):
        ingest.limiter.reset()
        self.sent.append((path, payload))
        r = CLIENT.post(path, data=json.dumps(payload),
                        headers={"Content-Type": "application/json",
                                 "Authorization": f"Bearer {self.token}"})
        return r.status_code, r.get_json()


class DeadTransport:
    def post(self, path, payload):
        raise OSError("connection refused")


def _config(**sections):
    cfg = {"server": {"url": "https://atlas.example.com", "token": TOKEN}}
    for name, defaults in atlas_relay.DEFAULTS.items():
        cfg[name] = dict(defaults)
    for name, values in sections.items():
        cfg.setdefault(name, {}).update(values)
    return cfg


def _write(name, text):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ── Config ───────────────────────────────────────────────────────────────────
def test_config_requires_url_and_token():
    path = _write("no-url.toml", '[signals]\nenabled = true\n')
    try:
        atlas_relay.read_config(path)
        assert False, "expected ConfigError for a missing url"
    except atlas_relay.ConfigError as e:
        assert "server.url" in str(e)

    path = _write("no-token.toml", '[server]\nurl = "https://a.example"\n')
    os.environ.pop("ATLAS_RELAY_TOKEN", None)
    try:
        atlas_relay.read_config(path)
        assert False, "expected ConfigError for a missing token"
    except atlas_relay.ConfigError as e:
        assert "token" in str(e)


def test_plain_http_is_refused_unless_acknowledged():
    body = '[server]\nurl = "http://atlas.home.example"\ntoken = "atlas_x"\n'
    try:
        atlas_relay.read_config(_write("http.toml", body))
        assert False, "expected ConfigError for plain http"
    except atlas_relay.ConfigError as e:
        assert "clear" in str(e) or "HTTP" in str(e)
    cfg = atlas_relay.read_config(
        _write("http-ok.toml", body + "allow_insecure_http = true\n"))
    assert cfg["server"]["url"] == "http://atlas.home.example"


def test_token_comes_from_a_file_and_defaults_are_applied():
    token_path = _write("token.txt", "atlas_from_file\n")
    cfg = atlas_relay.read_config(_write("with-file.toml",
        f'[server]\nurl = "https://a.example"\ntoken_file = {json.dumps(token_path)}\n'))
    assert cfg["server"]["token"] == "atlas_from_file", "token file not read/stripped"
    assert cfg["signals"]["interval"] == 30 and cfg["inventory"]["enabled"] is False


def test_json_config_is_accepted():
    path = _write("cfg.json", json.dumps(
        {"server": {"url": "https://a.example", "token": "atlas_j"},
         "scan": {"enabled": True, "targets": ["10.0.0.0/24"]}}))
    cfg = atlas_relay.read_config(path)
    assert cfg["scan"]["targets"] == ["10.0.0.0/24"]
    assert cfg["scan"]["nmap_args"] == ["-sn"], "defaults must survive a partial section"


def test_only_enabled_tasks_are_built():
    tasks = atlas_relay.build_tasks(ATLAS, _config(
        signals={"enabled": True, "interval": 15},
        scan={"enabled": True, "targets": ["10.0.0.0/24"]}))
    assert [t.name for t in tasks] == ["signals", "scan"]
    assert tasks[0].interval == 15
    assert tasks[0].path == "/api/v2/ingest/signals"


# ── Collectors ───────────────────────────────────────────────────────────────
def test_signals_collector_uses_the_atlas_adapters():
    payload = atlas_relay.collect_signals(ATLAS, _config(
        signals={"enabled": True, "sources": ["static"], "file": SIGNALS_FILE}))
    assert payload["nodes"]["downloads"]["state"] == "down"
    assert payload["metrics"]["watchfires_up"] == 9


def test_silent_sources_push_nothing_rather_than_an_empty_feed():
    payload = atlas_relay.collect_signals(ATLAS, _config(
        signals={"enabled": True, "sources": ["static"],
                 "file": os.path.join(TMP, "does-not-exist.json")}))
    assert payload is None, "an empty feed would blank the map — send nothing instead"
    assert atlas_relay.collect_signals(ATLAS, _config(signals={"sources": []})) is None


def test_scan_collector_parses_nmap_and_survives_its_absence():
    cfg = _config(scan={"enabled": True, "targets": ["10.77.33.0/24"]})
    payload = atlas_relay.collect_scan(ATLAS, cfg, runner=lambda cmd, timeout: SCAN_XML)
    assert len(payload["hosts"]) == 3 and payload["source"] == "relay"
    assert "promote" not in payload

    def missing(cmd, timeout):
        raise FileNotFoundError(cmd[0])
    assert atlas_relay.collect_scan(ATLAS, cfg, runner=missing) is None

    def slow(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)
    assert atlas_relay.collect_scan(ATLAS, cfg, runner=slow) is None
    assert atlas_relay.collect_scan(ATLAS, cfg, runner=lambda cmd, timeout: "<garbage") is None
    assert atlas_relay.collect_scan(ATLAS, _config(scan={"enabled": True})) is None


def test_scan_command_is_a_ping_sweep_by_default():
    seen = {}

    def spy(cmd, timeout):
        seen["cmd"] = cmd
        return SCAN_XML
    atlas_relay.collect_scan(ATLAS, _config(
        scan={"enabled": True, "targets": ["10.77.33.0/24"]}), runner=spy)
    assert seen["cmd"][:4] == ["nmap", "-sn", "-oX", "-"], seen["cmd"]
    assert seen["cmd"][-1] == "10.77.33.0/24"


# ── Pushing ──────────────────────────────────────────────────────────────────
def test_relay_pushes_signals_to_the_real_endpoint():
    transport = ClientTransport()
    tasks = atlas_relay.build_tasks(ATLAS, _config(
        signals={"enabled": True, "sources": ["static"], "file": SIGNALS_FILE}))
    assert atlas_relay.run(tasks, transport, once=True) == 0

    with session_scope() as s:
        rows = list(s.query(SignalSnapshot)
                    .filter(SignalSnapshot.site_id == get_site(s, "lab").id))
    assert rows, "nothing reached the server"
    assert rows[-1].payload_json["nodes"]["downloads"]["state"] == "down"


def test_relay_scan_push_reports_drift_end_to_end():
    transport = ClientTransport()
    cfg = _config(scan={"enabled": True, "targets": ["10.77.33.0/24"]})
    payload = atlas_relay.collect_scan(ATLAS, cfg, runner=lambda cmd, timeout: SCAN_XML)
    status, body = transport.post("/api/v2/ingest/observed", payload)
    assert status == 200, body
    assert body["stats"]["undocumented"] == 1, body["stats"]
    with session_scope() as s:
        strangers = [o.ip for o in s.query(ObservedNode)
                     .filter(ObservedNode.site_id == get_site(s, "lab").id,
                             ObservedNode.matched_node_id.is_(None))]
    assert "10.77.33.99" in strangers


def test_dry_run_collects_but_sends_nothing():
    transport = ClientTransport()
    tasks = atlas_relay.build_tasks(ATLAS, _config(
        signals={"enabled": True, "sources": ["static"], "file": SIGNALS_FILE}))
    assert atlas_relay.run(tasks, transport, once=True, dry_run=True) == 0
    assert transport.sent == [], "dry run must not push"


def test_unreachable_server_is_a_failure_not_a_crash():
    tasks = atlas_relay.build_tasks(ATLAS, _config(
        signals={"enabled": True, "sources": ["static"], "file": SIGNALS_FILE}))
    assert atlas_relay.run(tasks, DeadTransport(), once=True) == 1


def test_rejected_token_is_reported_as_failure():
    transport = ClientTransport(token="atlas_not_a_real_token")
    tasks = atlas_relay.build_tasks(ATLAS, _config(
        signals={"enabled": True, "sources": ["static"], "file": SIGNALS_FILE}))
    assert atlas_relay.run(tasks, transport, once=True) == 1


def test_collector_exceptions_never_escape():
    task = atlas_relay.Task("boom", "/api/v2/ingest/signals",
                            lambda: (_ for _ in ()).throw(RuntimeError("kaboom")), 30)
    assert atlas_relay.run_task(task, ClientTransport()) is False


def test_backoff_grows_then_resets():
    task = atlas_relay.Task("t", "/p", lambda: None, 30)
    task.schedule(0.0, failed=True)
    first = task.next_run
    task.schedule(0.0, failed=True)
    second = task.next_run
    assert first == atlas_relay.BACKOFF_START and second == 2 * first, (first, second)
    for _ in range(20):
        task.schedule(0.0, failed=True)
    assert task.next_run <= atlas_relay.BACKOFF_MAX, "backoff must be capped"
    task.schedule(100.0, failed=False)
    assert task.next_run == 130.0 and task.backoff == 0.0, "success must reset the backoff"


def test_loop_stops_and_reschedules():
    ticks = {"n": 0}

    def now():
        return ticks["n"]

    def sleeper(seconds):
        ticks["n"] += seconds
        if ticks["n"] > 90:
            raise KeyboardInterrupt
    transport = ClientTransport()
    tasks = atlas_relay.build_tasks(ATLAS, _config(
        signals={"enabled": True, "interval": 30, "sources": ["static"], "file": SIGNALS_FILE}))
    try:
        atlas_relay.run(tasks, transport, sleeper=sleeper, now=now)
    except KeyboardInterrupt:
        pass
    assert len(transport.sent) >= 2, "the loop should have pushed on its interval"


# ── /api/v2/ingest/inventory — the one ingest route with no route-level test ─
def _post_inventory(payload, token=TOKEN):
    ingest.limiter.reset()
    r = CLIENT.post("/api/v2/ingest/inventory", data=json.dumps(payload),
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {token}"})
    return r.status_code, r.get_json()


def test_inventory_ingest_validates_the_snapshot_shape():
    assert _post_inventory({"devices": "nope"})[0] == 422
    assert _post_inventory({"devices": [{"name": "no id"}]})[0] == 422
    assert _post_inventory({"vlans": [], "prefixes": [], "devices": [], "vms": []})[0] == 422
    status, body = _post_inventory({"devices": [{"id": 1, "name": "x"}], "role_map": "broken"})
    assert status == 422 and "error" in body
    status, body = _post_inventory({"site": "acme", "devices": [{"id": 1, "name": "x"}]})
    assert status == 403                                    # a token writes its own site only


def test_inventory_ingest_applies_a_netbox_snapshot_to_its_site():
    """The same sync the CLI importer runs, reached through the relay's door:
    a NetBox-shaped device lands as a node on the token's site, with its
    provenance, and the reply carries the sync's own stats."""
    with open(os.path.join(FIX, "netbox", "devices-page1.json"), encoding="utf-8") as f:
        device = json.load(f)["results"][0]
    status, body = _post_inventory({"vlans": [], "prefixes": [], "devices": [device], "vms": []})
    assert status == 200, body
    assert body["ok"] is True and body["site"] == "lab"
    stats = body["stats"]
    assert stats["nodes_created"] + stats["nodes_adopted"] >= 1, stats
    with session_scope() as s:
        row = next(n for n in s.query(Node).all()
                   if n.external_ref == f"device:{device['id']}")
        assert row.external_source == "netbox"
        assert row.site_id == get_site(s, "lab").id


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
