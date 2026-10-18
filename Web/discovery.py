"""The discovery inbox — devices seen on the wire that the map hasn't charted.

The plumbing for this has existed since Phase 1: `observed_nodes` rows, an
nmap importer that fills them, a relay that can push them, and
`/api/v1/sites/<slug>/observed` to read them. What was missing was anywhere to
*act* on it, so the drift signal only ever became a number.

This is the acting half — the Zabbix "auto-registration" / NetBox
"undocumented device" idea, kept deliberately manual: a scan proposes, a human
disposes. Nothing is ever charted automatically, because a guest VLAN would
otherwise fill the map with phones.

Works in both backends. In db mode it reads the real table; in file mode it
keeps its own small `observed.json` beside the dataset, so a homelab with no
database still gets the inbox.
"""

import ipaddress
import logging
import re

import settings
from jsonio import iso_utc
from jsonstore import JsonStore

log = logging.getLogger("atlas.live.discovery")


def _now():
    return iso_utc()


def key_of(host):
    """A stable key for an observed device: its address, else its MAC."""
    return host.get("ip") or host.get("mac") or ""


def slug_for(host, taken):
    """A map id for a discovered device — its hostname if it has one, else its
    address. Uniqueness matters more than elegance; a human renames it after."""
    base = (host.get("hostname") or "").split(".")[0].lower()
    if not base:
        base = "host-" + str(host.get("ip") or host.get("mac") or "unknown").replace(".", "-").replace(":", "")
    base = re.sub(r"[^a-z0-9-]+", "-", base).strip("-") or "device"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def zone_for_ip(data, ip):
    """The realm whose subnet contains this address, or None.

    Checks the most specific prefix first, so a /27 inside a /24 wins — the
    reason it walks `prefixes[]` before falling back to `zones[].subnet`.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return None
    best, best_len = None, -1
    for prefix in data.get("prefixes", []) or []:
        try:
            net = ipaddress.ip_network(prefix.get("cidr"), strict=False)
        except (ValueError, TypeError):
            continue
        if addr in net and net.prefixlen > best_len and prefix.get("zone"):
            best, best_len = prefix["zone"], net.prefixlen
    for zone in data.get("zones", []) or []:
        try:
            net = ipaddress.ip_network(zone.get("subnet"), strict=False)
        except (ValueError, TypeError):
            continue
        if addr in net and net.prefixlen > best_len:
            best, best_len = zone.get("id"), net.prefixlen
    return best


# ── The file-mode store ──────────────────────────────────────────────────────

def _shape(saved):
    saved = saved if isinstance(saved, dict) else {}
    return {"hosts": saved.get("hosts") or {}, "ignored": saved.get("ignored") or []}


#: The file-mode inbox: {hosts, ignored}. Path read live for settings reloads.
#: (db mode keeps its own store — `_record_db` and the ObservedNode queries.)
_STORE = JsonStore(lambda: settings.OBSERVED_PATH, _shape)


def record(hosts, backend=None, site=None):
    """Upsert a batch of observed devices. Returns how many were new.

    `first_seen` never moves and nothing is ever retired: a scan is evidence of
    what is present, never proof of what is gone.
    """
    backend = backend or settings.DATA_BACKEND
    if backend == "db":
        return _record_db(hosts, site or settings.SITE_SLUG)
    # read-modify-write, so it takes the same lock as every other writer
    with _STORE.locked():
        state = _STORE.load()
        new = _merge_hosts(state, hosts)
        _STORE.save(state)
    return new


def _merge_hosts(state, hosts):
    new = 0
    for host in hosts:
        key = key_of(host)
        if not key:
            continue
        existing = state["hosts"].get(key)
        if existing:
            existing.update({k: v for k, v in host.items() if v is not None})
            existing["last_seen"] = _now()
        else:
            state["hosts"][key] = {**host, "first_seen": _now(), "last_seen": _now(),
                                   "source": host.get("source") or "nmap"}
            new += 1
    return new


def _record_db(hosts, site_slug):
    from datetime import datetime, timezone

    from sqlalchemy import select

    from store import session_scope
    from store.labdata import get_site
    from store.models import ObservedNode

    now = datetime.now(timezone.utc)
    new = 0
    with session_scope() as session:
        site = get_site(session, site_slug)
        if site is None:
            return 0
        for host in hosts:
            row = session.scalar(select(ObservedNode).where(
                ObservedNode.site_id == site.id,
                ObservedNode.ip == host.get("ip"),
                ObservedNode.mac == host.get("mac")))
            if row is None:
                row = ObservedNode(site_id=site.id, ip=host.get("ip"), mac=host.get("mac"),
                                   source=host.get("source") or "nmap")
                session.add(row)
                new += 1
            row.hostname = host.get("hostname") or row.hostname
            row.raw_json = {"vendor": host.get("vendor"), "ports": host.get("ports") or []}
            row.last_seen = now
    return new


def listing(data, backend=None, site=None):
    """Every observed device, annotated with whether the map already has it.

    `undocumented` is the drift signal — a device on the wire with no marker.
    `ignored` is a human saying "yes, and I don't want it charted", which is
    the difference between an inbox and a nag.
    """
    backend = backend or settings.DATA_BACKEND
    charted = {}
    for node in data.get("nodes", []) or []:
        ip = node.get("ip")
        if isinstance(ip, str) and ip not in ("—", ""):
            charted[ip] = node.get("id")

    if backend == "db":
        rows = _listing_db(site or settings.SITE_SLUG)
        ignored = set(_STORE.load()["ignored"])   # the decision is server-local either way
    else:
        state = _STORE.load()
        ignored = set(state["ignored"])
        rows = []
        for key, host in state["hosts"].items():
            rows.append({
                "key": key,
                "ip": host.get("ip"),
                "mac": host.get("mac"),
                "hostname": host.get("hostname"),
                "vendor": host.get("vendor"),
                "ports": host.get("ports") or [],
                "source": host.get("source") or "nmap",
                "first_seen": host.get("first_seen"),
                "last_seen": host.get("last_seen"),
            })

    for row in rows:
        row["matched_node"] = charted.get(row.get("ip"))
        row["undocumented"] = row["matched_node"] is None
        row["ignored"] = row["key"] in ignored
        row["suggested_zone"] = zone_for_ip(data, row.get("ip"))
    rows.sort(key=lambda r: (not r["undocumented"], r["ignored"], str(r.get("ip") or "")))
    return rows


def _listing_db(site_slug):
    from sqlalchemy import select

    from store import session_scope
    from store.labdata import get_site
    from store.models import ObservedNode

    out = []
    with session_scope() as session:
        site = get_site(session, site_slug)
        if site is None:
            return []
        for row in session.scalars(select(ObservedNode).where(ObservedNode.site_id == site.id)):
            raw = row.raw_json or {}
            out.append({
                "key": row.ip or row.mac or str(row.id),
                "ip": row.ip, "mac": row.mac, "hostname": row.hostname,
                "vendor": raw.get("vendor"), "ports": raw.get("ports") or [],
                "source": row.source,
                "first_seen": row.first_seen.isoformat() if row.first_seen else None,
                "last_seen": row.last_seen.isoformat() if row.last_seen else None,
            })
    return out


def set_ignored(keys, ignored=True):
    """Silence (or un-silence) devices you don't want charted."""
    with _STORE.locked():
        state = _STORE.load()
        current = set(state["ignored"])
        current.update(keys) if ignored else current.difference_update(keys)
        state["ignored"] = sorted(current)
        _STORE.save(state)
        return len(state["ignored"])


