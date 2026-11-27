import requests

import integrations
from importers import hyperv, komodo, kuma, netbox, portainer, proxmox, unifi
from importers.wire import Refused as _Refused

CONNECTORS = (proxmox, hyperv, portainer, komodo, netbox, unifi, kuma)

SYSTEMS = tuple(m.SYSTEM for m in CONNECTORS)
_BY_KEY = {s["key"]: s for s in SYSTEMS}
_PROBES = {m.SYSTEM["key"]: m.probe for m in CONNECTORS}
_SURVEYS = {m.SYSTEM["key"]: m.survey for m in CONNECTORS}
_OBSERVERS = {m.SYSTEM["key"]: m.observe for m in CONNECTORS if hasattr(m, "observe")}
# A relayed system is one Atlas cannot reach: a relay on its network reads it and
# pushes a snapshot. It has no URL and no credential here, and its probe and
# survey take no arguments: they read what the relay last sent.
_RELAYED = {m.SYSTEM["key"]: m for m in CONNECTORS if m.SYSTEM.get("relay")}


def describe():
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
                    "observes": system["key"] in _OBSERVERS,
                    "relay": system["key"] in _RELAYED,
                    "configured": (_RELAYED[system["key"]].reported() if system["key"] in _RELAYED
                                   else any(f["kind"] == "url" and f["value"] for f in fields))})
    return out


def known(key):
    return key in _BY_KEY


def relayed(key):
    return key in _RELAYED


def field(key, kind):
    return [f[0] for f in _BY_KEY[key]["fields"] if f[3] == kind]


def credentials(key, value):
    return [value(f[0]) for f in _BY_KEY[key]["fields"] if f[3] in ("secret", "text")]


def insecure(key, value):
    names = field(key, "insecure")
    return bool(names) and str(value(names[0])).strip() == "1"


def ready(key, creds):
    test = _BY_KEY[key].get("ready")
    return test(creds) if test else all(creds)


def saved(key):
    if key in _RELAYED:
        return "", [], False
    return (integrations.get(field(key, "url")[0]), credentials(key, integrations.get),
            insecure(key, integrations.get))


def _with_monitors(rows, notes):
    url, creds, unverified = saved("kuma")
    url = url.rstrip("/")
    if not (url and all(creds)):
        return rows, notes
    from importers import review
    try:
        monitors = kuma.metrics(url, creds, not unverified)
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
    base = (url or "").rstrip("/")
    if not base:
        return False, "No URL to ask."
    if not ready(key, creds):
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


def _reported(ask):
    try:
        return True, ask()
    except _Refused as e:
        return False, str(e)
    except (ValueError, AttributeError, TypeError, KeyError):
        return False, "The relay's last report could not be read. Wait for its next one."


def probe(key, url, creds, insecure=False):
    if key in _RELAYED:
        return _reported(_RELAYED[key].probe)
    return _asking(key, url, creds, lambda base: _PROBES[key](base, creds, not insecure))


def survey(key, url, creds, insecure=False):
    if key in _RELAYED:
        ok, answer = _reported(_RELAYED[key].survey)
        return (True, _with_monitors(*answer)) if ok else (False, answer)

    def ask(base):
        rows, notes = _SURVEYS[key](base, creds, not insecure)
        return (rows, notes) if key == "kuma" else _with_monitors(rows, notes)
    return _asking(key, url, creds, ask)


def observes(key):
    return key in _OBSERVERS


def observe(key, url, creds, insecure=False):
    return _asking(key, url, creds, lambda base: _OBSERVERS[key](base, creds, not insecure))


def label(key):
    return _BY_KEY[key]["name"]
