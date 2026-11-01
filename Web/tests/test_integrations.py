"""THE SOURCES — integration settings (v1.37.0): layered right, secret right,
probed right, saved right, rebuilt right.

* LAYERED RIGHT — the settings file overrides the environment and says so;
  a blank stored value falls through to the deployment; unknown keys are
  refused; charts/vitals read the layer, not `os.environ`.
* SECRET RIGHT — a key is encrypted on disk (the file never holds the
  plaintext), `describe()` never echoes it (only `set`), '' keeps the stored
  key, `None` clears it, and a form that omits the field keeps it too.
* PROBED RIGHT — `/integrations/test` asks the named source with the values
  as typed, a blank key meaning the one in force; a bad URL is a 400; a
  source that will not answer is `ok: false` with the reason, never a 500.
* SAVED RIGHT — URLs must be http(s) with a host; a source cannot be enabled
  without its URL; the response describes, never leaks.
* REBUILT RIGHT — the signals hub built with a factory rebuilds its adapters
  when the settings file moves, so a save reaches every worker.
* GATED RIGHT — the routes sit under the admins-only blueprint.
"""

import json
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
WRITE = {"X-Atlas-Write": "1", "Content-Type": "application/json"}


@pytest.fixture
def handle(tmp_path, monkeypatch):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    for var in ("ATLAS_PROM_URL", "ATLAS_LOKI_URL", "ATLAS_KUMA_URL", "ATLAS_KUMA_API_KEY",
                "ATLAS_KUMA_API_KEY_FILE", "ATLAS_DECOYS_URL", "ATLAS_DECOYS_KEY",
                "ATLAS_DECOYS_KEY_FILE", "ATLAS_SIGNALS_SOURCES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ATLAS_INTEGRATIONS", str(tmp_path / "integrations.json"))
    # no ATLAS_ENCRYPTION_KEY(_FILE): crypto_at_rest mints one lazily under the
    # data dir, exactly as a fresh standalone deployment does
    monkeypatch.delenv("ATLAS_ENCRYPTION_KEY_FILE", raising=False)
    monkeypatch.delenv("ATLAS_ENCRYPTION_KEY", raising=False)
    h = fresh_app(ATLAS_DATA=str(data), ATLAS_POSITIONS=str(tmp_path / "positions.json"),
                  ATLAS_RACK=str(tmp_path / "rack.json"), ATLAS_READONLY="0")
    import integrations
    integrations._cache["mtime"] = None
    return h


@pytest.fixture
def client(handle):
    return handle.app.test_client()


# ── layered ─────────────────────────────────────────────────────────────────
def test_layered_right(client, monkeypatch, tmp_path):
    import integrations
    monkeypatch.setenv("ATLAS_PROM_URL", "http://env.prom:9090")
    assert integrations.get("ATLAS_PROM_URL") == "http://env.prom:9090"
    assert integrations.sources()["ATLAS_PROM_URL"] == "deployment"
    assert integrations.sources()["ATLAS_LOKI_URL"] == "unset"

    integrations.save({"ATLAS_PROM_URL": "http://set.prom:9090"})
    assert integrations.get("ATLAS_PROM_URL") == "http://set.prom:9090"
    assert integrations.sources()["ATLAS_PROM_URL"] == "settings"
    # blank stored = fall through to the deployment again
    integrations.save({"ATLAS_PROM_URL": ""})
    assert integrations.get("ATLAS_PROM_URL") == "http://env.prom:9090"
    with pytest.raises(ValueError):
        integrations.save({"ATLAS_READONLY": "0"})

    # the askers read the layer, not the environment
    from api.v2 import charts as ch, vitals as vt
    integrations.save({"ATLAS_PROM_URL": "http://set.prom:9090/"})
    assert ch._prom_url() == "http://set.prom:9090" and vt._prom_url() == "http://set.prom:9090"
    idx = {c["key"]: c for c in client.get("/api/v2/charts").get_json()["charts"]}
    assert idx["edge.bans"]["available"] and not idx["edge.status"]["available"]


