"""UniFi Network as review candidates: devices, clients, networks, ports and the
links between them.

The same reading Scanopy's UniFi integration makes (scanopy.net/docs/guides/
integrations/unifi, read 2026-11-02): the controller's own lists, never a scan.

    stat/device        adopted gateways, switches and access points, with their port
                       tables, their uplinks and their LLDP neighbours
    stat/sta           the clients connected now, and the port or access point each
                       one is on
    rest/networkconf   the networks, with their VLAN and subnet

Devices and clients become places, networks become realms, a port table becomes
`interfaces`, and an uplink, an LLDP neighbour or a client's port becomes a route.
Every one is a row in the review, and nothing lands until it is ticked.

These are the controller's unofficial endpoints, which is what every UniFi tool
reads, Scanopy included. They are not promised to stay put. Two ways in, both
read-only by the account they belong to:

    API key      UniFi OS only (a console, a Cloud Key, UniFi OS Server). The key
                 goes in `X-API-KEY`, and paths sit under `/proxy/network`.
    local user   any controller, the old self-hosted Network Application too. One
                 login (`/api/auth/login` on UniFi OS, `/api/login` before it), the
                 reads, then a logout. A cloud account with MFA cannot sign in here.

Written against the UniFi Network Application's answers as the community has
recorded them, then corrected against one real console (a UDM Pro SE on Network
10.6, 2026-11-10). What that reading taught is in the code below: a gateway
reports its WAN address as its own, a power strip reports itself as a switch,
and every guest of a hypervisor shows as a wired client on the hypervisor's
port. The answers in tests/test_unifi.py keep that shape with invented names.
"""

import ipaddress
import re

import requests

from . import review
from .wire import TIMEOUT, Refused, ok, plural
from .netbox import _hue_of

#: A site is a path segment, and only ever one.
SITE_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_SITE = "default"

#: Device types, as UniFi names them, and the heading each is listed under.
_GROUPS = {"ugw": "Gateways", "udm": "Gateways", "uxg": "Gateways", "usw": "Switches",
           "uap": "Access points"}
_ROLES = {"Gateways": "Gateway", "Switches": "Switch", "Access points": "Access point",
          "Power": "Power distribution"}

#: MAC prefixes hypervisors hand their guests: Hyper-V, KVM/QEMU, VMware (three),
#: Proxmox, VirtualBox, Xen. A client with one of these is a guest of something.
_VIRTUAL = ("00:15:5d", "52:54:00", "00:50:56", "00:0c:29", "00:05:69", "bc:24:11",
            "08:00:27", "00:16:3e")

#: Network purposes that are a segment of the LAN. `wan` and `remote-user-vpn` are not.
_LAN = ("corporate", "guest", "vlan-only")


def site_path(site):
    site = (site or "").strip() or DEFAULT_SITE
    if not SITE_OK.match(site):
        raise ValueError("A UniFi site is the short name in the controller's address, like `default`.")
    return f"/api/s/{site}"


def fetch_snapshot(get, site):
    """Everything a review needs, through `get(path) -> data`. Pure fetch.

    A controller that will not list its clients still lists its devices: the
    client list is a nicety, the way a guest's address is for Proxmox."""
    base = site_path(site)
    snapshot = {"devices": get(f"{base}/stat/device") or [], "clients": [], "networks": []}
    for part, path in (("clients", "stat/sta"), ("networks", "rest/networkconf")):
        try:
            snapshot[part] = get(f"{base}/{path}") or []
        except Exception:  # noqa: BLE001 — the devices are the review; the rest is detail
            snapshot.setdefault("missing", []).append(part)
    return snapshot


def _mac(text):
    mac = str(text or "").strip().lower()
    return mac if re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac) else ""


def _speed(mbps):
    try:
        mbps = int(mbps or 0)
    except (TypeError, ValueError):
        return ""
    if mbps <= 0:
        return ""
    if mbps >= 1000:
        g = mbps / 1000
        return f"{g:g}G"
    return f"{mbps}M"


