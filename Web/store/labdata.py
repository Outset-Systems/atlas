"""lab-data.json ⇄ DB round-trip (Atlas for Teams, Phase 1).

`load_labdata` ingests a canonical dataset dict into a site (authoritative
full-replace: the JSON is the truth, missing rows are removed — the importers
in `importers/` have softer never-delete semantics and do NOT
use this path).
`dump_labdata` reproduces the dict exactly: modeled columns + extra_json
passthrough + original top-level key order. The golden test (import → export →
deep-compare) is the contract; see tests/test_store.py.

Fidelity rules:
- a modeled key whose value is None stays in extra_json (explicit nulls survive)
- a modeled column that is NULL is omitted on export (absent keys stay absent)
- "links": [] round-trips via an extra_json marker (no rows to witness it)
- array order is preserved via sort_order; dict key order is not significant
"""

from datetime import datetime, timezone

from sqlalchemy import select

from .models import Node, NodeLink, Route, Site, Zone

# json key -> column attribute (identity unless renamed)
_ZONE_KEYS = {
    "id": "slug", "name": "name", "vlan": "vlan", "subnet": "subnet",
    "hue": "hue", "net_hue": "net_hue", "lore": "lore",
    "label_x": "label_x", "label_y": "label_y", "hide_label": "hide_label",
}
_NODE_KEYS = {
    "id": "slug", "name": "name", "kind": "kind", "zone": "zone_slug",
    "x": "x", "y": "y", "role": "role", "lore": "lore", "ip": "ip",
    "hw": "hw", "scroll": "scroll", "parent": "parent_slug",
}
_LINK_KEYS = {"label": "label", "url": "url", "hue": "hue"}
_ROUTE_KEYS = {"from": "from_slug", "to": "to_slug", "kind": "kind"}

# dataset sections that live in relational tables; everything else is settings
_RELATIONAL_TOP_KEYS = ("zones", "nodes", "routes")
_TOP_ORDER_KEY = "_top_keys"


def _split(obj, keymap, skip=()):
    """Partition a dataset object into (columns, extra) per the fidelity rules."""
    cols, extra = {}, {}
    for k, v in obj.items():
        if k in skip:
            continue
        col = keymap.get(k)
        if col is not None and v is not None:
            cols[col] = v
        else:
            extra[k] = v
    return cols, extra


def _emit(row, keymap):
    """Rebuild a dataset object from a row: non-NULL columns + extra_json."""
    out = {}
    for k, col in keymap.items():
        v = getattr(row, col)
        if v is not None:
            out[k] = v
    out.update(row.extra_json or {})
    return out


def get_site(session, site_slug):
    return session.scalar(select(Site).where(Site.slug == site_slug))


def load_labdata(session, data, site_slug="default", site_name=None, source="file"):
    """Full-replace import of a canonical dataset dict into `site_slug`.

    Upserts zones/nodes by slug (node identity — pk, first_seen, layout_locked,
    external provenance — survives re-imports); links and routes are replaced
    wholesale. Bumps data_version. Returns the Site.
    """
    now = datetime.now(timezone.utc)
    site = get_site(session, site_slug)
    if site is None:
        site = Site(slug=site_slug)
        session.add(site)
        session.flush()
    if site_name:
        site.name = site_name
    elif not site.name:
        site.name = str((data.get("meta") or {}).get("title") or site_slug)

    settings = {k: v for k, v in data.items() if k not in _RELATIONAL_TOP_KEYS}
    settings[_TOP_ORDER_KEY] = list(data.keys())
    site.settings_json = settings

    # zones: upsert by slug, drop the missing, keep file order.
    # (Query the tables, not the site.* relationship collections — rows are
    # inserted with explicit site_id, which a collection loaded earlier in the
    # session never sees; relying on it double-inserts on re-import.)
    existing = {z.slug: z for z in session.scalars(select(Zone).where(Zone.site_id == site.id))}
    seen = set()
    for i, zj in enumerate(data.get("zones", []) or []):
        cols, extra = _split(zj, _ZONE_KEYS)
        slug = cols.pop("slug", None) or extra.get("id") or f"zone-{i}"
        seen.add(slug)
        z = existing.get(slug) or Zone(site_id=site.id, slug=slug)
        if z.id is None:
            session.add(z)
        for col in set(_ZONE_KEYS.values()) - {"slug"}:
            setattr(z, col, cols.get(col))
        z.sort_order, z.extra_json = i, extra
    for slug, z in existing.items():
        if slug not in seen:
            session.delete(z)

    # nodes: upsert by slug (identity survives), links replaced wholesale
    existing = {n.slug: n for n in session.scalars(select(Node).where(Node.site_id == site.id))}
    seen = set()
    for i, nj in enumerate(data.get("nodes", []) or []):
        links = nj.get("links")
        cols, extra = _split(nj, _NODE_KEYS, skip=("links",))
        if links is not None and not links:
            extra["links"] = []  # witness an explicit empty service directory
        slug = cols.pop("slug", None) or extra.get("id") or f"node-{i}"
        seen.add(slug)
        n = existing.get(slug) or Node(site_id=site.id, slug=slug, external_source=source)
        if n.id is None:
            session.add(n)
        for col in set(_NODE_KEYS.values()) - {"slug"}:
            setattr(n, col, cols.get(col))
        n.sort_order, n.extra_json, n.last_imported = i, extra, now
        n.links.clear()
        for j, lj in enumerate(links or []):
            lcols, lextra = _split(lj, _LINK_KEYS)
            n.links.append(NodeLink(sort_order=j, extra_json=lextra, **lcols))
    for slug, n in existing.items():
        if slug not in seen:
            session.delete(n)

    # routes: no stable identity — wholesale replace
    for r in session.scalars(select(Route).where(Route.site_id == site.id)):
        session.delete(r)
    for i, rj in enumerate(data.get("routes", []) or []):
        cols, extra = _split(rj, _ROUTE_KEYS)
        session.add(Route(site_id=site.id, sort_order=i, extra_json=extra, **cols))

    site.data_version = (site.data_version or 0) + 1
    site.updated_at = now
    session.flush()
    # a dump in this same session must see the fresh rows, in sort_order
    session.expire(site, ["zones", "nodes", "routes"])
    return site


