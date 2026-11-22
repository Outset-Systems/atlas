import math

from sqlalchemy import select

from layoutgrid import (
    BAND_CENTER_X as _BAND_CENTER_X,
    BAND_LABEL_X as _BAND_LABEL_X,
    BAND_STEP as _BAND_STEP,
    BAND_TOP as _BAND_TOP,
    GRID_COLS as _GRID_COLS,
    GRID_STEP as _GRID_STEP,
    X_MAX as _X_MAX,
    X_MIN as _X_MIN,
    Y_MAX as _Y_MAX,
    Y_MIN as _Y_MIN,
    clamp as _clamp,
    grid_slot as _grid_slot,
)

from .models import Node, Zone



def _ring_radius(count):
    return _clamp(4.0 + 0.45 * count, 5.0, 12.0)


def _zone_order(zones):
    def numbered(z):
        return isinstance(z.vlan, int) and not isinstance(z.vlan, bool)
    return sorted(zones, key=lambda z: (not numbered(z), z.vlan if numbered(z) else 0, z.slug))


def auto_layout(session, site):
    zones = _zone_order(session.scalars(select(Zone).where(Zone.site_id == site.id)))

    auto_zones = set()
    unplaced = [z for z in zones if z.label_x is None or z.label_y is None]
    for i, z in enumerate(unplaced):
        z.label_x = _BAND_LABEL_X
        z.label_y = _clamp(_BAND_TOP + _BAND_STEP * i, _Y_MIN, _Y_MAX)
        auto_zones.add(z.slug)

    anchors = {
        z.slug: (_BAND_CENTER_X if z.slug in auto_zones else (z.label_x or _BAND_CENTER_X),
                 (z.label_y or 50.0) + 6.0)
        for z in zones
    }
    fallback_anchor = (_BAND_CENTER_X, 120.0)

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
        by_zone = {}
        for n in batch:
            by_zone.setdefault(n.zone_slug, []).append(n)
        for zone_slug, group in sorted(by_zone.items(), key=lambda kv: str(kv[0])):
            ax, ay = anchors.get(zone_slug, fallback_anchor)
            taken = sum(1 for n in nodes
                        if n.zone_slug == zone_slug and n.slug in positions
                        and n not in group)
            for i, n in enumerate(group):
                n.x, n.y = _grid_slot(ax, ay, taken + i)
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

    roots = [n for n in remaining if not n.parent_slug or n.parent_slug not in known]
    if roots:
        grid(roots)
        placed += len(roots)
        remaining = [n for n in remaining if n not in roots]

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

    if remaining:
        grid(remaining)
        placed += len(remaining)

    return placed
