"""nmap XML parsing — the half of the discovery importer that touches no DB.

`atlas-relay` runs the scan on the customer LAN and parses it here (stdlib
only) before pushing hosts to the server, which owns the matching half
(nmap.py).
"""

import re
import xml.etree.ElementTree as ET


class NmapError(RuntimeError):
    pass


def parse_nmap_xml(text):
    """Parse `nmap -oX` output into [{ip, mac, vendor, hostname, ports}].

    Down hosts are skipped. A DOCTYPE is refused outright: this file arrives
    from a customer LAN via the relay, and entity expansion is not a risk worth
    carrying for a format that never legitimately needs one.
    """
    if re.search(r"<!DOCTYPE", text, re.IGNORECASE):
        raise NmapError("refusing nmap XML containing a DOCTYPE declaration")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise NmapError(f"not valid nmap XML: {e}") from e

    hosts = []
    for h in root.iter("host"):
        status = h.find("status")
        if status is not None and status.get("state") not in (None, "up"):
            continue
        ip = mac = vendor = None
        for a in h.findall("address"):
            kind = a.get("addrtype")
            if kind in ("ipv4", "ipv6") and not ip:
                ip = a.get("addr")
            elif kind == "mac":
                mac, vendor = a.get("addr"), a.get("vendor")
        hn = h.find("hostnames/hostname")
        hostname = hn.get("name") if hn is not None else None
        ports = []
        for p in h.findall("ports/port"):
            st = p.find("state")
            if st is not None and st.get("state") != "open":
                continue
            svc = p.find("service")
            ports.append({
                "port": int(p.get("portid")) if p.get("portid", "").isdigit() else p.get("portid"),
                "proto": p.get("protocol"),
                "service": svc.get("name") if svc is not None else None,
            })
        if not ip and not mac:
            continue  # nothing to identify it by
        hosts.append({"ip": ip, "mac": mac, "vendor": vendor,
                      "hostname": hostname, "ports": ports})
    return hosts
