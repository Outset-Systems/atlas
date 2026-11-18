"""The editing API — `/api/v2/admin/*`, everything behind the ✎ chrome.

One namespace, every write through `security.write_refusal()` (as the
`write_required` decorator) and the same admin clearance for reads. A
read-only deployment refuses every write here and still answers its admins'
reads; a look-only standalone one has no admin, so there every request here is
refused. Nothing here exists for a viewer who isn't cleared: `/` doesn't even
render the editing chrome for them.

A NESTED blueprint (Flask ≥2), so the admin surface keeps its own
`before_request` (admins only) and `after_request` (never cache) without
touching the rest of v2, producing endpoints `api_v2.admin.*`.

The shape is deliberately small. The browser fetches the field catalogue once,
renders every form from it, and posts back a list of operations. There is no
per-section endpoint, because there is no per-section server logic — that is
what made six editors affordable.

`GET /map-art/<name>` (the binary serve) stays on `views` — it is not under
`/api/`.
"""

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

from . import _body, bp
from .auth import write_required

log = logging.getLogger("atlas.api.v2")

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

#: Sections whose entries the layout overlays can override, and the field that
#: collides. Editing one of these has to clear the override or the edit looks
#: like it silently didn't take.
OVERLAID = {"nodes": ("positions", ("x", "y")), "rack": ("rack", ("u",))}


# ── THE DIRECTORY's receipt ──────────────────────────────────────────────────
# The most dangerous screen in the app decides both who may sign in and who is
# an admin. Two guardrails, and they are the reason it is not just a form that
# writes a file:
#
#  1. TEST BEFORE SAVE. The test authenticates a REAL account against the
#     PROPOSED settings — not a ping, an actual bind — so "it works" means a
#     person can sign in, not that a port is open.
#  2. NEVER LOCK EVERYONE OUT. A config with no local backend and no proven
#     directory admin is refused. The proof is that test: it records, in this
#     session, that some account both authenticated AND mapped to admin under
#     the settings being saved. So the only way to hand the instance to the
#     directory alone is to have demonstrated an admin can get back in.
_LDAP_ADMIN_PROOF = "_ldap_admin_proof"

#: How long a successful directory test keeps unlocking an ldap-only save.
#: The proof used to be a bare `True` that was never cleared or expired, so one
#: successful test at any point in the past unlocked every later save for the
#: life of the session — including saves of settings the test never covered.
_PROOF_TTL_SECONDS = 15 * 60

#: Where the proof lives when there is no Atlas session to put it in. In `hub`
#: mode `_configure_sessions()` is never called, so `app.secret_key` is None and
#: assigning to `session` raises RuntimeError — a successful directory test was
#: answering 500. Hub mode still has an identity (the Hub signed it), so the
#: proof is held against that actor instead. Process-local and TTL'd by design:
#: it is a "you proved this a moment ago" receipt, not a grant.
#: ⚠ Per-PROCESS: under gunicorn's two workers a test-then-save can land on
#: different workers in hub mode (carried since the port; the deployment that
#: matters runs hybrid, where the receipt rides the session).
_proof_by_actor = {}


def _remember_ldap_admin_proof():
    """Record that this caller just bound as a directory admin."""
    import atlas_auth
    now = time.time()
    if atlas_auth.sessions_enabled():
        from flask import session
        session[_LDAP_ADMIN_PROOF] = now
        return
    _proof_by_actor[actor()] = now


def _has_ldap_admin_proof():
    """True if this caller proved a directory admin can sign in, recently."""
    import atlas_auth
    if atlas_auth.sessions_enabled():
        from flask import session
        at = session.get(_LDAP_ADMIN_PROOF)
    else:
        at = _proof_by_actor.get(actor())
    # A legacy `True` from an older session is not a timestamp; it reads as
    # long expired, which is the direction this should fail in.
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return False
    return (time.time() - at) <= _PROOF_TTL_SECONDS


def _local_admin_exists():
    try:
        import accounts
        return any(u.get("is_admin") and u.get("active") and u.get("source") == "local"
                   for u in accounts.list_users())
    except Exception:      # noqa: BLE001 — no store yet is simply "no local admin"
        return False


@admin_bp.before_request
def _admins_only():
    """Reads here are as sensitive as writes — the change log names people."""
    if not is_admin():
        return jsonify({"error": "admins only"}), 403
    return None


@admin_bp.after_request
def _never_cache(resp):
    """Nothing from this blueprint may be stored by anything, ever (v1 rule)."""
    resp.headers["Cache-Control"] = "no-store, private"
    import hub_auth.auth as _ha
    resp.headers["Vary"] = _ha.SIGNED_HEADER
    return resp


def _fail(exc, status):
    return jsonify({"error": str(exc),
                    "problems": getattr(exc, "problems", [str(exc)])}), status


