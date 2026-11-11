"""The `unifi` live source: "connected now" as a health signal, for charted
places nothing else watches.

Every name, MAC and address here is invented. The controller's answers keep the
shape of the two lists the adapter reads (`stat/device`, `stat/sta`).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import signals as S  # noqa: E402

BASE = "https://unifi.example.test"
KEY_CREDS = ["default", "an-api-key", "", ""]          # [site, api key, user, password]

DEVICES = [
    {"mac": "aa:bb:cc:00:00:01", "ip": "10.50.0.2", "state": 1, "name": "core-switch", "type": "usw"},
    {"mac": "aa:bb:cc:00:00:02", "ip": "10.50.0.3", "state": 0, "name": "attic-ap", "type": "uap"},
]
CLIENTS = [
    {"mac": "AA:BB:CC:00:01:01", "ip": "10.50.1.10", "is_wired": True, "name": "workbench"},
    {"mac": "aa:bb:cc:00:01:02", "ip": "10.50.1.20", "is_wired": True},
    {"mac": "aa:bb:cc:00:09:99", "ip": "10.50.9.99", "is_wired": False, "name": "somebody's phone"},
]

DATA = {"nodes": [
    {"id": "core-switch", "kind": "network", "ip": "10.50.0.2", "mac": "aa:bb:cc:00:00:01"},
    {"id": "attic-ap", "kind": "network", "ip": "10.50.0.3", "mac": "AA:BB:CC:00:00:02"},
    {"id": "workbench", "kind": "physical", "ip": "10.50.1.11", "mac": "aa:bb:cc:00:01:01"},
    {"id": "tower", "kind": "physical", "ip": "10.50.1.20"},                 # no MAC yet
    {"id": "laptop", "kind": "physical", "ip": "10.50.1.30", "mac": "aa:bb:cc:00:01:03"},
]}


class Answer:
    def __init__(self, data, status=200):
        self._body, self.status_code, self.headers = {"meta": {"rc": "ok"}, "data": data}, status, {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def controller(monkeypatch):
    """A fake controller behind `requests.get`. Returns the list of paths asked."""
    import requests
    asked = []
    lists = {"devices": DEVICES, "clients": CLIENTS, "fail": False}

    def get(url, **kw):
        assert url.startswith(BASE + "/proxy/network"), "an API key reads under /proxy/network"
        assert kw["headers"]["X-API-KEY"] == "an-api-key"
        path = url[len(BASE + "/proxy/network"):]
        asked.append(path)
        if lists["fail"]:
            raise requests.exceptions.ConnectTimeout("no answer")
        if path == "/api/self/sites":
            return Answer([{"name": "default", "desc": "Default"}])
        if path == "/api/s/default/stat/device":
            return Answer(lists["devices"])
        if path == "/api/s/default/stat/sta":
            return Answer(lists["clients"])
        return Answer([], status=404)

    def post(url, **kw):
        raise AssertionError("an API key never signs in or out")

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    return asked, lists


def _adapter(data=DATA):
    a = S.UniFiAdapter(BASE, KEY_CREDS, verify=True)
    a.set_places(*S.unifi_places(data))
    return a


def test_a_charted_place_matched_by_mac_is_healthy(controller):
    nodes = _adapter().fetch()["nodes"]
    # its address on the map is stale (10.50.1.11); the card is the same card
    assert nodes["workbench"] == {"state": "healthy"}
    assert nodes["core-switch"] == {"state": "healthy"}


def test_a_charted_place_matched_by_ip_is_healthy(controller):
    """The place has no MAC on the map yet: its address is enough."""
    assert _adapter().fetch()["nodes"]["tower"] == {"state": "healthy"}


def test_an_uncharted_client_appears_nowhere(controller):
    feed = _adapter().fetch()
    assert set(feed) == {"nodes"}
    assert set(feed["nodes"]) == {"core-switch", "attic-ap", "workbench", "tower"}
    blob = repr(feed)
    for trace in ("09:99", "10.50.9.99", "phone"):
        assert trace not in blob


def test_an_offline_charted_device_is_down(controller):
    assert _adapter().fetch()["nodes"]["attic-ap"] == {"state": "down"}


def test_an_uncharted_offline_device_is_not_reported(controller):
    _, lists = controller
    lists["devices"] = DEVICES + [{"mac": "aa:bb:cc:00:00:77", "ip": "10.50.0.77", "state": 0}]
    assert "10.50.0.77" not in repr(_adapter().fetch())


def test_a_charted_place_absent_from_the_lists_is_not_in_the_feed(controller):
    """A laptop asleep is unknown, not down."""
    assert "laptop" not in _adapter().fetch()["nodes"]


def test_a_place_with_a_kuma_monitor_is_left_alone(controller):
    data = {"nodes": [
        {"id": "core-switch", "kind": "network", "mac": "aa:bb:cc:00:00:01", "monitors": ["Core switch"]},
        {"id": "attic-ap", "kind": "network", "mac": "aa:bb:cc:00:00:02"},
        {"id": "workbench", "kind": "physical", "mac": "aa:bb:cc:00:01:01",
         "links": [{"label": "Console", "kuma": "Workbench console"}]},
        {"id": "tower", "kind": "physical", "ip": "10.50.1.20"},
    ], "signals": {"kuma": {"Attic AP": "attic-ap"}}}
    by_mac, by_ip, watched = S.unifi_places(data)
    assert watched == {"core-switch", "attic-ap", "workbench"}
    assert _adapter(data).fetch() == {"nodes": {"tower": {"state": "healthy"}}}


def test_a_controller_that_errors_yields_an_empty_feed(controller):
    _, lists = controller
    lists["fail"] = True
    assert _adapter().fetch() == {}


def test_a_refused_credential_yields_an_empty_feed(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda url, **kw: Answer([], status=401))
    assert _adapter().fetch() == {}


def test_the_site_is_looked_up_once_across_two_fetches(controller):
    asked, _ = controller
    a = _adapter()
    first, second = a.fetch(), a.fetch()
    assert first == second and first["nodes"]
    assert asked.count("/api/self/sites") == 1
    assert asked.count("/api/s/default/stat/device") == 2
    assert asked.count("/api/s/default/stat/sta") == 2


def test_nothing_charted_means_the_controller_is_not_asked(controller):
    asked, _ = controller
    assert S.UniFiAdapter(BASE, KEY_CREDS).fetch() == {}
    assert asked == []


def test_a_shared_address_belongs_to_the_machine():
    """Software drawn at its machine's address does not take the machine's signal,
    whichever of the two the dataset lists first."""
    software = {"id": "wiki", "kind": "unknown", "ip": "10.50.1.20"}
    machine = {"id": "tower", "kind": "vm", "ip": "10.50.1.20"}
    for nodes in ([software, machine], [machine, software]):
        assert S.unifi_places({"nodes": nodes})[1] == {"10.50.1.20": "tower"}
    # with no machine there, the first place charted keeps the address
    other = {"id": "notes", "kind": "unknown", "ip": "10.50.1.20"}
    assert S.unifi_places({"nodes": [software, other]})[1] == {"10.50.1.20": "wiki"}


def test_the_shared_address_lights_the_machine_only(controller):
    data = {"nodes": [{"id": "wiki", "kind": "unknown", "ip": "10.50.1.20"},
                      {"id": "tower", "kind": "physical", "ip": "10.50.1.20"}]}
    assert _adapter(data).fetch() == {"nodes": {"tower": {"state": "healthy"}}}


def test_places_without_a_real_address_are_not_mapped():
    by_mac, by_ip, _ = S.unifi_places({"nodes": [
        {"id": "nowhere", "ip": "—"}, {"id": "overlay", "ip": "10.50.64.0/20"},
        {"id": "blank"}, {"id": "card", "mac": " AA:BB:CC:00:02:01 "}]})
    assert by_ip == {} and by_mac == {"aa:bb:cc:00:02:01": "card"}


def test_a_gateway_is_known_by_its_lan_address_not_its_wan_one(controller):
    _, lists = controller
    lists["devices"] = [{"mac": "aa:bb:cc:00:00:09", "type": "udm", "state": 1,
                         "ip": "10.50.200.5", "lan_ip": "10.50.0.1"}]
    lists["clients"] = []
    data = {"nodes": [{"id": "gateway", "kind": "network", "ip": "10.50.0.1"},
                      {"id": "the-world", "kind": "network", "ip": "10.50.200.5"}]}
    assert _adapter(data).fetch() == {"nodes": {"gateway": {"state": "healthy"}}}


def test_the_feed_is_the_shape_the_hub_already_takes(controller):
    feed = _adapter().fetch()
    assert S._coerce_feed(feed) == feed
    for info in feed["nodes"].values():
        assert set(info) == {"state"} and info["state"] in ("healthy", "down")


def test_nothing_about_a_client_is_logged_at_info(controller, caplog):
    import logging
    with caplog.at_level(logging.INFO):
        _adapter().fetch()
    said = " ".join(r.getMessage() for r in caplog.records)
    for trace in ("aa:bb:cc", "10.50.", "workbench", "phone"):
        assert trace not in said.lower()


# ── wiring ──────────────────────────────────────────────────────────────────
def _settings(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("ATLAS_INTEGRATIONS", str(tmp_path / "integrations.json"))
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", "unifi")
    for name in ("ATLAS_UNIFI_URL", "ATLAS_UNIFI_SITE", "ATLAS_UNIFI_API_KEY",
                 "ATLAS_UNIFI_USERNAME", "ATLAS_UNIFI_PASSWORD", "ATLAS_UNIFI_INSECURE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def test_the_source_is_built_from_the_connection(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, ATLAS_UNIFI_URL=BASE + "/", ATLAS_UNIFI_API_KEY="an-api-key",
              ATLAS_UNIFI_INSECURE="1")
    adapters = S.make_adapters()
    assert [a.name for a in adapters] == ["unifi"]
    assert adapters[0].url == BASE and adapters[0].verify is False
    assert adapters[0].creds[1] == "an-api-key"


def test_a_local_user_is_a_credential_too(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, ATLAS_UNIFI_URL=BASE, ATLAS_UNIFI_USERNAME="reader",
              ATLAS_UNIFI_PASSWORD="invented")
    assert [a.name for a in S.make_adapters()] == ["unifi"]


def test_the_source_is_skipped_without_an_address_or_a_credential(monkeypatch, tmp_path):
    _settings(monkeypatch, tmp_path, ATLAS_UNIFI_API_KEY="an-api-key")
    assert S.make_adapters() == []
    _settings(monkeypatch, tmp_path, ATLAS_UNIFI_URL=BASE, ATLAS_UNIFI_USERNAME="reader")
    assert S.make_adapters() == []


def test_unifi_is_a_source_the_settings_accept():
    import integrations
    assert "unifi" in integrations.SOURCES
    assert integrations.SOURCE_NEEDS["unifi"] == "ATLAS_UNIFI_URL"


def test_the_feed_pushes_the_place_maps_from_the_dataset(controller):
    """`api.v2.feeds._apply_kuma_map` is where the adapter learns the map."""
    from types import SimpleNamespace
    from api.v2 import feeds
    adapter = S.UniFiAdapter(BASE, KEY_CREDS)
    ctx = SimpleNamespace(dataset=lambda: (DATA, None, None),
                          signals=SimpleNamespace(adapters=[adapter]))
    feeds._apply_kuma_map(ctx)
    assert adapter.fetch()["nodes"]["tower"] == {"state": "healthy"}


def test_a_device_mid_upgrade_is_not_an_outage(controller):
    _, lists = controller
    lists["devices"] = [{**DEVICES[1], "state": 4}]
    assert "attic-ap" not in _adapter().fetch().get("nodes", {})


def test_an_offline_device_is_down_only_where_its_mac_is_charted(controller):
    """An address may have passed to something else since the device went dark."""
    _, lists = controller
    lists["devices"] = [{"mac": "aa:bb:cc:00:00:66", "ip": "10.50.1.20", "state": 0}]
    lists["clients"] = []
    assert "tower" not in _adapter().fetch().get("nodes", {})
