import ipaddress
import logging
import re

import layoutgrid
import settings
from jsonio import iso_utc
from jsonstore import JsonStore

log = logging.getLogger("atlas.live.discovery")


def _now():
    return iso_utc()


def key_of(host):
    return host.get("ip") or host.get("mac") or ""


def slug_for(host, taken):
    base = (host.get("hostname") or "").split(".")[0].lower()
    if not base:
        base = "host-" + str(host.get("ip") or host.get("mac") or "unknown").replace(".", "-").replace(":", "")
    base = re.sub(r"[^a-z0-9-]+", "-", base).strip("-") or "device"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _is_address(text):
    try:
        ipaddress.ip_address(str(text))
        return True
    except ValueError:
        return False


def zone_for_ip(data, ip):
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



def _shape(saved):
    saved = saved if isinstance(saved, dict) else {}
    return {"hosts": saved.get("hosts") or {}, "ignored": saved.get("ignored") or []}


_STORE = JsonStore(lambda: settings.OBSERVED_PATH, _shape)


def record(hosts, backend=None, site=None):
    backend = backend or settings.DATA_BACKEND
    if backend == "db":
        return _record_db(hosts, site or settings.SITE_SLUG)
    with _STORE.locked():
        state = _STORE.load()
        new = _merge_hosts(state, hosts)
        _STORE.save(state)
    return new


def merge_into(existing, host):
    incoming = {k: v for k, v in host.items() if v is not None}
    if incoming.get("source") in ("dhcp", "unifi"):
        incoming = {k: v for k, v in incoming.items()
                    if k in ("ip", "source") or not existing.get(k)}
    incoming["source"] = _sources(existing.get("source"), host.get("source"))
    existing.update(incoming)
    return existing


def _merge_hosts(state, hosts):
    new = 0
    for host in hosts:
        key = key_of(host)
        if not key:
            continue
        existing = state["hosts"].get(key)
        if existing:
            merge_into(existing, host)
            existing["last_seen"] = _now()
        else:
            state["hosts"][key] = {**host, "first_seen": _now(), "last_seen": _now(),
                                   "source": host.get("source") or "nmap"}
            new += 1
    return new


def _sources(had, new):
    names = [s.strip() for s in f"{had or ''},{new or 'nmap'}".split(",") if s.strip()]
    return ", ".join(dict.fromkeys(names))


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
            if not key_of(host):
                continue
            row = _observed_row(session, select, ObservedNode, site.id, host)
            if row is None:
                row = ObservedNode(site_id=site.id, ip=host.get("ip"), mac=host.get("mac"),
                                   hostname=host.get("hostname"),
                                   source=host.get("source") or "nmap",
                                   raw_json={"vendor": host.get("vendor"),
                                             "ports": host.get("ports") or []})
                session.add(row)
                new += 1
            else:
                raw = dict(row.raw_json or {})
                known = merge_into({"ip": row.ip, "mac": row.mac, "hostname": row.hostname,
                                    "vendor": raw.get("vendor"), "ports": raw.get("ports"),
                                    "source": row.source}, host)
                row.mac, row.hostname, row.source = known.get("mac"), known.get("hostname"), known["source"]
                row.raw_json = {**raw, "vendor": known.get("vendor"), "ports": known.get("ports") or []}
            row.last_seen = now
    return new


def _observed_row(session, select, ObservedNode, site_id, host):
    ip, mac = host.get("ip"), host.get("mac")
    q = select(ObservedNode).where(ObservedNode.site_id == site_id)
    q = q.where(ObservedNode.ip == ip) if ip else q.where(ObservedNode.ip.is_(None), ObservedNode.mac == mac)
    rows = session.scalars(q.order_by(ObservedNode.id)).all()
    if not rows:
        return None
    return next((r for r in rows if mac and r.mac == mac), rows[0])


