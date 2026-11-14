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
        _, stamp = store.read()
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


@admin_bp.route("/ops", methods=["POST"])
@write_required
def apply_ops():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected {ops, expect}"}), 400
    # `origin` lets the page say "these came from a survey": it can only lower
    # the standing of what it writes (unreviewed), never raise it
    result, refused = _commit(atlas(), body.get("ops"), body.get("expect"),
                              str(body.get("note") or "")[:200], body.get("origin"))
    return refused or jsonify(result)


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
    try:
        result = ctx.store.revert(revision_id, actor=actor(),
                                  expect=_body().get("expect"))
    except _STORE_REFUSALS as e:
        return _store_refusal(e)
    except OSError as e:
        return jsonify({"error": f"could not revert: {e}"}), 500
    ctx.invalidate()
    return jsonify(result)


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
    admin_sources,
)
# Names that lived in this module before the split and are still reached through it.
from .admin_sources import _probe  # noqa: E402,F401

bp.register_blueprint(admin_bp)
