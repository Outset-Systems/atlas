"""The review step: fetch what a system knows, tick what to add, write through the store.

Every remote answer here is a fake. Proxmox and Portainer are shaped from their API
docs, NetBox from the recorded fixtures test_netbox.py uses, Komodo from komodo_client.
The rules that matter are the refusals: a review writes nothing, a tick only adds,
what lands comes from the system and not the browser, and an ignored thing stays out.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from appfixture import fresh_app, login_as  # noqa: E402

#: Everything else is set per test through monkeypatch, in `realm`.
ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "standalone"}

PW = "correct-horse-battery-staple-9"
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "netbox")
W = {"X-Atlas-Write": "1", "Origin": "http://localhost"}

LAB = {"meta": {"title": "Test Lab", "surveyed": "2026-10-31"},
       "zones": [{"id": "core", "name": "Core", "vlan": 10, "subnet": "10.0.10.0/24", "hue": "#7FB0C4",
                  "lore": "x", "label_x": 20, "label_y": 20}],
       "nodes": [{"id": "alpha", "name": "ALPHA", "kind": "physical", "zone": "core", "ip": "10.0.10.5",
                  "role": "router", "lore": "x", "x": 1, "y": 2,
                  "links": [{"label": "Grafana", "url": "http://10.0.10.5:3000"}]},
                 {"id": "pve1", "name": "PVE1", "kind": "physical", "zone": "core", "ip": "10.0.10.6",
                  "role": "host", "lore": "x", "x": 3, "y": 4, "links": []}],
       "routes": []}

SETTINGS = {
    "proxmox": {"ATLAS_PROXMOX_URL": "https://pve:8006", "ATLAS_PROXMOX_TOKEN": "u@pam!a=topsecret"},
    "portainer": {"ATLAS_PORTAINER_URL": "https://port:9443", "ATLAS_PORTAINER_KEY": "ptr_topsecret"},
    "komodo": {"ATLAS_KOMODO_URL": "https://komodo:9120", "ATLAS_KOMODO_KEY": "K-topsecret",
               "ATLAS_KOMODO_SECRET": "S-topsecret"},
    "netbox": {"ATLAS_NETBOX_URL": "https://netbox", "ATLAS_NETBOX_API_TOKEN": "topsecret"},
}


class Fake:
    def __init__(self, body=None, status=200, headers=None):
        self.body, self.status_code, self.headers = body, status, headers or {}
        self.text = json.dumps(body)

    def json(self):
        if self.body is None:
            raise ValueError("not json")
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(str(self.status_code))


GIB = 1024 ** 3

PROXMOX = {
    "api2/json/cluster/resources": Fake({"data": [
        {"type": "node", "node": "pve1", "id": "node/pve1", "status": "online", "maxcpu": 16, "maxmem": 64 * GIB},
        {"type": "node", "node": "pve2", "id": "node/pve2", "status": "online", "maxcpu": 8, "maxmem": 32 * GIB},
        {"type": "qemu", "vmid": 101, "name": "web", "node": "pve1", "status": "running", "maxcpu": 4, "maxmem": 8 * GIB},
        {"type": "qemu", "vmid": 102, "name": "agentless", "node": "pve1", "status": "running", "maxcpu": 2, "maxmem": 2 * GIB},
        {"type": "qemu", "vmid": 103, "name": "stopped", "node": "pve2", "status": "stopped", "maxcpu": 1, "maxmem": GIB},
        {"type": "qemu", "vmid": 9000, "name": "golden", "node": "pve1", "status": "stopped", "template": 1},
        {"type": "lxc", "vmid": 200, "name": "dns", "node": "pve2", "status": "running", "maxcpu": 1, "maxmem": GIB},
        {"type": "storage", "id": "storage/pve1/local"}]}),
    "api2/json/cluster/status": Fake({"data": [
        {"type": "cluster", "name": "lab"},
        {"type": "node", "name": "pve1", "ip": "10.0.10.6"},
        {"type": "node", "name": "pve2", "ip": "10.0.10.7"}]}),
    "api2/json/nodes/pve1/qemu/101/agent/network-get-interfaces": Fake({"data": {"result": [
        {"name": "lo", "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}]},
        {"name": "docker0", "ip-addresses": [{"ip-address": "172.17.0.1", "ip-address-type": "ipv4"}]},
        {"name": "eth0", "ip-addresses": [{"ip-address": "fe80::1", "ip-address-type": "ipv6"},
                                          {"ip-address": "10.0.10.21", "ip-address-type": "ipv4"}]}]}}),
    "api2/json/nodes/pve1/qemu/102/agent/network-get-interfaces": Fake({"data": None}, status=500),
    "api2/json/nodes/pve2/lxc/200/interfaces": Fake({"data": [
        {"name": "lo", "inet": "127.0.0.1/8"}, {"name": "eth0", "inet": "192.168.9.2/24"}]}),
}

PORTAINER = {
    "api/endpoints": Fake([
        {"Id": 1, "Name": "alpha", "Type": 1, "URL": "unix:///var/run/docker.sock", "Status": 1,
         "Snapshots": [{"DockerVersion": "27.1", "TotalCPU": 8, "TotalMemory": 32 * GIB}]},
        {"Id": 2, "Name": "beta", "Type": 2, "URL": "10.0.10.30:9001", "Status": 1, "Snapshots": []}]),
    "api/stacks": Fake([
        {"Id": 7, "Name": "monitoring", "EndpointId": 1, "Type": 2, "Status": 1},
        {"Id": 8, "Name": "media", "EndpointId": 2, "Type": 2, "Status": 2},
        {"Id": 9, "Name": "lost", "EndpointId": 99, "Type": 2, "Status": 1}]),
}

KOMODO = {
    "ListServers": Fake([
        {"id": "s1", "name": "alpha", "info": {"state": "Ok", "address": "https://10.0.10.5:8120", "version": "2.3.4"}},
        {"id": "s2", "name": "gamma", "info": {"state": "Ok", "address": None, "public_ip": "198.51.100.4",
                                               "logical_core_count": 12, "version": "2.3.4"}}]),
    "ListStacks": Fake([
        {"id": "a1", "name": "loki", "info": {"server_id": "s1", "state": "running", "services": [{}]}},
        {"id": "a2", "name": "traefik", "info": {"server_id": "s2", "state": "running", "services": [{}, {}]}},
        {"id": "a3", "name": "swarmed", "info": {"server_id": "", "swarm_id": "x", "state": "running", "services": []}}]),
}


def _fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def netbox_table():
    return {"api/ipam/vlans/": Fake(_fixture("vlans.json")), "api/ipam/prefixes/": Fake(_fixture("prefixes.json")),
            "api/dcim/devices/": Fake({"results": _fixture("devices-page2.json")["results"], "next": None}),
            "api/virtualization/virtual-machines/": Fake(_fixture("vms.json"))}


@pytest.fixture
def remote(monkeypatch):
    """A fake network. `remote.table` is what each path or Komodo request answers."""
    import requests

    class Remote:
        table, seen = {}, []

    Remote.seen = []

    def go(url, **kw):
        Remote.seen.append((url, kw))
        key = kw["json"]["type"] if "json" in kw else url.split("//", 1)[1].split("/", 1)[1]
        if key not in Remote.table:
            return Fake({"errors": "unknown"}, status=404)
        return Remote.table[key]

    monkeypatch.setattr(requests, "get", go)
    monkeypatch.setattr(requests, "post", go)
    return Remote


@pytest.fixture
def realm(tmp_path, monkeypatch):
    data = tmp_path / "lab-data.json"
    data.write_text(json.dumps(LAB), encoding="utf-8")
    for name, value in {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file",
                        "ATLAS_DATA": str(data), "ATLAS_ACCOUNTS_DB": str(tmp_path / "a.db"),
                        "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
                        "ATLAS_OBSERVED": str(tmp_path / "observed.json"),
                        "ATLAS_REVISIONS": str(tmp_path / "revisions"),
                        "ATLAS_SECRET_KEY": "test-signing-key", "ATLAS_INSECURE_COOKIES": "1",
                        "ATLAS_SIGNALS_SOURCES": "", "ATLAS_AUTH_BACKENDS": "local",
                        "ATLAS_MFA_REQUIRED": "", "ATLAS_ALLOW_INSECURE": "1"}.items():
        monkeypatch.setenv(name, value)
    app = fresh_app()
    import accounts
    accounts.create_local_user("ops", PW, display_name="Ops", is_admin=True)
    accounts.create_local_user("alice", PW, display_name="Alice", is_admin=False)
    realm_ = app
    realm_.data_path = data
    # the limiter is for a burst of probes; these tests are that burst
    from api.v2 import admin as admin_routes
    admin_routes._probe_log.clear()
    monkeypatch.setattr(admin_routes, "_PROBE_LIMIT", 10_000)
    yield realm_
    monkeypatch.undo()
    fresh_app()


@pytest.fixture
def admin(realm):
    c = realm.app.test_client()
    login_as(c, "ops", PW)
    return c


def connect(admin, system):
    r = admin.post("/api/v2/admin/integrations", headers=W, json={"settings": SETTINGS[system]})
    assert r.status_code == 200, r.get_json()


def review(admin, system):
    r = admin.post("/api/v2/admin/connections/review", headers=W, json={"key": system})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["ok"], body
    return body


def rows(body):
    return {r["key"]: r for r in body["rows"]}


def import_(admin, system, picks, body, **extra):
    return admin.post("/api/v2/admin/connections/import", headers=W,
                      json={"key": system, "picks": picks, "expect": body["stamp"], **extra})


def dataset(realm):
    return json.loads(realm.data_path.read_text(encoding="utf-8"))


def node(realm, node_id):
    return next(n for n in dataset(realm)["nodes"] if n["id"] == node_id)


# ── the pure half ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("given,want", [
    ("tcp://10.0.0.5:2375", "10.0.0.5"), ("10.0.0.5:9001", "10.0.0.5"), ("https://10.0.0.5:8120", "10.0.0.5"),
    ("10.0.0.5/24", "10.0.0.5"), ("unix:///var/run/docker.sock", "—"), ("nas.home.example", "—"), ("", "—"), (None, "—"),
])
def test_an_address_is_an_address_or_a_dash(given, want):
    from importers.review import address
    assert address(given) == want


def test_remote_text_loses_its_control_characters_and_its_length():
    from importers.review import clean
    assert clean("a\nb\x00c") == "a b c"
    assert len(clean("x" * 5000)) == 120
    assert clean({"not": "text"}) == "" and clean(None) == ""


def test_the_same_name_at_another_address_is_a_clash_not_a_match():
    from importers import review
    data = {"nodes": [{"id": "alpha", "name": "ALPHA", "ip": "10.0.0.5"}], "zones": []}
    row = review.place("x:1", "Things", "alpha", "vm", "r", ip="10.0.0.9")
    assert review.annotate([row], data)[0]["status"] == review.CLASH
    same = review.place("x:1", "Things", "alpha.home.example", "vm", "r")
    assert review.annotate([same], data)[0]["status"] == review.CHARTED, "no address to disagree with"


def test_a_record_stamped_by_an_earlier_import_is_known_by_its_origin():
    from importers import review
    data = {"nodes": [{"id": "renamed", "name": "RENAMED", "ip": "—", "origin": "x:1"}], "zones": []}
    got = review.annotate([review.place("x:1", "Things", "original", "vm", "r")], data)[0]
    assert (got["status"], got["matched"]) == (review.CHARTED, "renamed")


def test_the_ignore_list_covers_a_row_and_blocks_what_stands_on_it():
    from importers import review
    data = {"nodes": [], "zones": []}
    host = review.place("x:host", "Hosts", "host", "vm", "r")
    stack = review.service("x:stack", "Stacks", "stack", "http://x", "x:host", "a")
    got = {r["key"]: r for r in review.annotate([stack, host], data, {"x:host"})}
    assert got["x:host"]["status"] == review.IGNORED
    assert got["x:stack"]["blocked"] and "ignored" in got["x:stack"]["note"]


# ── each system: preview and tick ────────────────────────────────────────────

def test_proxmox_preview_lists_nodes_and_guests_without_writing(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    before = realm.data_path.read_bytes()
    body = review(admin, "proxmox")
    assert realm.data_path.read_bytes() == before, "a review must not touch the map"
    got = rows(body)
    assert "proxmox:qemu/9000" not in got, "a template is not a guest"
    assert got["proxmox:node/pve1"]["status"] == "charted" and got["proxmox:node/pve1"]["matched"] == "pve1"
    assert got["proxmox:node/pve2"]["status"] == "new" and got["proxmox:node/pve2"]["ip"] == "10.0.10.7"
    assert got["proxmox:qemu/101"]["ip"] == "10.0.10.21", "eth0, not docker0 or loopback"
    assert got["proxmox:qemu/101"]["zone"] == "core"
    assert got["proxmox:qemu/102"]["ip"] == "—"
    assert got["proxmox:lxc/200"]["group"] == "Containers"
    assert any("guest agent" in n for n in body["notes"])
    assert remote.seen[0][1]["headers"]["Authorization"].startswith("PVEAPIToken=")
    assert all(not kw.get("allow_redirects", False) for _u, kw in remote.seen), "a redirect would carry the token"


def test_proxmox_picks_land_as_guests_of_their_host(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    body = review(admin, "proxmox")
    r = import_(admin, "proxmox", ["proxmox:qemu/101", "proxmox:node/pve2", "proxmox:lxc/200", "proxmox:qemu/102"], body)
    assert r.status_code == 200, r.get_json()
    web, dns = node(realm, "web"), node(realm, "dns")
    assert web["kind"] == "vm" and web["zone"] == "core" and web["parent"] == "pve1"
    assert web["origin"] == "proxmox:qemu/101" and web["hw"] == "4 vCPU · 8GB RAM"
    assert dns["parent"] == "pve2", "ticked in the same import as its host"
    assert node(realm, "agentless")["zone"] == "uncharted", "no address names no realm"
    assert any(z["id"] == "uncharted" for z in dataset(realm)["zones"])
    assert [n["id"] for n in dataset(realm)["nodes"]].count("alpha") == 1


def test_portainer_stacks_become_services_on_their_environment(realm, admin, remote):
    connect(admin, "portainer")
    remote.table = PORTAINER
    body = review(admin, "portainer")
    got = rows(body)
    assert got["portainer:env/1"]["status"] == "charted" and got["portainer:env/1"]["matched"] == "alpha"
    assert got["portainer:env/2"]["ip"] == "10.0.10.30"
    assert got["portainer:stack/9"]["blocked"], "its environment is not listed"
    r = import_(admin, "portainer", ["portainer:stack/7", "portainer:stack/8", "portainer:env/2"], body)
    assert r.status_code == 200, r.get_json()
    alpha = node(realm, "alpha")
    assert [l["label"] for l in alpha["links"]] == ["Grafana", "monitoring"], "added beside what was there"
    assert alpha["links"][1]["url"].startswith("https://port:9443/#!/1/docker/stacks/monitoring?id=7")
    assert alpha["links"][1]["open_in"] == "tab"
    assert node(realm, "beta")["links"][0]["label"] == "media"
    assert remote.seen[0][1]["headers"]["X-API-Key"] == "ptr_topsecret"


def test_a_stack_cannot_land_without_its_host(realm, admin, remote):
    connect(admin, "portainer")
    remote.table = PORTAINER
    body = review(admin, "portainer")
    before = realm.data_path.read_bytes()
    r = import_(admin, "portainer", ["portainer:stack/8"], body)
    assert r.status_code == 422 and "beta" in r.get_json()["error"]
    r = import_(admin, "portainer", ["portainer:stack/9"], body)
    assert r.status_code == 422
    assert realm.data_path.read_bytes() == before


def test_a_service_already_on_its_host_is_charted(realm, admin, remote):
    connect(admin, "komodo")
    remote.table = {**KOMODO, "ListStacks": Fake([{"id": "a9", "name": "grafana", "info": {"server_id": "s1"}}])}
    assert rows(review(admin, "komodo"))["komodo:stack/a9"]["status"] == "charted"


def test_komodo_servers_and_stacks(realm, admin, remote):
    connect(admin, "komodo")
    remote.table = KOMODO
    body = review(admin, "komodo")
    got = rows(body)
    assert got["komodo:server/s1"]["status"] == "charted", "matched by its address"
    assert got["komodo:server/s2"]["ip"] == "198.51.100.4", "outbound Periphery has no address"
    assert got["komodo:stack/a3"]["blocked"], "a swarm stack names no server"
    r = import_(admin, "komodo", ["komodo:stack/a1", "komodo:stack/a2", "komodo:server/s2"], body)
    assert r.status_code == 200, r.get_json()
    assert node(realm, "alpha")["links"][-1]["url"] == "https://komodo:9120/stacks/a1"
    gamma = node(realm, "gamma")
    assert gamma["kind"] == "unknown" and gamma["links"][0]["label"] == "traefik"
    url, kw = remote.seen[0]
    assert url == "https://komodo:9120/read" and kw["headers"]["x-api-secret"] == "S-topsecret"


def test_netbox_reads_through_the_importer_and_vlans_become_realms(realm, admin, remote):
    connect(admin, "netbox")
    remote.table = netbox_table()
    body = review(admin, "netbox")
    got = rows(body)
    vlans = [r for r in body["rows"] if r["type"] == "zone"]
    places = [r for r in body["rows"] if r["type"] == "place"]
    assert vlans and places
    assert {"Devices", "Virtual machines"} <= {r["group"] for r in places}
    new_zone = next(r for r in vlans if r["status"] == "new")
    place = places[0]
    r = import_(admin, "netbox", [new_zone["key"], place["key"]], body)
    assert r.status_code == 200, r.get_json()
    zones = {z["id"]: z for z in dataset(realm)["zones"]}
    added = next(z for z in zones.values() if z.get("origin") == new_zone["key"])
    assert added["vlan"] == new_zone["vlan"]
    assert got[place["key"]]["status"] == "new"
    assert remote.seen[0][1]["headers"]["Authorization"] == "Token topsecret"
    assert remote.seen[0][1]["allow_redirects"] is False


def test_the_netbox_mapping_is_the_same_one_the_sync_uses():
    from importers import netbox
    snapshot = {"devices": _fixture("devices-page2.json")["results"], "vms": _fixture("vms.json")["results"],
                "vlans": [], "prefixes": []}
    reading = list(netbox._described(snapshot, netbox.DEFAULT_ROLE_MAP))
    rows_, _ = netbox.candidates(snapshot)
    assert [f"netbox:{d[0]}" for d in reading] == [r["key"] for r in rows_]
    assert [d[2] for d in reading] == [r["kind"] for r in rows_]


def test_a_version_2_netbox_token_is_a_bearer_token(monkeypatch):
    import requests

    from importers.netbox_client import NetBoxClient
    seen = {}

    def go(url, **kw):
        seen.update(kw["headers"])
        return Fake({"results": [], "next": None})

    monkeypatch.setattr(requests, "get", go)
    list(NetBoxClient("https://n", "nbt_abc").paged("/api/dcim/devices/"))
    assert seen["Authorization"] == "Bearer nbt_abc"


def test_a_netbox_next_url_never_sends_the_token_to_another_host(monkeypatch):
    import requests

    from importers.netbox_client import NetBoxClient
    urls = []

    def go(url, **kw):
        urls.append(url)
        if len(urls) == 1:
            return Fake({"results": [{"id": 1}], "next": "http://elsewhere.example/api/x/?limit=200&offset=200"})
        return Fake({"results": [], "next": None})

    monkeypatch.setattr(requests, "get", go)
    assert list(NetBoxClient("https://n", "t").paged("/api/x/")) == [{"id": 1}]
    assert urls[1] == "https://n/api/x/?limit=200&offset=200"


# ── the rules around the import ──────────────────────────────────────────────

def test_an_import_is_one_change_log_entry_and_undo_puts_it_back(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    before = dataset(realm)
    body = review(admin, "proxmox")
    r = import_(admin, "proxmox", ["proxmox:qemu/101", "proxmox:node/pve2"], body)
    result = r.get_json()
    log = admin.get("/api/v2/admin/revisions").get_json()["revisions"]
    assert log[0]["id"] == result["revision"] and log[0]["note"] == "imported from Proxmox VE"
    assert log[0]["actor"] == "ops" and log[0]["revertable"]
    assert len(result["changed"]) == 2
    back = admin.post(f"/api/v2/admin/revisions/{result['revision']}/revert", headers=W,
                      json={"expect": result["stamp"]})
    assert back.status_code == 200, back.get_json()
    assert dataset(realm) == before


def test_undo_refuses_to_take_later_edits_with_it(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    body = review(admin, "proxmox")
    result = import_(admin, "proxmox", ["proxmox:qemu/101"], body).get_json()
    later = admin.post("/api/v2/admin/ops", headers=W, json={"ops": [
        {"op": "upsert", "section": "nodes", "id": "alpha", "body": {"role": "edited since"}}]})
    assert later.status_code == 200
    back = admin.post(f"/api/v2/admin/revisions/{result['revision']}/revert", headers=W,
                      json={"expect": result["stamp"]})
    assert back.status_code == 409
    assert node(realm, "alpha")["role"] == "edited since"


def test_a_map_that_moved_since_the_review_refuses_the_import(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    body = review(admin, "proxmox")
    admin.post("/api/v2/admin/ops", headers=W, json={"ops": [
        {"op": "upsert", "section": "nodes", "id": "alpha", "body": {"role": "moved"}}]})
    assert import_(admin, "proxmox", ["proxmox:qemu/101"], body).status_code == 409


def test_what_lands_comes_from_the_system_not_the_browser(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    body = review(admin, "proxmox")
    r = import_(admin, "proxmox", ["proxmox:qemu/101"], body, rows=[{"key": "proxmox:qemu/101", "name": "evil"}])
    assert r.status_code == 200
    assert node(realm, "web")["name"] == "WEB"
    assert import_(admin, "proxmox", ["proxmox:qemu/666"], review(admin, "proxmox")).status_code == 422


def test_a_guest_that_vanished_since_the_review_says_so(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    body = review(admin, "proxmox")
    remote.table = {**PROXMOX, "api2/json/cluster/resources": Fake({"data": [
        {"type": "node", "node": "pve1", "status": "online"}]})}
    r = import_(admin, "proxmox", ["proxmox:qemu/101"], body)
    assert r.status_code == 422 and "no longer there" in r.get_json()["error"]


def test_what_is_already_on_the_map_cannot_be_ticked_twice(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    body = review(admin, "proxmox")
    assert import_(admin, "proxmox", ["proxmox:qemu/101"], body).status_code == 200
    again = review(admin, "proxmox")
    assert rows(again)["proxmox:qemu/101"]["status"] == "charted"
    assert rows(again)["proxmox:qemu/101"]["matched"] == "web"
    assert import_(admin, "proxmox", ["proxmox:qemu/101"], again).status_code == 422


def test_a_clash_can_be_added_on_purpose_under_its_own_id(realm, admin, remote):
    connect(admin, "portainer")
    remote.table = {"api/endpoints": Fake([{"Id": 3, "Name": "alpha", "Type": 1, "URL": "tcp://10.0.10.77:2375"}]),
                    "api/stacks": Fake([])}
    body = review(admin, "portainer")
    row = rows(body)["portainer:env/3"]
    assert row["status"] == "clash" and "10.0.10.5" in row["note"]
    assert import_(admin, "portainer", ["portainer:env/3"], body).status_code == 200
    assert node(realm, "alpha-2")["ip"] == "10.0.10.77" and node(realm, "alpha")["ip"] == "10.0.10.5"


def test_ignored_things_are_marked_stay_out_and_come_back(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    r = admin.post("/api/v2/admin/discovery/decide", headers=W,
                   json={"keys": ["proxmox:qemu/101"], "action": "ignore"})
    assert r.status_code == 200
    body = review(admin, "proxmox")
    assert rows(body)["proxmox:qemu/101"]["status"] == "ignored"
    assert import_(admin, "proxmox", ["proxmox:qemu/101"], body).status_code == 422
    admin.post("/api/v2/admin/discovery/decide", headers=W,
               json={"keys": ["proxmox:qemu/101"], "action": "unignore"})
    assert rows(review(admin, "proxmox"))["proxmox:qemu/101"]["status"] == "new"


def test_the_realm_for_the_homeless_is_the_admins_choice(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    body = review(admin, "proxmox")
    assert import_(admin, "proxmox", ["proxmox:qemu/102"], body, zone="core").status_code == 200
    assert node(realm, "agentless")["zone"] == "core"
    assert import_(admin, "proxmox", ["proxmox:lxc/200"], review(admin, "proxmox"), zone="nowhere").status_code == 422


def test_hostile_text_from_a_system_is_refused_or_cleaned_not_stored_raw(realm, admin, remote):
    connect(admin, "portainer")
    remote.table = {"api/endpoints": Fake([{"Id": 3, "Name": "<script>\nalert(1)</script>", "Type": 1,
                                            "URL": "not an address"}]),
                    "api/stacks": Fake([])}
    body = review(admin, "portainer")
    row = rows(body)["portainer:env/3"]
    assert "\n" not in row["name"] and row["ip"] == "—"
    assert import_(admin, "portainer", ["portainer:env/3"], body).status_code == 200
    placed = next(n for n in dataset(realm)["nodes"] if n.get("origin") == "portainer:env/3")
    assert "\n" not in placed["name"]


def test_an_import_lands_on_a_map_with_no_realms_at_all(realm, admin, remote):
    data = {**LAB, "zones": [], "nodes": []}
    realm.data_path.write_text(json.dumps(data), encoding="utf-8")
    connect(admin, "komodo")
    remote.table = KOMODO
    body = review(admin, "komodo")
    r = import_(admin, "komodo", ["komodo:server/s1", "komodo:stack/a1"], body)
    assert r.status_code == 200, r.get_json()
    assert [z["id"] for z in dataset(realm)["zones"]] == ["uncharted"]


def test_a_review_needs_an_admin_a_known_system_and_saved_settings(realm, admin, remote):
    c = realm.app.test_client()
    login_as(c, "alice", PW)
    url = "/api/v2/admin/connections/review"
    assert c.post(url, json={"key": "proxmox"}, headers=W).status_code == 403
    assert c.post("/api/v2/admin/connections/import", json={"key": "proxmox", "picks": ["x"]}, headers=W).status_code == 403
    assert admin.post(url, json={"key": "proxmox"}).status_code == 403, "the write header is the CSRF check"
    assert admin.post(url, json={"key": "nope"}, headers=W).status_code == 400
    j = admin.post(url, json={"key": "proxmox"}, headers=W).get_json()
    assert j["ok"] is False and "No URL" in j["error"]
    assert admin.post("/api/v2/admin/connections/import", json={"key": "proxmox", "picks": []}, headers=W).status_code == 400


def test_a_review_never_sends_a_stored_secret_to_a_typed_address(realm, admin, remote):
    connect(admin, "proxmox")
    remote.table = PROXMOX
    admin.post("/api/v2/admin/connections/review", headers=W,
               json={"key": "proxmox", "settings": {"ATLAS_PROXMOX_URL": "https://evil.example"}})
    assert remote.seen and all(url.startswith("https://pve:8006") for url, _kw in remote.seen)


def test_refusal_and_silence_each_say_so(realm, admin, remote):
    connect(admin, "netbox")
    remote.table = {"api/ipam/vlans/": Fake({"detail": "no"}, status=403)}
    j = admin.post("/api/v2/admin/connections/review", json={"key": "netbox"}, headers=W).get_json()
    assert j == {"ok": False, "error": "NetBox refused the credential."}
    remote.table = {"api/ipam/vlans/": Fake(status=302, headers={"Location": "http://elsewhere"})}
    j = admin.post("/api/v2/admin/connections/review", json={"key": "netbox"}, headers=W).get_json()
    assert not j["ok"] and "final URL" in j["error"]


def test_no_credential_ever_comes_back_from_a_review(realm, admin, remote):
    connect(admin, "komodo")
    remote.table = KOMODO
    r = admin.post("/api/v2/admin/connections/review", headers=W, json={"key": "komodo"})
    assert "topsecret" not in r.get_data(as_text=True)


def test_the_db_backend_keeps_the_origin_through_its_round_trip():
    from store import dump_labdata, init_db, load_labdata, session_scope
    init_db()
    data = {**LAB, "nodes": [{**LAB["nodes"][0], "origin": "proxmox:qemu/101"}]}
    with session_scope() as s:
        load_labdata(s, data, site_slug="review-origin")
    with session_scope() as s:
        assert dump_labdata(s, "review-origin")["nodes"][0]["origin"] == "proxmox:qemu/101"