def _iface_kind(port):
    media = str(port.get("media") or "").upper()
    if "SFP" not in media:
        return "rj45"
    return "sfp+" if any(fast in media for fast in ("SFP+", "SFP28", "10G")) else "sfp"


def _subnet(cidr):
    """`192.168.1.1/24` (the gateway's address, which is how UniFi writes it) as
    the network it belongs to, or ""."""
    try:
        return str(ipaddress.ip_interface(str(cidr or "").strip()).network)
    except ValueError:
        return ""


def _device_name(d):
    return (review.clean(d.get("name")) or review.clean(d.get("hostname"))
            or f"{review.clean(d.get('model')) or 'unifi'}-{_mac(d.get('mac'))[-5:].replace(':', '')}")


def _client_name(c):
    return (review.clean(c.get("name")) or review.clean(c.get("hostname"))
            or f"{review.clean(c.get('oui')) or 'client'} {_mac(c.get('mac'))[-5:]}")


def _lans(snapshot):
    """Every LAN network's (gateway address, subnet), as the controller writes them."""
    out = []
    for n in snapshot.get("networks", []):
        if n.get("purpose") not in _LAN:
            continue
        try:
            face = ipaddress.ip_interface(str(n.get("ip_subnet") or "").strip())
        except ValueError:
            continue
        out.append((str(face.ip), face.network))
    return out


def _inside(ip, lans):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for _, net in lans)


def _gateway_addresses(d, lans):
    """(the address to chart, the others it answers at).

    A gateway's `ip` is its WAN address, which is the one address of the site
    that must not land on the map. It holds one address on every LAN network;
    the map may know it by any of them. With no network list to judge by, the
    device's own `lan_ip` or `ip` is taken as it was before."""
    told = [a for a in (review.address(d.get("lan_ip")), review.address(d.get("ip"))) if a != "—"]
    if not lans:
        return (told[0] if told else "—"), []
    held = [a for a in told if _inside(a, lans)]
    for n in d.get("network_table") or []:
        addr = review.address(n.get("ip")) if isinstance(n, dict) else "—"
        if addr != "—" and _inside(addr, lans):
            held.append(addr)
    held += [gw for gw, _ in lans]
    held = list(dict.fromkeys(held))
    return (held[0], held[1:]) if held else ("—", [])


def _is_power(d):
    """A SmartPower strip reports type `usw`. Its model and its outlets say otherwise.
    Not every `USP…` model: the Pro Max switches are `USPM…`."""
    return str(d.get("model") or "").upper().startswith(("USPPDU", "USPRPS")) or bool(d.get("outlet_table"))


def _outlets(d):
    """("20 outlets", "6 on · 333 W") for a power strip, or ("", "")."""
    table = [o for o in d.get("outlet_table") or [] if isinstance(o, dict)]
    if not table:
        return "", ""
    live = sum(1 for o in table if o.get("relay_state"))
    try:
        watts = float(d.get("outlet_ac_power_consumption"))
    except (TypeError, ValueError):
        watts = None
    now = f"{live} on" + (f" · {watts:.0f} W" if watts is not None else "")
    return f"{len(table)} outlets", now


def _hosts(snapshot, devices):
    """{guest mac: host mac} for clients that sit behind another client's port.

    A hypervisor and its guests all show as wired clients on one switch port.
    When exactly one of them has a hardware MAC and the rest have a
    hypervisor's, the one is the host. Anything less certain is left alone."""
    by_port = {}
    for c in snapshot.get("clients", []):
        mac, sw = _mac(c.get("mac")), _mac(c.get("sw_mac"))
        if mac and mac not in devices and c.get("is_wired") and sw in devices                 and c.get("sw_port") is not None:
            by_port.setdefault((sw, c.get("sw_port")), []).append(mac)
    out = {}
    for macs in by_port.values():
        real = [m for m in macs if not m.startswith(_VIRTUAL)]
        if len(real) == 1 and len(macs) > 1:
            out.update({m: real[0] for m in macs if m != real[0]})
    return out


