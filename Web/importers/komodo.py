"""Komodo as review candidates: servers and stacks.

A server is a place. A stack is a service on it: its link opens the stack in Komodo.
A server reached by outbound Periphery has no `address`, so `public_ip` is the
fallback, and a server with neither lands with no address.
"""

from urllib.parse import quote

from . import review


def fetch_snapshot(read):
    """Everything a review needs, through `read(request) -> data`. Pure fetch."""
    return {"servers": read("ListServers") or [], "stacks": read("ListStacks") or []}


def _hw(info):
    bits = []
    if info.get("logical_core_count"):
        bits.append(f"{info['logical_core_count']} threads")
    if info.get("version"):
        bits.append(f"Periphery {info['version']}")
    return " · ".join(bits)


def candidates(snapshot, base):
    """(rows, notes). `base` is the Komodo URL the stack links point back at."""
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
        detail = f"{review.clean(info.get('state')) or 'unknown'} · {services} service{'' if services == 1 else 's'}"
        rows.append(review.service(
            f"komodo:stack/{stack_id}", "Stacks", stack.get("name"),
            f"{base}/stacks/{quote(str(stack_id), safe='')}",
            f"komodo:server/{server}" if server in known else None,
            "A stack managed in Komodo. This opens it there.", detail=detail))
    return rows, []
