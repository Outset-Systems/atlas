"""What a surveyed device probably is — a suggestion, never a fact.

A scan or a lease says an address answered and, at best, who made the network
card and what the device calls itself. That is often enough to guess a type
(a Synology is storage, a QEMU NIC is a VM), and a newcomer charting forty
strangers would rather correct a few guesses than set forty types by hand.

So this module guesses, and says why: every suggestion carries `because`, and
the Desk shows it on the draft the human reviews before anything is written.
A device nothing gives away gets no suggestion and charts as `unknown`, as
before. Kinds are the catalogue's (schema.NODE_KINDS); `role` is the words
for the draft's role line.
"""

import re

#: MAC prefixes that ARE a hypervisor's virtual NIC. Unlike a maker, these are
#: definitive, and a lease (which has no vendor) still carries them.
VIRTUAL_OUI = {
    "52:54:00": "QEMU/KVM",
    "00:15:5d": "Hyper-V",
    "00:50:56": "VMware", "00:0c:29": "VMware", "00:05:69": "VMware", "00:1c:14": "VMware",
    "08:00:27": "VirtualBox",
    "bc:24:11": "Proxmox",
    "00:16:3e": "Xen",
    "02:42:ac": "Docker",
}

#: Makers (as nmap names them, matched loosely) → (kind, role words).
MAKERS = [
    (r"netgate|ubiquiti|mikrotik|routerboard|tp-?link|cisco|juniper|aruba|fortinet|"
     r"zyxel|draytek|netgear|meraki|ruckus|palo alto|sophos|watchguard|opnsense|pfsense",
     "network", "network gear"),
    (r"synology|qnap|asustor|terramaster|western digital|buffalo|drobo|truenas|ixsystems",
     "physical", "storage"),
    (r"super ?micro|dell|hewlett|\bhpe?\b|lenovo|asrock|gigabyte|intel corporate|"
     r"minisforum|beelink|zotac|fujitsu", "physical", "a server or PC"),
    (r"raspberry pi", "physical", "a Raspberry Pi"),
    (r"espressif|tuya|shelly|sonoff|ezviz|wyze|tasmota", "physical", "a smart-home device"),
    (r"brother|canon|epson|lexmark|xerox|kyocera|ricoh", "physical", "a printer"),
    (r"hikvision|dahua|reolink|axis comm|amcrest", "physical", "a camera"),
    (r"apple|samsung|google|oneplus|xiaomi|huawei|motorola", "physical", "a phone, tablet or computer"),
    (r"sonos|roku|nvidia|amazon|lg electronics|sony|vizio", "physical", "a media device"),
    (r"apc|american power|eaton|cyberpower", "physical", "a UPS"),
]

#: What a device calls itself → (kind, role words). Whole words, so `nas`
#: matches `nas-01` and `office-nas` but never `dynasty`.
NAMES = [
    (r"gw|gateway|router|firewall|fw|opnsense|pfsense|edge", "network", "the gateway"),
    (r"sw|switch|core", "network", "a switch"),
    (r"ap|wap|unifi|wifi|access-?point|mesh", "network", "an access point"),
    (r"pve|proxmox|esxi|hyperv|hypervisor|xcp|hv", "physical", "a hypervisor"),
    (r"nas|truenas|unraid|storage|san|backup", "physical", "storage"),
    (r"pihole|pi-hole|adguard|dns|dc|ldap", "physical", "a DNS or directory server"),
    (r"printer|mfp|laserjet|officejet", "physical", "a printer"),
    (r"cam|camera|nvr|doorbell", "physical", "a camera"),
    (r"ups|pdu", "physical", "power equipment"),
    (r"docker|k8s|kube|k3s|swarm", "physical", "a container host"),
    (r"vm|ct|lxc|guest", "vm", "a VM or container"),
]


def _word(pattern):
    return re.compile(rf"(?:^|[^a-z0-9])(?:{pattern})(?:\d*)(?=$|[^a-z0-9])", re.I)


_NAMES = [(_word(p), kind, role) for p, kind, role in NAMES]
_MAKERS = [(re.compile(p, re.I), kind, role) for p, kind, role in MAKERS]


def virtual_vendor(mac):
    """The hypervisor whose virtual NIC this MAC is, or None."""
    return VIRTUAL_OUI.get((mac or "").lower()[:8]) if mac else None


def private_mac(mac):
    """True for a locally administered (randomized) MAC — phones and laptops
    hide behind one on Wi-Fi, and a virtual NIC may too."""
    try:
        return bool(int((mac or "").split(":")[0], 16) & 0x02)
    except ValueError:
        return False


def _first(rules, text):
    if text:
        for rx, kind, role in rules:
            if rx.search(text):
                return kind, role
    return None


def suggest(host):
    """{kind, role, because} for an observed device, or None. Checked in order
    of how much each clue proves: a virtual NIC, the maker, the device's own
    name, and last a randomized MAC. A maker and a name that agree on the kind
    take the name's role (a Raspberry Pi called pihole is the DNS server); when
    they disagree the maker wins, because it describes the hardware."""
    mac = (host.get("mac") or "").lower()
    virtual = virtual_vendor(mac)
    if virtual:
        return {"kind": "vm", "role": f"a {virtual} virtual machine",
                "because": f"its network card is a {virtual} virtual one"}
    vendor = host.get("vendor") or ""
    name = (host.get("hostname") or "").split(".")[0]
    by_maker, by_name = _first(_MAKERS, vendor), _first(_NAMES, name)
    if by_maker and by_name and by_maker[0] == by_name[0]:
        return {"kind": by_name[0], "role": by_name[1],
                "because": f"made by {vendor} and calls itself {name}"}
    if by_maker:
        return {"kind": by_maker[0], "role": by_maker[1], "because": f"made by {vendor}"}
    if by_name:
        return {"kind": by_name[0], "role": by_name[1], "because": f"it calls itself {name}"}
    if mac and private_mac(mac):
        return {"kind": "physical", "role": "a phone or laptop (private address)",
                "because": "its MAC is randomized, which phones and laptops do on Wi-Fi"}
    return None
