import re
from urllib.parse import urlsplit

import requests

from . import review
from .wire import TIMEOUT, Refused, ok, plural

_LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')
_ABSENT = ("", "null", "undefined")


def _label(labels, name):
    value = labels.get(name, "")
    return "" if value in _ABSENT else value


def parse_metrics(text):
    out, seen = [], set()
    for line in str(text or "").splitlines():
        if not line.startswith("monitor_status{"):
            continue
        head, _, value = line.rpartition(" ")
        labels = dict(_LABEL.findall(head))
        name = review.clean(_label(labels, "monitor_name"))
        if not name or name in seen:
            continue
        seen.add(name)
        url = review.clean(_label(labels, "monitor_url"), 400)
        if not urlsplit(url).hostname:
            url = ""
        host = review.clean(_label(labels, "monitor_hostname")) or (urlsplit(url).hostname or "")
        try:
            state = int(float(value))
        except ValueError:
            state = None
        out.append({"name": name, "type": review.clean(_label(labels, "monitor_type")),
                    "url": url, "host": host, "port": review.clean(_label(labels, "monitor_port")),
                    "state": state})
    return out


_STATE = {0: "down", 1: "up", 2: "pending", 3: "maintenance"}


def candidates(monitors):
    rows = []
    for m in monitors:
        target = m["url"] or ":".join(b for b in (m["host"], m["port"]) if b)
        rows.append(review.monitor(f"kuma:monitor/{m['name']}", m["name"], m["host"],
                                   detail=" · ".join(b for b in (m["type"], target,
                                                                 _STATE.get(m["state"], "")) if b)))
    notes = [] if monitors else ["Kuma answered with no monitors."]
    return rows, notes


SYSTEM = {
    "key": "kuma", "name": "Uptime Kuma",
    "about": "Which monitor watches which place. The same address and key THE SOURCES uses.",
    "credential": "Settings → API Keys. A key opens /metrics and nothing else: it cannot "
                  "add, pause or delete a monitor.",
    "fields": (("ATLAS_KUMA_URL", "URL", "http://kuma.example:3001", "url"),
               ("ATLAS_KUMA_API_KEY", "API key", "", "secret"),
               ("ATLAS_KUMA_INSECURE", "Self-signed certificate", "", "insecure")),
}


def metrics(base, creds, verify):
    r = requests.get(base + "/metrics", auth=("", creds[0]), timeout=TIMEOUT, verify=verify,
                     allow_redirects=False)
    return parse_metrics(ok(r, "Uptime Kuma").text)


def probe(base, creds, verify):
    monitors = metrics(base, creds, verify)
    if not monitors:
        raise Refused("Kuma answered, but listed no monitors. Is that the key's own instance?")
    up = sum(1 for m in monitors if m["state"] == 1)
    return f"Uptime Kuma: {plural(len(monitors), 'monitor')}, {up} up"


def survey(base, creds, verify):
    return candidates(metrics(base, creds, verify))
