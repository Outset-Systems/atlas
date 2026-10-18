"""Helpers shared by the importers."""

import ipaddress
import re

from sqlalchemy import select

from store.models import Zone

UNCHARTED_SLUG = "uncharted"

# A zone imported from a flat device list is a *place*, not a VLAN — but the
# dataset contract wants vlan/subnet present on every zone. Carry the repo's
# own unknown-value idiom ("—", as used for absent IPs) in extra_json rather
# than inventing a VLAN 0: the map label reads "vlan — · —", and the dash
# keeps the zone out of THE LEDGER's IPAM math instead of fabricating a /24.
# The subnet was "" until 2026-10-18; a blank required field fails strict
# validation, while "—" is the value the catalogue documents for "none".
UNKNOWN_ZONE_FIELDS = {"vlan": "—", "subnet": "—"}


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-") or "unnamed"


def subnet_index(session, site):
    """[(network, zone_slug)] for a site, longest prefix first."""
    nets = []
    for z in session.scalars(select(Zone).where(Zone.site_id == site.id)):
        if not z.subnet:
            continue
        try:
            nets.append((ipaddress.ip_network(z.subnet, strict=False), z.slug))
        except ValueError:
            continue  # a hand-typed subnet that isn't one: a validation problem, not a crash
    nets.sort(key=lambda t: t[0].prefixlen, reverse=True)
    return nets


def zone_for_ip(nets, ip):
    """Most specific zone whose subnet contains `ip`, or None."""
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


def ensure_uncharted(session, site):
    """The catch-all realm for devices whose subnet matches nothing."""
    z = session.scalar(select(Zone).where(Zone.site_id == site.id, Zone.slug == UNCHARTED_SLUG))
    if z is None:
        top = max([x.sort_order for x in
                   session.scalars(select(Zone).where(Zone.site_id == site.id))] + [-1]) + 1
        z = Zone(site_id=site.id, slug=UNCHARTED_SLUG, name="Uncharted", hue="#8A8069",
                 lore="Devices whose realm is not yet known.",
                 label_x=50.0, label_y=118.0, sort_order=top,
                 extra_json=dict(UNKNOWN_ZONE_FIELDS))
        session.add(z)
        session.flush()
    return z
