"""DHCP lease files → observed devices, beside the nmap survey.

A router already knows every device that asked it for an address, with the
name the device gave itself — usually better names than a ping sweep finds,
and no scan at all. The operator copies the lease file off their own router
and hands it over; the Atlas never fetches it (the same line as nmap: it reads
what it is given, it never probes).

Formats, recognised from the text itself:

    isc      dhcpd.leases — pfSense, OPNsense (ISC), most Linux routers
    dnsmasq  dhcp.leases  — Pi-hole, OpenWrt, many home routers
    kea      kea-leases4.csv — OPNsense / pfSense with Kea
    windows  `Get-DhcpServerv4Lease -ScopeId … | Export-Csv` — Windows Server

Each becomes the shape `parse_nmap_xml` returns, minus what a lease cannot
know: {ip, mac, hostname, source: "dhcp"}. No `ports` and no `vendor` keys at
all, so filing leases over an earlier scan of the same address keeps what the
scan found. Expired, released, free or declined leases are skipped: a lease
file remembers devices long gone, and the survey should list what is current.
"""

import csv
import io
import ipaddress
import re


class LeaseError(ValueError):
    """The text is not a lease file this importer knows."""


_MAC = re.compile(r"^[0-9a-f]{2}([:-][0-9a-f]{2}){5}$", re.I)


def _mac(raw):
    raw = (raw or "").strip().strip('"').lower().replace("-", ":")
    return raw if _MAC.match(raw) else None


def _ip(raw):
    raw = (raw or "").strip().strip('"')
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def _name(raw):
    raw = (raw or "").strip().strip('"').rstrip(".")
    return None if raw in ("", "*", "?") else raw


def _host(ip, mac, hostname):
    out = {"ip": ip, "source": "dhcp"}
    if mac:
        out["mac"] = mac
    if hostname:
        out["hostname"] = hostname
    return out


def _isc(text):
    """`lease 10.0.0.5 { … }` blocks. A later block for the same address is a
    newer state of that lease, so the last one wins."""
    found = {}
    for m in re.finditer(r"lease\s+(\S+)\s*\{(.*?)\}", text, re.S):
        ip = _ip(m.group(1))
        if not ip:
            continue
        body = m.group(2)
        state = re.search(r"\bbinding\s+state\s+(\w+)\s*;", body)
        if state and state.group(1).lower() not in ("active", "backup"):
            found.pop(ip, None)
            continue
        mac = re.search(r"\bhardware\s+ethernet\s+([0-9a-f:]+)\s*;", body, re.I)
        name = re.search(r'\bclient-hostname\s+"([^"]*)"\s*;', body)
        found[ip] = _host(ip, _mac(mac.group(1)) if mac else None,
                          _name(name.group(1)) if name else None)
    return list(found.values())


def _dnsmasq(text):
    """`<expiry> <mac> <ip> <hostname> <client-id>` per line."""
    found = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        ip = _ip(parts[2])
        if ip:
            found[ip] = _host(ip, _mac(parts[1]), _name(parts[3]))
    return list(found.values())


def _rows(text):
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#TYPE")]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def _kea(text):
    """Kea's memfile CSV. `state` 0 is a live lease (1 declined, 2 expired)."""
    found = {}
    for row in _rows(text):
        ip = _ip(row.get("address"))
        if not ip:
            continue
        if (row.get("state") or "0").strip() not in ("0", ""):
            found.pop(ip, None)
            continue
        found[ip] = _host(ip, _mac(row.get("hwaddr")), _name(row.get("hostname")))
    return list(found.values())


def _windows(text):
    """`Export-Csv` of Get-DhcpServerv4Lease: IPAddress, ClientId (the MAC,
    dash-separated), HostName (often the FQDN), AddressState."""
    found = {}
    for row in _rows(text):
        ip = _ip(row.get("IPAddress"))
        if not ip:
            continue
        state = (row.get("AddressState") or "Active").strip().lower()
        if state and not state.startswith("active"):
            found.pop(ip, None)
            continue
        found[ip] = _host(ip, _mac(row.get("ClientId")), _name(row.get("HostName")))
    return list(found.values())


def detect(text):
    """Which format this is, or None."""
    head = text.lstrip()[:4096]
    first = head.splitlines()[0] if head else ""
    if re.search(r"^\s*lease\s+\S+\s*\{", head, re.M):
        return "isc"
    lowered = first.lower()
    if lowered.startswith("address,hwaddr"):
        return "kea"
    if "ipaddress" in head.lower() and "clientid" in head.lower():
        return "windows"
    if re.match(r"^\d+\s+\S+\s+\S+\s+\S+", first):
        return "dnsmasq"
    return None


PARSERS = {"isc": _isc, "dnsmasq": _dnsmasq, "kea": _kea, "windows": _windows}


def parse_leases(text):
    """(format, hosts) for a lease file. Raises LeaseError when the text is
    none of the known formats, or names no current lease."""
    if not isinstance(text, str) or not text.strip():
        raise LeaseError("that is empty")
    fmt = detect(text)
    if fmt is None:
        raise LeaseError("that is not a lease file the Atlas knows: ISC dhcpd.leases, "
                         "dnsmasq dhcp.leases, Kea kea-leases4.csv, or a Windows "
                         "Get-DhcpServerv4Lease export")
    hosts = PARSERS[fmt](text)
    if not hosts:
        raise LeaseError(f"that looks like a {fmt} lease file but has no current leases")
    return fmt, hosts
