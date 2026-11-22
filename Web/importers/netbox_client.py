from urllib.parse import urlsplit

USER_AGENT = "atlas-netbox/1.0"


class NetBoxError(RuntimeError):

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NetBoxClient:

    def __init__(self, url, token, timeout=20, verify=True):
        self.base = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.verify = verify

    def _get(self, path, params=None):
        import requests
        scheme = "Bearer" if self.token.startswith("nbt_") else "Token"
        try:
            r = requests.get(
                self.base + path,
                params=params or {},
                headers={"Authorization": f"{scheme} {self.token}", "User-Agent": USER_AGENT},
                timeout=self.timeout,
                verify=self.verify,
                allow_redirects=False,
            )
        except requests.RequestException as e:
            raise NetBoxError(f"GET {path}: {e}") from e
        if r.status_code != 200:
            raise NetBoxError(f"GET {path}: HTTP {r.status_code} — {r.text[:200]}",
                              status=r.status_code)
        try:
            return r.json()
        except ValueError as e:
            raise NetBoxError(f"GET {path}: not JSON") from e

    def paged(self, path, params=None):
        params = dict(params or {}, limit=200)
        page = self._get(path, params)
        while True:
            if not isinstance(page, dict) or "results" not in page:
                raise NetBoxError(f"GET {path}: unexpected shape")
            yield from page["results"]
            nxt = page.get("next")
            if not nxt:
                return
            if nxt.startswith(self.base):
                nxt = nxt[len(self.base):]
            else:
                parts = urlsplit(nxt)
                nxt = f"{parts.path}?{parts.query}"
            page = self._get(nxt)


def fetch_snapshot(client, netbox_site=None):
    f = {"site": netbox_site} if netbox_site else {}
    return {
        "vlans": list(client.paged("/api/ipam/vlans/", f)),
        "prefixes": list(client.paged("/api/ipam/prefixes/", f)),
        "devices": list(client.paged("/api/dcim/devices/", f)),
        "vms": list(client.paged("/api/virtualization/virtual-machines/", f)),
    }
