"""Deterministic auto-layout.

Fills positions ONLY where they are missing: zones without a label position
get stacked bands ordered by VLAN id; nodes without x/y get placed near their
zone, with children ringed around their parent. Hand-placed values and
layout_locked nodes are never touched, and re-runs are stable (slug-sorted,
no randomness) so a re-import never reshuffles a map.

Placement order matters: roots grid first, then children ring around whatever
just got a position, wave by wave. Anything unreachable (parent cycle, parent
locked without a position) falls back to the zone grid rather than vanishing.
"""

import math

from sqlalchemy import select

from .models import Node, Zone

_GRID_COLS = 5
_GRID_STEP = 7.0
_BAND_TOP = 14.0
_BAND_STEP = 17.0
_BAND_LABEL_X = 12.0
_BAND_CENTER_X = 50.0
_X_MIN, _X_MAX = 2.0, 98.0
_Y_MIN, _Y_MAX = -38.0, 138.0


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _ring_radius(count):
    """Big enough that `count` markers don't overlap, small enough to read as
    a family around the parent."""
    return _clamp(4.0 + 0.45 * count, 5.0, 12.0)


def _zone_order(zones):
    """Bands run by VLAN id; zones without a VLAN sink to the bottom."""
    return sorted(zones, key=lambda z: (z.vlan is None, z.vlan if z.vlan is not None else 0, z.slug))


def auto_layout(session, site):
    """Assign missing zone-label and node positions for `site`. Returns the
    number of nodes placed. Caller is responsible for bumping data_version."""
    zones = _zone_order(session.scalars(select(Zone).where(Zone.site_id == site.id)))

    auto_zones = set()
    unplaced = [z for z in zones if z.label_x is None or z.label_y is None]
    for i, z in enumerate(unplaced):
        z.label_x = _BAND_LABEL_X
        z.label_y = _clamp(_BAND_TOP + _BAND_STEP * i, _Y_MIN, _Y_MAX)
        auto_zones.add(z.slug)

    # A hand-placed label sits where its region is, so cluster there. An
    # auto-placed label is just a band marker at the left margin — cluster the
    # band's nodes across the middle of the table instead.
    anchors = {
        z.slug: (_BAND_CENTER_X if z.slug in auto_zones else (z.label_x or _BAND_CENTER_X),
                 (z.label_y or 50.0) + 6.0)
        for z in zones
    }
    fallback_anchor = (_BAND_CENTER_X, 120.0)  # the void below the map

    nodes = list(session.scalars(select(Node).where(Node.site_id == site.id)))
    known = {n.slug for n in nodes}
    positions = {n.slug: (n.x, n.y) for n in nodes if n.x is not None and n.y is not None}
    pending = sorted(
        (n for n in nodes
         if not n.layout_locked and (n.x is None or n.y is None)),
        key=lambda n: n.slug,
    )
    if not pending:
        return 0

    def grid(batch):
        """Place a batch of nodes in slug order, gridded around their zone anchor."""
        by_zone = {}
        for n in batch:
            by_zone.setdefault(n.zone_slug, []).append(n)
        for zone_slug, group in sorted(by_zone.items(), key=lambda kv: str(kv[0])):
            ax, ay = anchors.get(zone_slug, fallback_anchor)
            # keep existing residents of the band from being sat on
            taken = sum(1 for n in nodes
                        if n.zone_slug == zone_slug and n.slug in positions
                        and n not in group)
            for i, n in enumerate(group):
                slot = taken + i
                col, row = slot % _GRID_COLS, slot // _GRID_COLS
                n.x = _clamp(ax + (col - (_GRID_COLS - 1) / 2) * _GRID_STEP, _X_MIN, _X_MAX)
                n.y = _clamp(ay + row * _GRID_STEP, _Y_MIN, _Y_MAX)
                positions[n.slug] = (n.x, n.y)

    def ring(parent_slug, children):
        px, py = positions[parent_slug]
        radius = _ring_radius(len(children))
        for i, n in enumerate(children):
            angle = math.radians(-90.0 + (360.0 / len(children)) * i)
            n.x = _clamp(px + radius * math.cos(angle), _X_MIN, _X_MAX)
            n.y = _clamp(py + radius * math.sin(angle), _Y_MIN, _Y_MAX)
            positions[n.slug] = (n.x, n.y)

    placed = 0
    remaining = list(pending)

    # roots: no parent, or a parent this site has never heard of
    roots = [n for n in remaining if not n.parent_slug or n.parent_slug not in known]
    if roots:
        grid(roots)
        placed += len(roots)
        remaining = [n for n in remaining if n not in roots]

    # waves: ring each generation around parents that now have positions
    while remaining:
        wave = [n for n in remaining if n.parent_slug in positions]
        if not wave:
            break
        by_parent = {}
        for n in wave:
            by_parent.setdefault(n.parent_slug, []).append(n)
        for parent_slug, children in sorted(by_parent.items()):
            ring(parent_slug, children)
        placed += len(wave)
        remaining = [n for n in remaining if n not in wave]

    if remaining:  # cycles, or a parent locked without a position
        grid(remaining)
        placed += len(remaining)

    return placed