def listing(data, backend=None, site=None):
    backend = backend or settings.DATA_BACKEND
    charted = {}
    for node in data.get("nodes", []) or []:
        ip = node.get("ip")
        if isinstance(ip, str) and ip not in ("—", ""):
            charted[ip] = node.get("id")

    if backend == "db":
        rows = _listing_db(site or settings.SITE_SLUG)
        ignored = set(_STORE.load()["ignored"])
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

    import suggest
    for row in rows:
        row["matched_node"] = charted.get(row.get("ip"))
        row["undocumented"] = row["matched_node"] is None
        row["ignored"] = row["key"] in ignored
        row["suggested_zone"] = zone_for_ip(data, row.get("ip"))
        row["vendor"] = row.get("vendor") or suggest.virtual_vendor(row.get("mac"))
        row["suggestion"] = suggest.suggest(row)
    rows.sort(key=lambda r: (not r["undocumented"], r["ignored"], _address_order(r.get("ip"))))
    return rows


def _address_order(ip):
    try:
        addr = ipaddress.ip_address(str(ip))
        return (0, addr.version, int(addr), "")
    except ValueError:
        return (1, 0, 0, str(ip or ""))


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


def ignored():
    return set(_STORE.load()["ignored"])


def set_ignored(keys, ignored=True):
    with _STORE.locked():
        state = _STORE.load()
        current = set(state["ignored"])
        current.update(keys) if ignored else current.difference_update(keys)
        state["ignored"] = sorted(current)
        _STORE.save(state)
        return len(state["ignored"])


def forget(keys):
    with _STORE.locked():
        state = _STORE.load()
        for key in keys:
            state["hosts"].pop(key, None)
        state["ignored"] = [k for k in state["ignored"] if k not in set(keys)]
        _STORE.save(state)
        return len(state["hosts"])




def place_drafts(data, drafts):
    def num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    anchors, band = {}, 0
    for z in data.get("zones", []) or []:
        if num(z.get("label_x")) and num(z.get("label_y")):
            anchors[z.get("id")] = (z["label_x"], z["label_y"] + 6.0)
        else:
            anchors[z.get("id")] = (layoutgrid.BAND_CENTER_X,
                                    layoutgrid.BAND_TOP + layoutgrid.BAND_STEP * band + 6.0)
            band += 1
    residents = {}
    for n in data.get("nodes", []) or []:
        zone = n.get("zone") if isinstance(n.get("zone"), str) else None
        residents[zone] = residents.get(zone, 0) + 1
    slots = {}
    for node in drafts:
        zone = node.get("zone")
        ax, ay = anchors.get(zone, (layoutgrid.BAND_CENTER_X, 120.0))
        slot = residents.get(zone, 0) + slots.get(zone, 0)
        slots[zone] = slots.get(zone, 0) + 1
        x, y = layoutgrid.grid_slot(ax, ay, slot)
        node["x"], node["y"] = round(x, 1), round(y, 1)
    return drafts


def as_node(host, data, taken=None):
    import suggest
    taken = taken if taken is not None else {n.get("id") for n in data.get("nodes", []) or []}
    zone = zone_for_ip(data, host.get("ip"))
    if not zone:
        zones = data.get("zones") or []
        zone = zones[0].get("id") if zones else "uncharted"
    ports = host.get("ports") or []
    port_note = ", ".join(str(p.get("port")) for p in ports[:6]) if ports else ""
    hostname = host.get("hostname") or ""
    short = hostname.split(".")[0] if hostname and not _is_address(hostname) else hostname
    vendor = host.get("vendor") or suggest.virtual_vendor(host.get("mac"))
    guess = host.get("suggestion") if "suggestion" in host else suggest.suggest(host)
    return {
        "id": slug_for(host, taken),
        "name": (short or host.get("ip") or "UNKNOWN").upper(),
        "kind": guess["kind"] if guess else "unknown",
        "zone": zone,
        "x": 50.0, "y": 50.0,
        "role": (f"looks like {guess['role']} · {guess['because']} — check it" if guess
                 else "found by a survey · not yet identified"),
        "lore": "A stranger on the road. The surveyors noted it and moved on.",
        "ip": host.get("ip") or "—",
        "hw": " · ".join(x for x in [vendor,
                                     f"open ports {port_note}" if port_note else ""] if x),
    }
