"""NetBox importer — read-only sync into one Atlas site.

Mapping:
  ipam/vlans + ipam/prefixes  -> zones   (matched to existing zones by VLAN id;
                                          new zones get palette hue + auto label)
  dcim/devices                -> nodes   (kind via role map, ip from primary_ip4,
  virtualization/virtual-machines          hw from device_type/platform or
                                          vcpus/memory, external_ref = device:<id>/vm:<id>)
  custom_fields atlas_url|url -> scroll  (per-node doc link)

Sync semantics: upsert on (external_source='netbox', external_ref). New rows get
NetBox-owned fields + auto-layout position; existing rows get NetBox-owned
fields refreshed but lore/links/scroll/positions are never touched (hand-edits
win). A non-netbox node with the same slug and a matching ip is ADOPTED
(provenance stamped) rather than duplicated — the homelab-map-meets-NetBox
case. Rows missing from the sync are status='retired' (dump hides them),
resurrected if they return. All network fetching happens before any write.
"""

from datetime import datetime, timezone

import requests

from sqlalchemy import select

from store.labdata import get_site
from store.layout import auto_layout
from store.models import Node, Site, Zone

from . import review
from .wire import TIMEOUT, Refused, ok, plural
from .common import UNCHARTED_SLUG, slugify, subnet_index, zone_for_ip
from .common import ensure_uncharted as _ensure_uncharted
# The HTTP half lives in netbox_client so the relay can import it without the
# DB stack; re-exported here so `from importers.netbox import ...` still works.
from .netbox_client import (  # noqa: F401
    USER_AGENT, NetBoxClient, NetBoxError, fetch_snapshot,
)

# zone hue palette for auto-created zones (existing zone hues are hand-picked)
_PALETTE = ["#7FB0C4", "#7A9B6E", "#C9A554", "#8A8069",
            "#5FA8D3", "#D3869B", "#C06B62", "#8EC07C"]

DEFAULT_ROLE_MAP = {
    "server": "physical",
    "firewall": "network",
    "router": "network",
    "switch": "network",
    "access-point": "network",
    "wireless-ap": "network",
}


def parse_role_map(text):
    """--role-map 'server=physical,edge-router=network' -> dict (validated)."""
    out = dict(DEFAULT_ROLE_MAP)
    for pair in (text or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"bad --role-map entry {pair!r} (want role=kind)")
        role, kind = (s.strip() for s in pair.split("=", 1))
        out[role] = kind
    return out


def _ip_of(obj):
    addr = ((obj.get("primary_ip4") or {}).get("address")) or ""
    return addr.split("/")[0] or None


def _role_of(obj):
    role = obj.get("role") or obj.get("device_role") or {}
    return role.get("slug") or "", role.get("name") or ""


def _hw_of(dev):
    dt = dev.get("device_type") or {}
    bits = [(dt.get("manufacturer") or {}).get("name"), dt.get("model"),
            (dev.get("platform") or {}).get("name")]
    return " · ".join(b for b in bits if b) or None


def _hw_of_vm(vm):
    bits = []
    if vm.get("vcpus"):
        bits.append(f"{int(vm['vcpus'])} vCPU")
    if vm.get("memory"):
        bits.append(f"{int(vm['memory']) // 1024}GB RAM")
    if (vm.get("cluster") or {}).get("name"):
        bits.append(vm["cluster"]["name"])
    return " · ".join(bits) or None


def _scroll_of(obj):
    cf = obj.get("custom_fields") or {}
    return cf.get("atlas_url") or cf.get("url") or None


def _hue_of(vid):
    return _PALETTE[vid % len(_PALETTE)]


def _described(snapshot, role_map):
    """Every device and VM as (ref, name, kind, ip, hw, role name, scroll). One
    reading of a snapshot, shared by the sync below and the review step."""
    for d in snapshot.get("devices", []):
        role_slug, role_name = _role_of(d)
        yield (f"device:{d['id']}", d.get("name") or f"device-{d['id']}",
               role_map.get(role_slug, "physical"), _ip_of(d), _hw_of(d), role_name, _scroll_of(d))
    for vm in snapshot.get("vms", []):
        role_slug, role_name = _role_of(vm)
        yield (f"vm:{vm['id']}", vm.get("name") or f"vm-{vm['id']}",
               role_map.get(role_slug, "vm"), _ip_of(vm), _hw_of_vm(vm), role_name, _scroll_of(vm))


