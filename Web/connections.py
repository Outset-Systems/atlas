"""CONNECTIONS — the systems an Atlas can be pointed at, and a real test of each.

SolarWinds keeps one credential library and Zabbix one list of integrations, and
both pay off for the same reason: one screen answers "what does this touch, and
is it working?". This is that list. The settings live in `integrations.py` like
every other runtime setting, so secrets are encrypted the same way and the same
save route writes them.

A test is one or two read-only calls, and it reports what the system said: a
version and a count of what the credential can see. A survey reads what the system
knows, for the review step in `importers/review.py`. Neither writes to the map here:
an import is a separate, reviewed step, the way SolarWinds puts a results wizard
between discovery and monitoring, and it is never a background sync.

Each credential should be the system's read-only kind. The hints say which.

UniFi and Uptime Kuma are built as a pair. UniFi says what exists and how it is
wired; Kuma says whether it is up. A review of any system reads Kuma's monitors
too, when Kuma is set up here, so a place arrives with the monitors that watch it
(`review.watch`), and Kuma's own review ties monitors to places already charted.
"""

import requests

import integrations

TIMEOUT = 6

#: key, name, what it is for, how to get a read-only credential, fields.
#: A field is (setting, label, hint, kind) and kind is url | secret | text | insecure.
#: `ready` says which credentials are enough, given them in field order (secret and
#: text fields both); without it, every one is needed.
SYSTEMS = (
    {"key": "proxmox", "name": "Proxmox VE",
     "about": "Nodes, virtual machines and containers.",
     "credential": "Datacenter → Permissions → API Tokens. Give the token the PVEAuditor "
                   "role on /. Paste it as user@pam!name=secret.",
     "fields": (("ATLAS_PROXMOX_URL", "URL", "https://proxmox.example:8006", "url"),
                ("ATLAS_PROXMOX_TOKEN", "API token", "", "secret"),
                ("ATLAS_PROXMOX_INSECURE", "Self-signed certificate", "", "insecure"))},
    {"key": "portainer", "name": "Portainer",
     "about": "Docker environments and stacks.",
     "credential": "My account → Access tokens. A token has its owner's rights, so make it "
                   "from a read-only user.",
     "fields": (("ATLAS_PORTAINER_URL", "URL", "https://portainer.example:9443", "url"),
                ("ATLAS_PORTAINER_KEY", "Access token", "", "secret"),
                ("ATLAS_PORTAINER_INSECURE", "Self-signed certificate", "", "insecure"))},
    {"key": "komodo", "name": "Komodo",
     "about": "Servers and stacks.",
     "credential": "Settings → API keys, for a user who only has read access.",
     "fields": (("ATLAS_KOMODO_URL", "URL", "https://komodo.example:9120", "url"),
                ("ATLAS_KOMODO_KEY", "API key", "", "secret"),
                ("ATLAS_KOMODO_SECRET", "API secret", "", "secret"),
                ("ATLAS_KOMODO_INSECURE", "Self-signed certificate", "", "insecure"))},
    {"key": "netbox", "name": "NetBox",
     "about": "Devices, virtual machines and VLANs.",
     "credential": "User menu → API tokens, with Write enabled turned off.",
     "fields": (("ATLAS_NETBOX_URL", "URL", "https://netbox.example", "url"),
                ("ATLAS_NETBOX_API_TOKEN", "API token", "", "secret"),
                ("ATLAS_NETBOX_INSECURE", "Self-signed certificate", "", "insecure"))},
    {"key": "unifi", "name": "UniFi Network",
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
     "ready": lambda c: bool(c[1] or (c[2] and c[3]))},
    {"key": "kuma", "name": "Uptime Kuma",
     "about": "Which monitor watches which place. The same address and key THE SOURCES uses.",
     "credential": "Settings → API Keys. A key opens /metrics and nothing else: it cannot "
                   "add, pause or delete a monitor.",
     "fields": (("ATLAS_KUMA_URL", "URL", "http://kuma.example:3001", "url"),
                ("ATLAS_KUMA_API_KEY", "API key", "", "secret"),
                ("ATLAS_KUMA_INSECURE", "Self-signed certificate", "", "insecure"))},
)
_BY_KEY = {s["key"]: s for s in SYSTEMS}


