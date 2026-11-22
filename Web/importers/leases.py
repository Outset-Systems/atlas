import csv
import io
import ipaddress
import re


class LeaseError(ValueError):
    pass


def _mac(raw):
    import schema
    return schema.mac_key((raw or "").strip().strip('"')) or None


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
