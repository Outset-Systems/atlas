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
recorded them. No controller has answered this code yet: the fake responses in
tests/test_unifi.py are shaped from those records.
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
_ROLES = {"Gateways": "Gateway", "Switches": "Switch", "Access points": "Access point"}

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
        group = _GROUPS.get(d.get("type"), "Other UniFi gear")
        ports = d.get("port_table") or []
        model = review.clean(d.get("model_name") or d.get("model"))
        bits = [b for b in (model, f"{len(ports)} ports" if ports else "",
                            f"UniFi {review.clean(d.get('version'))}" if d.get("version") else "") if b]
        state = "online" if d.get("state") == 1 else "offline"
        rows.append(review.place(key, group, names[mac], "network",
                                 f"{_ROLES.get(group, 'UniFi device')} · from UniFi",
                                 ip=review.address(d.get("ip")), hw=" · ".join(bits),
                                 detail=" · ".join(bits + [state])))
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
    for c in snapshot.get("clients", []):
        mac = _mac(c.get("mac"))
        if not mac or mac in devices:
            continue
        key = f"unifi:client/{mac}"
        on_wire = bool(c.get("is_wired"))
        wired += on_wire
        wireless += not on_wire
        where = ""
        if on_wire and _mac(c.get("sw_mac")) in devices:
            where = f"port {c.get('sw_port')} of {names[_mac(c.get('sw_mac'))]}"
            link(key, f"unifi:device/{_mac(c.get('sw_mac'))}", f"on port {c.get('sw_port')}")
        elif not on_wire and _mac(c.get("ap_mac")) in devices:
            where = f"{review.clean(c.get('essid')) or 'Wi-Fi'} on {names[_mac(c.get('ap_mac'))]}"
            link(key, f"unifi:device/{_mac(c.get('ap_mac'))}",
                 f"Wi-Fi {review.clean(c.get('essid'))}".strip())
        vendor = review.clean(c.get("oui"))
        rows.append(review.place(key, "Wired clients" if on_wire else "Wireless clients",
                                 _client_name(c), "unknown",
                                 f"{'wired' if on_wire else 'wireless'} client · from UniFi",
                                 ip=review.address(c.get("ip")), hw=vendor,
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


def _with_controller(base, creds, verify, ask):
    try:
        site_path(creds[0])
    except ValueError as e:
        raise Refused(str(e)) from e
    conn = Controller(base, creds, verify)
    try:
        return ask(conn, creds[0] or DEFAULT_SITE)
    finally:
        conn.close()


def probe(base, creds, verify):
    def ask(conn, site):
        sites = conn.get("/api/self/sites") or []
        names = [s.get("name") for s in sites if isinstance(s, dict)]
        if site not in names:
            listed = ", ".join(f"{s.get('name')} ({s.get('desc')})" for s in sites[:6]
                               if isinstance(s, dict)) or "none"
            raise Refused(f"This controller has no site called {site}. It has: {listed}.")
        devices = conn.get(f"/api/s/{site}/stat/device") or []
        clients = conn.get(f"/api/s/{site}/stat/sta") or []
        return (f"UniFi site {site}: {plural(len(devices), 'device')}, "
                f"{plural(len(clients), 'client')} connected")
    return _with_controller(base, creds, verify, ask)


def survey(base, creds, verify):
    return _with_controller(base, creds, verify,
                            lambda conn, site: candidates(fetch_snapshot(conn.get, site)))