def _networks(snapshot):
    """(zone rows, {network id: vlan})."""
    rows, vlan_of = [], {}
    for n in snapshot.get("networks", []):
        if n.get("purpose") not in _LAN:
            continue
        vlan = n.get("vlan") if n.get("vlan_enabled") else 1
        try:
            vlan = int(vlan)
        except (TypeError, ValueError):
            continue
        vlan_of[str(n.get("_id"))] = vlan
        rows.append(review.zone(f"unifi:network/{n.get('_id')}", "Networks",
                                n.get("name") or f"VLAN {vlan}", vlan, _subnet(n.get("ip_subnet")),
                                _hue_of(vlan)))
    return rows, vlan_of


def candidates(snapshot):
    """(rows, notes)."""
    rows, vlan_of = _networks(snapshot)
    lans = _lans(snapshot)
    devices = {}
    for d in snapshot.get("devices", []):
        mac = _mac(d.get("mac"))
        if mac:
            devices[mac] = d
    names = {mac: _device_name(d) for mac, d in devices.items()}
    links = {}

    def link(a, b, detail):
        """One route per pair of things, whichever side reported it first."""
        pair = tuple(sorted((a, b)))
        if a != b and pair not in links:
            ends = "~".join(k.split(":", 1)[1] for k in pair)      # device/<mac>~client/<mac>
            links[pair] = review.route(f"unifi:link/{ends}", "Links",
                                       a, b, detail)

    for mac, d in devices.items():
        key = f"unifi:device/{mac}"
        group = "Power" if _is_power(d) else _GROUPS.get(d.get("type"), "Other UniFi gear")
        ports = d.get("port_table") or []
        model = review.clean(d.get("model_name") or d.get("model"))
        outlets, drawing = _outlets(d) if group == "Power" else ("", "")
        bits = [b for b in (model, outlets or (f"{len(ports)} ports" if ports else ""),
                            f"UniFi {review.clean(d.get('version'))}" if d.get("version") else "") if b]
        state = "online" if d.get("state") == 1 else "offline"
        ip, also = (_gateway_addresses(d, lans) if group == "Gateways"
                    else (review.address(d.get("ip")), []))
        # what it draws right now is a reading, so it is shown and not kept
        rows.append(review.place(key, group, names[mac], "network",
                                 f"{_ROLES.get(group, 'UniFi device')} · from UniFi",
                                 ip=ip, also=also, hw=" · ".join(bits),
                                 detail=" · ".join(b for b in bits + [drawing, state] if b)))
        up = d.get("uplink") or {}
        upstream = _mac(up.get("uplink_mac"))
        if upstream in devices:
            how = ("wireless" if up.get("type") == "wireless" else
                   f"port {up.get('port_idx')} → {names[upstream]} port {up.get('uplink_remote_port')}"
                   if up.get("port_idx") and up.get("uplink_remote_port") else "uplink")
            link(key, f"unifi:device/{upstream}", how)
        for n in d.get("lldp_table") or []:
            other = _mac(n.get("chassis_id"))
            if other in devices:
                link(key, f"unifi:device/{other}", f"LLDP on port {n.get('local_port_idx')}")
        for p in ports:
            idx = p.get("port_idx")
            if idx is None:
                continue
            vlan = vlan_of.get(str(p.get("native_networkconf_id")))
            speed = _speed(p.get("speed")) if p.get("up") else ""
            rows.append(review.port(f"unifi:port/{mac}/{idx}", f"Ports on {names[mac]}", str(idx), key,
                                    kind=_iface_kind(p), speed=speed, vlan=vlan,
                                    poe=bool(p.get("port_poe")),
                                    detail=" · ".join(b for b in (review.clean(p.get("name")),
                                                                  speed or "down") if b)))

    wired = wireless = 0
    host_of = _hosts(snapshot, devices)
    client_names = {_mac(c.get("mac")): _client_name(c) for c in snapshot.get("clients", [])}
    for c in snapshot.get("clients", []):
        mac = _mac(c.get("mac"))
        if not mac or mac in devices:
            continue
        key = f"unifi:client/{mac}"
        on_wire = bool(c.get("is_wired"))
        wired += on_wire
        wireless += not on_wire
        where, host = "", host_of.get(mac)
        if host:
            # a guest: it hangs off its host, and the host's cable is the only road
            where = f"a guest of {client_names[host]}"
        elif on_wire and _mac(c.get("sw_mac")) in devices:
            where = f"port {c.get('sw_port')} of {names[_mac(c.get('sw_mac'))]}"
            link(key, f"unifi:device/{_mac(c.get('sw_mac'))}", f"on port {c.get('sw_port')}")
        elif not on_wire and _mac(c.get("ap_mac")) in devices:
            where = f"{review.clean(c.get('essid')) or 'Wi-Fi'} on {names[_mac(c.get('ap_mac'))]}"
            link(key, f"unifi:device/{_mac(c.get('ap_mac'))}",
                 f"Wi-Fi {review.clean(c.get('essid'))}".strip())
        vendor = review.clean(c.get("oui"))
        what = "virtual machine" if host else "wired client" if on_wire else "wireless client"
        rows.append(review.place(key, "Wired clients" if on_wire else "Wireless clients",
                                 _client_name(c), "vm" if host else "unknown",
                                 f"{what} · from UniFi",
                                 ip=review.address(c.get("ip")), hw=vendor,
                                 parent=f"unifi:client/{host}" if host else None,
                                 detail=" · ".join(b for b in (vendor, where) if b)))
    rows += links.values()

    notes = []
    if not devices:
        notes.append("The controller lists no devices for this site. A wrong site name looks "
                     "exactly like this: it is the short name in the controller's address, "
                     "usually `default`.")
    for part in snapshot.get("missing", []):
        notes.append(f"The controller would not list its {part}, so this review has none.")
    if wired + wireless:
        notes.append(f"{wired + wireless} client{'' if wired + wireless == 1 else 's'} connected now "
                     f"({wired} wired, {wireless} wireless). A client that is off is not listed.")
    return rows, notes


