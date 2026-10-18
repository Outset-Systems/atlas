"""NetBox HTTP client — the half of the importer that talks to the network.

Deliberately free of any store/SQLAlchemy import: `atlas-relay` runs this on a
customer LAN with nothing but the standard library and `requests`, then pushes
the snapshot to the server, which owns the mapping half (netbox.py).
"""

USER_AGENT = "atlas-netbox/1.0"


class NetBoxError(RuntimeError):
    pass


class NetBoxClient:
    """Minimal paginated REST client (token auth, read-only)."""

    def __init__(self, url, token, timeout=20, verify=True):
        self.base = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.verify = verify

    def _get(self, path, params=None):
        import requests
        try:
            r = requests.get(
                self.base + path,
                params=params or {},
                headers={"Authorization": f"Token {self.token}", "User-Agent": USER_AGENT},
                timeout=self.timeout,
                verify=self.verify,
            )
        except requests.RequestException as e:
            raise NetBoxError(f"GET {path}: {e}") from e
        if r.status_code != 200:
            raise NetBoxError(f"GET {path}: HTTP {r.status_code} — {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise NetBoxError(f"GET {path}: not JSON") from e

    def paged(self, path, params=None):
        """Yield results across all pages; any failure raises (atomicity)."""
        params = dict(params or {}, limit=200)
        page = self._get(path, params)
        while True:
            if not isinstance(page, dict) or "results" not in page:
                raise NetBoxError(f"GET {path}: unexpected shape")
            yield from page["results"]
            nxt = page.get("next")
            if not nxt:
                return
            # follow the absolute next-URL (already carries the query string)
            page = self._get(nxt[len(self.base):] if nxt.startswith(self.base) else nxt)


def fetch_snapshot(client, netbox_site=None):
    """Pull everything a sync needs. Pure fetch — no DB writes here."""
    f = {"site": netbox_site} if netbox_site else {}
    return {
        "vlans": list(client.paged("/api/ipam/vlans/", f)),
        "prefixes": list(client.paged("/api/ipam/prefixes/", f)),
        "devices": list(client.paged("/api/dcim/devices/", f)),
        "vms": list(client.paged("/api/virtualization/virtual-machines/", f)),
    }
