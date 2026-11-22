import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .models import Node, NodeLink, Route, Site, Zone

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

_RELATIONAL_TOP_KEYS = ("zones", "nodes", "routes")
_TOP_ORDER_KEY = "_top_keys"


_COLUMN_TYPES = {
    "vlan": (int,),
    "label_x": (int, float), "label_y": (int, float),
    "x": (int, float), "y": (int, float),
    "hide_label": (bool,),
}


def _fits(col, v):
    want = _COLUMN_TYPES.get(col)
    if want is None:
        return True
    if isinstance(v, bool) and bool not in want:
        return False
    return isinstance(v, want)


def _split(obj, keymap, skip=()):
    cols, extra = {}, {}
    for k, v in obj.items():
        if k in skip:
            continue
        col = keymap.get(k)
        if col is not None and v is not None and _fits(col, v):
            cols[col] = v
        else:
            extra[k] = v
    return cols, extra


def _emit(row, keymap):
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
    if only_changed:
        return _load_changed(session, data, site_slug, site_name, source)
    import schema
    data = schema.upgrade(dict(data))
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

    existing = {n.slug: n for n in session.scalars(select(Node).where(Node.site_id == site.id))}
    seen = set()
    for i, nj in enumerate(data.get("nodes", []) or []):
        links = nj.get("links")
        cols, extra = _split(nj, _NODE_KEYS, skip=("links",))
        if links is not None and not links:
            extra["links"] = []
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

    for r in session.scalars(select(Route).where(Route.site_id == site.id)):
        session.delete(r)
    for i, rj in enumerate(data.get("routes", []) or []):
        cols, extra = _split(rj, _ROUTE_KEYS)
        session.add(Route(site_id=site.id, sort_order=i, extra_json=extra, **cols))

    site.data_version = (site.data_version or 0) + 1
    site.updated_at = now
    session.flush()
    session.expire(site, ["zones", "nodes", "routes"])
    return site


def _revive(node, source):
    node.status = "documented"
    node.external_source, node.external_ref = source, None


def _rows(session, model, site, *, links=False):
    stmt = select(model).where(model.site_id == site.id).order_by(model.sort_order, model.id)
    if links:
        stmt = stmt.options(selectinload(Node.links))
    return list(session.scalars(stmt))


def _link_rows(links):
    out = []
    for j, lj in enumerate(links or []):
        lcols, lextra = _split(lj, _LINK_KEYS)
        out.append(({c: lcols.get(c) for c in _LINK_KEYS.values()}, j, lextra))
    return out


def _typed(value):
    return json.dumps(value, sort_keys=True, default=str)


def _load_changed(session, data, site_slug, site_name, source):
    import schema
    data = schema.upgrade(dict(data))
    now = datetime.now(timezone.utc)
    site = get_site(session, site_slug)
    if site is None:
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
        revive = n.status == "retired"
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
        if slug not in seen and n.status != "retired":
            session.delete(n)

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
    out = {k: row[col] for k, col in keymap.items() if row[col] is not None}
    out.update(row["extra_json"] or {})
    return out


def _emit_table(session, model, site, keymap):
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
        if r["status"] == "retired":
            continue
        node = _emit_row(r, _NODE_KEYS)
        if r["id"] in links:
            node["links"] = links[r["id"]]
        out.append(node)
    return out


def dump_labdata(session, site_slug="default"):
    site = get_site(session, site_slug)
    if site is None:
        return None
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
    for k, v in settings.items():
        out.setdefault(k, v)
    import schema
    return schema.upgrade(out)


def restamp(session, site_slug, before, actor, origin):
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
        if row.slug not in marks:
            continue
        extra = dict(row.extra_json or {})
        want = marks[row.slug]
        if extra.get(provenance.KEY) == want:
            continue
        if want is None:
            extra.pop(provenance.KEY, None)
        else:
            extra[provenance.KEY] = want
        row.extra_json = extra
        moved += 1
    if moved:
        session.flush()
        session.expire(site, ["nodes"])
    return moved


def site_stamp(session, site_slug="default"):
    site = get_site(session, site_slug)
    if site is None:
        return None
    ts = site.updated_at.timestamp() if site.updated_at else 0
    return site.data_version or 0, ts