# ── the connection: what Settings shows, the test, and the survey ───────────
SYSTEM = {
    "key": "unifi", "name": "UniFi Network",
    "about": "Devices, clients, networks and the ports and links between them.",
    "credential": "Either an API key (UniFi OS: Settings → Control Plane → Integrations), "
                  "made by an admin with the View Only role, or a local account with the "
                  "View Only role and no MFA, for any controller. A console listens on 443, "
                  "UniFi OS Server on 11443, the older Network Application on 8443.",
    "fields": (("ATLAS_UNIFI_URL", "URL", "https://unifi.example", "url"),
               ("ATLAS_UNIFI_SITE", "Site", "default", "text"),
               ("ATLAS_UNIFI_API_KEY", "API key", "", "secret"),
               ("ATLAS_UNIFI_USERNAME", "Or a local user", "", "secret"),   # half a credential, so write-only too
               ("ATLAS_UNIFI_PASSWORD", "Its password", "", "secret"),
               ("ATLAS_UNIFI_INSECURE", "Self-signed certificate", "", "insecure")),
    # [site, key, user, password]: the key alone, or a user with a password
    "ready": lambda c: bool(c[1] or (c[2] and c[3])),
}


class Controller:
    """A read-only conversation with a UniFi controller: an API key on every call, or
    one login, the reads and a logout. `get(path)` answers the `data` list."""

    def __init__(self, base, creds, verify):
        site, key, user, password = creds
        self.base, self.verify, self.site = base, verify, site
        self.head, self.cookies, self.prefix, self.out = {"Accept": "application/json"}, {}, "", None
        if key:
            # an API key exists only on UniFi OS, where the Network app sits under /proxy/network
            self.head["X-API-KEY"] = key
            self.prefix = "/proxy/network"
            return
        body = {"username": user, "password": password}
        for login, prefix, logout in (("/api/auth/login", "/proxy/network", "/api/auth/logout"),
                                      ("/api/login", "", "/api/logout")):
            r = requests.post(base + login, json=body, headers=self.head, timeout=TIMEOUT,
                              verify=verify, allow_redirects=False)
            if r.status_code == 404:
                continue                      # not this generation of controller
            if r.status_code in (400, 401, 403):
                raise Refused("UniFi refused the user name and password. A cloud account "
                              "with MFA cannot sign in here: use a local account.")
            ok(r, "UniFi")
            jar = getattr(r, "cookies", None)
            self.cookies = jar.get_dict() if hasattr(jar, "get_dict") else dict(jar or {})
            token = r.headers.get("X-CSRF-Token") or r.headers.get("x-csrf-token")
            if token:
                self.head["X-CSRF-Token"] = token
            self.prefix, self.out = prefix, logout
            return
        raise Refused("UniFi did not offer a sign-in at this address. Is it the controller's URL?")

    def get(self, path):
        r = requests.get(self.base + self.prefix + path, headers=self.head, cookies=self.cookies,
                         timeout=TIMEOUT, verify=self.verify, allow_redirects=False)
        body = ok(r, "UniFi").json()
        if isinstance(body, dict) and (body.get("meta") or {}).get("rc") == "error":
            raise Refused(f"UniFi said no: {(body.get('meta') or {}).get('msg') or 'an error'}.")
        return body.get("data") if isinstance(body, dict) else body

    def close(self):
        if not self.out:
            return
        try:
            requests.post(self.base + self.out, headers=self.head, cookies=self.cookies,
                          timeout=TIMEOUT, verify=self.verify, allow_redirects=False)
        except requests.exceptions.RequestException:
            pass                               # the session times out on its own