def dump_labdata(session, site_slug="default"):
    """Rebuild the canonical dataset dict for a site, or None if it doesn't exist."""
    site = get_site(session, site_slug)
    if site is None:
        return None
    settings = dict(site.settings_json or {})
    top_keys = settings.pop(_TOP_ORDER_KEY, None) or (
        list(settings.keys()) + list(_RELATIONAL_TOP_KEYS)
    )

    def _emit_node(n):
        out = _emit(n, _NODE_KEYS)
        if n.links:
            out["links"] = [_emit(l, _LINK_KEYS) for l in n.links]
        return out

    sections = {
        "zones": lambda: [_emit(z, _ZONE_KEYS) for z in site.zones],
        # retired = importer saw it vanish: kept in the DB,
        # hidden from the map until a P1 UI decides its fate
        "nodes": lambda: [_emit_node(n) for n in site.nodes if n.status != "retired"],
        "routes": lambda: [_emit(r, _ROUTE_KEYS) for r in site.routes],
    }

    out = {}
    for k in top_keys:
        if k in sections:
            out[k] = sections[k]()
        elif k in settings:
            out[k] = settings[k]
    for k, v in settings.items():  # defensive: settings not named in _top_keys
        out.setdefault(k, v)
    return out


def restamp(session, site_slug, before, actor, origin):
    """Stamp what an importer just wrote straight into the tables.

    The netbox, nmap and csv importers write rows, not a dataset, so they pass
    `dataset.DatasetStore` and its stamp. Call this in the same session, with
    the dump taken before the import: a place it added starts unreviewed and a
    place it changed is marked changed (provenance.py). Returns how many
    stamps moved.
    """
    import provenance
    site = get_site(session, site_slug)
    if site is None:
        return 0
    session.flush()
    session.expire(site, ["zones", "nodes", "routes"])
    after = dump_labdata(session, site_slug)
    provenance.stamp(before or {}, after, None, actor, origin)
    marks = {n["id"]: n.get(provenance.KEY) for n in after.get("nodes") or []
             if isinstance(n.get("id"), str)}
    moved = 0
    for row in session.scalars(select(Node).where(Node.site_id == site.id)):
        if row.slug not in marks:        # retired: not on the map, nothing to say
            continue
        extra = dict(row.extra_json or {})
        want = marks[row.slug]
        if extra.get(provenance.KEY) == want:
            continue
        if want is None:
            extra.pop(provenance.KEY, None)
        else:
            extra[provenance.KEY] = want
        row.extra_json = extra           # a new dict, so the JSON column sees the change
        moved += 1
    if moved:
        session.flush()
        session.expire(site, ["nodes"])
    return moved


def site_stamp(session, site_slug="default"):
    """(data_version, updated_at epoch) for cache/ETag — or None if no site."""
    site = get_site(session, site_slug)
    if site is None:
        return None
    ts = site.updated_at.timestamp() if site.updated_at else 0
    return site.data_version or 0, ts
