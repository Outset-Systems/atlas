"""UniFi and Uptime Kuma, the pair: UniFi says what exists and how it is wired, Kuma
says whether it is up, and both land on the same places.

Every answer here is a fake, shaped from the UniFi Network Application's recorded
answers (stat/device, stat/sta, rest/networkconf, self/sites) and from Kuma's own
/metrics text. The refusals are the point, as in test_connection_review.py: a review
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
    assert gets and all("/proxy/network/api/s/default/" in u for _, u, _ in gets)
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