def forget(keys):
    """Drop devices from the inbox entirely (file mode only)."""
    with _STORE.locked():
        state = _STORE.load()
        for key in keys:
            state["hosts"].pop(key, None)
        state["ignored"] = [k for k in state["ignored"] if k not in set(keys)]
        _STORE.save(state)
        return len(state["hosts"])


def as_node(host, data, taken=None):
    """Turn an observed device into a place, ready for an `insert` op.

    `kind` is deliberately `unknown` rather than a guess: promoting a scanned
    device as "physical" would be a claim the scan cannot support, and the map
    already renders unknown as a plain circle marker.
    """
    taken = taken if taken is not None else {n.get("id") for n in data.get("nodes", []) or []}
    zone = zone_for_ip(data, host.get("ip"))
    if not zone:
        zones = data.get("zones") or []
        zone = zones[0].get("id") if zones else "uncharted"
    ports = host.get("ports") or []
    port_note = ", ".join(str(p.get("port")) for p in ports[:6]) if ports else ""
    return {
        "id": slug_for(host, taken),
        "name": (host.get("hostname") or host.get("ip") or "UNKNOWN").upper(),
        "kind": "unknown",
        "zone": zone,
        "x": 50.0, "y": 50.0,
        "role": "found by a survey · not yet identified",
        "lore": "A stranger on the road. The surveyors noted it and moved on.",
        "ip": host.get("ip") or "—",
        "hw": " · ".join(x for x in [host.get("vendor"),
                                     f"open ports {port_note}" if port_note else ""] if x),
    }
