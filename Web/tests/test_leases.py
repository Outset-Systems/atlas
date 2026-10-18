"""DHCP lease import and the type suggestions a survey's drafts carry.

Run: `python -m pytest Web/tests/test_leases.py -q`
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from importers.leases import LeaseError, detect, parse_leases  # noqa: E402
import suggest  # noqa: E402

ISC = """# The format of this file is documented in the dhcpd.leases(5) manual page.
lease 10.0.0.20 {
  starts 4 2026/10/15 10:00:00;
  ends 4 2026/10/15 12:00:00;
  binding state active;
  hardware ethernet 00:11:32:aa:bb:cc;
  client-hostname "nas";
}
lease 10.0.0.31 {
  binding state free;
  hardware ethernet 02:aa:bb:cc:dd:ee;
}
lease 10.0.0.40 {
  binding state active;
  hardware ethernet 52:54:00:12:34:56;
  client-hostname "docker-01";
}
lease 10.0.0.40 {
  binding state expired;
  hardware ethernet 52:54:00:12:34:56;
}
lease 10.0.0.41 {
  binding state active;
  hardware ethernet 52:54:00:12:34:57;
}
"""

DNSMASQ = """1792400000 b8:27:eb:01:02:03 10.0.0.30 pihole 01:b8:27:eb:01:02:03
1792400100 7a:11:22:33:44:55 10.0.0.66 * *
"""

KEA = """address,hwaddr,client_id,valid_lifetime,expire,subnet_id,fqdn_fwd,fqdn_rev,hostname,state,user_context
10.0.0.50,00:15:5d:01:02:03,,3600,1792403600,1,0,0,hyperv-guest,0,
10.0.0.51,aa:bb:cc:dd:ee:01,,3600,1792403600,1,0,0,gone,2,
"""

WINDOWS = """#TYPE Microsoft.Management.Infrastructure.CimInstance
"IPAddress","ScopeId","AddressState","ClientId","HostName"
"10.0.0.60","10.0.0.0","Active","00-1b-21-aa-bb-cc","printer.corp.example"
"10.0.0.61","10.0.0.0","Declined","00-1b-21-aa-bb-cd",""
"""


def test_each_format_is_recognised():
    assert detect(ISC) == "isc"
    assert detect(DNSMASQ) == "dnsmasq"
    assert detect(KEA) == "kea"
    assert detect(WINDOWS) == "windows"
    assert detect("hello world") is None


def test_isc_keeps_current_leases_and_the_latest_state_wins():
    fmt, hosts = parse_leases(ISC)
    by_ip = {h["ip"]: h for h in hosts}
    assert fmt == "isc"
    assert set(by_ip) == {"10.0.0.20", "10.0.0.41"}, "free and since-expired leases are gone"
    assert by_ip["10.0.0.20"] == {"ip": "10.0.0.20", "mac": "00:11:32:aa:bb:cc",
                                  "hostname": "nas", "source": "dhcp"}
    assert "hostname" not in by_ip["10.0.0.41"]


def test_dnsmasq_reads_a_star_as_no_name():
    _, hosts = parse_leases(DNSMASQ)
    by_ip = {h["ip"]: h for h in hosts}
    assert by_ip["10.0.0.30"]["hostname"] == "pihole"
    assert "hostname" not in by_ip["10.0.0.66"]


def test_kea_and_windows_skip_dead_leases_and_normalise_macs():
    _, kea = parse_leases(KEA)
    assert [h["ip"] for h in kea] == ["10.0.0.50"]
    _, win = parse_leases(WINDOWS)
    assert win == [{"ip": "10.0.0.60", "mac": "00:1b:21:aa:bb:cc",
                    "hostname": "printer.corp.example", "source": "dhcp"}]


def test_a_lease_never_claims_ports_or_a_vendor():
    for text in (ISC, DNSMASQ, KEA, WINDOWS):
        for host in parse_leases(text)[1]:
            assert "ports" not in host and "vendor" not in host


def test_unknown_or_empty_text_is_refused():
    with pytest.raises(LeaseError):
        parse_leases("")
    with pytest.raises(LeaseError):
        parse_leases("this is a shopping list")
    with pytest.raises(LeaseError):
        parse_leases("lease 10.0.0.9 {\n  binding state free;\n}\n")


# ── suggestions ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host, kind, role_part", [
    ({"mac": "52:54:00:aa:bb:cc"}, "vm", "QEMU/KVM"),
    ({"mac": "00:15:5d:aa:bb:cc", "hostname": "nas"}, "vm", "Hyper-V"),
    ({"vendor": "Synology Incorporated"}, "physical", "storage"),
    ({"vendor": "Ubiquiti Networks"}, "network", "network gear"),
    ({"vendor": "Raspberry Pi Trading", "hostname": "pihole"}, "physical", "DNS"),
    ({"hostname": "core-sw-01.home.example"}, "network", "switch"),
    ({"hostname": "pve2"}, "physical", "hypervisor"),
    ({"mac": "7a:11:22:33:44:55"}, "physical", "phone or laptop"),
])
def test_suggestions_name_a_kind_and_say_why(host, kind, role_part):
    got = suggest.suggest(host)
    assert got["kind"] == kind and role_part in got["role"]
    assert got["because"], "every suggestion says why"


def test_words_must_be_whole_and_nothing_is_guessed_from_nothing():
    assert suggest.suggest({"hostname": "dynasty"}) is None, "nas inside a word is not a NAS"
    assert suggest.suggest({"hostname": "stranger", "mac": "00:11:22:33:44:55"}) is None
    assert suggest.suggest({}) is None


def test_the_maker_wins_when_it_disagrees_with_the_name():
    got = suggest.suggest({"vendor": "Synology", "hostname": "gateway"})
    assert got["kind"] == "physical" and "Synology" in got["because"]


# ── the endpoint, and merging with an earlier scan ──────────────────────────

NMAP = """<?xml version="1.0"?><nmaprun>
  <host><status state="up"/><address addr="10.0.0.20" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="5000"><state state="open"/></port></ports></host>
