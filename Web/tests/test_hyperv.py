"""The Hyper-V importer, with no Windows machine: the WinRM call is injected.

Every name and address here is invented (home.example, 192.0.2.0/24).
Run from Web/: python -m pytest tests
"""
import importlib.util
import json
import logging
import os
import re

import pytest

import connections
import relayed
from importers import hyperv, hyperv_client, review

HERE = os.path.dirname(os.path.abspath(__file__))
ANSWER = open(os.path.join(HERE, "fixtures", "hyperv_host_answer.json"), encoding="utf-8").read()
PASSWORD = "correct-horse-battery-staple"


def _relay():
    path = os.path.join(HERE, "..", "..", "relay", "atlas_relay.py")
    spec = importlib.util.spec_from_file_location("atlas_relay", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


relay = _relay()
ATLAS = {"hyperv": hyperv_client}


def snapshot(**answers):
    answers = answers or {"hv1.home.example": ANSWER}

    def run(host):
        answer = answers[host]
        if isinstance(answer, Exception):
            raise answer
        return answer
    return hyperv_client.fetch_snapshot(run, [(h, "192.0.2.11") for h in answers])


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(relayed.settings, "DATA_DIR", str(tmp_path))
    return tmp_path


# ── the script ──────────────────────────────────────────────────────────────

def test_the_script_only_reads():
    called = set(re.findall(r"\b[A-Z][a-z]+-[A-Za-z]+\b", hyperv_client.SCRIPT))
    assert called - {"ForEach-Object", "ConvertTo-Json"} == set(hyperv_client.READS)
    assert all(name.startswith("Get-") for name in hyperv_client.READS)
    for verb in ("Set-", "Remove-", "Stop-", "Start-", "New-", "Invoke-", "iex"):
        assert verb not in hyperv_client.SCRIPT


# ── one host's answer into a snapshot ───────────────────────────────────────

def test_a_host_answer_becomes_a_snapshot():
    snap = snapshot()
    assert snap["silent"] == []
    assert snap["hosts"] == [{"name": "hv1.home.example", "label": "HV1", "asked": "hv1.home.example",
                              "address": "192.0.2.11", "cores": 16, "memory": 137438953472}]
    assert [v["name"] for v in snap["vms"]] == ["wiki", "quiet", "parked", "mirror", "v6only"]
    assert snap["vms"][0]["id"] == "7c1d0e52-0000-4000-8000-000000000001"
    # PowerShell 5.1 can write a one-item array as the bare item
    assert snap["vms"][2]["nics"] == [{"mac": "000000000000", "switch": "LAN", "ips": []}]
    assert snap["vms"][4]["nics"][0]["ips"] == ["2001:db8::5"]


def test_a_silent_host_does_not_stop_the_rest():
    snap = snapshot(**{"hv1.home.example": ANSWER,
                       "hv2.home.example": hyperv_client.Unanswered("it refused the account"),
                       "hv3.home.example": RuntimeError(f"login failed for password {PASSWORD}"),
                       "hv4.home.example": "<html>not json</html>"})
    assert [h["name"] for h in snap["hosts"]] == ["hv1.home.example"]
    assert snap["silent"] == [
        {"host": "hv2.home.example", "why": "it refused the account"},
        {"host": "hv3.home.example", "why": "it did not answer (RuntimeError)"},
        {"host": "hv4.home.example", "why": "it answered, but not with the inventory Atlas asked for"}]
    assert PASSWORD not in json.dumps(snap)


def test_the_same_host_listed_twice_is_read_once():
    snap = snapshot(**{"hv1.home.example": ANSWER, "hv1": ANSWER})
    assert len(snap["hosts"]) == 1 and len(snap["vms"]) == 5


def test_the_time_budget_leaves_late_hosts_silent():
    ticks = iter([0, 0, 10_000, 10_000])
    snap = hyperv_client.fetch_snapshot(lambda h: ANSWER, [("hv1", ""), ("hv2", "")],
                                        clock=lambda: next(ticks), budget=1)
    assert [s["host"] for s in snap["silent"]] == ["hv2"]


# ── a snapshot into review rows ─────────────────────────────────────────────

def test_rows_for_the_review():
    rows, notes = hyperv.candidates(snapshot())
    by_name = {r["name"]: r for r in rows}
    host = by_name["HV1"]
    assert (host["key"], host["kind"], host["ip"], host["group"]) == (
        "hyperv:host/hv1.home.example", "physical", "192.0.2.11", "Hosts")
    assert host["hw"] == "16 cores · 128GB RAM"

    wiki = by_name["wiki"]
    assert wiki["key"] == "hyperv:vm/7c1d0e52-0000-4000-8000-000000000001"
    assert (wiki["kind"], wiki["ip"], wiki["also"], wiki["mac"]) == (
        "vm", "192.0.2.40", ["192.0.2.41"], "00:15:5D:01:02:03")
    assert wiki["parent"] == host["key"]
    assert wiki["hw"] == "2 vCPU · 4GB RAM" and wiki["detail"] == "2 vCPU · 4GB RAM · Running"
    assert wiki["role"] == "virtual machine on hv1.home.example · from Hyper-V"

    assert by_name["quiet"]["ip"] == "—" and by_name["quiet"]["mac"] == "00:15:5D:01:02:04"
    assert by_name["v6only"]["ip"] == "—"
    assert "mac" not in by_name["parked"]          # an unassigned dynamic MAC is all zeroes
    assert "mirror" not in by_name                 # a replica is its primary's copy
    assert notes == ["2 running virtual machines did not report an address. "
                     "That takes the Data Exchange integration service in the guest.",
                     "1 replica left out: a replica is its primary's copy."]


def test_a_silent_host_is_named_in_the_notes():
    snap = snapshot(**{"hv1.home.example": ANSWER,
                       "hv2.home.example": hyperv_client.Unanswered("it refused the account")})
    assert hyperv.candidates(snap)[1][0] == (
        "hv2.home.example is missing from this review: it refused the account.")


def test_one_vm_seen_on_two_hosts_is_one_place():
    other = json.loads(ANSWER)
    other.update(name="HV2", fqdn="hv2.home.example")
    snap = snapshot(**{"hv1.home.example": ANSWER, "hv2.home.example": json.dumps(other)})
    rows, _ = hyperv.candidates(snap)
    keys = [r["key"] for r in rows]
    assert len(keys) == len(set(keys))
    assert sum(1 for r in rows if r["name"] == "wiki") == 1


# ── what the server accepts ─────────────────────────────────────────────────

def test_the_server_accepts_what_the_relay_builds():
    snap = snapshot()
    assert hyperv_client.checked(json.loads(json.dumps(snap))) == snap


@pytest.mark.parametrize("payload, words", [
    ({"mode": "scvmm", "hosts": [{"name": "a"}]}, "'mode' must be"),
    ({"mode": "standalone", "hosts": "hv1"}, "'hosts' must be a list"),
    ({"mode": "standalone", "hosts": [{}]}, "every host needs a 'name'"),
    ({"mode": "standalone", "hosts": [{"name": "a"}], "vms": [{"name": "x"}]}, "every vm needs an 'id'"),
    ({"mode": "standalone", "hosts": []}, "no host answered"),
    ({"mode": "standalone", "hosts": [{"name": "a"}] * 65}, "more than 64"),
])
def test_the_server_refuses_a_bad_snapshot(payload, words):
    with pytest.raises(ValueError, match=words):
        hyperv_client.checked(payload)


def test_unknown_fields_are_dropped():
    snap = hyperv_client.checked({"mode": "standalone", "password": PASSWORD,
                                  "hosts": [{"name": "HV1", "password": PASSWORD}],
                                  "vms": [{"id": "a", "host": "HV1", "secret": PASSWORD}]})
    assert PASSWORD not in json.dumps(snap)
    assert snap["vms"][0]["host"] == "hv1"


# ── the ingest route and the connection ─────────────────────────────────────

@pytest.fixture
def client(store, monkeypatch):
    import ingest
    from app import app
    from flask import g

    def as_site():
        g.site_slug, g.token_id = "default", 1

    monkeypatch.setattr(ingest, "enabled", lambda: True)
    monkeypatch.setattr(ingest, "authenticate", as_site)
    return app.test_client()


def test_ingest_keeps_the_snapshot_for_review(client):
    assert not hyperv.reported()
    ok, why = connections.survey("hyperv", *connections.saved("hyperv"))
    assert not ok and "No relay has reported" in why

    r = client.post("/api/v2/ingest/hyperv", json=snapshot())
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["stats"] == {"hosts": 1, "vms": 5, "silent": 0}
    assert hyperv.reported()

    ok, words = connections.probe("hyperv", "", [], False)
    assert ok and words == "Hyper-V, read by the relay just now: 1 host, 5 virtual machines"
    ok, (rows, notes) = connections.survey("hyperv", *connections.saved("hyperv"))
    assert ok and len(rows) == 5 and notes[0] == "This is what the relay read just now."


def test_ingest_refuses_a_bad_snapshot(client):
    r = client.post("/api/v2/ingest/hyperv", json={"mode": "standalone", "hosts": []})
    assert r.status_code == 422 and "no host answered" in r.get_json()["error"]
    assert not hyperv.reported()


def test_ingest_is_not_there_when_ingest_is_off(store):
    from app import app
    assert app.test_client().post("/api/v2/ingest/hyperv", json=snapshot()).status_code == 404


def test_another_sites_snapshot_is_not_this_sites(store):
    relayed.put("hyperv", "branch", snapshot())
    assert not hyperv.reported()
    assert hyperv.reported("branch")


def test_the_connection_is_listed_as_relayed(store):
    listed = {s["key"]: s for s in connections.describe()}["hyperv"]
    assert listed["relay"] is True and listed["fields"] == [] and listed["configured"] is False
    relayed.put("hyperv", "default", snapshot())
    assert {s["key"]: s for s in connections.describe()}["hyperv"]["configured"] is True
    assert {s["key"]: s for s in connections.describe()}["proxmox"]["relay"] is False


def test_review_then_import_then_review_again(store):
    relayed.put("hyperv", "default", snapshot())
    _, (candidates, _) = connections.survey("hyperv", "", [], False)
    data = {"zones": [{"id": "lan", "name": "LAN", "subnet": "192.0.2.0/24", "vlan": 1}],
            "nodes": [], "links": []}
    rows = review.annotate(candidates, data, set())
    assert {r["status"] for r in rows} == {review.NEW}
    vm = "hyperv:vm/7c1d0e52-0000-4000-8000-000000000001"
    ops = review.plan(rows, ["hyperv:host/hv1.home.example", vm], data, label="Hyper-V",
                      fallback="lan")
    bodies = {op["body"]["origin"]: op["body"] for op in ops if op["section"] == "nodes"}
    assert bodies[vm]["parent"] == bodies["hyperv:host/hv1.home.example"]["id"]
    assert (bodies[vm]["ip"], bodies[vm]["kind"], bodies[vm]["zone"]) == ("192.0.2.40", "vm", "lan")

    data["nodes"] = list(bodies.values())
    again = {r["key"]: r["status"] for r in review.annotate(candidates, data, set())}
    assert again[vm] == review.CHARTED and again["hyperv:host/hv1.home.example"] == review.CHARTED
    assert again["hyperv:vm/7c1d0e52-0000-4000-8000-000000000002"] == review.NEW


# ── the relay ───────────────────────────────────────────────────────────────

def section(**over):
    base = {"enabled": True, "hosts": ["hv1.home.example"], "auth": "ntlm",
            "username": "atlas-read", "password": PASSWORD}
    base.update(over)
    return base


def test_relay_default_plan_is_https_and_verified(tmp_path):
    plan = relay.hyperv_plan(section())
    assert (plan["https"], plan["port"], plan["cert"], plan["auth"]) == (True, 5986, True, "ntlm")
    ca = tmp_path / "lab-ca.pem"
    ca.write_text("invented", encoding="utf-8")
    assert relay.hyperv_plan(section(ca_file=str(ca)))["cert"] == str(ca)
    with pytest.raises(relay.ConfigError, match="cannot read ca_file"):
        relay.hyperv_plan(section(ca_file=str(tmp_path / "missing.pem")))


@pytest.mark.parametrize("over, words", [
    ({"auth": "basic"}, "refused"),
    ({"auth": "credssp"}, "refused"),
    ({"auth": "certificate"}, "auth must be one of"),
    ({"transport": "http"}, "cannot tell the real host"),
    ({"verify_tls": False}, "cannot tell the real host"),
    ({"auth": "negotiate", "transport": "http"}, "cannot tell the real host"),
    ({"hosts": []}, "no hosts"),
    ({"mode": "cluster"}, "not built yet"),
    ({"password": ""}, "needs username and password_file"),
    ({"transport": "ssh"}, "transport must be"),
])
def test_relay_refuses_unsafe_or_unbuilt_settings(over, words):
    with pytest.raises(relay.ConfigError, match=words) as e:
        relay.hyperv_plan(section(**over))
    assert PASSWORD not in str(e.value)


def test_relay_allows_kerberos_over_http_and_a_lab_override(caplog):
    plan = relay.hyperv_plan(section(auth="kerberos", transport="http", password=""))
    assert (plan["https"], plan["port"]) == (False, 5985)
    with caplog.at_level(logging.WARNING, logger="atlas-relay"):
        plan = relay.hyperv_plan(section(transport="http", allow_unverified_ntlm=True))
    assert plan["port"] == 5985 and "Lab use only" in caplog.text


def test_relay_reads_the_password_from_its_file(tmp_path):
    secret = tmp_path / "hyperv-password"
    secret.write_text(PASSWORD + "\n", encoding="utf-8")
    plan = relay.hyperv_plan(section(password=None, password_file=str(secret)))
    assert plan["password"] == PASSWORD


def test_relay_collects_and_never_sends_or_logs_the_password(caplog):
    cfg = {"hyperv": section()}
    with caplog.at_level(logging.DEBUG, logger="atlas-relay"):
        payload = relay.collect_hyperv(ATLAS, cfg, runner=lambda host: ANSWER,
                                       resolve=lambda host: "192.0.2.11")
    assert payload["hosts"][0]["address"] == "192.0.2.11" and len(payload["vms"]) == 5
    assert hyperv_client.checked(json.loads(json.dumps(payload))) == payload
    assert PASSWORD not in json.dumps(payload) and PASSWORD not in caplog.text
    assert "atlas-read" not in json.dumps(payload)
    assert "hv1.home.example: 5 vm(s), 2 with an address" in caplog.text
    assert relay._summarize(payload) == "1 hyper-v host(s), 5 vm(s), 0 silent"


def test_relay_pushes_nothing_when_every_host_is_silent():
    def run(host):
        raise hyperv_client.Unanswered("nothing answered on port 5986")
    with pytest.raises(RuntimeError, match="no Hyper-V host answered"):
        relay.collect_hyperv(ATLAS, {"hyperv": section()}, runner=run, resolve=lambda h: "")


def test_relay_schedules_hyperv_only_when_enabled():
    cfg = {"hyperv": section()}
    tasks = relay.build_tasks(ATLAS, cfg)
    assert [(t.name, t.path) for t in tasks] == [("hyperv", "/api/v2/ingest/hyperv")]
    assert relay.build_tasks(ATLAS, {"hyperv": section(enabled=False)}) == []


def test_relay_without_pypsrp_says_how_to_get_it(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_pypsrp(name, *a, **k):
        if name.startswith("pypsrp"):
            raise ImportError("No module named 'pypsrp'")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_pypsrp)
    with pytest.raises(relay.ConfigError, match="pip install pypsrp"):
        relay.collect_hyperv(ATLAS, {"hyperv": section()})


def test_dry_run_can_write_the_snapshot_and_the_server_can_load_it(tmp_path, store, capsys):
    import cli
    task = relay.build_tasks(ATLAS, {"hyperv": section()})[0]
    task.collect = lambda: relay.collect_hyperv(ATLAS, {"hyperv": section()},
                                                runner=lambda h: ANSWER, resolve=lambda h: "")
    assert relay.run_task(task, transport=None, dry_run=True, dump=str(tmp_path / "out"))
    written = tmp_path / "out" / "hyperv.json"
    assert oct(written.stat().st_mode & 0o777) == "0o600"
    assert PASSWORD not in written.read_text(encoding="utf-8")

    assert cli.main(["hyperv-load", str(written)]) == 0
    assert "1 host(s), 5 vm(s)" in capsys.readouterr().out
    assert hyperv.reported()
    assert cli.main(["hyperv-load", str(tmp_path / "missing.json")]) == 2
