"""UniFi and Uptime Kuma, the pair: UniFi says what exists and how it is wired, Kuma
says whether it is up, and both land on the same places.

Every answer here is a fake, shaped from the UniFi Network Application's recorded
answers (stat/device, stat/sta, rest/networkconf, self/sites) and from Kuma's own
/metrics text. The last section keeps the shape one real console answered with
(2026-11-10), under invented names and addresses. The refusals are the point, as in test_connection_review.py: a review
writes nothing, what lands comes from the system, a link needs both its ends, and
no credential ever comes back to the browser.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_connection_review import (PW, W, Fake, admin, dataset, import_, node, realm,  # noqa: E402,F401
                                    review, rows)

UNIFI_KEY = {"ATLAS_UNIFI_URL": "https://unifi:443", "ATLAS_UNIFI_API_KEY": "uk-topsecret"}
UNIFI_USER = {"ATLAS_UNIFI_URL": "https://unifi:8443", "ATLAS_UNIFI_USERNAME": "atlas-viewer",
              "ATLAS_UNIFI_PASSWORD": "pw-topsecret"}
KUMA = {"ATLAS_KUMA_URL": "http://kuma:3001", "ATLAS_KUMA_API_KEY": "kk-topsecret"}

SW, AP, GW = "aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02", "aa:bb:cc:00:00:03"
NAS, PHONE = "de:ad:be:ef:00:01", "de:ad:be:ef:00:02"


def _ok(data):
    return Fake({"meta": {"rc": "ok"}, "data": data})


DEVICES = _ok([
    {"mac": GW, "type": "udm", "name": "Edge Router", "model": "UDMPRO", "ip": "10.0.10.1",
     "version": "4.1.13", "state": 1, "port_table": []},
    {"mac": SW, "type": "usw", "name": "Core Switch", "model_name": "USW Pro 24", "ip": "10.0.10.2",
     "version": "7.1.26", "state": 1,
     "uplink": {"uplink_mac": GW, "port_idx": 24, "uplink_remote_port": 9, "type": "wire"},
     "lldp_table": [{"chassis_id": GW, "local_port_idx": 24}],
     "port_table": [
         {"port_idx": 1, "name": "Port 1", "up": True, "speed": 1000, "media": "GE", "port_poe": True,
          "native_networkconf_id": "net-core"},
         {"port_idx": 2, "name": "Port 2", "up": False, "speed": 0, "media": "GE"},
         {"port_idx": 25, "name": "SFP+ 1", "up": True, "speed": 10000, "media": "SFP+"}]},
    {"mac": AP, "type": "uap", "name": "Hall AP", "model": "U7PG2", "ip": "10.0.10.3", "state": 1,
     "uplink": {"uplink_mac": SW, "port_idx": 1, "uplink_remote_port": 1, "type": "wire"},
     "port_table": []},
])
CLIENTS = _ok([
    {"mac": NAS, "ip": "10.0.10.40", "hostname": "nas", "oui": "Synology", "is_wired": True,
     "sw_mac": SW, "sw_port": 1},
    {"mac": PHONE, "ip": "10.0.20.77", "name": "Pixel", "oui": "Google", "is_wired": False,
     "ap_mac": AP, "essid": "home"},
    {"mac": SW, "ip": "10.0.10.2", "is_wired": True},            # a device seen as a client too
])
NETWORKS = _ok([
    {"_id": "net-core", "name": "Core", "purpose": "corporate", "vlan_enabled": False,
     "ip_subnet": "10.0.10.1/24"},
    {"_id": "net-iot", "name": "IoT", "purpose": "corporate", "vlan_enabled": True, "vlan": 66,
     "ip_subnet": "10.0.66.1/24"},
    {"_id": "net-wan", "name": "Internet", "purpose": "wan"},
])
SITES = _ok([{"name": "default", "desc": "Default"}, {"name": "x7k2", "desc": "Cabin"}])

KUMA_METRICS = "\n".join([
    "# HELP monitor_status Monitor Status (1 = UP, 0= DOWN, 2= PENDING, 3= MAINTENANCE)",
    'monitor_status{monitor_name="Core switch ping",monitor_type="ping",monitor_url="https://",'
    'monitor_hostname="10.0.10.2",monitor_port="null"} 1',
    'monitor_status{monitor_name="NAS web",monitor_type="http",monitor_url="https://nas.home.example:5001",'
    'monitor_hostname="null",monitor_port="null"} 0',
    'monitor_status{monitor_name="Alpha",monitor_type="ping",monitor_url="https://",'
    'monitor_hostname="10.0.10.5",monitor_port="null"} 1',
    'monitor_status{monitor_name="Somewhere else",monitor_type="http",monitor_url="https://elsewhere.example",'
    'monitor_hostname="null",monitor_port="null"} 1',
    'monitor_response_time{monitor_name="Alpha",monitor_type="ping"} 3',
])


class Answer(Fake):
    def __init__(self, body=None, status=200, headers=None, cookies=None, text=None):
        super().__init__(body, status, headers)
        self.cookies = cookies or {}
        if text is not None:
            self.text = text


@pytest.fixture
def net(monkeypatch):
    """A fake UniFi controller and a fake Kuma. `net.os` picks UniFi OS (login at
    /api/auth/login, reads under /proxy/network) or the older Network Application."""
    import requests

    class Net:
        os, seen = True, []

    def answer(url, method, kw):
        Net.seen.append((method, url, kw))
        path = "/" + url.split("//", 1)[1].split("/", 1)[1]
        if path == "/metrics":
            return Answer(text=KUMA_METRICS)
        if path in ("/api/auth/login", "/api/auth/logout"):
            if not Net.os:
                return Answer({"error": "not found"}, status=404)
            if path.endswith("login"):
                return Answer({"ok": True}, cookies={"TOKEN": "session-token"},
                              headers={"X-CSRF-Token": "csrf-1"})
            return Answer({})
        if path in ("/api/login", "/api/logout"):
            return Answer({"meta": {"rc": "ok"}}, cookies={"unifi_ses": "legacy-session"})
        prefix = "/proxy/network" if Net.os else ""
        if not path.startswith(prefix):
            return Answer({"error": "not found"}, status=404)
        table = {"/api/self/sites": SITES, "/api/s/default/stat/device": DEVICES,
                 "/api/s/default/stat/sta": CLIENTS, "/api/s/default/rest/networkconf": NETWORKS}
        return table.get(path[len(prefix):], Answer({"meta": {"rc": "error", "msg": "api.err.NoSiteContext"}}))

    monkeypatch.setattr(requests, "get", lambda url, **kw: answer(url, "GET", kw))
    monkeypatch.setattr(requests, "post", lambda url, **kw: answer(url, "POST", kw))
    return Net


def save(admin, settings):
    r = admin.post("/api/v2/admin/integrations", headers=W, json={"settings": settings})
    assert r.status_code == 200, r.get_json()


def unifi_review(admin):
    return review(admin, "unifi")


# ── reading ──────────────────────────────────────────────────────────────────

def test_an_api_key_reads_under_proxy_network_and_writes_nothing(realm, admin, net):
    save(admin, UNIFI_KEY)
    before = realm.data_path.read_text(encoding="utf-8")
    body = unifi_review(admin)
    assert realm.data_path.read_text(encoding="utf-8") == before
    by = rows(body)
    sw = by[f"unifi:device/{SW}"]
    assert (sw["group"], sw["kind"], sw["ip"]) == ("Switches", "network", "10.0.10.2")
    assert "USW Pro 24" in sw["hw"] and "3 ports" in sw["hw"]
    assert by[f"unifi:device/{GW}"]["group"] == "Gateways"
    assert by[f"unifi:device/{AP}"]["group"] == "Access points"
    assert by[f"unifi:client/{NAS}"]["group"] == "Wired clients"
    assert "port 1 of Core Switch" in by[f"unifi:client/{NAS}"]["detail"]
    assert by[f"unifi:client/{PHONE}"]["group"] == "Wireless clients"
    assert f"unifi:client/{SW}" not in by, "a device listed as a client is still one thing"
    gets = [(m, u, kw) for m, u, kw in net.seen if m == "GET"]
    assert gets and all("/proxy/network/api/s/default/" in u or u.endswith("/proxy/network/api/self/sites")
                        for _, u, _ in gets)
    assert all(kw["headers"]["X-API-KEY"] == "uk-topsecret" for _, _, kw in gets)
    assert all(kw.get("allow_redirects") is False for _, _, kw in net.seen)
    assert not [u for m, u, _ in net.seen if m == "POST"], "an API key needs no login"


def test_networks_become_realms_and_the_wan_does_not(realm, admin, net):
    save(admin, UNIFI_KEY)
    by = rows(unifi_review(admin))
    iot = by["unifi:network/net-iot"]
    assert (iot["type"], iot["vlan"], iot["subnet"]) == ("zone", 66, "10.0.66.0/24")
    assert by["unifi:network/net-core"]["vlan"] == 1, "an untagged LAN is VLAN 1"
    assert by["unifi:network/net-core"]["status"] == "charted", "the map's Core realm already is it"
    assert "unifi:network/net-wan" not in by


def test_ports_and_links_are_listed_once_each(realm, admin, net):
    save(admin, UNIFI_KEY)
    by = rows(unifi_review(admin))
    p1, p2, sfp = (by[f"unifi:port/{SW}/{i}"] for i in (1, 2, 25))
    assert (p1["type"], p1["speed"], p1["poe"], p1["vlan"]) == ("port", "1G", True, 1)
    assert p2["speed"] == "" and "down" in p2["detail"]
    assert (sfp["kind"], sfp["speed"]) == ("sfp+", "10G")
    links = [r for r in by.values() if r["type"] == "route"]
    pairs = {frozenset((r["parent"], r["peer"])) for r in links}
    assert len(links) == len(pairs) == 4, "uplink and LLDP name the same wire once"
    assert frozenset((f"unifi:device/{SW}", f"unifi:device/{GW}")) in pairs
    assert frozenset((f"unifi:client/{PHONE}", f"unifi:device/{AP}")) in pairs


def test_a_local_user_signs_in_once_reads_and_signs_out(realm, admin, net):
    save(admin, UNIFI_USER)
    unifi_review(admin)
    posts = [u for m, u, _ in net.seen if m == "POST"]
    assert posts == ["https://unifi:8443/api/auth/login", "https://unifi:8443/api/auth/logout"]
    login = next(kw for m, u, kw in net.seen if u.endswith("/api/auth/login"))
    assert login["json"] == {"username": "atlas-viewer", "password": "pw-topsecret"}
    gets = [kw for m, u, kw in net.seen if m == "GET"]
    assert all(kw["cookies"] == {"TOKEN": "session-token"} for kw in gets)
    assert all("X-API-KEY" not in kw["headers"] for kw in gets)


def test_an_older_controller_is_found_by_its_own_sign_in(realm, admin, net):
    net.os = False
    save(admin, UNIFI_USER)
    body = unifi_review(admin)
    assert f"unifi:device/{SW}" in rows(body)
    posts = [u for m, u, _ in net.seen if m == "POST"]
    assert posts == ["https://unifi:8443/api/auth/login", "https://unifi:8443/api/login",
                     "https://unifi:8443/api/logout"]
    assert all("/proxy/network" not in u for m, u, _ in net.seen if m == "GET")


def test_the_test_names_the_site_and_says_when_it_is_wrong(realm, admin, net):
    save(admin, UNIFI_KEY)
    j = admin.post("/api/v2/admin/connections/test", headers=W, json={"key": "unifi"}).get_json()
    assert j["ok"] and j["detail"] == "UniFi site default: 3 devices, 3 clients connected"
    save(admin, {"ATLAS_UNIFI_SITE": "cabin"})
    j = admin.post("/api/v2/admin/connections/test", headers=W, json={"key": "unifi"}).get_json()
    assert not j["ok"] and "no site called cabin" in j["error"] and "x7k2 (Cabin)" in j["error"]


def test_a_site_is_a_name_never_a_path(realm, admin, net):
    r = admin.post("/api/v2/admin/integrations", headers=W,
                   json={"settings": {"ATLAS_UNIFI_SITE": "default/../../api/x"}})
    assert r.status_code == 422
    from importers import unifi
    with pytest.raises(ValueError):
        unifi.site_path("a/b")


def test_either_credential_is_enough_and_neither_is_not(realm, admin, net):
    save(admin, {"ATLAS_UNIFI_URL": "https://unifi:443", "ATLAS_UNIFI_USERNAME": "atlas-viewer"})
    j = admin.post("/api/v2/admin/connections/review", headers=W, json={"key": "unifi"}).get_json()
    assert j == {"ok": False, "error": "No credential to ask with."}
    assert not net.seen


def test_a_refused_sign_in_says_why(realm, admin, monkeypatch):
    import requests
    monkeypatch.setattr(requests, "post", lambda url, **kw: Answer({"meta": {"rc": "error"}}, status=401))
    save(admin, UNIFI_USER)
    j = admin.post("/api/v2/admin/connections/review", headers=W, json={"key": "unifi"}).get_json()
    assert not j["ok"] and "MFA" in j["error"]


# ── landing ──────────────────────────────────────────────────────────────────

def test_a_switch_its_port_and_its_link_land_together(realm, admin, net):
    save(admin, UNIFI_KEY)
    body = unifi_review(admin)
    picks = [f"unifi:device/{SW}", f"unifi:device/{GW}", f"unifi:port/{SW}/25",
             next(r["key"] for r in body["rows"] if r["type"] == "route"
                  and {r["parent"], r["peer"]} == {f"unifi:device/{SW}", f"unifi:device/{GW}"})]
    r = import_(admin, "unifi", picks, body)
    assert r.status_code == 200, r.get_json()
    data = dataset(realm)
    sw = next(n for n in data["nodes"] if n.get("origin") == f"unifi:device/{SW}")
    gw = next(n for n in data["nodes"] if n.get("origin") == f"unifi:device/{GW}")
    assert sw["kind"] == "network" and sw["zone"] == "core"
    assert {"from": sw["id"], "to": gw["id"], "kind": "vlan"} in data["routes"] \
        or {"from": gw["id"], "to": sw["id"], "kind": "vlan"} in data["routes"]
    assert {"device": sw["id"], "name": "25", "kind": "sfp+", "speed": "10G",
            "note": "from UniFi Network"} in data["interfaces"]
    again = rows(unifi_review(admin))
    assert again[f"unifi:port/{SW}/25"]["status"] == "charted"
    assert [r for r in again.values() if r["type"] == "route" and r["status"] == "charted"]


def test_a_link_cannot_land_without_both_ends(realm, admin, net):
    save(admin, UNIFI_KEY)
    body = unifi_review(admin)
    link = next(r for r in body["rows"] if r["type"] == "route"
                and {r["parent"], r["peer"]} == {f"unifi:device/{SW}", f"unifi:device/{GW}"})
    r = import_(admin, "unifi", [link["key"], f"unifi:device/{SW}"], body)
    assert r.status_code == 422 and "Edge Router" in r.get_json()["error"]
    r = import_(admin, "unifi", [f"unifi:port/{SW}/1"], body)
    assert r.status_code == 422, "a port needs its switch"


def test_ignoring_a_device_blocks_its_ports_and_links(realm, admin, net):
    save(admin, UNIFI_KEY)
    admin.post("/api/v2/admin/discovery/decide", headers=W,
               json={"keys": [f"unifi:device/{GW}"], "action": "ignore"})
    by = rows(unifi_review(admin))
    link = next(r for r in by.values() if r["type"] == "route"
                and {r["parent"], r["peer"]} == {f"unifi:device/{SW}", f"unifi:device/{GW}"})
    assert link["blocked"] and "ignored" in link["note"]


# ── Kuma ─────────────────────────────────────────────────────────────────────

def test_kuma_metrics_are_read_label_by_label():
    from importers import kuma
    got = {m["name"]: m for m in kuma.parse_metrics(KUMA_METRICS)}
    assert list(got) == ["Core switch ping", "NAS web", "Alpha", "Somewhere else"]
    assert got["Core switch ping"]["host"] == "10.0.10.2" and got["Core switch ping"]["state"] == 1
    assert got["NAS web"]["host"] == "nas.home.example" and got["NAS web"]["state"] == 0


def test_kuma_review_ties_monitors_to_places_on_the_map(realm, admin, net):
    save(admin, KUMA)
    body = review(admin, "kuma")
    by = rows(body)
    alpha = by["kuma:monitor/Alpha"]
    assert alpha["status"] == "new" and alpha["place"] == "alpha" and "ALPHA" in alpha["note"]
    assert by["kuma:monitor/Somewhere else"]["blocked"]
    assert by["kuma:monitor/Core switch ping"]["blocked"], "no switch on the map yet"
    r = import_(admin, "kuma", ["kuma:monitor/Alpha"], body)
    assert r.status_code == 200, r.get_json()
    assert node(realm, "alpha")["monitors"] == ["Alpha"]
    assert rows(review(admin, "kuma"))["kuma:monitor/Alpha"]["status"] == "charted"


def test_the_pair_a_unifi_place_brings_its_kuma_monitor(realm, admin, net):
    save(admin, {**UNIFI_KEY, **KUMA})
    body = unifi_review(admin)
    sw = rows(body)[f"unifi:device/{SW}"]
    assert sw["monitors"] == ["Core switch ping"] and "Kuma: Core switch ping" in sw["detail"]
    nas = rows(body)[f"unifi:client/{NAS}"]
    assert nas["monitors"] == ["NAS web"], "matched by the monitor's host name"
    assert any("Kuma watches 2 of these places" in n for n in body["notes"])
    assert import_(admin, "unifi", [f"unifi:device/{SW}"], body).status_code == 200
    placed = next(n for n in dataset(realm)["nodes"] if n.get("origin") == f"unifi:device/{SW}")
    assert placed["monitors"] == ["Core switch ping"]
    # and the live layer lights that marker from it
    import signals
    assert signals.monitor_map(dataset(realm))["Core switch ping"] == placed["id"]
    assert rows(review(admin, "kuma"))["kuma:monitor/Core switch ping"]["status"] == "charted"


def test_a_silent_kuma_never_stops_a_unifi_review(realm, admin, net, monkeypatch):
    import requests
    real_get = requests.get

    def get(url, **kw):
        if url.endswith("/metrics"):
            raise requests.exceptions.ConnectTimeout("no")
        return real_get(url, **kw)
    monkeypatch.setattr(requests, "get", get)
    save(admin, {**UNIFI_KEY, **KUMA})
    body = unifi_review(admin)
    assert f"unifi:device/{SW}" in rows(body)
    assert any("no monitors come with this review" in n for n in body["notes"])


def test_a_hand_kept_kuma_line_wins_over_a_places_own(realm):
    import signals
    data = {"nodes": [{"id": "a", "monitors": ["M"]}, {"id": "b"}], "signals": {"kuma": {"M": "b"}}}
    assert signals.monitor_map(data) == {"M": "b"}


def test_a_hidden_places_monitors_are_not_a_viewers(realm):
    import redaction
    data = {"nodes": [{"id": "a", "monitors": ["Seen"]},
                      {"id": "b", "require_group": "ops", "monitors": ["Secret"]}]}
    assert redaction.visible_monitors(data, []) == {"Seen"}


# ── secrets ──────────────────────────────────────────────────────────────────

def test_no_unifi_or_kuma_credential_ever_comes_back(realm, admin, net):
    save(admin, {**UNIFI_USER, "ATLAS_UNIFI_API_KEY": "uk-topsecret", **KUMA})
    answers = [admin.get("/api/v2/admin/connections"),
               admin.get("/api/v2/admin/integrations"),
               admin.post("/api/v2/admin/connections/review", headers=W, json={"key": "unifi"}),
               admin.post("/api/v2/admin/connections/review", headers=W, json={"key": "kuma"}),
               admin.post("/api/v2/admin/connections/test", headers=W, json={"key": "unifi"}),
               admin.post("/api/v2/admin/connections/test", headers=W, json={"key": "kuma"})]
    for r in answers:
        text = r.get_data(as_text=True)
        assert "topsecret" not in text and "session-token" not in text, r.request.path
        assert "atlas-viewer" not in text, "a user name is half a credential"
    stored = json.dumps(json.loads(open(os.environ["ATLAS_INTEGRATIONS"], encoding="utf-8").read()))
    assert "topsecret" not in stored and "atlas-viewer" not in stored, "all of it encrypted at rest"


def test_a_stored_unifi_password_never_goes_to_a_typed_address(realm, admin, net):
    save(admin, UNIFI_USER)
    r = admin.post("/api/v2/admin/connections/test", headers=W,
                   json={"key": "unifi", "settings": {"ATLAS_UNIFI_URL": "https://evil.example"}})
    assert r.status_code == 400
    assert not [u for _, u, _ in net.seen if "evil" in u]


# ── what a real console taught ───────────────────────────────────────────────
# The shape of a UDM Pro SE's answers on Network 10.6. Every name, MAC and address
# is invented; 203.0.113.0/24 is the documentation range, standing for a WAN address.
R_GW, R_PDU = "aa:bb:cc:10:00:01", "aa:bb:cc:10:00:02"
R_HOST, R_NAS = "f4:4d:30:00:00:10", "00:11:32:00:00:20"
R_VM1, R_VM2 = "00:15:5d:00:00:31", "00:15:5d:00:00:32"
REAL = {
    "devices": [
        {"mac": R_GW, "type": "udm", "model": "UDMPROSE", "name": "Front Door", "ip": "203.0.113.7",
         "lan_ip": "10.50.1.1", "version": "6.0.17", "state": 1,
         "network_table": [{"name": "Home", "ip": "10.50.1.1"}, {"name": "Servers", "ip": "10.50.40.1"}],
         "lldp_table": [{"chassis_id": R_PDU, "local_port_idx": 7}],
         "port_table": [{"port_idx": 6, "name": "Host", "up": True, "speed": 1000, "media": "GE"}]},
        {"mac": R_PDU, "type": "usw", "model": "USPPDUP", "name": "Power Strip", "ip": "10.50.66.41",
         "version": "7.2.123", "state": 1, "outlet_ac_power_consumption": "333.330",
         "uplink": {"uplink_mac": R_GW, "type": "wire"},
         "port_table": [{"port_idx": 1, "name": "Uplink", "up": True, "speed": 100, "media": "GE"}],
         "outlet_table": [{"index": 1, "name": "Host", "relay_state": True, "outlet_power": "42.0"},
                          {"index": 2, "name": "Fan", "relay_state": True, "outlet_power": "98.6"},
                          {"index": 3, "name": "Outlet 3", "relay_state": False, "outlet_power": "0.000"}]},
    ],
    "clients": [
        {"mac": R_HOST, "ip": "10.50.40.6", "name": "Big Iron", "is_wired": True, "sw_mac": R_GW, "sw_port": 6},
        {"mac": R_VM1, "ip": "10.50.90.36", "name": "Old Name", "oui": "Microsoft Corporation",
         "is_wired": True, "sw_mac": R_GW, "sw_port": 6},
        {"mac": R_VM2, "ip": "10.50.40.21", "oui": "Microsoft Corporation", "is_wired": True,
         "sw_mac": R_GW, "sw_port": 6},
        {"mac": R_NAS, "ip": "10.50.40.15", "name": "Vault", "oui": "Synology", "is_wired": True,
         "sw_mac": R_GW, "sw_port": 8},
    ],
    "networks": [
        {"_id": "n-wan", "name": "Internet 1", "purpose": "wan"},
        {"_id": "n-home", "name": "Home", "purpose": "corporate", "ip_subnet": "10.50.1.1/24"},
        {"_id": "n-srv", "name": "Servers", "purpose": "corporate", "vlan_enabled": True, "vlan": 4,
         "ip_subnet": "10.50.40.1/24"},
        # the controller and the map disagree about which of these two is called what
        {"_id": "n-9", "name": "Edge", "purpose": "guest", "vlan_enabled": True, "vlan": 9,
         "ip_subnet": "10.50.9.1/24"},
        {"_id": "n-90", "name": "Guests", "purpose": "corporate", "vlan_enabled": True, "vlan": 90,
         "ip_subnet": "10.50.90.1/24"},
    ],
}
REAL_MAP = {
    "zones": [{"id": "servers", "name": "Servers", "vlan": 4, "subnet": "10.50.40.0/24"},
              {"id": "guests", "name": "Guests", "vlan": 9, "subnet": "10.50.9.0/24"},
              {"id": "edge", "name": "Edge", "vlan": 90, "subnet": "10.50.90.0/24"}],
    "nodes": [
        {"id": "front-door", "name": "FRONT-DOOR", "ip": "10.50.40.1", "kind": "network"},
        {"id": "big-iron", "name": "BIG IRON", "ip": "10.50.40.6", "kind": "physical"},
        # one machine, and two pieces of software on it drawn at the same address
        {"id": "edge-host", "name": "EDGE-HOST", "ip": "10.50.90.36", "kind": "vm", "parent": "big-iron"},
        {"id": "proxy", "name": "PROXY", "ip": "10.50.90.36", "kind": "network"},
        {"id": "tunnel", "name": "TUNNEL", "ip": "10.50.90.36", "kind": "network"},
    ],
    "routes": [{"from": "front-door", "to": "big-iron", "kind": "vlan"}],
}


def _real_rows():
    from importers import review as rv
    from importers import unifi
    cands, _notes = unifi.candidates(REAL)
    return {r["key"]: r for r in rv.annotate(cands, REAL_MAP)}


def test_a_gateway_is_charted_at_a_lan_address_never_its_wan_one():
    got = _real_rows()
    gw = got[f"unifi:device/{R_GW}"]
    assert gw["ip"] == "10.50.1.1" and "10.50.40.1" in gw["also"]
    assert (gw["status"], gw["matched"]) == ("charted", "front-door")     # known by another of its addresses
    assert "203.0.113.7" not in json.dumps(list(got.values()))


def test_a_gateway_with_no_network_list_keeps_the_address_it_gave():
    from importers import unifi
    rows, _ = unifi.candidates({"devices": [{"mac": R_GW, "type": "udm", "name": "Edge", "ip": "10.0.10.1"}]})
    assert rows[0]["ip"] == "10.0.10.1" and "also" not in rows[0]


def test_a_network_is_matched_by_its_vlan_before_its_name():
    got = _real_rows()
    nine, ninety = got["unifi:network/n-9"], got["unifi:network/n-90"]
    assert (nine["matched"], ninety["matched"]) == ("guests", "edge")
    assert "calls this realm Guests" in nine["note"] and "calls this realm Edge" in ninety["note"]
    assert got["unifi:network/n-srv"]["note"] == ""


def test_two_networks_with_no_vlan_are_not_one_network():
    from importers import review as rv
    chart = rv._Map({"zones": [{"id": "old", "name": "Old"}]})
    assert chart.find_zone({"key": "k", "name": "New", "vlan": None}) is None


def test_a_power_strip_is_not_a_switch():
    pdu = _real_rows()[f"unifi:device/{R_PDU}"]
    assert pdu["group"] == "Power" and pdu["role"].startswith("Power distribution")
    assert "3 outlets" in pdu["hw"] and " W" not in pdu["hw"]           # a reading is not kept
    assert "2 on · 333 W" in pdu["detail"]


def test_a_hypervisors_guests_hang_off_it_and_bring_no_road_of_their_own():
    got = _real_rows()
    vm1, vm2, host = (got[f"unifi:client/{m}"] for m in (R_VM1, R_VM2, R_HOST))
    assert vm1["parent"] == vm2["parent"] == f"unifi:client/{R_HOST}" and vm1["kind"] == "vm"
    assert host["parent"] is None and host["kind"] == "unknown"
    roads = [r for r in got.values() if r["type"] == "route"]
    assert not any(m in r["key"] for r in roads for m in (R_VM1, R_VM2))
    # the host's own cable is the road, and the map already has it
    assert got[f"unifi:link/client/{R_HOST}~device/{R_GW}"]["status"] == "charted"
    # a lone client on a port is nobody's guest, whatever its MAC
    assert got[f"unifi:client/{R_NAS}"]["parent"] is None


def test_of_several_places_at_one_address_a_client_is_the_machine():
    assert _real_rows()[f"unifi:client/{R_VM1}"]["matched"] == "edge-host"


def test_a_monitor_at_a_shared_address_lights_what_it_always_did():
    from importers import review as rv
    chart = rv._Map(REAL_MAP)
    assert chart.watched_by({"host": "10.50.90.36", "name": "x"})["id"] == "tunnel"


def test_a_wrong_site_on_a_one_site_controller_reads_that_site_and_says_so(realm, admin, net, monkeypatch):
    monkeypatch.setitem(globals(), "SITES", _ok([{"name": "default", "desc": "Default"}]))
    save(admin, {**UNIFI_KEY, "ATLAS_UNIFI_SITE": "Homelab"})
    j = admin.post("/api/v2/admin/connections/test", headers=W, json={"key": "unifi"}).get_json()
    assert j["ok"] and j["detail"].startswith("UniFi site default: 3 devices")
    assert "no site called Homelab" in j["detail"]
    told = unifi_review(admin)
    assert any("no site called Homelab" in n for n in told["notes"]) and told["rows"]
    assert not any("Homelab" in url for _, url, _ in net.seen)          # the typed word never met a path


def test_a_pro_max_switch_is_still_a_switch():
    from importers import unifi
    rows, _ = unifi.candidates({"devices": [{"mac": R_GW, "type": "usw", "model": "USPM16", "name": "Max",
                                             "ip": "10.0.10.2"}]})
    assert rows[0]["group"] == "Switches"


def test_clients_with_no_port_reported_are_nobodys_guests():
    from importers import unifi
    snap = {"devices": [{"mac": R_GW, "type": "udm", "name": "Edge", "ip": "10.0.10.1"}],
            "clients": [{"mac": R_HOST, "ip": "10.0.10.6", "is_wired": True, "sw_mac": R_GW},
                        {"mac": R_VM1, "ip": "10.0.10.7", "is_wired": True, "sw_mac": R_GW}]}
    rows, _ = unifi.candidates(snap)
    assert all(r.get("parent") is None for r in rows if r["type"] == "place")


# ── what UniFi adds to a map that already has the place ──────────────────────
def _facts(data=None):
    from importers import review as rv
    from importers import unifi
    cands, _notes = unifi.candidates(REAL)
    rows = rv.annotate(cands, data or REAL_MAP)
    return rows, {r["key"]: r for r in rows}


def test_a_charted_place_is_offered_its_mac_and_a_new_one_carries_its_own():
    rows, got = _facts()
    fact = got[f"unifi:fact/device/{R_GW}"]
    assert (fact["type"], fact["status"], fact["adds"]) == ("fact", "new", {"mac": R_GW})
    assert got[f"unifi:client/{R_NAS}"]["mac"] == R_NAS                   # new: the place row has it
    assert f"unifi:fact/client/{R_NAS}" not in got                        # and no second row says so


def test_a_fact_never_overwrites_what_a_person_wrote():
    data = json.loads(json.dumps(REAL_MAP))
    data["nodes"][0].update(hw="hand-written", mac="aa:aa:aa:aa:aa:aa")
    _, got = _facts(data)
    assert got[f"unifi:fact/device/{R_GW}"]["status"] == "charted"       # nothing left to add
    data["nodes"][0].update(origin=f"unifi:device/{R_GW}", mac="")
    _, got = _facts(data)
    adds = got[f"unifi:fact/device/{R_GW}"]["adds"]
    assert adds["mac"] == R_GW and adds["hw"].startswith("UDMPROSE")      # its own import: UniFi's line


def test_ticked_facts_land_as_edits_to_the_places_and_ports_already_there():
    from importers import review as rv
    data = json.loads(json.dumps(REAL_MAP))
    data["interfaces"] = [{"device": "front-door", "name": "6", "kind": "rj45", "note": "by hand"}]
    rows, got = _facts(data)
    port = got[f"unifi:fact/port/{R_GW}/6"]
    assert port["adds"] == {"peer": "Big Iron and 2 guests", "speed": "1G"}
    ops = rv.plan(rows, [f"unifi:fact/device/{R_GW}", port["key"]], data, label="UniFi Network")
    assert {"op": "upsert", "section": "nodes", "id": "front-door", "body": {"mac": R_GW}} in ops
    assert {"op": "upsert", "section": "interfaces", "index": 0,
            "body": {"peer": "Big Iron and 2 guests", "speed": "1G"}} in ops
    data["interfaces"][0]["peer"] = "the big one"                         # a person's words stand
    _, got = _facts(data)
    assert "peer" not in got[f"unifi:fact/port/{R_GW}/6"]["adds"]


def test_a_place_is_known_by_its_mac_after_its_address_changes():
    data = json.loads(json.dumps(REAL_MAP))
    data["nodes"].append({"id": "vault", "name": "OLD NAME", "ip": "10.50.40.99", "mac": R_NAS.upper()})
    _, got = _facts(data)
    assert (got[f"unifi:client/{R_NAS}"]["status"], got[f"unifi:client/{R_NAS}"]["matched"]) == ("charted", "vault")


def test_a_power_strips_outlets_are_ports_of_their_own_kind():
    _, got = _facts()
    outlet = got[f"unifi:outlet/{R_PDU}/2"]
    assert (outlet["type"], outlet["name"], outlet["kind"], outlet["peer"]) == ("port", "outlet 2", "power", "Fan")
    assert got[f"unifi:port/{R_PDU}/1"]["name"] == "1"                    # its network port keeps its name


def test_an_access_point_says_what_it_broadcasts():
    from importers import unifi
    rows, _ = unifi.candidates({"devices": [{
        "mac": R_GW, "type": "uap", "model": "U7PROMAX", "name": "Hall", "ip": "10.0.10.3",
        "vap_table": [{"essid": "home", "radio": "na"}, {"essid": "home", "radio": "ng"}, {"essid": "things"}]}]})
    assert rows[0]["hw"] == "U7PROMAX · Wi-Fi home, things" and rows[0]["mac"] == R_GW


# ── the controller as a survey, and as a first import ────────────────────────
def test_the_survey_can_be_read_from_the_controller_and_nothing_is_charted(realm, admin, net):
    save(admin, UNIFI_KEY)
    before = realm.data_path.read_text(encoding="utf-8")
    j = admin.post("/api/v2/admin/discovery/connection", headers=W, json={"key": "unifi"}).get_json()
    assert j["ok"] and j["source"] == "UniFi Network" and j["seen"] == 5 and j["new"] == 5
    assert realm.data_path.read_text(encoding="utf-8") == before
    seen = {o["ip"]: o for o in admin.get("/api/v2/admin/discovery").get_json()["observed"]}
    assert seen["10.0.10.40"]["mac"] == NAS and seen["10.0.10.40"]["hostname"] == "nas"
    assert "unifi" in seen["10.0.10.40"]["source"]
    again = admin.post("/api/v2/admin/discovery/connection", headers=W, json={"key": "unifi"}).get_json()
    assert again["seen"] == 5 and again["new"] == 0                       # seen twice is still one device


def test_only_a_system_that_sees_the_network_can_feed_the_survey(realm, admin, net):
    r = admin.post("/api/v2/admin/discovery/connection", headers=W, json={"key": "kuma"})
    assert r.status_code == 400
    j = admin.post("/api/v2/admin/discovery/connection", headers=W, json={"key": "unifi"}).get_json()
    assert not j["ok"] and j["error"] == "No URL to ask."                 # not set up: said, not raised


def test_a_gateway_is_sighted_at_a_lan_address():
    from importers import unifi
    hosts = {h["mac"]: h for h in unifi.sightings(REAL)}
    assert hosts[R_GW]["ip"] == "10.50.1.1"
    assert "203.0.113.7" not in json.dumps(list(hosts.values()))
    assert hosts[R_VM1]["vendor"] == "Microsoft Corporation" and hosts[R_VM1]["source"] == "unifi"


def test_networks_gear_and_machines_land_on_an_empty_map_in_one_import():
    from importers import review as rv
    from importers import unifi
    empty = {"zones": [], "nodes": [], "routes": []}
    cands, _ = unifi.candidates(REAL)
    rows = rv.annotate(cands, empty)
    assert not [r for r in rows if r["type"] == "fact"]                    # nothing on the map to add to
    picks = [r["key"] for r in rows if r["status"] == "new" and not r["blocked"]]
    ops = rv.plan(rows, picks, empty, label="UniFi Network")
    zones = {o["body"]["id"] for o in ops if o["section"] == "zones"}
    nodes = {o["body"]["id"]: o["body"] for o in ops if o["section"] == "nodes"}
    assert {"home", "servers", "edge", "guests"} <= zones
    assert nodes["front-door"]["zone"] == "home" and nodes["front-door"]["mac"] == R_GW
    assert nodes["big-iron"]["zone"] == "servers"
    guest = next(n for n in nodes.values() if n.get("mac") == R_VM2)
    assert guest["parent"] == "big-iron" and guest["kind"] == "vm"
    outlets = [o["body"] for o in ops if o["section"] == "interfaces" and o["body"]["kind"] == "power"]
    assert [o["name"] for o in outlets] == ["outlet 1", "outlet 2", "outlet 3"] and outlets[1]["peer"] == "Fan"


def test_a_wan_port_is_on_no_network_of_the_site():
    from importers import unifi
    rows, _ = unifi.candidates({
        "devices": [{"mac": R_GW, "type": "udm", "name": "Edge", "ip": "10.50.1.1", "port_table": [
            {"port_idx": 9, "name": "ISP", "up": True, "speed": 1000, "media": "GE",
             "network_name": "wan", "native_networkconf_id": "n-home"}]}],
        "networks": REAL["networks"]})
    port = next(r for r in rows if r["type"] == "port")
    assert port["vlan"] is None and port["peer"] == "the internet"