</nmaprun>"""

WRITE = {"X-Atlas-Write": "1"}


@pytest.fixture
def client(tmp_path):
    import shutil
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "default-lab-data.json"), data)
    app = fresh_app(ATLAS_DATA_BACKEND="file", ATLAS_AUTH_MODE="standalone",
                    ATLAS_ALLOW_INSECURE="1", ATLAS_READONLY="0", ATLAS_DATA=str(data),
                    ATLAS_OBSERVED=str(tmp_path / "observed.json"),
                    ATLAS_REVISIONS=str(tmp_path / "revisions"))
    return app.app.test_client()


def test_leases_file_into_the_survey_beside_a_scan(client):
    r = client.post("/api/v2/admin/discovery/scan", headers=WRITE, json={"nmap_xml": NMAP})
    assert r.status_code == 200
    r = client.post("/api/v2/admin/discovery/leases", headers=WRITE, json={"leases": ISC})
    body = r.get_json()
    assert r.status_code == 200 and body["format"] == "isc" and body["seen"] == 2
    assert body["new"] == 1, "10.0.0.20 was already in the survey from the scan"

    rows = {row["ip"]: row for row in client.get("/api/v2/admin/discovery").get_json()["observed"]}
    nas = rows["10.0.0.20"]
    assert nas["ports"] and nas["ports"][0]["port"] == 5000, "the lease kept what the scan found"
    assert nas["mac"] == "00:11:32:aa:bb:cc" and nas["hostname"] == "nas", "and added what it knew"
    assert nas["source"] == "nmap, dhcp"
    assert nas["suggestion"]["role"] == "storage"
    vm = rows["10.0.0.41"]
    assert vm["vendor"] == "QEMU/KVM" and vm["suggestion"]["kind"] == "vm"

    drafts = client.post("/api/v2/admin/discovery/as-nodes", headers=WRITE,
                         json={"keys": ["10.0.0.20", "10.0.0.41"]}).get_json()["nodes"]
    by_ip = {d["ip"]: d for d in drafts}
    assert by_ip["10.0.0.20"]["name"] == "NAS"
    assert by_ip["10.0.0.41"]["kind"] == "vm"
    assert "looks like" in by_ip["10.0.0.41"]["role"] and "check it" in by_ip["10.0.0.41"]["role"]


def test_a_bad_lease_file_is_refused_with_the_reason(client):
    r = client.post("/api/v2/admin/discovery/leases", headers=WRITE, json={"leases": "nope"})
    assert r.status_code == 422 and "lease file" in r.get_json()["error"]
    assert client.post("/api/v2/admin/discovery/leases", headers=WRITE,
                       json={}).status_code == 400
