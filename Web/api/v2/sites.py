"""The multi-site read API — `/api/v2/sites…` (db mode only).

    GET /api/v2/sites                        every charted site + counts
    GET /api/v2/sites/<slug>/lab-data        canonical dataset (ETag/304)
    GET /api/v2/sites/<slug>/nodes           inventory view (provenance, status)
    GET /api/v2/sites/<slug>/observed        discovery view — drift candidates

File mode is the single-dataset homelab edition and has no notion of sites,
so there these paths do not exist: the blueprint mounts once for every mode,
and the posture is a per-request `abort(404)` — the framework's own NotFound,
identical to an unrouted path.

These sit **behind** the normal session gate — they are read endpoints for
people and UIs, not for agents. Every handler is scoped to one site by
construction: the site is resolved first and every query filters on its id,
so there is no code path that can read across sites. The tests assert that
per endpoint (`tests/test_api_v2_sites_scoping.py`).
"""

from datetime import timezone

from flask import abort, current_app, jsonify, make_response, request

from context import atlas
from redaction import (cleared, redact_for_groups, sees_everything,
                       vary_on_viewer, viewer_groups)

from . import bp

NODE_STATUSES = ("documented", "retired", "all")


def _db_only():
    if atlas().backend != "db":
        abort(404)                    # file mode has no sites: the paths do not exist


def _iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _site_or_404(session, slug):
    from store.labdata import get_site
    site = get_site(session, slug)
    if site is None:
        return None, (jsonify({"error": f"no such site: {slug!r}"}), 404)
    return site, None


@bp.route("/sites")
def list_sites():
    _db_only()
    from sqlalchemy import func, select
    from store import session_scope
    from store.models import Node, Site, Zone

    with session_scope() as session:
        out = []
        for site in session.scalars(select(Site).order_by(Site.slug)):
            nodes = session.scalar(
                select(func.count(Node.id))
                .where(Node.site_id == site.id, Node.status != "retired"))
            zones = session.scalar(
                select(func.count(Zone.id)).where(Zone.site_id == site.id))
            out.append({
                "slug": site.slug,
                "name": site.name,
                "data_version": site.data_version,
                "updated_at": _iso(site.updated_at),
                "counts": {"zones": zones, "nodes": nodes},
            })
    return jsonify({"sites": out})


@bp.route("/sites/<slug>/lab-data")
def site_lab_data(slug):
    _db_only()
    from store import session_scope
    from store.labdata import dump_labdata, site_stamp
    from validation import validate

    with session_scope() as session:
        site, err = _site_or_404(session, slug)
        if err:
            return err
        stamp = site_stamp(session, slug)
        data = dump_labdata(session, slug)

    problems = validate(data)
    data, gkey = redact_for_groups(data)
    resp = make_response(jsonify(data))
    version, ts = stamp
    resp.set_etag(f"{current_app.config.get('APP_VERSION', 'v1')}-{slug}-{version}-{ts}"
                  f"-{hash(gkey) & 0xffffffff:x}")
    resp.headers["Cache-Control"] = "private, no-cache"
    if problems:
        resp.headers["X-Atlas-Data-Problems"] = str(len(problems))
    return vary_on_viewer(resp.make_conditional(request))


@bp.route("/sites/<slug>/nodes")
def site_nodes(slug):
    _db_only()
    from sqlalchemy import select
    from store import session_scope
    from store.models import Node

    status = (request.args.get("status") or "documented").lower()
    if status not in NODE_STATUSES:
        return jsonify({"error": f"status must be one of {list(NODE_STATUSES)}"}), 400
    source = request.args.get("source")

    groups = viewer_groups()
    with session_scope() as session:
        site, err = _site_or_404(session, slug)
        if err:
            return err
        q = select(Node).where(Node.site_id == site.id)
        if status != "all":
            q = q.where(Node.status == status)
        if source:
            q = q.where(Node.external_source == source)
        rows = list(session.scalars(q.order_by(Node.sort_order, Node.slug)))

        out = []
        for n in rows:
            extra = n.extra_json or {}
            if not cleared(extra, groups):
                continue
            out.append({
                "id": n.slug,
                "name": n.name,
                "kind": n.kind,
                "zone": n.zone_slug,
                "parent": n.parent_slug,
                "ip": n.ip,
                "hw": n.hw,
                "role": n.role,
                "status": n.status,
                "x": n.x, "y": n.y, "layout_locked": n.layout_locked,
                "source": n.external_source,
                "external_ref": n.external_ref,
                "first_seen": _iso(n.first_seen),
                "last_imported": _iso(n.last_imported),
                "links": [{"label": l.label, "url": l.url}
                          for l in n.links if cleared(l.extra_json or {}, groups)],
            })
    resp = make_response(jsonify({"site": slug, "count": len(out), "nodes": out}))
    resp.headers["Cache-Control"] = "private, no-cache"
    return vary_on_viewer(resp)


@bp.route("/sites/<slug>/observed")
def site_observed(slug):
    _db_only()
    from sqlalchemy import select
    from store import session_scope
    from store.models import Node, ObservedNode

    show_all = request.args.get("all") in ("1", "true", "yes")
    groups = viewer_groups()
    everything = sees_everything(groups)
    with session_scope() as session:
        site, err = _site_or_404(session, slug)
        if err:
            return err
        q = select(ObservedNode).where(ObservedNode.site_id == site.id)
        if not show_all:
            q = q.where(ObservedNode.matched_node_id.is_(None))
        rows = list(session.scalars(q.order_by(ObservedNode.ip, ObservedNode.id)))
        all_nodes = list(session.scalars(select(Node).where(Node.site_id == site.id)))
        node_slugs = {n.id: n.slug for n in all_nodes}
        if not everything:
            visible_ids = {n.id for n in all_nodes
                           if cleared(n.extra_json or {}, groups)}
            rows = [o for o in rows
                    if o.matched_node_id is not None
                    and o.matched_node_id in visible_ids]
        out = [{
            "ip": o.ip,
            "mac": o.mac,
            "hostname": o.hostname,
            "vendor": (o.raw_json or {}).get("vendor"),
            "ports": (o.raw_json or {}).get("ports") or [],
            "source": o.source,
            "first_seen": _iso(o.first_seen),
            "last_seen": _iso(o.last_seen),
            "matched_node": node_slugs.get(o.matched_node_id),
            "undocumented": o.matched_node_id is None,
        } for o in rows]
    undocumented = sum(1 for o in out if o["undocumented"])
    resp = make_response(jsonify({"site": slug, "count": len(out),
                                  "undocumented": undocumented, "observed": out}))
    resp.headers["Cache-Control"] = "private, no-cache"
    return vary_on_viewer(resp)