def _read(ctx):
    """The dataset and its stamp, or the 409 a route answers when the store
    cannot be read. Returns (data, stamp, None) or (None, None, response)."""
    try:
        data, stamp = ctx.store.read()
    except ds.RejectedError as e:
        return None, None, _fail(e, 409)
    return data, stamp, None


# ── Boot ─────────────────────────────────────────────────────────────────────
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


# ── Writes ───────────────────────────────────────────────────────────────────
_STORE_REFUSALS = (ds.ConflictError, ds.BusyError, ds.RejectedError)


def _store_refusal(exc):
    """What a write answers when the store refuses it: 409 for a map that has
    moved on, 503 with `Retry-After` for a store that is busy, 422 for a change
    it rejects."""
    if isinstance(exc, ds.ConflictError):
        return _fail(exc, 409)
    if isinstance(exc, ds.BusyError):
        resp = jsonify({"error": str(exc), "problems": [str(exc)]})
        resp.headers["Retry-After"] = "2"
        return resp, 503
    return _fail(exc, 422)


def _commit(ctx, ops, expect, note, origin=None):
    """One batch through the store, or the error response a write route answers with.
    Returns (result, None) or (None, response)."""
    try:
        result = ctx.store.apply(ops, actor=actor(), expect=expect, note=note, origin=origin)
    except _STORE_REFUSALS as e:
        return None, _store_refusal(e)
    except (TypeError, AttributeError, KeyError) as e:
        # a value of the wrong shape (an id that is a list, say) that the checks
        # tripped over before they could name it: refused, and nothing was saved
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
    """The collection ids stored alert rules name (kind `collection`, or the
    old `set`). Empty when there are none or the store cannot be read."""
    try:
        import alerts
        doc, _ = alerts.read()
    except Exception:  # noqa: BLE001 — no alerts store, no rule to protect
        return set()
    return {r["target"]["id"] for r in doc.get("rules") or []
            if isinstance(r, dict) and isinstance(r.get("target"), dict)
            and alerts.target_kind(r["target"].get("kind")) == "collection"
            and isinstance(r["target"].get("id"), str)}


def _window_collection_ids():
    """The collection ids stored maintenance windows name (2026-11-14). A new
    collection taking one of these would land in that window unseen."""
    try:
        stored = maintenance.read()
    except Exception:  # noqa: BLE001 — no repairs store, no window to protect
        return set()
    return {c for w in stored["windows"] for c in (w.get("collections") if isinstance(w.get("collections"), list) else [])
            if isinstance(c, str)}


@admin_bp.route("/ops", methods=["POST"])
@write_required
def apply_ops():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected {ops, expect}"}), 400
    # A NEW COLLECTION NEVER TAKES AN ID AN ALERT RULE STILL NAMES (round 14).
    # Removing a collection suspends its rules; inserting one with the same
    # id from anywhere (the rail, the Desk, a script) would quietly revive
    # them on new members. Pick another id, or point the rule elsewhere first.
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
            # the id the entry will have: the body's (an insert, or an edit
            # that renames the id), else the one the upsert names (round 15)
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
    # CARRYING RENAMES (2026-11-15, the owner's toggle): with the map's
    # `carry_service_renames` on, a write that renames a service (its label,
    # its monitor, its place's id) takes the collections naming it along in
    # this same save, and the windows and alert rules straight after
    ops = body.get("ops")
    plan = _service_moves(ops)
    if plan and plan["moves"]:
        ops = list(ops) + renames.collection_ops(plan["after"], plan["moves"])
    # `origin` lets the page say "these came from a survey": it can only lower
    # the standing of what it writes (unreviewed), never raise it
    result, refused = _commit(atlas(), ops, body.get("expect"),
                              str(body.get("note") or "")[:200], body.get("origin"))
    if refused:
        return refused
    if plan:
        result["carried"] = _carry_elsewhere(plan)
    return jsonify(result)


def _service_moves(ops):
    """What a write carries, when the map asks for renames to be carried:
    {"moves": {old key: [new keys]}, "stayed": [keys still in use], "before",
    "after"} (the map on either side of the ops), or None when there is
    nothing to carry or to say.

    The whole map decides (`renames.map_moves`), so the ops are applied to a
    copy first. A batch the store will refuse carries nothing: the save
    answers with the refusal, as it would have."""
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
    except Exception:  # noqa: BLE001 (no map, or ops the store will refuse: nothing to carry)
        return None
    return _carry_plan(data, after, renames.renamed_places(ops, data))


def _carry_plan(before, after, renamed=None):
    """The plan `_carry_elsewhere` works from, or None when no key changed."""
    moves, stayed = renames.map_moves(before, after, renamed)
    if not moves and not stayed:
        return None
    return {"moves": moves, "stayed": stayed, "before": before, "after": after}