# ── secrets ─────────────────────────────────────────────────────────────────
def test_secret_right(client, tmp_path):
    import integrations
    integrations.save({"ATLAS_KUMA_API_KEY": "uk1_super_secret"})
    on_disk = open(integrations.path(), encoding="utf-8").read()
    assert "uk1_super_secret" not in on_disk, "the key must not sit on disk in the clear"
    assert integrations.get("ATLAS_KUMA_API_KEY") == "uk1_super_secret"
    d = integrations.describe()["ATLAS_KUMA_API_KEY"]
    assert d == {"value": "", "set": True, "source": "settings", "secret": True}

    integrations.save({"ATLAS_KUMA_API_KEY": "", "ATLAS_PROM_URL": "http://p:9090"})
    assert integrations.get("ATLAS_KUMA_API_KEY") == "uk1_super_secret", "'' keeps the stored key"
    integrations.save({"ATLAS_PROM_URL": "http://p2:9090"})
    assert integrations.get("ATLAS_KUMA_API_KEY") == "uk1_super_secret", "omitted keeps it too"
    integrations.save({"ATLAS_KUMA_API_KEY": None})
    assert integrations.get("ATLAS_KUMA_API_KEY") == "" and not integrations.describe()["ATLAS_KUMA_API_KEY"]["set"]

    # the API never echoes a key either
    integrations.save({"ATLAS_DECOYS_KEY": "read-me-not"})
    body = client.get("/api/v2/admin/integrations").get_json()
    assert "read-me-not" not in json.dumps(body)
    assert body["settings"]["ATLAS_DECOYS_KEY"]["set"] is True
    # the signals layer resolves the stored one ahead of the environment
    import signals
    assert signals._read_secret("ATLAS_DECOYS_KEY") == "read-me-not"


# ── probing ─────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status=200, text="", payload=None):
        self.status_code, self.text, self._payload = status, text, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_probed_right(client, monkeypatch):
    import requests
    seen = []

    def fake_get(url, **kw):
        seen.append((url, kw))
        if url.endswith("/-/ready"):
            return _Resp(text="Prometheus Server is Ready.")
        if "/api/v1/query" in url:
            return _Resp(payload={"data": {"result": [{"value": [0, "6"]}]}})
        if url.endswith("/metrics"):
            if kw.get("auth") != ("", "the-key"):
                return _Resp(status=401)
            return _Resp(text="monitor_status{a=1} 1\nmonitor_status{b=2} 0\nother 1\n")
        if url.endswith("/api/stones"):
            if kw.get("headers", {}).get("X-Api-Key") != "stone-key":
                return _Resp(status=403)
            return _Resp(payload={"stones": {"a": {}, "b": {}, "c": {}}})
        raise ConnectionError("refused")

    monkeypatch.setattr(requests, "get", fake_get)
    r = client.post("/api/v2/admin/integrations/test", headers=WRITE,
                    json={"kind": "prometheus", "settings": {"ATLAS_PROM_URL": "http://p:9090"}})
    assert r.status_code == 200 and r.get_json()["ok"] and "6 watchfires" in r.get_json()["detail"]

    # a blank key means "the one in force" — a stored secret can be tested without retyping
    import integrations
    integrations.save({"ATLAS_KUMA_URL": "http://k:3001", "ATLAS_KUMA_API_KEY": "the-key"})
    r = client.post("/api/v2/admin/integrations/test", headers=WRITE, json={"kind": "kuma", "settings": {}})
    assert r.get_json() == {"ok": True, "detail": "Kuma answers — 2 monitors", "error": ""}
    r = client.post("/api/v2/admin/integrations/test", headers=WRITE,
                    json={"kind": "kuma", "settings": {"ATLAS_KUMA_API_KEY": "wrong"}})
    assert r.get_json()["ok"] is False and "refused the key" in r.get_json()["error"]

    r = client.post("/api/v2/admin/integrations/test", headers=WRITE,
                    json={"kind": "decoys", "settings": {"ATLAS_DECOYS_URL": "http://s:5013",
                                                          "ATLAS_DECOYS_KEY": "stone-key"}})
    assert r.get_json()["ok"] and "3 decoys" in r.get_json()["detail"]

    # a stored key never goes to a typed address, and saving cannot move it either
    r = client.post("/api/v2/admin/integrations/test", headers=WRITE,
                    json={"kind": "kuma", "settings": {"ATLAS_KUMA_URL": "http://evil.example"}})
    assert r.status_code == 400 and "saved address" in r.get_json()["error"]
    from api.v2 import admin as adm
    for blank in (None, "", 0, False, []):
        r = client.post("/api/v2/admin/integrations/test", headers=WRITE, json={
            "kind": "kuma", "settings": {"ATLAS_KUMA_URL": "http://evil.example", "ATLAS_KUMA_API_KEY": blank}})
        assert r.status_code == 400 and "saved address" in r.get_json()["error"]
    adm._probe_log.clear()   # those five were the limiter's to count, not the rest of this test's
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"ATLAS_KUMA_URL": "http://evil.example", "ATLAS_KUMA_API_KEY": ""}})
    assert r.status_code == 422 and integrations.get("ATLAS_KUMA_URL") == "http://k:3001"

    # a source that will not answer is a finding, not a 500
    r = client.post("/api/v2/admin/integrations/test", headers=WRITE,
                    json={"kind": "loki", "settings": {"ATLAS_LOKI_URL": "http://nowhere:3100"}})
    assert r.status_code == 200 and r.get_json()["ok"] is False and "did not answer" in r.get_json()["error"]
    # bad inputs are 400s
    assert client.post("/api/v2/admin/integrations/test", headers=WRITE,
                       json={"kind": "grafana", "settings": {}}).status_code == 400
    assert client.post("/api/v2/admin/integrations/test", headers=WRITE,
                       json={"kind": "loki", "settings": {"ATLAS_LOKI_URL": "loki:3100"}}).status_code == 400
    assert client.post("/api/v2/admin/integrations/test", headers=WRITE,
                       json={"kind": "loki", "settings": {"ATLAS_READONLY": "0"}}).status_code == 400


