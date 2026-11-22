from urllib.parse import quote

import requests

from . import review
from .wire import TIMEOUT, ok, plural


def fetch_snapshot(read):
    return {"servers": read("ListServers") or [], "stacks": read("ListStacks") or []}


def _hw(info):
    bits = []
    if info.get("logical_core_count"):
        bits.append(f"{info['logical_core_count']} threads")
    if info.get("version"):
        bits.append(f"Periphery {info['version']}")
    return " · ".join(bits)


def candidates(snapshot, base):
    rows, known = [], set()
    for server in snapshot.get("servers", []):
        info = server.get("info") or {}
        known.add(server.get("id"))
        ip = review.address(info.get("address"))
        if ip == "—":
            ip = review.address(info.get("public_ip"))
        hw = _hw(info)
        rows.append(review.place(f"komodo:server/{server.get('id')}", "Servers", server.get("name"),
                                 "unknown", "Docker host · from Komodo", ip=ip, hw=hw,
                                 detail=" · ".join(b for b in (hw, review.clean(info.get("state"))) if b)))
    for stack in snapshot.get("stacks", []):
        info, stack_id = stack.get("info") or {}, stack.get("id")
        server = info.get("server_id")
        services = len(info.get("services") or [])
        detail = f"{review.clean(info.get('state')) or 'unknown'} · {plural(services, 'service')}"
        rows.append(review.service(
            f"komodo:stack/{stack_id}", "Stacks", stack.get("name"),
            f"{base}/stacks/{quote(str(stack_id), safe='')}",
            f"komodo:server/{server}" if server in known else None,
            "A stack managed in Komodo. This opens it there.", detail=detail))
    return rows, []


SYSTEM = {
    "key": "komodo", "name": "Komodo",
    "about": "Servers and stacks.",
    "credential": "Settings → API keys, for a user who only has read access.",
    "fields": (("ATLAS_KOMODO_URL", "URL", "https://komodo.example:9120", "url"),
               ("ATLAS_KOMODO_KEY", "API key", "", "secret"),
               ("ATLAS_KOMODO_SECRET", "API secret", "", "secret"),
               ("ATLAS_KOMODO_INSECURE", "Self-signed certificate", "", "insecure")),
}


def _read(base, creds, verify):
    head = {"x-api-key": creds[0], "x-api-secret": creds[1], "content-type": "application/json"}

    def read(kind):
        r = requests.post(base + "/read", json={"type": kind, "params": {}}, headers=head,
                          timeout=TIMEOUT, verify=verify, allow_redirects=False)
        return ok(r, "Komodo").json()

    return read


def probe(base, creds, verify):
    read = _read(base, creds, verify)
    version = read("GetVersion")
    version = version.get("version", "?") if isinstance(version, dict) else version
    return (f"Komodo {version}: {plural(len(read('ListServers') or []), 'server')}, "
            f"{plural(len(read('ListStacks') or []), 'stack')}")


def survey(base, creds, verify):
    return candidates(fetch_snapshot(_read(base, creds, verify)), base)
