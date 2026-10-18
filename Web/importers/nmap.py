"""nmap importer — discovery into `observed_nodes`.

`nmap -oX scan.xml <targets>` output becomes observation rows, each matched to
a documented node by IP. Rows that match nothing are the product's headline
signal: **an undocumented device is on the network**. Phase 1 records and
counts them; the alerting UI is P1.

`promote=True` turns unmatched hosts into real nodes (kind='unknown', realm by
subnet, auto-laid-out) — the "map a site from nothing" path for an MSP with no
NetBox. Promotion never retires or deletes anything: a scan is evidence of what
is there, never proof of what is gone (a powered-off host must not erase its
marker).
"""

from datetime import datetime, timezone

from sqlalchemy import select

from store.labdata import get_site
from store.layout import auto_layout
from store.models import Node, ObservedNode, Site

from .common import ensure_uncharted, slugify, subnet_index, zone_for_ip
# Parsing lives in scan.py so the relay can import it without the DB stack;
# re-exported here so `from importers.nmap import parse_nmap_xml` still works.
from .scan import NmapError, parse_nmap_xml  # noqa: F401

NO_IP = {None, "", "—", "-"}


def _short(hostname):
    return (hostname or "").split(".")[0]


def import_observations(session, hosts, site_slug, source="nmap", promote=False):
    """Record observations for `site_slug`. Returns stats including the drift
    count (`undocumented`). One transaction; never deletes."""
    now = datetime.now(timezone.utc)
    stats = {"observed_new": 0, "observed_seen": 0, "matched": 0,
             "undocumented": 0, "promoted": 0, "placed": 0}

    site = get_site(session, site_slug)
    if site is None:
        site = Site(slug=site_slug, name=site_slug)
        session.add(site)
        session.flush()

    nodes = list(session.scalars(select(Node).where(Node.site_id == site.id)))
    by_ip = {n.ip: n for n in nodes if n.ip not in NO_IP}
    by_slug = {n.slug: n for n in nodes}
    node_sort = max([n.sort_order for n in nodes] + [-1]) + 1
    nets = subnet_index(session, site)

    promoted_any = False
    for host in hosts:
        ip, mac = host.get("ip"), host.get("mac")
        node = by_ip.get(ip)

        if node is None and promote:
            name = _short(host.get("hostname")) or ip or mac
            slug = slugify(name)
            if slug in by_slug:  # name collision with an unrelated node
                slug = slugify(f"{name}-{ip or mac}")
            zone_slug = zone_for_ip(nets, ip) or ensure_uncharted(session, site).slug
            node = Node(
                site_id=site.id, slug=slug, name=name, kind="unknown",
                zone_slug=zone_slug, role="Discovered device", lore="",
                ip=ip, hw=host.get("vendor") or None, scroll=None,
                external_source=source, external_ref=f"ip:{ip}" if ip else f"mac:{mac}",
                sort_order=node_sort, extra_json={},
            )
            session.add(node)
            node_sort += 1
            by_slug[slug] = node
            if ip:
                by_ip[ip] = node
            promoted_any = True
            stats["promoted"] += 1

        if node is not None:
            stats["matched"] += 1
        else:
            stats["undocumented"] += 1

        q = select(ObservedNode).where(ObservedNode.site_id == site.id,
                                       ObservedNode.ip == ip)
        q = q.where(ObservedNode.mac.is_(None) if mac is None else ObservedNode.mac == mac)
        obs = session.scalar(q)
        if obs is None:
            obs = ObservedNode(site_id=site.id, ip=ip, mac=mac, first_seen=now)
            session.add(obs)
            stats["observed_new"] += 1
        else:
            stats["observed_seen"] += 1
        obs.hostname = host.get("hostname") or obs.hostname
        obs.source = source
        obs.last_seen = now
        obs.raw_json = {k: v for k, v in host.items() if k not in ("ip", "mac")}
        session.flush()  # node pk for the match below
        obs.matched_node_id = node.id if node is not None else None

    if promoted_any:
        session.flush()
        stats["placed"] = auto_layout(session, site)
    if stats["promoted"]:
        site.data_version = (site.data_version or 0) + 1
        site.updated_at = now
    session.flush()
    session.expire(site, ["zones", "nodes", "routes"])
    return stats


def undocumented(session, site_slug):
    """Observations matching no documented node — the drift list (P1 UI)."""
    site = get_site(session, site_slug)
    if site is None:
        return []
    return list(session.scalars(
        select(ObservedNode)
        .where(ObservedNode.site_id == site.id, ObservedNode.matched_node_id.is_(None))
        .order_by(ObservedNode.ip)
    ))