def _carry_elsewhere(plan):
    """Carry a plan's moves in the repair windows, the alert rules and what
    the checks last heard, each under its own store's lock; what moved where,
    for the answer. A store that cannot be read or written is said, never
    raised: the map is already saved.

    The answer: `services` ("old -> new", one line for each key a key went
    to), `windows` and `rules` (how many changed), `checks` (how many checks
    kept what they last heard); `split` when one key went to several (which,
    where to, and the one its alert rules now name); `stayed` for a key that
    changed on one link and is still another's, which is why it moved nothing."""
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
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
        log.warning("v2: could not carry renames into the alert rules: %s", e)
        out["rules_failed"] = True
    try:
        import watch
        out["checks"] = watch.carry(plan["before"], plan["after"], moves)
    except Exception as e:  # noqa: BLE001
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


# ── History ──────────────────────────────────────────────────────────────────
@admin_bp.route("/revisions")
def revisions():
    limit = request.args.get("limit", type=int) or 25
    return jsonify({"revisions": atlas().store.revisions(limit=min(limit, 200)),
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
    """The map as it stands, when it asks for renames to be carried; else None."""
    try:
        data, _ = ctx.store.read()
    except Exception:  # noqa: BLE001 (the undo itself says what is wrong)
        return None
    return data if renames.enabled(data) else None


def _carry_undo(ctx, before, revision_id):
    """AN UNDO PUTS THE CARRY BACK (2026-11-18). The snapshot brings the
    collections back with the map; the repair windows, the alert rules and
    the checks are stores of their own and would be left on keys the map no
    longer has. So an undo is carried like any other write: every key that
    differs between the map as it was (`before`) and the map as it is now
    goes back the same way, a key that had gone to several included (they
    all go back to the one). The setting that decides is the one the map had
    before the undo.

    Places are paired by id. A place the undo gives its old id back is known
    only when the undo took back the one latest change (its ops are in the
    change log); an undo reaching further back carries nothing for a place
    whose id it changed. Never raises."""
    if before is None:
        return None
    try:
        after, _ = ctx.store.read()
        renamed = {}
        latest = ctx.store.revisions(limit=2)      # the undo itself, then what came before it
        if len(latest) == 2 and latest[1].get("id") == revision_id:
            forward = renames.renamed_places(latest[1].get("ops"), after)
            renamed = {new: old for old, new in forward.items()}
        plan = _carry_plan(before, after, renamed)
        return _carry_elsewhere(plan) if plan else None
    except Exception as e:  # noqa: BLE001 (the map is already put back)
        log.warning("v2: could not carry an undo's renames: %s: %s", type(e).__name__, e)
        return None


# ── THE REPAIRS — maintenance windows ────────────────────────────────────────
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

    # `expect` is checked inside the write's lock (`maintenance.save`), not
    # here: checked first and written later, two editors holding the same
    # stamp both passed and the second overwrote the first (11-12 audit).
    try:
        result = maintenance.save(body["windows"], actor=actor(), expect=body.get("expect"))
    except maintenance.StaleError:
        return jsonify({"error": "someone else changed the repairs while you were "
                                 "editing — reload and try again"}), 409
    return jsonify({"ok": True, **result})


# ── THE ANNALS — acknowledging what happened ─────────────────────────────────
@admin_bp.route("/events/<int:event_id>/ack", methods=["POST"])
@write_required
def event_ack(event_id):
    body = _body()
    event = events.acknowledge(event_id, actor(), body.get("note") or "")
    if event is None:
        return jsonify({"error": f"no event {event_id}"}), 404
    return jsonify({"ok": True, "event": event})


# ── Shared by the screens that reach outward ─────────────────────────────────
# THE SOURCES and CONNECTIONS (admin_sources.py, admin_connections.py) both aim
# requests at addresses an admin typed. The URL check, the rule about saved
# secrets and the limiter are one copy, here.
def _valid_url(value):
    from urllib.parse import urlparse
    try:
        u = urlparse(value)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.netloc)


def _secret_stays_home():
    """The answer when a new address would receive a stored secret."""
    return ("A saved credential only goes to its saved address. "
            "Type the credential again to use this one.")


#: Probes are outbound requests an admin can aim at any http(s) host they can
#: type; a burst of them is a scanner with an admin cookie. Ten a minute per
#: actor is more than a human testing four sources needs (v1.38.0).
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


# The other admin screens. They attach to `admin_bp`, so they are imported here,
# after everything above exists and before the blueprint is registered. The
# editor stays in this file; each of these is one screen of Settings.
from . import (  # noqa: E402,F401
    admin_alerts, admin_connections, admin_directory, admin_discovery, admin_mapart,
    admin_shadow, admin_sources,
)
# Names that lived in this module before the split and are still reached through it.
from .admin_sources import _probe  # noqa: E402,F401

bp.register_blueprint(admin_bp)
