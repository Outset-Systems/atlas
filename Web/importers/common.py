import ipaddress
import re

from sqlalchemy import select

from store.models import Node, Zone

UNCHARTED_SLUG = "uncharted"

UNKNOWN_ZONE_FIELDS = {"vlan": "—", "subnet": "—"}

UNCHARTED_ZONE = {"name": "Uncharted", "hue": "#8A8069",
                  "lore": "Devices whose realm is not yet known.",
                  "label_x": 50.0, "label_y": 118.0}


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-") or "unnamed"


def subnet_index(session, site):
    nets = []
    for z in session.scalars(select(Zone).where(Zone.site_id == site.id)):
        if not z.subnet:
            continue
        try:
            nets.append((ipaddress.ip_network(z.subnet, strict=False), z.slug))
        except ValueError:
            continue
    nets.sort(key=lambda t: t[0].prefixlen, reverse=True)
    return nets


def zone_for_ip(nets, ip):
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return None
    for net, slug in nets:
        if addr in net:
            return slug
    return None


def heal_revived(session, site, node, zone_slug):
    zones = set(session.scalars(select(Zone.slug).where(Zone.site_id == site.id)))
    if node.zone_slug not in zones:
        node.zone_slug = zone_slug
    if node.parent_slug:
        alive = session.scalar(select(Node.id).where(
            Node.site_id == site.id, Node.slug == node.parent_slug, Node.status != "retired"))
        if alive is None:
            node.parent_slug = None


def ensure_uncharted(session, site):
    z = session.scalar(select(Zone).where(Zone.site_id == site.id, Zone.slug == UNCHARTED_SLUG))
    if z is None:
        top = max([x.sort_order for x in
                   session.scalars(select(Zone).where(Zone.site_id == site.id))] + [-1]) + 1
        z = Zone(site_id=site.id, slug=UNCHARTED_SLUG, sort_order=top,
                 extra_json=dict(UNKNOWN_ZONE_FIELDS), **UNCHARTED_ZONE)
        session.add(z)
        session.flush()
    return z
