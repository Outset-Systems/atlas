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

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

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


def load_labdata(session, data, site_slug="default", site_name=None, source="file",
                 only_changed=False):
    """Full-replace import of a canonical dataset dict into `site_slug`.

    Upserts zones/nodes by slug (node identity — pk, first_seen, layout_locked,
    external provenance — survives re-imports); links and routes are replaced
    wholesale. Bumps data_version. Returns the Site.

    `only_changed` (the editor's saves, 2026-11-15): the same end state, but a
    row is written only when it differs, a node's links only when they do,
    and `last_imported` moves only on a node that changed. One difference on
    purpose: a retired place missing from `data` is kept (the editor's copy
    never had it), where the import removes it. One place edited
    at 2,000 places was 13,418 statements (every node updated, every link
    deleted and inserted again); it is a handful now. The import path keeps
    the wholesale write, and is the oracle the partial one is tested against
    (tests/test_store_partial.py).
    """
    if only_changed:
        return _load_changed(session, data, site_slug, site_name, source)
    import schema   # lazy: store/ is imported by the CLI before the app's path is set
    data = schema.upgrade(dict(data))   # old section names are stored as today's
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
        if n.status == "retired":
            _revive(n, source)
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


def _revive(node, source):
    """A retired row the dataset names again (2026-11-15): back on the map
    (the dump hides a retired row, so it stayed hidden however often it was
    added), and charted by hand now: the importer's claim on it goes, or its
    next run would retire it again for being missing from its source. The
    same holds for an undo or an `import-json` that reaches back across a
    retirement: the place comes back charted by hand, and the importer can
    take it again only by name and address (`netbox.sync`'s adoption)."""
    node.status = "documented"
    node.external_source, node.external_ref = source, None


def _rows(session, model, site, *, links=False):
    """A site's rows of one table in their order, a node's links loaded with
    them in one more query (2026-11-15: through the relationship, each node's
    links were a query of their own: a dump at 2,000 places was 1.2 s)."""
    stmt = select(model).where(model.site_id == site.id).order_by(model.sort_order, model.id)
    if links:
        stmt = stmt.options(selectinload(Node.links))
    return list(session.scalars(stmt))


def _link_rows(links):
    """A node's links as they are stored: (columns, sort order, extra)."""
    out = []
    for j, lj in enumerate(links or []):
        lcols, lextra = _split(lj, _LINK_KEYS)
        out.append(({c: lcols.get(c) for c in _LINK_KEYS.values()}, j, lextra))
    return out


def _typed(value):
    """`value` as JSON text, so a change of type alone (8080 to 8080.0, true
    to 1) counts as a change: Python's `==` calls those equal, and the full
    replace writes links and routes anew whatever they hold (review,
    2026-11-15). Key order does not count (the stamp sorts keys too)."""
    return json.dumps(value, sort_keys=True, default=str)


def _load_changed(session, data, site_slug, site_name, source):
    """`load_labdata(only_changed=True)`: see there."""
    import schema   # lazy: store/ is imported by the CLI before the app's path is set
    data = schema.upgrade(dict(data))
    now = datetime.now(timezone.utc)
    site = get_site(session, site_slug)
    if site is None:   # a first save is an import
        return load_labdata(session, data, site_slug, site_name, source)
    if site_name and site.name != site_name:
        site.name = site_name
    elif not site_name and not site.name:
        site.name = str((data.get("meta") or {}).get("title") or site_slug)

    settings = {k: v for k, v in data.items() if k not in _RELATIONAL_TOP_KEYS}
    settings[_TOP_ORDER_KEY] = list(data.keys())
    if site.settings_json != settings:
        site.settings_json = settings

    def same(row, want):
        return all(getattr(row, col) == value for col, value in want.items())

    # zones
    existing = {z.slug: z for z in _rows(session, Zone, site)}
    seen = set()
    for i, zj in enumerate(data.get("zones", []) or []):
        cols, extra = _split(zj, _ZONE_KEYS)
        slug = cols.pop("slug", None) or extra.get("id") or f"zone-{i}"
        seen.add(slug)
        want = {col: cols.get(col) for col in set(_ZONE_KEYS.values()) - {"slug"}}
        want.update(sort_order=i, extra_json=extra)
        z = existing.get(slug)
        if z is None:
            session.add(Zone(site_id=site.id, slug=slug, **want))
        elif not same(z, want):
            for col, value in want.items():
                setattr(z, col, value)
    for slug, z in existing.items():
        if slug not in seen:
            session.delete(z)

    # nodes, and their links only when they differ
    existing = {n.slug: n for n in _rows(session, Node, site, links=True)}
    seen = set()
    for i, nj in enumerate(data.get("nodes", []) or []):
        links = nj.get("links")
        cols, extra = _split(nj, _NODE_KEYS, skip=("links",))
        if links is not None and not links:
            extra["links"] = []
        slug = cols.pop("slug", None) or extra.get("id") or f"node-{i}"
        seen.add(slug)
        want = {col: cols.get(col) for col in set(_NODE_KEYS.values()) - {"slug"}}
        want.update(sort_order=i, extra_json=extra)
        want_links = _link_rows(links)
        n = existing.get(slug)
        if n is None:
            n = Node(site_id=site.id, slug=slug, external_source=source, last_imported=now, **want)
            session.add(n)
            for lcols, j, lextra in want_links:
                n.links.append(NodeLink(sort_order=j, extra_json=lextra, **lcols))
            continue
        have_links = [({c: getattr(l, c) for c in _LINK_KEYS.values()}, l.sort_order, l.extra_json or {})
                      for l in n.links]
        links_differ = _typed(have_links) != _typed(want_links)
        revive = n.status == "retired"   # named again: back on the map (see load_labdata)
        if same(n, want) and not links_differ and not revive:
            continue
        for col, value in want.items():
            setattr(n, col, value)
        if revive:
            _revive(n, source)
        n.last_imported = now
        if links_differ:
            n.links.clear()
            for lcols, j, lextra in want_links:
                n.links.append(NodeLink(sort_order=j, extra_json=lextra, **lcols))
    for slug, n in existing.items():
        # A retired place is not in the editor's copy because the dump hides
        # it, not because anyone removed it: it stays, as the importers keep
        # it (2026-11-15; a Desk save used to delete every one). The import's
        # full replace still removes it: there the file is the whole truth.
        if slug not in seen and n.status != "retired":
            session.delete(n)

    # routes: no identity, so replaced, but only when the list differs
    have = [({c: getattr(r, c) for c in _ROUTE_KEYS.values()}, r.extra_json or {})
            for r in _rows(session, Route, site)]
    want_routes = []
    for rj in data.get("routes", []) or []:
        cols, extra = _split(rj, _ROUTE_KEYS)
        want_routes.append(({c: cols.get(c) for c in _ROUTE_KEYS.values()}, extra))
    if _typed(have) != _typed(want_routes):
        for r in _rows(session, Route, site):
            session.delete(r)
        for i, (cols, extra) in enumerate(want_routes):
            session.add(Route(site_id=site.id, sort_order=i, extra_json=extra, **cols))

    site.data_version = (site.data_version or 0) + 1
    site.updated_at = now
    session.flush()
    session.expire(site, ["zones", "nodes", "routes"])
    return site


