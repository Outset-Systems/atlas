from urllib.parse import quote

import requests

from . import review
from .wire import TIMEOUT, ok, plural

_DOCKER = (1, 2, 4)


def fetch_snapshot(get):
    return {"endpoints": get("/api/endpoints") or [], "stacks": get("/api/stacks") or []}


def _hw(env):
    snap = (env.get("Snapshots") or [{}])[0] or {}
    bits = []
    if snap.get("DockerVersion"):
        bits.append(f"Docker {snap['DockerVersion']}")
    if snap.get("TotalCPU"):
        bits.append(f"{snap['TotalCPU']} CPU")
    if snap.get("TotalMemory"):
        bits.append(f"{int(snap['TotalMemory'] / 1024 ** 3)}GB RAM")
    return " · ".join(bits)


def candidates(snapshot, base):
    rows, known = [], set()
    for env in snapshot.get("endpoints", []):
        key = f"portainer:env/{env.get('Id')}"
        known.add(env.get("Id"))
        role = "Docker host" if env.get("Type") in _DOCKER else "Cluster"
        rows.append(review.place(key, "Environments", env.get("Name"), "unknown",
                                 f"{role} · from Portainer", ip=review.address(env.get("URL")),
                                 hw=_hw(env)))
    for stack in snapshot.get("stacks", []):
        env, stack_id, name = stack.get("EndpointId"), stack.get("Id"), review.clean(stack.get("Name"))
        url = (f"{base}/#!/{env}/docker/stacks/{quote(name, safe='')}"
               f"?id={stack_id}&type={stack.get('Type')}&regular=true")
        rows.append(review.service(
            f"portainer:stack/{stack_id}", "Stacks", name, url,
            f"portainer:env/{env}" if env in known else None,
            "A stack managed in Portainer. This opens it there.",
            detail="running" if stack.get("Status") == 1 else "stopped"))
    return rows, []


SYSTEM = {
    "key": "portainer", "name": "Portainer",
    "about": "Docker environments and stacks.",
    "credential": "My account → Access tokens. A token has its owner's rights, so make it "
                  "from a read-only user.",
    "fields": (("ATLAS_PORTAINER_URL", "URL", "https://portainer.example:9443", "url"),
               ("ATLAS_PORTAINER_KEY", "Access token", "", "secret"),
               ("ATLAS_PORTAINER_INSECURE", "Self-signed certificate", "", "insecure")),
}


def _get(base, creds, verify):
    head = {"X-API-Key": creds[0]}
    return lambda p: ok(requests.get(base + p, headers=head, timeout=TIMEOUT, verify=verify,
                                     allow_redirects=False), "Portainer").json()


def probe(base, creds, verify):
    get = _get(base, creds, verify)
    return (f"Portainer: {plural(len(get('/api/endpoints') or []), 'environment')}, "
            f"{plural(len(get('/api/stacks') or []), 'stack')}")


def survey(base, creds, verify):
    return candidates(fetch_snapshot(_get(base, creds, verify)), base)
