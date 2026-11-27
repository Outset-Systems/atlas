import relayed
import settings

from . import review
from .hyperv_client import READS, SCRIPT, checked, fetch_snapshot  # noqa: F401
from .wire import Refused, plural

KEY = "hyperv"

# A replica has its primary's id. Only the primary is a place.
_COPIES = ("replica", "testreplica", "extendedreplica")


def _gb(n):
    return int((n or 0) / 1024 ** 3)


def _usable(ip):
    ip = str(ip or "")
    if ":" in ip or ip.startswith(("127.", "169.254.")):
        return False
    return review.address(ip) != "—"


def _mac(raw):
    digits = "".join(c for c in str(raw or "") if c.isalnum()).upper()
    if len(digits) != 12 or not digits.strip("0"):
        return ""
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2))


def _addresses(vm):
    """(first address, its adapter's MAC, the other addresses)."""
    first, mac, also = "—", "", []
    for nic in vm.get("nics") or []:
        for ip in nic.get("ips") or []:
            if not _usable(ip):
                continue
            ip = review.address(ip)
            if first == "—":
                first, mac = ip, _mac(nic.get("mac"))
            elif ip != first and ip not in also:
                also.append(ip)
    if first == "—":
        macs = [m for m in (_mac(n.get("mac")) for n in vm.get("nics") or []) if m]
        mac = macs[0] if len(macs) == 1 else ""
    return first, mac, also


def host_key(name):
    return f"hyperv:host/{str(name or '').lower()}"


def candidates(snapshot):
    rows, seen = [], set()
    for h in snapshot.get("hosts", []):
        hw = f"{h.get('cores') or 0} cores · {_gb(h.get('memory'))}GB RAM"
        rows.append(review.place(host_key(h.get("name")), "Hosts", h.get("label") or h.get("name"),
                                 "physical", "Hyper-V host · from Hyper-V",
                                 ip=review.address(h.get("address")), hw=hw))
    silent = copies = 0
    for vm in snapshot.get("vms", []):
        if str(vm.get("replication") or "").lower() in _COPIES:
            copies += 1
            continue
        key = f"hyperv:vm/{vm.get('id')}"
        if key in seen:
            continue
        seen.add(key)
        ip, mac, also = _addresses(vm)
        state = vm.get("state") or "unknown"
        silent += ip == "—" and state.lower() == "running"
        hw = f"{vm.get('vcpu') or 0} vCPU · {_gb(vm.get('memory'))}GB RAM"
        detail = " · ".join([hw, state] + (["clustered"] if vm.get("clustered") else []))
        rows.append(review.place(key, "Virtual machines", vm.get("name") or vm.get("id"), "vm",
                                 f"virtual machine on {vm.get('host')} · from Hyper-V",
                                 ip=ip, hw=hw, parent=host_key(vm.get("host")), detail=detail,
                                 also=also, mac=mac))
    notes = []
    for s in snapshot.get("silent", []):
        notes.append(f"{review.clean(s.get('host')) or 'A host'} is missing from this review: "
                     f"{review.clean(s.get('why'), 200) or 'it did not answer'}.")
    if silent:
        notes.append(f"{plural(silent, 'running virtual machine')} did not report an address. "
                     "That takes the Data Exchange integration service in the guest.")
    if copies:
        notes.append(f"{plural(copies, 'replica')} left out: a replica is its primary's copy.")
    return rows, notes


SYSTEM = {
    "key": KEY, "name": "Hyper-V",
    "about": "Hosts and virtual machines, read by a relay on your network.",
    "credential": "Nothing to type here. A relay on your network reads Hyper-V over WinRM and "
                  "sends what it finds; the Windows account stays in the relay's own files. "
                  "Turn on [hyperv] in relay.toml, with an account in Hyper-V Administrators "
                  "and Remote Management Users on each host. That account can also change "
                  "virtual machines, so keep its password on the relay only.",
    "fields": (),
    "relay": True,
}


def _held(site=None):
    held = relayed.get(KEY, site or settings.SITE_SLUG)
    if held is None:
        raise Refused("No relay has reported Hyper-V yet. Turn on [hyperv] in relay.toml and "
                      "check this Atlas accepts relay pushes (ATLAS_INGEST_ENABLED), or load "
                      "a snapshot file with `cli.py hyperv-load`.")
    return held


def reported(site=None):
    return relayed.get(KEY, site or settings.SITE_SLUG) is not None


def probe(site=None):
    held = _held(site)
    snap = held["snapshot"]
    words = (f"Hyper-V, read by the relay {relayed.age_words(held)}: "
             f"{plural(len(snap.get('hosts', [])), 'host')}, "
             f"{plural(len(snap.get('vms', [])), 'virtual machine')}")
    quiet = len(snap.get("silent", []))
    return words + (f", {plural(quiet, 'host')} silent" if quiet else "")


def survey(site=None):
    held = _held(site)
    rows, notes = candidates(held["snapshot"])
    return rows, [f"This is what the relay read {relayed.age_words(held)}."] + notes