# ── saving ──────────────────────────────────────────────────────────────────
def test_saved_right(client):
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"ATLAS_PROM_URL": "ftp://p:9090"}})
    assert r.status_code == 422 and "http(s)" in r.get_json()["error"]
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"ATLAS_SIGNALS_SOURCES": "kuma,grafana"}})
    assert r.status_code == 422 and "unknown signals source" in r.get_json()["error"]
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"ATLAS_SIGNALS_SOURCES": "prometheus"}})
    assert r.status_code == 422 and "ATLAS_PROM_URL" in r.get_json()["error"]
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"ATLAS_NOT_A_THING": "x"}})
    assert r.status_code == 400

    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"ATLAS_SIGNALS_SOURCES": "prometheus",
                                       "ATLAS_PROM_URL": "http://p:9090",
                                       "ATLAS_DECOYS_KEY": "s3cret"}})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["settings"]["ATLAS_PROM_URL"]["source"] == "settings"
    assert "s3cret" not in json.dumps(body)
    assert body["hub"]["enabled"] == ["prometheus"], "the hub follows the save at once"


# ── the hub follows the file ────────────────────────────────────────────────
def test_rebuilt_right(handle, tmp_path):
    import integrations
    import signals
    hub = handle.app.extensions["atlas"].signals
    assert hub.enabled == []
    integrations.save({"ATLAS_SIGNALS_SOURCES": "prometheus,kuma",
                       "ATLAS_PROM_URL": "http://p:9090", "ATLAS_KUMA_URL": "http://k:3001"})
    # another worker would see this on its next poll: feed() notices the mtime
    os.utime(integrations.path(), (1, 1))     # a definitely-different stamp
    hub.feed()
    assert sorted(hub.enabled) == ["kuma", "prometheus"]
    prom = next(a for a in hub.adapters if a.name == "prometheus")
    assert prom.url == "http://p:9090"
    # a fixed hub (tests, static) never rebuilds
    fixed = signals.SignalsHub([signals.StaticFileAdapter(str(tmp_path / "none.json"))])
    fixed.feed()
    assert fixed.enabled == ["static"]


