import logging
import threading
import time

from flask import Blueprint, jsonify, request

import dataset as ds
import events
import maintenance
import renames
import schema
import settings
from context import atlas
from overlays import slot_key
from security import actor, is_admin

from . import _body, _count, bp
from .auth import write_required

log = logging.getLogger("atlas.api.v2")

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

OVERLAID = {"nodes": ("positions", ("x", "y")), "rack": ("rack", ("u",))}


_LDAP_ADMIN_PROOF = "_ldap_admin_proof"

_PROOF_TTL_SECONDS = 15 * 60

_proof_by_actor = {}


def _remember_ldap_admin_proof():
    import atlas_auth
    now = time.time()
    if atlas_auth.sessions_enabled():
        from flask import session
        session[_LDAP_ADMIN_PROOF] = now
        return
    _proof_by_actor[actor()] = now


def _has_ldap_admin_proof():
    import atlas_auth
    if atlas_auth.sessions_enabled():
        from flask import session
        at = session.get(_LDAP_ADMIN_PROOF)
    else:
        at = _proof_by_actor.get(actor())
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return False
    return (time.time() - at) <= _PROOF_TTL_SECONDS


def _local_admin_exists():
    try:
        import accounts
        return any(u.get("is_admin") and u.get("active") and u.get("source") == "local"
                   for u in accounts.list_users())
    except Exception:
        return False


@admin_bp.before_request
def _admins_only():
    if not is_admin():
        return jsonify({"error": "admins only"}), 403
    return None


@admin_bp.after_request
def _never_cache(resp):
    resp.headers["Cache-Control"] = "no-store, private"
    import hub_auth.auth as _ha
    resp.headers["Vary"] = _ha.SIGNED_HEADER
    return resp


def _fail(exc, status):
    return jsonify({"error": str(exc),
                    "problems": getattr(exc, "problems", [str(exc)])}), status


def _read(ctx):
    try:
        data, stamp = ctx.store.read()
    except ds.RejectedError as e:
        return None, None, _fail(e, 409)
    return data, stamp, None


@admin_bp.route("/context")
def context():
    ctx = atlas()
    store = ctx.store
    try:
        stamp = store.stamp()
        readable = True
    except ds.RejectedError as e:
        stamp, readable = None, False
        log.warning("v2 editor context: %s", e)
    return jsonify({
        "schema": schema.catalogue(),
        "stamp": stamp,
        "actor": actor(),
        "backend": ctx.backend,
        "site": ctx.site,
        "seeded": ctx.reader.seeded(),
        "readable": readable,
        "writable": settings.writes_enabled() and store.writable(),
        "read_only": settings.READ_ONLY,
        "version": settings.APP_VERSION,
    })


@admin_bp.route("/dataset")
def get_dataset():
    ctx = atlas()
    data, stamp, refusal = _read(ctx)
    if refusal:
        return refusal

    overridden = {}
    for section, (overlay_name, _fields) in OVERLAID.items():
        saved = ctx.overlays[overlay_name].read()
        if saved:
            overridden[section] = sorted(saved.keys())
    return jsonify({"data": data, "stamp": stamp, "overridden": overridden})


_STORE_REFUSALS = (ds.ConflictError, ds.BusyError, ds.RejectedError)


def _store_refusal(exc):
    if isinstance(exc, ds.ConflictError):
        return _fail(exc, 409)
    if isinstance(exc, ds.BusyError):
        resp = jsonify({"error": str(exc), "problems": [str(exc)]})
        resp.headers["Retry-After"] = "2"
        return resp, 503
    return _fail(exc, 422)


def _commit(ctx, ops, expect, note, origin=None):
    try:
        result = ctx.store.apply(ops, actor=actor(), expect=expect, note=note, origin=origin)
    except _STORE_REFUSALS as e:
        return None, _store_refusal(e)
    except (TypeError, AttributeError, KeyError) as e:
        log.warning("v2: malformed change refused: %s: %s", e.__class__.__name__, e)
        return None, _fail(ds.RejectedError("that change holds a value of the wrong shape"), 422)
    except OSError as e:
        log.error("v2: dataset write failed: %s", e)
        return None, (jsonify({"error": f"could not save: {e}"}), 500)
    result["overlays_cleared"] = _clear_superseded_overlays(ctx, ops)
    ctx.invalidate()
    return result, None


def _clear_superseded_overlays(ctx, ops):
    cleared = 0
    for op in ops:
        section = op.get("section")
        if section not in OVERLAID or op.get("op") not in ("upsert", "insert", "delete"):
            continue
        overlay_name, fields = OVERLAID[section]
        body = op.get("body") or {}
        touched = op.get("op") == "delete" or any(f in body for f in fields)
        if not touched:
            continue
        key = op.get("id") or (slot_key(body) if section == "rack" else None)
        if key:
            cleared += ctx.overlays[overlay_name].drop([key])
    return cleared


