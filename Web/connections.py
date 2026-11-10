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
from importers import komodo, kuma, netbox, portainer, proxmox, unifi
from importers.wire import Refused as _Refused

#: THE REGISTRY. One module per system, in the order Settings lists them. Each
#: has `SYSTEM` (its catalogue entry), `probe` and `survey` (importers/wire.py
#: says what each must do). Adding a system is a module and a name on this line.
CONNECTORS = (proxmox, portainer, komodo, netbox, unifi, kuma)

#: key, name, what it is for, how to get a read-only credential, fields.
#: A field is (setting, label, hint, kind) and kind is url | secret | text | insecure.
#: `ready` says which credentials are enough, given them in field order (secret and
#: text fields both); without it, every one is needed.
SYSTEMS = tuple(m.SYSTEM for m in CONNECTORS)
_BY_KEY = {s["key"]: s for s in SYSTEMS}
_PROBES = {m.SYSTEM["key"]: m.probe for m in CONNECTORS}
_SURVEYS = {m.SYSTEM["key"]: m.survey for m in CONNECTORS}


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


def _with_monitors(rows, notes):
    """Kuma's monitors on the places a review found, when Kuma is set up here. Its
    saved address and key only, the same as its own review; it never stops a review."""
    url = integrations.get("ATLAS_KUMA_URL").rstrip("/")
    key = integrations.get("ATLAS_KUMA_API_KEY")
    if not (url and key):
        return rows, notes
    from importers import review
    try:
        monitors = kuma.metrics(url, [key], not insecure("kuma", integrations.get))
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