def candidates(snapshot, role_map=None):
    """A snapshot as review candidates (importers/review.py): VLANs become realms,
    devices and VMs become places. Where `sync` upserts and retires, a review only
    ever proposes additions. Returns (rows, notes)."""
    subnet = {}
    for p in snapshot.get("prefixes", []):
        vid = (p.get("vlan") or {}).get("vid")
        if vid is not None:
            subnet.setdefault(vid, p.get("prefix"))
    rows = [review.zone(f"netbox:vlan:{v['vid']}", "VLANs", v.get("name") or f"VLAN {v['vid']}",
                        v["vid"], subnet.get(v["vid"]), _hue_of(v["vid"]))
            for v in snapshot.get("vlans", []) if isinstance(v.get("vid"), int)]
    for ref, name, kind, ip, hw, role, scroll in _described(snapshot, role_map or DEFAULT_ROLE_MAP):
        group = "Devices" if ref.startswith("device:") else "Virtual machines"
        rows.append(review.place(f"netbox:{ref}", group, name, kind,
                                 f"{role} · from NetBox" if role else "from NetBox",
                                 ip=review.address(ip), hw=hw or "", scroll=scroll))
    return rows, []


def sync(session, snapshot, site_slug, role_map=None):
    """Write a fetched snapshot into `site_slug`. One transaction; returns stats."""
    role_map = role_map or DEFAULT_ROLE_MAP
    now = datetime.now(timezone.utc)
    stats = {"zones_created": 0, "nodes_created": 0, "nodes_updated": 0,
             "nodes_adopted": 0, "nodes_retired": 0, "nodes_resurrected": 0, "placed": 0}

    site = get_site(session, site_slug)
    if site is None:
        site = Site(slug=site_slug, name=site_slug)
        session.add(site)
        session.flush()

    zones = list(session.scalars(select(Zone).where(Zone.site_id == site.id)))
    zone_sort = max([z.sort_order for z in zones] + [-1]) + 1
    by_vid = {z.vlan: z for z in zones if z.vlan is not None}
    by_slug = {z.slug: z for z in zones}

    # subnet per VLAN (first prefix wins), used for new zones and ip→zone lookup
    vlan_subnet = {}
    for p in snapshot.get("prefixes", []):
        vid = ((p.get("vlan") or {}).get("vid"))
        if vid is not None:
            vlan_subnet.setdefault(vid, p.get("prefix"))

    def ensure_zone(vid, name):
        nonlocal zone_sort
        z = by_vid.get(vid)
        if z is None:
            slug = slugify(name) if name else f"vlan-{vid}"
            if slug in by_slug:
                slug = f"vlan-{vid}"
            z = Zone(
                site_id=site.id, slug=slug, name=name or f"VLAN {vid}", vlan=vid,
                subnet=vlan_subnet.get(vid), hue=_hue_of(vid),
                lore="", sort_order=zone_sort, extra_json={},
            )
            session.add(z)
            zone_sort += 1
            by_vid[vid], by_slug[z.slug] = z, z
            stats["zones_created"] += 1
        elif z.subnet is None and vlan_subnet.get(vid):
            z.subnet = vlan_subnet[vid]  # backfill only; hand-set zones stay theirs
        return z

    for v in snapshot.get("vlans", []):
        ensure_zone(v.get("vid"), v.get("name"))
    session.flush()

    # after the flush, so the zones just made for this snapshot's VLANs are in
    # the index too; the same index csv_import and nmap place by
    nets = subnet_index(session, site)

    def ensure_uncharted():
        if UNCHARTED_SLUG not in by_slug:
            by_slug[UNCHARTED_SLUG] = _ensure_uncharted(session, site)
            stats["zones_created"] += 1
        return by_slug[UNCHARTED_SLUG]

    existing = {
        n.external_ref: n
        for n in session.scalars(select(Node).where(
            Node.site_id == site.id, Node.external_source == "netbox"))
    }
    by_node_slug = {n.slug: n for n in session.scalars(
        select(Node).where(Node.site_id == site.id))}
    node_sort = max([n.sort_order for n in by_node_slug.values()] + [-1]) + 1
    seen = set()

    def upsert(ref, name, kind, ip, hw, role_name, scroll):
        nonlocal node_sort
        seen.add(ref)
        zone_slug = zone_for_ip(nets, ip) or ensure_uncharted().slug
        adopted = False
        n = existing.get(ref)
        if n is None:
            slug = slugify(name)
            other = by_node_slug.get(slug)
            if other is not None and other.external_source != "netbox" and (
                    not other.ip or not ip or other.ip == ip):
                # same slug, compatible ip: this IS the hand-charted node — adopt
                n = other
                n.external_source, n.external_ref = "netbox", ref
                existing[ref] = n
                adopted = True
                stats["nodes_adopted"] += 1
            elif other is not None:
                slug = f"{slug}-{ref.replace(':', '')}"
        if n is None:
            n = Node(
                site_id=site.id, slug=slug, name=name, kind=kind, zone_slug=zone_slug,
                # role "" not None: the dataset contract requires the key present
                role=role_name or "", lore="", ip=ip, hw=hw, scroll=scroll,
                external_source="netbox", external_ref=ref,
                sort_order=node_sort, extra_json={},
            )
            session.add(n)
            node_sort += 1
            by_node_slug[slug] = n
            stats["nodes_created"] += 1
        else:
            # NetBox-owned fields refresh; lore/links/scroll/x/y stay human
            if n.status == "retired":
                n.status = "documented"
                stats["nodes_resurrected"] += 1
            elif not adopted:
                stats["nodes_updated"] += 1
            n.name, n.kind, n.ip, n.hw = name, kind, ip, hw
            if role_name:
                n.role = role_name
            if n.zone_slug is None:
                n.zone_slug = zone_slug
        n.last_imported = now

    for described in _described(snapshot, role_map):
        upsert(*described)

    for ref, n in existing.items():
        if ref not in seen and n.status != "retired":
            n.status = "retired"
            stats["nodes_retired"] += 1

    session.flush()
    stats["placed"] = auto_layout(session, site)
    site.data_version = (site.data_version or 0) + 1
    site.updated_at = now
    session.flush()
    session.expire(site, ["zones", "nodes", "routes"])
    return stats