def _rule_collection_ids():
    try:
        import alerts
        doc, _ = alerts.read()
    except Exception:
        return set()
    return {r["target"]["id"] for r in doc.get("rules") or []
            if isinstance(r, dict) and isinstance(r.get("target"), dict)
            and alerts.target_kind(r["target"].get("kind")) == "collection"
            and isinstance(r["target"].get("id"), str)}


def _window_collection_ids():
    try:
        stored = maintenance.read()
    except Exception:
        return set()
    return {c for w in stored["windows"] for c in (w.get("collections") if isinstance(w.get("collections"), list) else [])
            if isinstance(c, str)}


@admin_bp.route("/ops", methods=["POST"])
@write_required
def apply_ops():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected {ops, expect}"}), 400
    rule_ids, window_ids = _rule_collection_ids(), _window_collection_ids()
    taken = rule_ids | window_ids
    if taken:
        data, _, refused = _read(atlas())
        if refused:
            return refused
        listed = data.get("collections")
        current = {c.get("id") for c in listed if isinstance(c, dict)} if isinstance(listed, list) else set()
        for op in body.get("ops") if isinstance(body.get("ops"), list) else []:
            if not (isinstance(op, dict) and op.get("op") in ("insert", "upsert")
                    and op.get("section") == "collections"):
                continue
            fields = op.get("body") if isinstance(op.get("body"), dict) else {}
            new_id = fields.get("id") if isinstance(fields.get("id"), str) else op.get("id")
            if isinstance(new_id, str) and new_id in taken and new_id not in current:
                if new_id in rule_ids:
                    return jsonify({"error": "that collection id is still named by an alert rule",
                                    "problems": [f"collection {new_id!r}: an alert rule on a removed "
                                                 "collection still names this id, and would start "
                                                 "watching this one; choose another id, or remove that "
                                                 "rule first (with alerts on: Settings › Alerts, Rules on something gone)"]}), 422
                return jsonify({"error": "that collection id is still named by a maintenance window",
                                "problems": [f"collection {new_id!r}: a maintenance window still "
                                             "names this id, and would put this collection in "
                                             "maintenance; choose another id, or take it out of "
                                             "that window first"]}), 422
    ops = body.get("ops")
    plan = _service_moves(ops)
    if plan and plan["moves"]:
        ops = list(ops) + renames.collection_ops(plan["after"], plan["moves"])
    result, refused = _commit(atlas(), ops, body.get("expect"),
                              str(body.get("note") or "")[:200], body.get("origin"))
    if refused:
        return refused
    if plan:
        result["carried"] = _carry_elsewhere(plan)
    return jsonify(result)


def _service_moves(ops):
    if not isinstance(ops, list) or not any(
            isinstance(op, dict) and op.get("op") == "upsert" and op.get("section") == "nodes"
            and isinstance(op.get("body"), dict)
            and ("links" in op["body"] or isinstance(op["body"].get("id"), str)) for op in ops):
        return None
    try:
        data, _, refused = _read(atlas())
        if refused or not renames.enabled(data):
            return None
        after, _ = ds.apply_ops(data, ops)
    except Exception:
        return None
    return _carry_plan(data, after, renames.renamed_places(ops, data))


def _carry_plan(before, after, renamed=None):
    moves, stayed = renames.map_moves(before, after, renamed)
    if not moves and not stayed:
        return None
    return {"moves": moves, "stayed": stayed, "before": before, "after": after}


def _carry_elsewhere(plan):
    moves = plan["moves"]
    out = {"services": [f"{a} -> {b}" for a, news in sorted(moves.items()) for b in news],
           "windows": 0, "rules": 0, "checks": 0}
    split = [{"key": a, "to": list(news), "rule_to": news[0], "rules": 0}
             for a, news in sorted(renames.splits(moves).items())]
    if split:
        out["split"] = split
    if plan["stayed"]:
        out["stayed"] = list(plan["stayed"])
    if not moves:
        return out
    try:
        stored = maintenance.read()
        windows = renames.carried_windows(stored["windows"], moves)
        if windows is not None:
            maintenance.save(windows, actor=actor(), expect=maintenance.stamp())
            out["windows"] = sum(1 for w, was in zip(windows, stored["windows"]) if w is not was)
    except Exception as e:
        log.warning("v2: could not carry renames into the repairs: %s", e)
        out["windows_failed"] = True
    try:
        import alerts
        doc, stamp = alerts.read()
        carried = renames.carried_rules(doc, moves)
        if carried is not None:
            alerts.save(carried, expect=stamp)
            named = [was["target"]["id"] for now, was in zip(carried["rules"], doc.get("rules") or [])
                     if now is not was]
            out["rules"] = len(named)
            for entry in split:
                entry["rules"] = named.count(entry["key"])
    except Exception as e:
        log.warning("v2: could not carry renames into the alert rules: %s", e)
        out["rules_failed"] = True
    try:
        import watch
        out["checks"] = watch.carry(plan["before"], plan["after"], moves)
    except Exception as e:
        log.warning("v2: could not carry renames into the checks: %s: %s", type(e).__name__, e)
        out["checks_failed"] = True
    return out