def _emit_row(row, keymap):
    """`_emit` for a plain result row (a mapping), not an ORM object."""
    out = {k: row[col] for k, col in keymap.items() if row[col] is not None}
    out.update(row["extra_json"] or {})
    return out


def _emit_table(session, model, site, keymap):
    """A section read as plain rows (2026-11-15): building an ORM object per
    row was most of a dump (2.2 s for 10,000 places)."""
    t = model.__table__
    cols = [t.c[c] for c in keymap.values()] + [t.c.extra_json]
    stmt = select(*cols).where(t.c.site_id == site.id).order_by(t.c.sort_order, t.c.id)
    return [_emit_row(r, keymap) for r in session.execute(stmt).mappings()]


def _emit_nodes(session, site):
    n, lk = Node.__table__, NodeLink.__table__
    links = {}
    lstmt = (select(lk.c.node_id, *[lk.c[c] for c in _LINK_KEYS.values()], lk.c.extra_json)
             .join(n, n.c.id == lk.c.node_id).where(n.c.site_id == site.id)
             .order_by(lk.c.node_id, lk.c.sort_order, lk.c.id))
    for r in session.execute(lstmt).mappings():
        links.setdefault(r["node_id"], []).append(_emit_row(r, _LINK_KEYS))
    stmt = (select(n.c.id, n.c.status, *[n.c[c] for c in _NODE_KEYS.values()], n.c.extra_json)
            .where(n.c.site_id == site.id).order_by(n.c.sort_order, n.c.id))
    out = []
    for r in session.execute(stmt).mappings():
        # retired = importer saw it vanish: kept in the DB,
        # hidden from the map until a P1 UI decides its fate
        if r["status"] == "retired":
            continue
        node = _emit_row(r, _NODE_KEYS)
        if r["id"] in links:
            node["links"] = links[r["id"]]
        out.append(node)
    return out


def dump_labdata(session, site_slug="default"):
    """Rebuild the canonical dataset dict for a site, or None if it doesn't exist."""
    site = get_site(session, site_slug)
    if site is None:
        return None
    # the sections are read as plain rows, which see only what is flushed:
    # rows an importer added in this session must be in them
    session.flush()
    settings = dict(site.settings_json or {})
    top_keys = settings.pop(_TOP_ORDER_KEY, None) or (
        list(settings.keys()) + list(_RELATIONAL_TOP_KEYS)
    )

    sections = {
        "zones": lambda: _emit_table(session, Zone, site, _ZONE_KEYS),
        "nodes": lambda: _emit_nodes(session, site),
        "routes": lambda: _emit_table(session, Route, site, _ROUTE_KEYS),
    }

    out = {}
    for k in top_keys:
        if k in sections:
            out[k] = sections[k]()
        elif k in settings:
            out[k] = settings[k]
    for k, v in settings.items():  # defensive: settings not named in _top_keys
        out.setdefault(k, v)
    # a site stored before a section was renamed (`sets`, 2026-11-14) dumps
    # under today's name, for every caller: the reader, the store and the
    # multi-site routes alike
    import schema   # lazy: store/ is imported by the CLI before the app's path is set
    return schema.upgrade(out)


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