def test_gated_right(client, monkeypatch):
    from api.v2 import admin as adm
    monkeypatch.setattr(adm, "is_admin", lambda: False)
    assert client.get("/api/v2/admin/integrations").status_code == 403
    assert client.post("/api/v2/admin/integrations", headers=WRITE, json={"settings": {}}).status_code == 403
    assert client.get("/api/v2/admin/deployment").status_code == 403


# ── THE REALM + THE DEPLOYMENT (v1.38.0) ─────────────────────────────────────
def test_realm_right(client, monkeypatch):
    """HUB_URL, the vault root and the heartbeat token ride the same layer:
    settings first, environment second — and the token is a secret."""
    import integrations
    import settings
    monkeypatch.setenv("HUB_URL", "https://env.hub")
    monkeypatch.setenv("ATLAS_SCROLL_ROOT", "E:\\vault\\")
    with client.application.test_request_context("/"):
        assert settings.hub_url() == "https://env.hub"
        assert settings.client_config()["scrollRoot"] == "E:\\vault\\"
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"HUB_URL": "https://set.hub", "ATLAS_SCROLL_ROOT": "/srv/docs/",
                                       "ATLAS_BEAT_TOKEN": "beat-me"}})
    assert r.status_code == 200, r.get_json()
    with client.application.test_request_context("/"):
        assert settings.hub_url() == "https://set.hub"
        assert settings.client_config()["scrollRoot"] == "/srv/docs/"
        # the forwarded header still wins — the Hub knows where it is
        with client.application.test_request_context("/", headers={"X-Hub-URL": "https://hdr.hub"}):
            assert settings.hub_url() == "https://hdr.hub"
    assert settings.beat_token() == "beat-me"
    assert "beat-me" not in open(integrations.path(), encoding="utf-8").read()
    r = client.post("/api/v2/admin/integrations", headers=WRITE, json={"settings": {"HUB_URL": "hub:5000"}})
    assert r.status_code == 422


def test_deployment_view_right(client, monkeypatch):
    """Every knob, its layer, secrets masked — and no way to write."""
    import integrations
    monkeypatch.setenv("ATLAS_LDAP_URL", "ldaps://dc.test:636")
    monkeypatch.setenv("ATLAS_SECRET_KEY", "hush-hush")
    integrations.save({"ATLAS_PROM_URL": "http://set.prom:9090", "ATLAS_KUMA_API_KEY": "k3y"})
    r = client.get("/api/v2/admin/deployment")
    assert r.status_code == 200
    body = r.get_json()
    knobs = {k["name"]: k for k in body["knobs"]}
    assert knobs["ATLAS_PROM_URL"] == {"name": "ATLAS_PROM_URL", "source": "settings", "secret": False,
                                       "value": "http://set.prom:9090"}
    assert knobs["ATLAS_LDAP_URL"]["source"] == "environment" and knobs["ATLAS_LDAP_URL"]["value"] == "ldaps://dc.test:636"
    assert knobs["ATLAS_SECRET_KEY"] == {"name": "ATLAS_SECRET_KEY", "source": "environment", "secret": True, "value": "set"}
    assert knobs["ATLAS_KUMA_API_KEY"]["value"] == "set" and knobs["ATLAS_KUMA_API_KEY"]["secret"]
    assert knobs["ATLAS_READONLY"]["source"] in ("environment", "default")
    assert "hush-hush" not in r.get_data(as_text=True) and "k3y" not in r.get_data(as_text=True)
    assert client.post("/api/v2/admin/deployment", headers=WRITE, json={}).status_code == 405
    # review, 2026-09-03: a DSN's password never shows; the metrics flag is
    # what /metrics will DO (registry up AND token set), not the token alone
    monkeypatch.setenv("ATLAS_DB_URL", "postgresql://atlas:s3cr3t-dsn@db.test:5432/atlas")
    monkeypatch.delenv("ATLAS_METRICS_TOKEN", raising=False)
    monkeypatch.delenv("ATLAS_METRICS_TOKEN_FILE", raising=False)
    body = client.get("/api/v2/admin/deployment").get_json()
    knobs = {k["name"]: k for k in body["knobs"]}
    assert knobs["ATLAS_DB_URL"]["value"] == "postgresql://atlas:***@db.test:5432/atlas"
    assert "s3cr3t-dsn" not in json.dumps(body)
    assert body["metrics"] is False and body["metrics_token"] is False
    monkeypatch.setenv("ATLAS_METRICS_TOKEN", "t")
    body = client.get("/api/v2/admin/deployment").get_json()
    assert body["metrics_token"] is True and body["metrics"] == body["metrics_registry"]


