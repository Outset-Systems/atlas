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
"""

import requests

import integrations

TIMEOUT = 6

#: key, name, what it is for, how to get a read-only credential, fields.
#: A field is (setting, label, hint, kind) and kind is url | secret | insecure.
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


_PROBES = {"proxmox": _proxmox, "portainer": _portainer, "komodo": _komodo, "netbox": _netbox}


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


_SURVEYS = {"proxmox": _survey_proxmox, "portainer": _survey_portainer,
            "komodo": _survey_komodo, "netbox": _survey_netbox}


def _asking(url, creds, ask):
    """Run one call to a system. Returns (True, answer) or (False, a sentence). Never
    raises: an answer of any kind is the point of the button."""
    base = (url or "").rstrip("/")
    if not base:
        return False, "No URL to ask."
    if not all(creds):
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
    return _asking(url, creds, lambda base: _PROBES[key](base, creds, not insecure))


def survey(key, url, creds, insecure=False):
    """Read what one system knows. Returns (True, (candidates, notes)) or
    (False, a sentence). Read-only: nothing here writes to the system or the map."""
    return _asking(url, creds, lambda base: _SURVEYS[key](base, creds, not insecure))


def label(key):
    return _BY_KEY[key]["name"]
