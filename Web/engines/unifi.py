"""The `unifi` source: what a UniFi Network controller says is connected now,
for charted places nothing else watches."""

from engines.base import DOWN, HEALTHY, _Adapter, _worse, log, monitor_map

#: UniFi device types that are a gateway: their `ip` is the WAN address.
_UNIFI_GATEWAYS = ("ugw", "udm", "uxg")


class UniFiAdapter(_Adapter):
    """A UniFi Network controller's "connected now" → marker states, for charted
    places nothing else watches.

    Three rules keep it honest:

    * Only a charted place is ever reported. The place maps come from the
      dataset (`unifi_places`, pushed by `api.v2.feeds._apply_kuma_map`), and a
      client that is on no map leaves no trace in the feed: not its address,
      not its name, not a count.
    * Absent is unknown, never down. The client list is "connected now", so a
      laptop asleep is simply not in it; reporting that as an outage would fill
      the annals with fiction. Only a UniFi device the controller itself lists
      as disconnected (`state` 0) is `down`, and only when the place is known
      by that device's MAC: an address may have passed to something else, and
      a device that is upgrading or adopting is not an outage.
    * Kuma is the authority where it watches. A place with a monitor tied to it
      is left alone, so the two sources never argue over one marker.

    One controller session per fetch: open, read the two lists, close.
    """

    name = "unifi"

    def __init__(self, url, creds, verify=True):
        self.url = url.rstrip("/")
        self.creds = list(creds)          # [site, api key, user, password]
        self.verify = verify
        self._places = ({}, {}, frozenset())
        self._site = None                 # the resolved site, looked up once

    def set_places(self, by_mac, by_ip, watched):
        """{mac: node id}, {ip: node id} and the node ids Kuma already watches."""
        self._places = (dict(by_mac or {}), dict(by_ip or {}), frozenset(watched or ()))

    def use_map(self, data):
        self.set_places(*unifi_places(data))

    def _fetch(self):
        by_mac, by_ip, watched = self._places
        if not (by_mac or by_ip):
            return {}                     # nothing charted to report on: do not ask
        from importers import unifi       # local import: needs `requests`, never at module load

        conn = unifi.Controller(self.url, self.creds, self.verify)   # a user session logs in here
        try:
            if self._site is None:
                site, _ = unifi._site(conn, self.creds[0])
                unifi.site_path(site)     # a site is one path segment, or it is refused
                self._site = site
            base = f"/api/s/{self._site}"
            devices = conn.get(f"{base}/stat/device") or []
            try:
                clients = conn.get(f"{base}/stat/sta") or []
            except Exception as e:  # noqa: BLE001 — the devices still stand; absent is unknown
                log.warning("unifi: no client list this poll (%s)", type(e).__name__)
                clients = []
        finally:
            conn.close()

        states = {}

        def seen(mac, ip, state):
            # MAC first, then address — and one thing lights one place only
            nid = by_mac.get(unifi._mac(mac))
            if nid is None and state == HEALTHY:
                nid = by_ip.get(str(ip or "").strip())
            if nid is None or nid in watched:
                return
            states[nid] = _worse(states.get(nid), state)

        for d in devices:
            if not isinstance(d, dict):
                continue
            ip = d.get("ip")
            if d.get("type") in _UNIFI_GATEWAYS:
                ip = unifi._gateway_addresses(d, [])[0]   # its LAN address, not the WAN one
            if d.get("state") in (0, 1):               # anything else is mid-change: say nothing
                seen(d.get("mac"), ip, HEALTHY if d.get("state") == 1 else DOWN)
        for c in clients:
            if isinstance(c, dict):
                seen(c.get("mac"), c.get("ip"), HEALTHY)
        return {"nodes": {nid: {"state": state} for nid, state in states.items()}}


def unifi_places(data):
    """({mac: place id}, {ip: place id}, {place ids Kuma already watches}) from a
    dataset: what the `unifi` source may report on, and what it must leave alone.

    Several places can be drawn at one address: a machine, and the software on
    it that someone gave a marker of its own. The address belongs to the machine
    (`kind` vm or physical). A place that *is* a network (a prefix) has no
    address to be connected at.
    """
    by_mac, by_ip, machine_at = {}, {}, set()
    nodes = [n for n in data.get("nodes", []) or [] if isinstance(n, dict) and n.get("id")]
    watched = {nid for nid in monitor_map(data).values() if nid}
    for node in nodes:
        nid = node["id"]
        if node.get("monitors") or any(isinstance(link, dict) and link.get("kuma")
                                       for link in node.get("links") or []):
            watched.add(nid)
        mac = str(node.get("mac") or "").strip().lower()
        if mac:
            by_mac.setdefault(mac, nid)
        ip = str(node.get("ip") or "").strip()
        if not ip or ip == "—" or "/" in ip:
            continue
        machine = node.get("kind") in ("vm", "physical")
        if ip not in by_ip or (machine and ip not in machine_at):
            by_ip[ip] = nid
        if machine:
            machine_at.add(ip)
    return by_mac, by_ip, watched


def _unifi_adapter(url):
    """The `unifi` source from the UniFi connection's saved credential, or None
    (said in the log) when it has none."""
    import connections
    _, creds, insecure = connections.saved("unifi")
    if not connections.ready("unifi", creds):
        log.warning("unifi source requested but the UniFi connection has no credential "
                    "(an API key, or a user and its password) — skipping")
        return None
    return UniFiAdapter(url, creds, verify=not insecure)