def _site(conn, typed):
    """(the site to read, a sentence when that is not the one typed).

    The controller is asked for its sites before anything typed goes into a
    path. A wrong name on a controller with one site is read as that site, and
    said: people type the console's name, and the site is nearly always
    `default`. With more than one site a wrong name is refused, with the list."""
    typed = (typed or "").strip() or DEFAULT_SITE
    try:
        sites = [s for s in conn.get("/api/self/sites") or [] if isinstance(s, dict)]
    except Refused:
        sites = []                             # a key that may not list sites: take it as typed
    names = [s.get("name") for s in sites if SITE_OK.match(str(s.get("name") or ""))]
    if not names or typed in names:
        return typed, ""
    shown = review.clean(typed, 64)
    if len(names) == 1:
        return names[0], (f"This controller has no site called {shown}. Its only site is "
                          f"`{names[0]}`, so that is the one read here.")
    listed = ", ".join(f"{s.get('name')} ({s.get('desc')})" for s in sites[:6])
    raise Refused(f"This controller has no site called {shown}. It has: {listed}.")


def _with_controller(base, creds, verify, ask):
    conn = Controller(base, creds, verify)
    try:
        site, said = _site(conn, creds[0])
        try:
            site_path(site)
        except ValueError as e:
            raise Refused(str(e)) from e
        return ask(conn, site, said)
    finally:
        conn.close()


def probe(base, creds, verify):
    def ask(conn, site, said):
        devices = conn.get(f"/api/s/{site}/stat/device") or []
        clients = conn.get(f"/api/s/{site}/stat/sta") or []
        return (f"UniFi site {site}: {plural(len(devices), 'device')}, "
                f"{plural(len(clients), 'client')} connected" + (f". {said}" if said else ""))
    return _with_controller(base, creds, verify, ask)


def survey(base, creds, verify):
    def ask(conn, site, said):
        rows, notes = candidates(fetch_snapshot(conn.get, site))
        return rows, ([said] if said else []) + notes
    return _with_controller(base, creds, verify, ask)
