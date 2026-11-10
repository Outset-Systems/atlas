"""Relay ingest — `POST /api/v2/ingest/{signals,inventory,observed}`.

A nested blueprint whose `before_request` does two things: the existence
check (`ingest.enabled()` — the surface is off unless ATLAS_INGEST_ENABLED=1
and the db backend is on, and an endpoint that cannot be used should not be
reachable, so it 404s), then `ingest.authenticate()` — the bearer check, the
size cap and the shared rate limiter. The three handlers read their payload
through `ingest.body()`, which enforces the tenancy invariant: a token writes
to its own site or nowhere.

The prefix is exempted from the app gate in `create_app`
(`api_v2.INGEST_URL_PREFIX`) — the bearer token is the whole boundary here.
"""

import logging

from flask import Blueprint, abort, jsonify, g

import ingest

from . import bp

log = logging.getLogger("atlas.api.v2")

#: Who a stamp names for what a relay pushed in (provenance.py).
RELAY = "relay"

ingest_bp = Blueprint("ingest", __name__, url_prefix="/ingest")


@ingest_bp.before_request
def _gate():
    if not ingest.enabled():
        abort(404)
    return ingest.authenticate()


@ingest_bp.route("/signals", methods=["POST"])
def ingest_signals():
    """Store a merged health feed; the `relay` signals source serves it back."""
    from signals import _coerce_feed
    from sqlalchemy import select
    from store import session_scope
    from store.models import SignalSnapshot, Site

    payload, err = ingest.body()
    if err:
        return err
    feed = _coerce_feed({k: v for k, v in payload.items() if k != "site"})
    if not any(feed.get(k) for k in ("nodes", "services", "metrics")):
        return jsonify({"error": "no recognisable signal data (nodes/services/metrics)"}), 422

    with session_scope() as session:
        site = session.scalar(select(Site).where(Site.slug == g.site_slug))
        session.add(SignalSnapshot(site_id=site.id, payload_json=feed))
        session.flush()
        old = list(session.scalars(
            select(SignalSnapshot)
            .where(SignalSnapshot.site_id == site.id)
            .order_by(SignalSnapshot.received_at.desc(), SignalSnapshot.id.desc())
            .offset(ingest.SNAPSHOT_RING)
        ))
        for row in old:
            session.delete(row)
    return jsonify({"ok": True, "site": g.site_slug,
                    "nodes": len(feed.get("nodes", {})),
                    "services": len(feed.get("services", {})),
                    "metrics": len(feed.get("metrics", {}))})


@ingest_bp.route("/inventory", methods=["POST"])
def ingest_inventory():
    """Apply a NetBox-shaped snapshot the relay fetched on the customer LAN."""
    from importers.netbox import DEFAULT_ROLE_MAP, parse_role_map, sync
    from store import dump_labdata, restamp, session_scope

    payload, err = ingest.body()
    if err:
        return err

    snapshot = {}
    for key in ("vlans", "prefixes", "devices", "vms"):
        value = payload.get(key, [])
        if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
            return jsonify({"error": f"{key!r} must be a list of objects"}), 422
        snapshot[key] = value
    for key in ("devices", "vms"):
        if any("id" not in x for x in snapshot[key]):
            return jsonify({"error": f"every {key[:-1]} needs an 'id'"}), 422
    if not any(snapshot.values()):
        return jsonify({"error": "empty snapshot"}), 422

    try:
        role_map = parse_role_map(payload.get("role_map") or "")
    except ValueError as e:
        return jsonify({"error": str(e)}), 422

    with session_scope() as session:
        before = dump_labdata(session, g.site_slug)
        stats = sync(session, snapshot, site_slug=g.site_slug,
                     role_map=role_map or DEFAULT_ROLE_MAP)
        restamp(session, g.site_slug, before, RELAY, "netbox")
    log.info("ingest inventory: site=%s %s", g.site_slug, stats)
    return jsonify({"ok": True, "site": g.site_slug, "stats": stats})


@ingest_bp.route("/observed", methods=["POST"])
def ingest_observed():
    """Record a discovery sweep. Returns the drift count — the product's point."""
    from importers.nmap import import_observations
    from store import dump_labdata, restamp, session_scope

    payload, err = ingest.body()
    if err:
        return err

    hosts = payload.get("hosts")
    if not isinstance(hosts, list) or any(not isinstance(h, dict) for h in hosts):
        return jsonify({"error": "'hosts' must be a list of objects"}), 422
    if any(not (h.get("ip") or h.get("mac")) for h in hosts):
        return jsonify({"error": "every host needs an 'ip' or a 'mac'"}), 422
    source = payload.get("source", "relay")
    if source not in ("nmap", "arp", "relay"):
        return jsonify({"error": "source must be nmap, arp or relay"}), 422

    with session_scope() as session:
        before = dump_labdata(session, g.site_slug)
        stats = import_observations(session, hosts, site_slug=g.site_slug,
                                    source=source, promote=bool(payload.get("promote")))
        restamp(session, g.site_slug, before, RELAY, source)
    if stats["undocumented"]:
        log.warning("ingest observed: site=%s %d undocumented device(s)",
                    g.site_slug, stats["undocumented"])
    return jsonify({"ok": True, "site": g.site_slug, "stats": stats})


bp.register_blueprint(ingest_bp)