def test_save_is_a_merge_across_forms(client):
    """Review, 2026-09-03: THE SOURCES, THE REALM and THE GLASS post disjoint
    subsets of one file. A save must keep every key it does not mention —
    the first cut rebuilt the file from the posted keys and forgot the rest."""
    import integrations
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"ATLAS_PROM_URL": "http://p:9090", "ATLAS_KUMA_API_KEY": "k1"}})
    assert r.status_code == 200
    # THE REALM's form posts only its own keys
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"HUB_URL": "https://hub.test", "ATLAS_SCROLL_ROOT": "", "ATLAS_BEAT_TOKEN": ""}})
    assert r.status_code == 200
    assert integrations.get("ATLAS_PROM_URL") == "http://p:9090", "the sources survived a realm save"
    assert integrations.get("ATLAS_KUMA_API_KEY") == "k1"
    assert integrations.get("HUB_URL") == "https://hub.test"
    # and '' really does clear a plain key back to the deployment
    r = client.post("/api/v2/admin/integrations", headers=WRITE, json={"settings": {"ATLAS_PROM_URL": ""}})
    assert r.status_code == 200
    assert integrations.sources()["ATLAS_PROM_URL"] == "unset"
    assert integrations.get("HUB_URL") == "https://hub.test"


def test_glass_knobs_are_live(client, monkeypatch):
    """ATLAS_EMBED_HOSTS / _SERVICES / _PROBE (v1.38.2): settings first, env
    second; the CSP floor follows a saved hosts value on the NEXT response;
    a header-breaking hosts value and a non-boolean switch are refused."""
    import settings
    monkeypatch.setenv("ATLAS_EMBED_PROBE", "0")
    assert settings.embed_probe() is False and settings.embed_services() is True
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"ATLAS_EMBED_HOSTS": "https://glass.test:8443",
                                       "ATLAS_EMBED_PROBE": "1", "ATLAS_EMBED_SERVICES": "0"}})
    assert r.status_code == 200, r.get_json()
    assert settings.embed_probe() is True and settings.embed_services() is False
    assert settings.embed_hosts() == "https://glass.test:8443"
    # the CSP of the very next response carries it (services off ⇒ the floor)
    csp = client.get("/api/v2/health").headers.get("Content-Security-Policy", "")
    assert "https://glass.test:8443" in csp
    # refusals
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"ATLAS_EMBED_HOSTS": "https://a; default-src *"}})
    assert r.status_code == 422
    r = client.post("/api/v2/admin/integrations", headers=WRITE,
                    json={"settings": {"ATLAS_EMBED_PROBE": "yes"}})
    assert r.status_code == 422


def test_probes_are_rate_limited(client, monkeypatch):
    from api.v2 import admin as adm
    adm._probe_log.clear()
    monkeypatch.setattr(adm, "_probe", lambda kind, url, key: (True, "fine"))
    for _ in range(adm._PROBE_LIMIT):
        r = client.post("/api/v2/admin/integrations/test", headers=WRITE,
                        json={"kind": "loki", "settings": {"ATLAS_LOKI_URL": "http://l:3100"}})
        assert r.status_code == 200
    r = client.post("/api/v2/admin/integrations/test", headers=WRITE,
                    json={"kind": "loki", "settings": {"ATLAS_LOKI_URL": "http://l:3100"}})
    assert r.status_code == 429
    adm._probe_log.clear()
