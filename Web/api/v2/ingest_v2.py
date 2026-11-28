import logging

from flask import Blueprint, abort, jsonify, g

import ingest
from dataset import site_lock
from filelock import LockTimeout

from . import bp

log = logging.getLogger("atlas.api.v2")

RELAY = "relay"


def _busy():
    resp = jsonify({"error": "the map is being saved; send again shortly"})
    resp.headers["Retry-After"] = "5"
    return resp, 503


ingest_bp = Blueprint("ingest", __name__, url_prefix="/ingest")


@ingest_bp.before_request
def _gate():
    if not ingest.enabled():
        abort(404)
    return ingest.authenticate()


@ingest_bp.route("/signals", methods=["POST"])
def ingest_signals():
    from engines.base import _coerce_feed
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

    try:
        with site_lock(g.site_slug), session_scope() as session:
            before = dump_labdata(session, g.site_slug)
            stats = sync(session, snapshot, site_slug=g.site_slug,
                         role_map=role_map or DEFAULT_ROLE_MAP)
            restamp(session, g.site_slug, before, RELAY, "netbox")
    except LockTimeout:
        return _busy()
    log.info("ingest inventory: site=%s %s", g.site_slug, stats)
    return jsonify({"ok": True, "site": g.site_slug, "stats": stats})


@ingest_bp.route("/hyperv", methods=["POST"])
def ingest_hyperv():
    """Keeps the relay's Hyper-V snapshot for an admin to review. Writes nothing to
    the map: Settings, Connections, Hyper-V, Review does, row by ticked row."""
    import relayed
    from importers import hyperv

    payload, err = ingest.body()
    if err:
        return err
    try:
        snapshot = hyperv.checked(payload)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    relayed.put(hyperv.KEY, g.site_slug, snapshot)
    stats = {"hosts": len(snapshot["hosts"]), "vms": len(snapshot["vms"]),
             "silent": len(snapshot["silent"])}
    log.info("ingest hyperv: site=%s %s", g.site_slug, stats)
    return jsonify({"ok": True, "site": g.site_slug, "stats": stats})


@ingest_bp.route("/observed", methods=["POST"])
def ingest_observed():
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

    try:
        with site_lock(g.site_slug), session_scope() as session:
            before = dump_labdata(session, g.site_slug)
            stats = import_observations(session, hosts, site_slug=g.site_slug,
                                        source=source, promote=bool(payload.get("promote")))
            restamp(session, g.site_slug, before, RELAY, source)
    except LockTimeout:
        return _busy()
    if stats["undocumented"]:
        log.warning("ingest observed: site=%s %d undocumented device(s)",
                    g.site_slug, stats["undocumented"])
    return jsonify({"ok": True, "site": g.site_slug, "stats": stats})


bp.register_blueprint(ingest_bp)