@admin_bp.route("/dependents")
def dependents():
    section = request.args.get("section", "")
    entry_id = request.args.get("id", "")
    if not schema.get(section):
        return jsonify({"error": f"unknown section {section!r}"}), 400
    data, _, refusal = _read(atlas())
    if refusal:
        return refusal
    return jsonify({"dependents": ds.dependents(data, section, entry_id)})


@admin_bp.route("/revisions")
def revisions():
    return jsonify({"revisions": atlas().store.revisions(limit=_count("limit", 25, 200)),
                    "kept": ds.KEEP_REVISIONS})


@admin_bp.route("/revisions/<int:revision_id>/revert", methods=["POST"])
@write_required
def revert(revision_id):
    ctx = atlas()
    before = _map_to_carry_from(ctx)
    try:
        result = ctx.store.revert(revision_id, actor=actor(),
                                  expect=_body().get("expect"))
    except _STORE_REFUSALS as e:
        return _store_refusal(e)
    except OSError as e:
        return jsonify({"error": f"could not revert: {e}"}), 500
    ctx.invalidate()
    carried = _carry_undo(ctx, before, revision_id)
    if carried:
        result["carried"] = carried
    return jsonify(result)


def _map_to_carry_from(ctx):
    try:
        data, _ = ctx.store.read()
    except Exception:
        return None
    return data if renames.enabled(data) else None


def _carry_undo(ctx, before, revision_id):
    if before is None:
        return None
    try:
        after, _ = ctx.store.read()
        renamed = {}
        latest = ctx.store.revisions(limit=2)
        if len(latest) == 2 and latest[1].get("id") == revision_id:
            forward = renames.renamed_places(latest[1].get("ops"), after)
            renamed = {new: old for old, new in forward.items()}
        plan = _carry_plan(before, after, renamed)
        return _carry_elsewhere(plan) if plan else None
    except Exception as e:
        log.warning("v2: could not carry an undo's renames: %s: %s", type(e).__name__, e)
        return None


@admin_bp.route("/maintenance")
def maintenance_list():
    stored = maintenance.read()
    return jsonify({
        "windows": maintenance.annotated(),
        "legacy_nodes": stored["nodes"],
        "summary": maintenance.summary(),
        "stamp": maintenance.stamp(),
    })


@admin_bp.route("/maintenance", methods=["POST"])
@write_required
def maintenance_save():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("windows"), list):
        return jsonify({"error": "expected {windows: [...]}"}), 400

    problems = maintenance.problems(body["windows"])
    if problems:
        return jsonify({"error": "those repairs have problems", "problems": problems}), 422

    try:
        result = maintenance.save(body["windows"], actor=actor(), expect=body.get("expect"))
    except maintenance.StaleError:
        return jsonify({"error": "someone else changed the repairs while you were "
                                 "editing — reload and try again"}), 409
    return jsonify({"ok": True, **result})


@admin_bp.route("/events/<int:event_id>/ack", methods=["POST"])
@write_required
def event_ack(event_id):
    body = _body()
    event = events.acknowledge(event_id, actor(), body.get("note") or "")
    if event is None:
        return jsonify({"error": f"no event {event_id}"}), 404
    return jsonify({"ok": True, "event": event})


def _valid_url(value):
    from urllib.parse import urlparse
    try:
        u = urlparse(value)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.netloc)


def _secret_stays_home():
    return ("A saved credential only goes to its saved address. "
            "Type the credential again to use this one.")


_PROBE_LIMIT, _PROBE_WINDOW_S = 10, 60
_probe_log: dict = {}
_probe_lock = threading.Lock()


def _probe_allowed(who):
    now = time.monotonic()
    with _probe_lock:
        recent = [t for t in _probe_log.get(who, []) if now - t < _PROBE_WINDOW_S]
        if len(recent) >= _PROBE_LIMIT:
            _probe_log[who] = recent
            return False
        recent.append(now)
        _probe_log[who] = recent
        return True


from . import (
    admin_alerts, admin_connections, admin_directory, admin_discovery, admin_mapart,
    admin_shadow, admin_sources,
)
from .admin_sources import _probe

bp.register_blueprint(admin_bp)
