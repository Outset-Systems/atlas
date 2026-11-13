"""The discovery inbox — devices seen on the wire that the map hasn't charted.

The plumbing for this has existed since Phase 1: `observed_nodes` rows, an
nmap importer that fills them, a relay that can push them, and
`/api/v2/sites/<slug>/observed` to read them. What was missing was anywhere to
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

import layoutgrid
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


def _is_address(text):
    try:
        ipaddress.ip_address(str(text))
        return True
    except ValueError:
        return False


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
            incoming = {k: v for k, v in host.items() if v is not None}
            if incoming.get("source") in ("dhcp", "unifi"):
                # a lease, or a controller's client list, adds what a scan could
                # not see (the MAC, the name the device gave itself) and never
                # overwrites what one found
                incoming = {k: v for k, v in incoming.items()
                            if k in ("ip", "source") or not existing.get(k)}
            incoming["source"] = _sources(existing.get("source"), host.get("source"))
            existing.update(incoming)
            existing["last_seen"] = _now()
        else:
            state["hosts"][key] = {**host, "first_seen": _now(), "last_seen": _now(),
                                   "source": host.get("source") or "nmap"}
            new += 1
    return new


def _sources(had, new):
    """Every source that has seen a device, e.g. "nmap, dhcp"."""
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
            row = session.scalar(select(ObservedNode).where(
                ObservedNode.site_id == site.id,
                ObservedNode.ip == host.get("ip"),
                ObservedNode.mac == host.get("mac")))
            if row is None:
                row = ObservedNode(site_id=site.id, ip=host.get("ip"), mac=host.get("mac"),
                                   source=host.get("source") or "nmap")
                session.add(row)
                new += 1
            else:
                row.source = _sources(row.source, host.get("source"))
            # merge, as the file store does: a lease carries no vendor or ports,
            # and must not erase what a scan of the same device found
            raw = dict(row.raw_json or {})
            if host.get("vendor"):
                raw["vendor"] = host["vendor"]
            if "ports" in host:
                raw["ports"] = host.get("ports") or []
            raw.setdefault("ports", [])
            raw.setdefault("vendor", None)
            if host.get("source") == "dhcp":
                row.hostname = row.hostname or host.get("hostname")
            else:
                row.hostname = host.get("hostname") or row.hostname
            row.raw_json = raw
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

    import suggest
    for row in rows:
        row["matched_node"] = charted.get(row.get("ip"))
        row["undocumented"] = row["matched_node"] is None
        row["ignored"] = row["key"] in ignored
        row["suggested_zone"] = zone_for_ip(data, row.get("ip"))
        # a lease names no maker, but a hypervisor's virtual NIC is its own
        row["vendor"] = row.get("vendor") or suggest.virtual_vendor(row.get("mac"))
        row["suggestion"] = suggest.suggest(row)
    rows.sort(key=lambda r: (not r["undocumented"], r["ignored"], _address_order(r.get("ip"))))
    return rows


def _address_order(ip):
    """Sort addresses as numbers (10.0.0.2 before 10.0.0.10), v4 before v6;
    anything that is not an address after them, as text."""
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
    """Every key a human has said not to chart. One list for the survey and for the
    connections review, whose keys read `proxmox:qemu/101` and cannot collide."""
    return set(_STORE.load()["ignored"])


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


# Draft placement uses the grid store.layout uses (`layoutgrid`), so both
# backends lay a survey out the same way: five across, 7% apart, starting just
# under the realm's label and below whatever already stands there.


def place_drafts(data, drafts):
    """Give each draft place a spot of its own near its realm's label.

    `as_node` drafts all start at (50, 50); charting twenty scanned devices
    used to stack them in one pile in the middle of the map. Each realm's
    drafts are gridded under its label, after the places it already has, so
    they arrive readable and in a stable order. Mutates and returns `drafts`.
    """
    def num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    # a labelled realm clusters under its label; an unlabelled one gets a band
    # of its own down the table (store.layout's bands), and a realm the map
    # has never heard of goes to the void below it, so no two groups share one
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
        residents[n.get("zone")] = residents.get(n.get("zone"), 0) + 1
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
    """Turn an observed device into a place, ready for an `insert` op.

    `kind` is `unknown` unless its maker, its own name or its virtual NIC
    gives it away (suggest.py), and then the draft says so in its role line:
    a suggestion the human sees and corrects before anything is written, not a
    claim the scan cannot support. The map renders unknown as a plain circle.
    """
    import suggest
    taken = taken if taken is not None else {n.get("id") for n in data.get("nodes", []) or []}
    zone = zone_for_ip(data, host.get("ip"))
    if not zone:
        zones = data.get("zones") or []
        zone = zones[0].get("id") if zones else "uncharted"
    ports = host.get("ports") or []
    port_note = ", ".join(str(p.get("port")) for p in ports[:6]) if ports else ""
    # `nas.home.example` charts as NAS, as the db backend's importer has always
    # done (importers.nmap._short); the full name stays in the survey list
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