def describe():
    """The catalogue for the form, with each field's state from `integrations`."""
    settings_now = integrations.describe()
    out = []
    for system in SYSTEMS:
        fields = []
        for key, label, hint, kind in system["fields"]:
            f = settings_now.get(key) or {}
            fields.append({"key": key, "label": label, "hint": hint, "kind": kind,
                           "value": f.get("value") or "", "set": bool(f.get("set")),
                           "source": f.get("source") or ""})
        out.append({"key": system["key"], "name": system["name"], "about": system["about"],
                    "credential": system["credential"], "fields": fields,
                    "configured": any(f["kind"] == "url" and f["value"] for f in fields)})
    return out


def known(key):
    return key in _BY_KEY


def field(key, kind):
    """The setting names of a system's `kind` fields, in order."""
    return [f[0] for f in _BY_KEY[key]["fields"] if f[3] == kind]


def credentials(key, value):
    """What a system is asked with: its secret and text fields in order, each read
    through `value(name)`. The routes pass a reader of the typed values or of the
    saved ones; the secrets themselves never travel further than the call."""
    return [value(f[0]) for f in _BY_KEY[key]["fields"] if f[3] in ("secret", "text")]


def insecure(key, value):
    """The self-signed tick, through `value(name)`, or False for a system without one."""
    names = field(key, "insecure")
    return bool(names) and str(value(names[0])).strip() == "1"


def _ready(key, creds):
    test = _BY_KEY[key].get("ready")
    return test(creds) if test else all(creds)


class _Refused(Exception):
    """The system answered and said no. Its message is what the admin needs."""


def _ok(resp, who):
    if resp.status_code in (401, 403):
        raise _Refused(f"{who} refused the credential.")
    if 300 <= resp.status_code < 400:
        # Never followed: a redirect would carry the credential to wherever it points.
        raise _Refused(f"{who} redirected to {resp.headers.get('Location', 'somewhere else')}. "
                       "Use the final URL.")
    resp.raise_for_status()
    return resp


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _proxmox_get(base, creds, verify):
    head = {"Authorization": f"PVEAPIToken={creds[0]}"}
    return lambda p: _ok(requests.get(base + p, headers=head, timeout=TIMEOUT, verify=verify,
                                      allow_redirects=False), "Proxmox").json().get("data")


def _proxmox(base, creds, verify):
    get = _proxmox_get(base, creds, verify)
    version = (get("/api2/json/version") or {}).get("version", "?")
    rows = get("/api2/json/cluster/resources") or []
    if not rows:
        raise _Refused("Proxmox answered, but this token can see nothing. Give it PVEAuditor on /.")
    nodes = sum(1 for r in rows if r.get("type") == "node")
    guests = sum(1 for r in rows if r.get("type") in ("qemu", "lxc"))
    return f"Proxmox VE {version}: {_plural(nodes, 'node')}, {_plural(guests, 'guest')}"


def _portainer_get(base, creds, verify):
    head = {"X-API-Key": creds[0]}
    return lambda p: _ok(requests.get(base + p, headers=head, timeout=TIMEOUT, verify=verify,
                                      allow_redirects=False), "Portainer").json()


def _portainer(base, creds, verify):
    get = _portainer_get(base, creds, verify)
    return (f"Portainer: {_plural(len(get('/api/endpoints') or []), 'environment')}, "
            f"{_plural(len(get('/api/stacks') or []), 'stack')}")


def _komodo_read(base, creds, verify):
    head = {"x-api-key": creds[0], "x-api-secret": creds[1], "content-type": "application/json"}

    def read(kind):
        r = requests.post(base + "/read", json={"type": kind, "params": {}}, headers=head,
                          timeout=TIMEOUT, verify=verify, allow_redirects=False)
        return _ok(r, "Komodo").json()

    return read


def _komodo(base, creds, verify):
    read = _komodo_read(base, creds, verify)
    version = read("GetVersion")
    version = version.get("version", "?") if isinstance(version, dict) else version
    return (f"Komodo {version}: {_plural(len(read('ListServers') or []), 'server')}, "
            f"{_plural(len(read('ListStacks') or []), 'stack')}")


