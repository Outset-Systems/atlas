import time

import requests

from . import review
from .wire import TIMEOUT, Refused, ok, plural

ADDRESS_BUDGET = 15

_PLUMBING = ("lo", "docker", "br-", "veth", "virbr", "cni", "flannel", "tailscale")


def _gb(n):
    return int((n or 0) / 1024 ** 3)


def _usable(name, ip):
    if str(name or "").startswith(_PLUMBING):
        return False
    return review.address(ip) != "—" and not str(ip).startswith(("127.", "169.254."))


def _lxc_ip(interfaces):
    for nic in interfaces or []:
        ip = str(nic.get("inet") or "")
        if _usable(nic.get("name"), ip):
            return review.address(ip)
    return "—"


def _qemu_ip(answer):
    for nic in (answer or {}).get("result") or []:
        for found in nic.get("ip-addresses") or []:
            ip = found.get("ip-address")
            if found.get("ip-address-type") == "ipv4" and _usable(nic.get("name"), ip):
                return review.address(ip)
    return "—"


def fetch_snapshot(get, *, clock=time.monotonic):
    rows = get("/api2/json/cluster/resources") or []
    guests = [r for r in rows if r.get("type") in ("qemu", "lxc") and not r.get("template")]
    try:
        status = get("/api2/json/cluster/status") or []
    except Exception:
        status = []
    snapshot = {"nodes": [r for r in rows if r.get("type") == "node"], "guests": guests,
                "status": status, "addresses": {}}
    deadline = clock() + ADDRESS_BUDGET
    for guest in guests:
        if guest.get("status") != "running":
            continue
        if clock() > deadline:
            break
        where = f"/api2/json/nodes/{guest.get('node')}/{guest['type']}/{guest.get('vmid')}"
        try:
            ip = (_lxc_ip(get(f"{where}/interfaces")) if guest["type"] == "lxc"
                  else _qemu_ip(get(f"{where}/agent/network-get-interfaces")))
        except Exception:
            continue
        snapshot["addresses"][str(guest.get("vmid"))] = ip
    return snapshot


def candidates(snapshot):
    node_ip = {s.get("name"): s.get("ip") for s in snapshot.get("status", [])
               if s.get("type") == "node"}
    rows = []
    for n in snapshot.get("nodes", []):
        name = n.get("node") or n.get("name") or n.get("id")
        hw = f"{n.get('maxcpu') or 0} cores · {_gb(n.get('maxmem'))}GB RAM"
        rows.append(review.place(f"proxmox:node/{name}", "Nodes", name, "physical",
                                 "Proxmox node · from Proxmox", ip=review.address(node_ip.get(name)),
                                 hw=hw, detail=f"{hw} · {n.get('status') or 'unknown'}"))
    silent = 0
    for g in snapshot.get("guests", []):
        vmid, lxc = g.get("vmid"), g.get("type") == "lxc"
        ip = snapshot.get("addresses", {}).get(str(vmid), "—")
        silent += ip == "—" and g.get("status") == "running"
        hw = f"{g.get('maxcpu') or 0} vCPU · {_gb(g.get('maxmem'))}GB RAM"
        rows.append(review.place(f"proxmox:{g.get('type')}/{vmid}",
                                 "Containers" if lxc else "Virtual machines",
                                 g.get("name") or f"{g.get('type')}-{vmid}", "vm",
                                 f"{'container' if lxc else 'virtual machine'} on {g.get('node')} · from Proxmox",
                                 ip=ip, hw=hw, parent=f"proxmox:node/{g.get('node')}",
                                 detail=f"{hw} · {g.get('status') or 'unknown'}"))
    notes = []
    if silent:
        notes.append(f"{plural(silent, 'running guest')} did not report an address. "
                     "That takes the QEMU guest agent, and a role that may read it.")
    return rows, notes


SYSTEM = {
    "key": "proxmox", "name": "Proxmox VE",
    "about": "Nodes, virtual machines and containers.",
    "credential": "Datacenter → Permissions → API Tokens. Give the token the PVEAuditor "
                  "role on /. Paste it as user@pam!name=secret.",
    "fields": (("ATLAS_PROXMOX_URL", "URL", "https://proxmox.example:8006", "url"),
               ("ATLAS_PROXMOX_TOKEN", "API token", "", "secret"),
               ("ATLAS_PROXMOX_INSECURE", "Self-signed certificate", "", "insecure")),
}


def _get(base, creds, verify):
    head = {"Authorization": f"PVEAPIToken={creds[0]}"}
    return lambda p: ok(requests.get(base + p, headers=head, timeout=TIMEOUT, verify=verify,
                                     allow_redirects=False), "Proxmox").json().get("data")


def probe(base, creds, verify):
    get = _get(base, creds, verify)
    version = (get("/api2/json/version") or {}).get("version", "?")
    rows = get("/api2/json/cluster/resources") or []
    if not rows:
        raise Refused("Proxmox answered, but this token can see nothing. Give it PVEAuditor on /.")
    nodes = sum(1 for r in rows if r.get("type") == "node")
    guests = sum(1 for r in rows if r.get("type") in ("qemu", "lxc"))
    return f"Proxmox VE {version}: {plural(nodes, 'node')}, {plural(guests, 'guest')}"


def survey(base, creds, verify):
    return candidates(fetch_snapshot(_get(base, creds, verify)))
