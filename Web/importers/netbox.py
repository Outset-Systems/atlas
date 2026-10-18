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

import ipaddress
from datetime import datetime, timezone

from sqlalchemy import select

from store.labdata import get_site
from store.layout import auto_layout
from store.models import Node, Site, Zone

from .common import UNCHARTED_SLUG, slugify
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
    networks = []  # (network, zone_slug), longest prefix first at lookup time
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
                subnet=vlan_subnet.get(vid), hue=_PALETTE[vid % len(_PALETTE)],
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

    for z in by_slug.values():
        if z.subnet:
            try:
                networks.append((ipaddress.ip_network(z.subnet, strict=False), z.slug))
            except ValueError:
                pass
    networks.sort(key=lambda t: t[0].prefixlen, reverse=True)

    def zone_for_ip(ip):
        if ip:
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                return None
            for net, slug in networks:
                if addr in net:
                    return slug
        return None

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
        zone_slug = zone_for_ip(ip) or ensure_uncharted().slug
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

    for d in snapshot.get("devices", []):
        role_slug, role_name = _role_of(d)
        upsert(f"device:{d['id']}", d.get("name") or f"device-{d['id']}",
               role_map.get(role_slug, "physical"), _ip_of(d), _hw_of(d),
               role_name, _scroll_of(d))
    for vm in snapshot.get("vms", []):
        role_slug, role_name = _role_of(vm)
        upsert(f"vm:{vm['id']}", vm.get("name") or f"vm-{vm['id']}",
               role_map.get(role_slug, "vm"), _ip_of(vm), _hw_of_vm(vm),
               role_name, _scroll_of(vm))

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