def _netbox(base, creds, verify):
    # v2 tokens (nbt_...) are bearer tokens; the older kind says `Token`.
    scheme = "Bearer" if creds[0].startswith("nbt_") else "Token"
    head = {"Authorization": f"{scheme} {creds[0]}", "Accept": "application/json"}
    get = lambda p: _ok(requests.get(base + p, headers=head, timeout=TIMEOUT,   # noqa: E731
                                     verify=verify, allow_redirects=False), "NetBox").json()
    version = get("/api/status/").get("netbox-version", "?")
    return f"NetBox {version}: {_plural(get('/api/dcim/devices/?limit=1').get('count', 0), 'device')}"


class _UniFi:
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
                raise _Refused("UniFi refused the user name and password. A cloud account "
                               "with MFA cannot sign in here: use a local account.")
            _ok(r, "UniFi")
            jar = getattr(r, "cookies", None)
            self.cookies = jar.get_dict() if hasattr(jar, "get_dict") else dict(jar or {})
            token = r.headers.get("X-CSRF-Token") or r.headers.get("x-csrf-token")
            if token:
                self.head["X-CSRF-Token"] = token
            self.prefix, self.out = prefix, logout
            return
        raise _Refused("UniFi did not offer a sign-in at this address. Is it the controller's URL?")

    def get(self, path):
        r = requests.get(self.base + self.prefix + path, headers=self.head, cookies=self.cookies,
                         timeout=TIMEOUT, verify=self.verify, allow_redirects=False)
        body = _ok(r, "UniFi").json()
        if isinstance(body, dict) and (body.get("meta") or {}).get("rc") == "error":
            raise _Refused(f"UniFi said no: {(body.get('meta') or {}).get('msg') or 'an error'}.")
        return body.get("data") if isinstance(body, dict) else body

    def close(self):
        if not self.out:
            return
        try:
            requests.post(self.base + self.out, headers=self.head, cookies=self.cookies,
                          timeout=TIMEOUT, verify=self.verify, allow_redirects=False)
        except requests.exceptions.RequestException:
            pass                               # the session times out on its own


def _with_unifi(base, creds, verify, ask):
    from importers import unifi
    try:
        unifi.site_path(creds[0])
    except ValueError as e:
        raise _Refused(str(e)) from e
    conn = _UniFi(base, creds, verify)
    try:
        return ask(conn, creds[0] or unifi.DEFAULT_SITE)
    finally:
        conn.close()


def _unifi(base, creds, verify):
    def ask(conn, site):
        sites = conn.get("/api/self/sites") or []
        names = [s.get("name") for s in sites if isinstance(s, dict)]
        if site not in names:
            listed = ", ".join(f"{s.get('name')} ({s.get('desc')})" for s in sites[:6]
                               if isinstance(s, dict)) or "none"
            raise _Refused(f"This controller has no site called {site}. It has: {listed}.")
        devices = conn.get(f"/api/s/{site}/stat/device") or []
        clients = conn.get(f"/api/s/{site}/stat/sta") or []
        return (f"UniFi site {site}: {_plural(len(devices), 'device')}, "
                f"{_plural(len(clients), 'client')} connected")
    return _with_unifi(base, creds, verify, ask)


def _kuma_metrics(base, creds, verify):
    # Kuma's /metrics is HTTP Basic: no user name, the key as the password
    r = requests.get(base + "/metrics", auth=("", creds[0]), timeout=TIMEOUT, verify=verify,
                     allow_redirects=False)
    from importers import kuma
    return kuma.parse_metrics(_ok(r, "Uptime Kuma").text)


def _kuma(base, creds, verify):
    monitors = _kuma_metrics(base, creds, verify)
    if not monitors:
        raise _Refused("Kuma answered, but listed no monitors. Is that the key's own instance?")
    up = sum(1 for m in monitors if m["state"] == 1)
    return f"Uptime Kuma: {_plural(len(monitors), 'monitor')}, {up} up"


_PROBES = {"proxmox": _proxmox, "portainer": _portainer, "komodo": _komodo, "netbox": _netbox,
           "unifi": _unifi, "kuma": _kuma}


