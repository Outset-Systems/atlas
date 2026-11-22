from engines.base import DOWN, HEALTHY, _Adapter, _worse, log, monitor_map

_UNIFI_GATEWAYS = ("ugw", "udm", "uxg")


class UniFiAdapter(_Adapter):

    name = "unifi"

    def __init__(self, url, creds, verify=True):
        self.url = url.rstrip("/")
        self.creds = list(creds)
        self.verify = verify
        self._places = ({}, {}, frozenset())
        self._site = None

    def set_places(self, by_mac, by_ip, watched):
        self._places = (dict(by_mac or {}), dict(by_ip or {}), frozenset(watched or ()))

    def use_map(self, data):
        self.set_places(*unifi_places(data))

    def _fetch(self):
        by_mac, by_ip, watched = self._places
        if not (by_mac or by_ip):
            return {}
        from importers import unifi

        conn = unifi.Controller(self.url, self.creds, self.verify)
        try:
            if self._site is None:
                site, _ = unifi._site(conn, self.creds[0])
                unifi.site_path(site)
                self._site = site
            base = f"/api/s/{self._site}"
            devices = conn.get(f"{base}/stat/device") or []
            try:
                clients = conn.get(f"{base}/stat/sta") or []
            except Exception as e:
                log.warning("unifi: no client list this poll (%s)", type(e).__name__)
                clients = []
        finally:
            conn.close()

        states = {}

        def seen(mac, ip, state):
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
                ip = unifi._gateway_addresses(d, [])[0]
            if d.get("state") in (0, 1):
                seen(d.get("mac"), ip, HEALTHY if d.get("state") == 1 else DOWN)
        for c in clients:
            if isinstance(c, dict):
                seen(c.get("mac"), c.get("ip"), HEALTHY)
        return {"nodes": {nid: {"state": state} for nid, state in states.items()}}


def unifi_places(data):
    import schema
    by_mac, by_ip, machine_at = {}, {}, set()
    nodes = [n for n in data.get("nodes", []) or [] if isinstance(n, dict) and n.get("id")]
    watched = {nid for nid in monitor_map(data).values() if nid}
    for node in nodes:
        nid = node["id"]
        if node.get("monitors") or any(isinstance(link, dict) and link.get("kuma")
                                       for link in node.get("links") or []):
            watched.add(nid)
        mac = schema.mac_key(node.get("mac"))
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
    import connections
    _, creds, insecure = connections.saved("unifi")
    if not connections.ready("unifi", creds):
        log.warning("unifi source requested but the UniFi connection has no credential "
                    "(an API key, or a user and its password) — skipping")
        return None
    return UniFiAdapter(url, creds, verify=not insecure)