# ── the connection: what Settings shows, the test, and the survey ───────────
SYSTEM = {
    "key": "netbox", "name": "NetBox",
    "about": "Devices, virtual machines and VLANs.",
    "credential": "User menu → API tokens, with Write enabled turned off.",
    "fields": (("ATLAS_NETBOX_URL", "URL", "https://netbox.example", "url"),
               ("ATLAS_NETBOX_API_TOKEN", "API token", "", "secret"),
               ("ATLAS_NETBOX_INSECURE", "Self-signed certificate", "", "insecure")),
}


def probe(base, creds, verify):
    # v2 tokens (nbt_...) are bearer tokens; the older kind says `Token`.
    scheme = "Bearer" if creds[0].startswith("nbt_") else "Token"
    head = {"Authorization": f"{scheme} {creds[0]}", "Accept": "application/json"}
    get = lambda p: ok(requests.get(base + p, headers=head, timeout=TIMEOUT,   # noqa: E731
                                    verify=verify, allow_redirects=False), "NetBox").json()
    version = get("/api/status/").get("netbox-version", "?")
    return f"NetBox {version}: {plural(get('/api/dcim/devices/?limit=1').get('count', 0), 'device')}"


def survey(base, creds, verify):
    try:
        return candidates(fetch_snapshot(NetBoxClient(base, creds[0], timeout=TIMEOUT * 2, verify=verify)))
    except NetBoxError as e:
        if e.status in (401, 403):
            raise Refused("NetBox refused the credential.") from e
        if 300 <= (e.status or 0) < 400:
            raise Refused("NetBox redirected somewhere else. Use the final URL.") from e
        if isinstance(e.__cause__, requests.exceptions.RequestException):
            raise e.__cause__
        raise Refused(f"NetBox answered, but not usefully: {e}") from e