def _survey_proxmox(base, creds, verify):
    from importers import proxmox
    return proxmox.candidates(proxmox.fetch_snapshot(_proxmox_get(base, creds, verify)))


def _survey_portainer(base, creds, verify):
    from importers import portainer
    return portainer.candidates(portainer.fetch_snapshot(_portainer_get(base, creds, verify)), base)


def _survey_komodo(base, creds, verify):
    from importers import komodo
    return komodo.candidates(komodo.fetch_snapshot(_komodo_read(base, creds, verify)), base)


def _survey_netbox(base, creds, verify):
    from importers.netbox import NetBoxClient, NetBoxError, candidates, fetch_snapshot
    try:
        return candidates(fetch_snapshot(NetBoxClient(base, creds[0], timeout=TIMEOUT * 2, verify=verify)))
    except NetBoxError as e:
        if e.status in (401, 403):
            raise _Refused("NetBox refused the credential.") from e
        if 300 <= (e.status or 0) < 400:
            raise _Refused("NetBox redirected somewhere else. Use the final URL.") from e
        if isinstance(e.__cause__, requests.exceptions.RequestException):
            raise e.__cause__
        raise _Refused(f"NetBox answered, but not usefully: {e}") from e


def _survey_unifi(base, creds, verify):
    from importers import unifi
    return _with_unifi(base, creds, verify,
                       lambda conn, site: unifi.candidates(unifi.fetch_snapshot(conn.get, site)))


def _survey_kuma(base, creds, verify):
    from importers import kuma
    return kuma.candidates(_kuma_metrics(base, creds, verify))


_SURVEYS = {"proxmox": _survey_proxmox, "portainer": _survey_portainer,
            "komodo": _survey_komodo, "netbox": _survey_netbox,
            "unifi": _survey_unifi, "kuma": _survey_kuma}


def _with_monitors(rows, notes):
    """Kuma's monitors on the places a review found, when Kuma is set up here. Its
    saved address and key only, the same as its own review; it never stops a review."""
    url = integrations.get("ATLAS_KUMA_URL").rstrip("/")
    key = integrations.get("ATLAS_KUMA_API_KEY")
    if not (url and key):
        return rows, notes
    from importers import review
    try:
        monitors = _kuma_metrics(url, [key], not insecure("kuma", integrations.get))
    except (_Refused, requests.exceptions.RequestException, ValueError) as e:
        why = str(e).rstrip(".") if isinstance(e, _Refused) else "it did not answer"
        return rows, notes + [f"Uptime Kuma is set up but did not list its monitors ({why}), "
                              "so no monitors come with this review."]
    watched = review.watch(rows, monitors)
    if watched:
        notes = notes + [f"Kuma watches {watched} of these place{'' if watched == 1 else 's'}. "
                         "Their monitors land with them."]
    return rows, notes


def _asking(key, url, creds, ask):
    """Run one call to a system. Returns (True, answer) or (False, a sentence). Never
    raises: an answer of any kind is the point of the button."""
    base = (url or "").rstrip("/")
    if not base:
        return False, "No URL to ask."
    if not _ready(key, creds):
        return False, "No credential to ask with."
    try:
        return True, ask(base)
    except _Refused as e:
        return False, str(e)
    except requests.exceptions.SSLError:
        return False, "The certificate was not trusted. If it is self-signed, tick the box."
    except requests.exceptions.RequestException as e:
        return False, f"Did not answer: {e.__class__.__name__}."
    except (ValueError, AttributeError, TypeError):
        return False, "It answered, but not in a way this Atlas understands. Is that the right URL?"


def probe(key, url, creds, insecure=False):
    """Ask one system who it is. Returns (ok, detail)."""
    return _asking(key, url, creds, lambda base: _PROBES[key](base, creds, not insecure))


def survey(key, url, creds, insecure=False):
    """Read what one system knows. Returns (True, (candidates, notes)) or
    (False, a sentence). Read-only: nothing here writes to the system or the map."""
    def ask(base):
        rows, notes = _SURVEYS[key](base, creds, not insecure)
        return (rows, notes) if key == "kuma" else _with_monitors(rows, notes)
    return _asking(key, url, creds, ask)


def label(key):
    return _BY_KEY[key]["name"]
