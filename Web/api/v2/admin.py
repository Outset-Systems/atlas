"""The editing API — `/api/v2/admin/*`, everything behind the ✎ chrome.

One namespace, every write through `security.write_refusal()` and the same
admin clearance for reads. Nothing here is reachable in a read-only
deployment, and nothing here exists for a viewer who isn't cleared: `/`
doesn't even render the editing chrome for them.

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
import os
import time

from flask import Blueprint, jsonify, request

import dataset as ds
import discovery
import events
import maintenance
import mapart
import schema
import settings
from context import atlas
from overlays import slot_key
from security import actor, is_admin, write_refusal

from . import bp

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
    try:
        data, stamp = ctx.store.read()
    except ds.RejectedError as e:
        return _fail(e, 409)

    overridden = {}
    for section, (overlay_name, _fields) in OVERLAID.items():
        saved = ctx.overlays[overlay_name].read()
        if saved:
            overridden[section] = sorted(saved.keys())
    return jsonify({"data": data, "stamp": stamp, "overridden": overridden})


# ── Writes ───────────────────────────────────────────────────────────────────
def _commit(ctx, ops, expect, note):
    """One batch through the store, or the error response a write route answers with.
    Returns (result, None) or (None, response)."""
    try:
        result = ctx.store.apply(ops, actor=actor(), expect=expect, note=note)
    except ds.ConflictError as e:
        return None, _fail(e, 409)
    except ds.BusyError as e:
        resp = jsonify({"error": str(e), "problems": [str(e)]})
        resp.headers["Retry-After"] = "2"
        return None, (resp, 503)
    except ds.RejectedError as e:
        return None, _fail(e, 422)
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
def apply_ops():
    refusal = write_refusal()
    if refusal:
        return refusal
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected {ops, expect}"}), 400
    result, refused = _commit(atlas(), body.get("ops"), body.get("expect"),
                              str(body.get("note") or "")[:200])
    return refused or jsonify(result)


@admin_bp.route("/dependents")
def dependents():
    section = request.args.get("section", "")
    entry_id = request.args.get("id", "")
    if not schema.get(section):
        return jsonify({"error": f"unknown section {section!r}"}), 400
    try:
        data, _ = atlas().store.read()
    except ds.RejectedError as e:
        return _fail(e, 409)
    return jsonify({"dependents": ds.dependents(data, section, entry_id)})


# ── History ──────────────────────────────────────────────────────────────────
@admin_bp.route("/revisions")
def revisions():
    limit = request.args.get("limit", type=int) or 25
    return jsonify({"revisions": atlas().store.revisions(limit=min(limit, 200)),
                    "kept": ds.KEEP_REVISIONS})


@admin_bp.route("/revisions/<int:revision_id>/revert", methods=["POST"])
def revert(revision_id):
    refusal = write_refusal()
    if refusal:
        return refusal
    ctx = atlas()
    try:
        result = ctx.store.revert(revision_id, actor=actor(),
                                  expect=(request.get_json(silent=True) or {}).get("expect"))
    except ds.ConflictError as e:
        return _fail(e, 409)
    except ds.BusyError as e:
        resp = jsonify({"error": str(e), "problems": [str(e)]})
        resp.headers["Retry-After"] = "2"
        return resp, 503
    except ds.RejectedError as e:
        return _fail(e, 422)
    except OSError as e:
        return jsonify({"error": f"could not revert: {e}"}), 500
    ctx.invalidate()
    return jsonify(result)


# ── Discovery inbox ──────────────────────────────────────────────────────────
@admin_bp.route("/discovery")
def discovery_list():
    ctx = atlas()
    try:
        data, _ = ctx.store.read()
    except ds.RejectedError as e:
        return _fail(e, 409)
    rows = discovery.listing(data, ctx.backend, ctx.site)
    return jsonify({
        "observed": rows,
        "undocumented": sum(1 for r in rows if r["undocumented"] and not r["ignored"]),
    })


@admin_bp.route("/discovery/scan", methods=["POST"])
def discovery_scan():
    refusal = write_refusal()
    if refusal:
        return refusal
    body = request.get_json(silent=True) or {}
    text = body.get("nmap_xml") or ""
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "send {nmap_xml: '<nmaprun>…'}"}), 400
    if len(text) > 4_000_000:
        return jsonify({"error": "that scan is too large (max 4 MB)"}), 413
    from importers.scan import NmapError, parse_nmap_xml
    try:
        hosts = parse_nmap_xml(text)
    except NmapError as e:
        return jsonify({"error": str(e)}), 422
    new = discovery.record(hosts, atlas().backend, atlas().site)
    log.info("v2 discovery: %d hosts filed (%d new) by %s", len(hosts), new, actor())
    return jsonify({"ok": True, "seen": len(hosts), "new": new})


@admin_bp.route("/discovery/leases", methods=["POST"])
def discovery_leases():
    """A router's DHCP lease file, filed into the same survey as a scan: the
    devices that asked for an address, with the names they gave themselves.
    Read from what the operator hands over, never fetched from the router."""
    refusal = write_refusal()
    if refusal:
        return refusal
    body = request.get_json(silent=True) or {}
    text = body.get("leases") or ""
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "send {leases: '<the lease file>'}"}), 400
    if len(text) > 4_000_000:
        return jsonify({"error": "that lease file is too large (max 4 MB)"}), 413
    from importers.leases import LeaseError, parse_leases
    try:
        fmt, hosts = parse_leases(text)
    except LeaseError as e:
        return jsonify({"error": str(e)}), 422
    new = discovery.record(hosts, atlas().backend, atlas().site)
    log.info("v2 discovery: %d %s leases filed (%d new) by %s", len(hosts), fmt, new, actor())
    return jsonify({"ok": True, "format": fmt, "seen": len(hosts), "new": new})


@admin_bp.route("/discovery/decide", methods=["POST"])
def discovery_decide():
    refusal = write_refusal()
    if refusal:
        return refusal
    body = request.get_json(silent=True) or {}
    keys = body.get("keys")
    action = body.get("action")
    if not isinstance(keys, list) or not keys:
        return jsonify({"error": "send {keys: [...], action: ignore|unignore|forget}"}), 400
    if action == "ignore":
        discovery.set_ignored(keys, True)
    elif action == "unignore":
        discovery.set_ignored(keys, False)
    elif action == "forget":
        if atlas().backend == "db":
            # `discovery.forget` edits the FILE inbox; on the db backend that
            # file is not the inbox, so the edit would succeed and change
            # nothing the viewer can see.
            return jsonify({"error": "forget is not available on the db backend "
                                     "— ignore the device instead"}), 400
        discovery.forget(keys)
    else:
        return jsonify({"error": f"unknown action {action!r}"}), 400
    return jsonify({"ok": True, "action": action, "count": len(keys)})


@admin_bp.route("/discovery/as-nodes", methods=["POST"])
def discovery_as_nodes():
    refusal = write_refusal()
    if refusal:
        return refusal
    body = request.get_json(silent=True) or {}
    keys = set(body.get("keys") or [])
    ctx = atlas()
    try:
        data, _ = ctx.store.read()
    except ds.RejectedError as e:
        return _fail(e, 409)
    taken = {n.get("id") for n in data.get("nodes", []) or []}
    drafts = []
    for row in discovery.listing(data, ctx.backend, ctx.site):
        if row["key"] not in keys:
            continue
        node = discovery.as_node(row, data, taken)
        taken.add(node["id"])
        drafts.append(node)
    return jsonify({"nodes": discovery.place_drafts(data, drafts)})


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
def maintenance_save():
    refusal = write_refusal()
    if refusal:
        return refusal
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("windows"), list):
        return jsonify({"error": "expected {windows: [...]}"}), 400

    expect = body.get("expect")
    if expect and expect != maintenance.stamp():
        return jsonify({"error": "someone else changed the repairs while you were "
                                 "editing — reload and try again"}), 409

    problems = []
    seen = set()
    for i, window in enumerate(body["windows"]):
        if not isinstance(window, dict):
            problems.append(f"window #{i + 1}: not an object")
            continue
        label = window.get("id") or f"#{i + 1}"
        problems += [f"window {label}: {p}"
                     for p in schema.check_entry("maintenance", window, strict=True)]
        if window.get("id") in seen:
            problems.append(f"window {label}: duplicate id")
        seen.add(window.get("id"))
        state, _s, _e = maintenance.occurrence(window)
        if state == "invalid":
            problems.append(f"window {label}: it ends before it starts")
    if problems:
        return jsonify({"error": "those repairs have problems", "problems": problems}), 422

    result = maintenance.save(body["windows"], actor=actor())
    return jsonify({"ok": True, "stamp": maintenance.stamp(), **result})


# ── THE ANNALS — acknowledging what happened ─────────────────────────────────
@admin_bp.route("/events/<int:event_id>/ack", methods=["POST"])
def event_ack(event_id):
    refusal = write_refusal()
    if refusal:
        return refusal
    body = request.get_json(silent=True) or {}
    event = events.acknowledge(event_id, actor(), body.get("note") or "")
    if event is None:
        return jsonify({"error": f"no event {event_id}"}), 404
    return jsonify({"ok": True, "event": event})


# ── Bulk import ──────────────────────────────────────────────────────────────
@admin_bp.route("/import/csv", methods=["POST"])
def import_csv():
    refusal = write_refusal()
    if refusal:
        return refusal
    body = request.get_json(silent=True) or {}
    text = body.get("csv") or ""
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "send {csv: 'name,ip,kind,...'}"}), 400
    from importers.csv_import import parse_csv
    rows, errors = parse_csv(text)
    if errors:
        return jsonify({"error": "that list has problems", "problems": errors}), 422
    try:
        data, _ = atlas().store.read()
    except ds.RejectedError as e:
        return _fail(e, 409)

    taken = {n.get("id") for n in data.get("nodes", []) or []}
    zones = {z.get("id") for z in data.get("zones", []) or []}
    fallback = next(iter(zones), "uncharted")
    drafts = []
    for row in rows:
        node = discovery.as_node(
            {"ip": row["ip"], "hostname": row["name"]}, data, taken)
        node.update({
            "name": row["name"].upper(),
            "kind": row["kind"],
            "role": row["role"] or "imported · not yet described",
            "lore": row["notes"] or "Newly charted, its story not yet written.",
        })
        if row["zone"]:
            node["zone"] = row["zone"] if row["zone"] in zones else fallback
        if row["url"]:
            node["links"] = [{"label": row["url_label"] or "Service", "url": row["url"]}]
        taken.add(node["id"])
        drafts.append(node)
    return jsonify({"nodes": discovery.place_drafts(data, drafts), "count": len(drafts)})


# ── The base render ──────────────────────────────────────────────────────────
@admin_bp.route("/map-art")
def map_art_list():
    return jsonify({"images": mapart.available(),
                    "default": mapart.DEFAULT,
                    "max_bytes": mapart.MAX_BYTES})


@admin_bp.route("/map-art", methods=["POST"])
def map_art_upload():
    refusal = write_refusal()
    if refusal:
        return refusal
    upload = request.files.get("image")
    if not upload:
        return jsonify({"error": "send a file as `image`"}), 400
    name = (request.form.get("name") or upload.filename or "").strip()
    try:
        stored = mapart.save(name, upload.read())
    except ValueError as e:
        return jsonify({"error": str(e), "problems": [str(e)]}), 422
    except OSError as e:
        log.error("v2: could not store map art: %s", e)
        return jsonify({"error": f"could not store that render: {e}"}), 500
    log.info("v2: map art %s uploaded by %s", stored, actor())
    return jsonify({"ok": True, "name": stored, "images": mapart.available()})


@admin_bp.route("/map-art/survey", methods=["POST"])
def map_art_survey():
    refusal = write_refusal()
    if refusal:
        return refusal
    q = (request.get_json(silent=True) or {}).get("query") or ""
    import worldsurvey
    try:
        name, display = worldsurvey.survey(q)
    except worldsurvey.SurveyError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:                       # noqa: BLE001 — one sentence out
        log.error("v2: survey failed for %r: %s", q, e, exc_info=True)
        return jsonify({"error": "the survey failed — see the server log"}), 502
    log.info("v2: survey render %s stored by %s", name, actor())
    return jsonify({"ok": True, "name": name, "surveyed": display,
                    "images": mapart.available()})


@admin_bp.route("/map-art/<name>", methods=["DELETE"])
def map_art_delete(name):
    refusal = write_refusal()
    if refusal:
        return refusal
    try:
        mapart.remove(name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except OSError as e:
        return jsonify({"error": f"could not remove that render: {e}"}), 500
    log.info("v2: map art %s removed by %s", name, actor())
    return jsonify({"ok": True, "images": mapart.available()})


# ── THE DIRECTORY ────────────────────────────────────────────────────────────
@admin_bp.route("/auth")
def auth_settings():
    import auth_config
    import ldap_backend
    return jsonify({
        "settings": auth_config.effective(),
        "sources": auth_config.sources(),
        "allowed": list(auth_config.ALLOWED),
        "mode": settings.auth_config().get("mode", ""),
        "ldap_ready": ldap_backend.enabled(),
        "backends": ldap_backend.backends(),
        "local_admin_exists": _local_admin_exists(),
    })


@admin_bp.route("/auth/test", methods=["POST"])
def auth_settings_test():
    refusal = write_refusal()
    if refusal:
        return refusal
    body = request.get_json(silent=True) or {}
    proposed = body.get("settings") or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return jsonify({"ok": False, "error": "A name and password are needed to test a bind."}), 400
    import auth_config
    unknown = [k for k in proposed if k not in auth_config.ALLOWED]
    if unknown:
        return jsonify({"ok": False, "error": f"not a directory setting: {unknown[0]}"}), 400

    import ldap_backend
    overrides = {k: str(proposed.get(k, "") or "").strip() for k in auth_config.ALLOWED}
    try:
        ok, info = ldap_backend.authenticate(username, password, overrides=overrides)
    except ValueError as e:            # ldaps:// enforcement, bad URL
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:             # noqa: BLE001 — the directory is remote
        log.warning("v2: directory test failed: %s", e)
        return jsonify({"ok": False, "error": f"The directory did not answer: {e}"}), 200

    info = info or {}
    is_admin_result = bool(info.get("is_admin"))
    if ok and is_admin_result:
        _remember_ldap_admin_proof()           # the SHARED receipt (H5)
    log.info("v2: directory test by %s: ok=%s admin=%s", actor(), bool(ok), is_admin_result)
    return jsonify({"ok": bool(ok), "is_admin": is_admin_result,
                    "groups": info.get("groups") or [],
                    "display_name": info.get("display_name") or "",
                    "error": "" if ok else (info.get("error") or "That account could not sign in.")})


@admin_bp.route("/auth", methods=["POST"])
def auth_settings_save():
    refusal = write_refusal()
    if refusal:
        return refusal
    import auth_config
    proposed = (request.get_json(silent=True) or {}).get("settings") or {}
    unknown = [k for k in proposed if k not in auth_config.ALLOWED]
    if unknown:
        return jsonify({"error": f"not a directory setting: {unknown[0]}"}), 400

    def in_force(key):
        return (str(proposed.get(key, "") or "").strip()
                or os.environ.get(key, "") or "").strip()

    backends = [b.strip().lower() for b in (in_force("ATLAS_AUTH_BACKENDS") or "local").split(",")
                if b.strip()]
    if not any(b in ("local", "ldap") for b in backends):
        return jsonify({"error": "At least one sign-in backend (local or ldap) must stay enabled."}), 422
    url = in_force("ATLAS_LDAP_URL")
    if "ldap" in backends:
        if not url or not in_force("ATLAS_LDAP_BASE_DN"):
            return jsonify({"error": "The directory needs both a URL and a base DN."}), 422
        if not url.lower().startswith("ldaps://"):
            return jsonify({"error": "Only ldaps:// is accepted — a plaintext bind "
                                     "would put every password on the wire."}), 422

    if "local" not in backends and not _has_ldap_admin_proof():
        return jsonify({
            "error": "Test the directory with an admin account first. Saving a "
                     "directory-only sign-in without proving an admin can get "
                     "back in would lock this Atlas for everyone.",
            "needs_proof": True,
        }), 422
    if "local" in backends and not _local_admin_exists() and not _has_ldap_admin_proof():
        log.warning("v2: directory settings saved with no local admin present")

    try:
        effective = auth_config.save(proposed)
    except (ValueError, OSError) as e:
        return jsonify({"error": f"could not save: {e}"}), 500
    log.info("v2: directory settings changed by %s", actor())
    import ldap_backend
    return jsonify({"ok": True, "settings": effective,
                    "sources": auth_config.sources(),
                    "backends": ldap_backend.backends(),
                    "ldap_ready": ldap_backend.enabled()})


# ── THE SOURCES — integration settings (v1.37.0) ─────────────────────────────
def _hub_state():
    """What the live hub is actually running, and how each source answered
    last time — so the form shows the truth beside the settings."""
    try:
        hub = atlas().signals
        feed = hub._cache or {}
        return {"enabled": list(getattr(hub, "enabled", [])),
                "last": dict(feed.get("sources") or {})}
    except Exception:  # noqa: BLE001 — a form must never 500 over a status line
        return {"enabled": [], "last": {}}


def _probe(kind, url, key, path=None):
    """Ask one source whether it is there, the way the Atlas will ask it.
    Returns (ok, detail). Never raises — the answer is the point. `path` is
    the decoy feed's roster path as typed (None = the one in force)."""
    import requests
    base = (url or "").rstrip("/")
    if not base:
        return False, "no URL to ask"
    try:
        if kind == "prometheus":
            r = requests.get(base + "/-/ready", timeout=5)
            r.raise_for_status()
            q = requests.get(base + "/api/v1/query", params={"query": "count(up == 1)"}, timeout=5)
            q.raise_for_status()
            res = q.json().get("data", {}).get("result", [])
            n = int(float(res[0]["value"][1])) if res else 0
            return True, f"Prometheus is ready — {n} watchfire{'s' if n != 1 else ''} up"
        if kind == "loki":
            r = requests.get(base + "/ready", timeout=5)
            r.raise_for_status()
            return True, "Loki is ready"
        if kind == "kuma":
            r = requests.get(base + "/metrics", auth=("", key) if key else None, timeout=5)
            if r.status_code == 401:
                return False, "Kuma refused the key"
            r.raise_for_status()
            n = sum(1 for line in r.text.splitlines() if line.startswith("monitor_status{"))
            return True, f"Kuma answers — {n} monitor{'s' if n != 1 else ''}"
        if kind == "decoys":
            import envnames
            import integrations
            header = envnames.env("ATLAS_DECOYS_KEY_HEADER")
            # TRIPWIRES: ask where the adapter will ask (ATLAS_DECOYS_PATH)
            r = requests.get(base + (path or integrations.decoys_path()),
                             headers={header: key or ""}, timeout=5)
            if r.status_code in (401, 403, 404):
                return False, "the decoy feed did not admit that key"
            r.raise_for_status()
            stones = r.json().get("stones", {})
            n = len(stones)
            return True, f"the decoy feed answers — {n} decoy{'s' if n != 1 else ''} charted"
        return False, f"unknown source {kind!r}"
    except Exception as e:  # noqa: BLE001 — a remote that will not answer is the finding
        return False, f"did not answer: {e.__class__.__name__}: {str(e)[:120]}"


_PROBE_FIELDS = {"prometheus": ("ATLAS_PROM_URL", None),
                 "loki": ("ATLAS_LOKI_URL", None),
                 "kuma": ("ATLAS_KUMA_URL", "ATLAS_KUMA_API_KEY"),
                 "decoys": ("ATLAS_DECOYS_URL", "ATLAS_DECOYS_KEY")}


def _valid_url(value):
    from urllib.parse import urlparse
    try:
        u = urlparse(value)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.netloc)


@admin_bp.route("/integrations")
def integrations_get():
    import integrations
    return jsonify({"settings": integrations.describe(),
                    "allowed": list(integrations.ALLOWED),
                    "groups": {k: list(v) for k, v in integrations.GROUPS.items()},
                    "sources": list(integrations.SOURCES),
                    "hub": _hub_state()})


# ── THE DEPLOYMENT — every knob the app knows, read-only (v1.38.0) ───────────
_SECRETISH = ("KEY", "SECRET", "PASSWORD", "TOKEN")


def _known_env_names():
    """Every environment variable settings.py (and the two secret readers)
    consult, found by reading the source — so a knob added tomorrow shows up
    without anyone remembering to register it."""
    import glob as _glob
    import re as _re
    import integrations
    import auth_config
    import settings as _settings
    names = set()
    web = os.path.dirname(os.path.abspath(_settings.__file__))
    pattern = _re.compile(r'"((?:ATLAS|PROMETHEUS)_[A-Z0-9_]+|HUB_URL)"')
    for path in _glob.glob(os.path.join(web, "*.py")) + _glob.glob(os.path.join(web, "api", "**", "*.py"), recursive=True):
        try:
            with open(path, encoding="utf-8") as fh:
                names |= set(pattern.findall(fh.read()))
        except OSError:
            pass
    names |= set(integrations.ALLOWED)   # the runtime-settable ones live outside settings.py
    names |= set(auth_config.ALLOWED)    # ldap_backend reads these, not settings.py
    names |= {"ATLAS_AUTH_MODE", "ATLAS_HUB_SECRET", "ATLAS_HUB_SECRET_FILE",
              "ATLAS_HUB_AUTH_HEADER", "ATLAS_ADMIN_GROUP", "ATLAS_THEME", "HUB_URL", "ATLAS_METRICS_TOKEN", "ATLAS_METRICS_TOKEN_FILE",
              "ATLAS_KUMA_URL", "ATLAS_KUMA_API_KEY", "ATLAS_KUMA_API_KEY_FILE",
              "ATLAS_DECOYS_URL", "ATLAS_DECOYS_KEY", "ATLAS_DECOYS_KEY_FILE",
              "ATLAS_DECOYS_KEY_HEADER", "ATLAS_DECOYS_PATH",
              "ATLAS_TRIPWIRES_WEBHOOK", "ATLAS_TRIPWIRES_SECRET", "ATLAS_TRIPWIRES_SECRET_FILE",
              "ATLAS_TRIPWIRES_STATE",
              "ATLAS_LOKI_URL", "ATLAS_INTEGRATIONS", "PROMETHEUS_MULTIPROC_DIR"}
    return sorted(names)


@admin_bp.route("/deployment")
def deployment_view():
    """What this instance is actually running with: each knob, the layer its
    value came from (settings file / environment / default), and the value —
    masked to set/unset for anything that looks like a secret. Read-only by
    construction: there is no POST twin, and there must never be one (the
    allow-lists in auth_config/integrations are the only writable knobs)."""
    import auth_config
    import integrations
    layer = {"settings": "settings", "deployment": "environment", "unset": "default"}
    stored = integrations.sources()
    dir_stored, dir_values = auth_config.sources(), auth_config.effective()
    from urllib.parse import urlsplit, urlunsplit
    from flask import current_app

    def shown(name, value, secret):
        if secret:
            return "set" if value else "unset"
        # a URL that carries credentials (ATLAS_DB_URL is a DSN; a proxy URL
        # could be one) shows its shape, never its password (review, 2026-09-03)
        try:
            u = urlsplit(value)
            if u.password or u.username:
                host = u.hostname or ""
                if u.port:
                    host += f":{u.port}"
                return urlunsplit((u.scheme, f"{u.username or ''}:***@{host}", u.path, u.query, u.fragment))
        except ValueError:
            pass
        return value

    rows = []
    for name in _known_env_names():
        secret = any(tag in name for tag in _SECRETISH) or name in integrations.SECRETS
        if name in integrations.ALLOWED:
            value, source = integrations.get(name), layer[stored[name]]
        elif name in auth_config.ALLOWED:
            value, source = dir_values[name], layer[dir_stored[name]]
        else:
            # NAMES THAT CHANGED (v1.48.0): a deployment still on an old name
            # is still configured; envnames reads either spelling
            import envnames
            value = os.environ.get(name, "") or (
                (envnames.env(name) or "") if envnames.is_set(name) else "")
            source = "environment" if value else "default"
        rows.append({"name": name, "source": source, "secret": secret,
                     "value": shown(name, value, secret)})
    # `metrics` is what /metrics will actually DO: the registry came up AND a
    # token is configured. A token with a registry that failed to start (the
    # 09-03 uid case) is "off", not "on" — the first cut reported the token alone.
    token_set = bool(os.environ.get("ATLAS_METRICS_TOKEN") or os.environ.get("ATLAS_METRICS_TOKEN_FILE"))
    return jsonify({"version": settings.APP_VERSION, "mode": settings.auth_config().get("mode", ""),
                    "metrics": bool(current_app.config.get("METRICS_ENABLED")) and token_set,
                    "metrics_registry": bool(current_app.config.get("METRICS_ENABLED")),
                    "metrics_token": token_set,
                    "knobs": rows})


def _secret_stays_home():
    """The answer when a new address would receive a stored secret."""
    return ("A saved credential only goes to its saved address. "
            "Type the credential again to use this one.")


#: Probes are outbound requests an admin can aim at any http(s) host they can
#: type; a burst of them is a scanner with an admin cookie. Ten a minute per
#: actor is more than a human testing four sources needs (v1.38.0).
_PROBE_LIMIT, _PROBE_WINDOW_S = 10, 60
_probe_log: dict = {}
_probe_lock = __import__("threading").Lock()


def _probe_allowed(who):
    import time as _t
    now = _t.monotonic()
    with _probe_lock:
        recent = [t for t in _probe_log.get(who, []) if now - t < _PROBE_WINDOW_S]
        if len(recent) >= _PROBE_LIMIT:
            _probe_log[who] = recent
            return False
        recent.append(now)
        _probe_log[who] = recent
        return True


@admin_bp.route("/integrations/test", methods=["POST"])
def integrations_test():
    """Probe ONE source with the values as typed (unsaved) — a blank key means
    'the one in force', so a stored secret can be tested without retyping it, at
    the address it was saved with and nowhere else."""
    refusal = write_refusal()
    if refusal:
        return refusal
    if not _probe_allowed(actor()):
        return jsonify({"ok": False, "error": "Too many tests in a minute — wait a moment."}), 429
    import integrations
    body = request.get_json(silent=True) or {}
    kind = str(body.get("kind") or "").strip().lower()
    if kind not in _PROBE_FIELDS:
        return jsonify({"ok": False, "error": f"not a source that can be tested: {kind!r}"}), 400
    proposed = body.get("settings") or {}
    unknown = [k for k in proposed if k not in integrations.ALLOWED]
    if unknown:
        return jsonify({"ok": False, "error": f"not an integration setting: {unknown[0]}"}), 400
    url_key, secret_key = _PROBE_FIELDS[kind]
    url = str(proposed.get(url_key) or "").strip() or integrations.get(url_key)
    if not url:
        return jsonify({"ok": False, "error": f"No URL is set for {kind} — nothing to ask."}), 400
    if not _valid_url(url):
        return jsonify({"ok": False, "error": "That is not an http(s) URL with a host."}), 400
    if integrations.moves_secret(url_key, proposed):
        return jsonify({"ok": False, "error": _secret_stays_home()}), 400
    key = (str(proposed.get(secret_key) or "").strip() or integrations.get(secret_key)) if secret_key else None
    path = None
    if kind == "decoys":
        path = str(proposed.get("ATLAS_DECOYS_PATH") or "").strip() or None
        if path and not integrations.valid_decoys_path(path):
            return jsonify({"ok": False, "error": "ATLAS_DECOYS_PATH must be an absolute "
                                                  "path like /api/stones."}), 400
    # the path only when one was typed: `_probe(kind, url, key)` stays the call shape
    ok, detail = _probe(kind, url, key, path=path) if path else _probe(kind, url, key)
    log.info("v2: source test %s by %s: ok=%s", kind, actor(), ok)
    return jsonify({"ok": ok, "detail": detail if ok else "", "error": "" if ok else detail})


@admin_bp.route("/integrations", methods=["POST"])
def integrations_save():
    refusal = write_refusal()
    if refusal:
        return refusal
    import integrations
    proposed = (request.get_json(silent=True) or {}).get("settings") or {}
    unknown = [k for k in proposed if k not in integrations.ALLOWED]
    if unknown:
        return jsonify({"error": f"not an integration setting: {unknown[0]}"}), 400

    def in_force(key):
        given = proposed.get(key)
        if key in integrations.SECRETS:
            if given is None and key in proposed:
                return ""                              # being cleared
            return str(given or "").strip() or integrations.get(key)
        if key in proposed:
            return str(given or "").strip() or integrations._env(key)
        return integrations.get(key)

    for key in integrations.URLS:
        value = in_force(key)
        if value and not _valid_url(value):
            return jsonify({"error": f"{key} must be an http(s) URL with a host."}), 422
        # saving is how a blank secret would otherwise follow a URL to a new host
        if integrations.moves_secret(key, proposed, saving=True):
            return jsonify({"error": _secret_stays_home()}), 422
    # THE GLASS (v1.38.2): the hosts list goes into a CSP header, where a `;`
    # or a newline voids the whole value (embeddable.frame_src refuses it, but
    # the form should say so before the save, not the log after); the two
    # switches are '1', '0' or blank.
    hosts = str(proposed.get("ATLAS_EMBED_HOSTS", "") or "")
    if ";" in hosts or "\n" in hosts or "\r" in hosts:
        return jsonify({"error": "ATLAS_EMBED_HOSTS is a space-separated list of origins — no ';' or newlines."}), 422
    decoys_path = str(proposed.get("ATLAS_DECOYS_PATH", "") or "").strip()
    if decoys_path and not integrations.valid_decoys_path(decoys_path):
        return jsonify({"error": "ATLAS_DECOYS_PATH must be an absolute path on the decoy "
                                 "feed, like /api/stones — no scheme, host, query or spaces."}), 422
    for key in integrations.BOOLS:
        if key in proposed and str(proposed.get(key) or "").strip() not in ("", "0", "1"):
            return jsonify({"error": f"{key} must be 1, 0, or blank (the deployment's value)."}), 422
    wanted = [s.strip().lower() for s in in_force("ATLAS_SIGNALS_SOURCES").split(",") if s.strip()]
    bad = [s for s in wanted if s not in integrations.SOURCES]
    if bad:
        return jsonify({"error": f"unknown signals source: {bad[0]} — one of "
                                 f"{', '.join(integrations.SOURCES)}"}), 422
    for src, need in integrations.SOURCE_NEEDS.items():
        if src in wanted and not in_force(need):
            return jsonify({"error": f"the {src} source needs {need} before it can be enabled."}), 422
    try:
        described = integrations.save(proposed)
    except Exception as e:  # noqa: BLE001 — ValueError, OSError, or a master key that will not open
        log.warning("v2: integration settings save failed: %s", e)
        return jsonify({"error": f"could not save: {e}"}), 500
    log.info("v2: integration settings changed by %s", actor())
    # the hub rebuilds on its next poll (it watches the file's mtime); make it now
    try:
        atlas().signals._refresh_adapters()
    except Exception:  # noqa: BLE001 — the next poll will
        pass
    return jsonify({"ok": True, "settings": described, "hub": _hub_state()})


# ── CONNECTIONS: API tokens and the systems an Atlas can be pointed at ───────

@admin_bp.route("/tokens")
def tokens_get():
    import api_tokens
    return jsonify({"tokens": api_tokens.listing(), "lifetimes": list(api_tokens.LIFETIMES),
                    "default_days": api_tokens.DEFAULT_DAYS})


@admin_bp.route("/tokens", methods=["POST"])
def tokens_issue():
    refusal = write_refusal()
    if refusal:
        return refusal
    import api_tokens
    body = request.get_json(silent=True) or {}
    try:
        record, raw = api_tokens.issue(body.get("name"), body.get("days"), actor())
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    # the only time the plaintext exists outside the caller's hands
    resp = jsonify({"ok": True, "token": record, "secret": raw})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@admin_bp.route("/tokens/<tid>", methods=["DELETE"])
def tokens_revoke(tid):
    refusal = write_refusal()
    if refusal:
        return refusal
    import api_tokens
    if not api_tokens.revoke(tid, actor()):
        return jsonify({"error": "no such token"}), 404
    return jsonify({"ok": True})


@admin_bp.route("/connections")
def connections_get():
    import connections
    return jsonify({"systems": connections.describe()})


@admin_bp.route("/connections/test", methods=["POST"])
def connections_test():
    """One read-only call to one system, with the values as typed. A blank secret
    means the one in force, so a stored key can be tested without retyping it, at
    the address it was saved with and nowhere else."""
    refusal = write_refusal()
    if refusal:
        return refusal
    if not _probe_allowed(actor()):
        return jsonify({"ok": False, "error": "Too many tests in a minute. Wait a moment."}), 429
    import connections
    import integrations
    body = request.get_json(silent=True) or {}
    key = str(body.get("key") or "").strip().lower()
    if not connections.known(key):
        return jsonify({"ok": False, "error": "not a system that can be tested"}), 400
    typed = body.get("settings") or {}

    def value(name):
        return str(typed.get(name) or "").strip() or integrations.get(name)

    url = value(connections.field(key, "url")[0])
    if url and not _valid_url(url):
        return jsonify({"ok": False, "error": "That is not an http(s) URL with a host."}), 400
    if integrations.moves_secret(connections.field(key, "url")[0], typed):
        return jsonify({"ok": False, "error": _secret_stays_home()}), 400
    creds = [value(name) for name in connections.field(key, "secret")]
    name = connections.field(key, "insecure")[0]
    insecure = str(typed[name] if name in typed else integrations.get(name)).strip() == "1"
    ok, detail = connections.probe(key, url, creds, insecure)
    log.info("v2: connection test %s by %s: ok=%s", key, actor(), ok)
    return jsonify({"ok": ok, "detail": detail if ok else "", "error": "" if ok else detail})


def _survey(key):
    """What a system knows, read with its SAVED settings. A review takes nothing
    typed, so there is no address here for `moves_secret` to judge."""
    import connections
    import integrations
    url = integrations.get(connections.field(key, "url")[0])
    creds = [integrations.get(name) for name in connections.field(key, "secret")]
    insecure = str(integrations.get(connections.field(key, "insecure")[0])).strip() == "1"
    return connections.survey(key, url, creds, insecure)


def _review_key(body):
    import connections
    key = str(body.get("key") or "").strip().lower()
    return key if connections.known(key) else None


@admin_bp.route("/connections/review", methods=["POST"])
def connections_review():
    """Discovery and the results list, in one read-only pass. Nothing is written:
    the rows go to a person, who ticks what to add."""
    refusal = write_refusal()
    if refusal:
        return refusal
    if not _probe_allowed(actor()):
        return jsonify({"ok": False, "error": "Too many requests in a minute. Wait a moment."}), 429
    key = _review_key(request.get_json(silent=True) or {})
    if key is None:
        return jsonify({"ok": False, "error": "not a system that can be reviewed"}), 400
    from importers import review
    ok, answer = _survey(key)
    log.info("v2: connection review %s by %s: ok=%s", key, actor(), ok)
    if not ok:
        return jsonify({"ok": False, "error": answer})
    try:
        data, stamp = atlas().store.read()
    except ds.RejectedError as e:
        return _fail(e, 409)
    candidates, notes = answer
    return jsonify({"ok": True, "stamp": stamp, "notes": notes,
                    "rows": review.annotate(candidates, data, discovery.ignored()),
                    "zones": [{"id": z.get("id"), "name": z.get("name")}
                              for z in data.get("zones", []) or []]})


@admin_bp.route("/connections/import", methods=["POST"])
def connections_import():
    """Write the ticked rows through the store, so they land in the change log and
    can be undone. The system is read again first: what is written is what it says
    now, and a browser can only choose among those rows, not supply them."""
    refusal = write_refusal()
    if refusal:
        return refusal
    if not _probe_allowed(actor()):
        return jsonify({"ok": False, "error": "Too many requests in a minute. Wait a moment."}), 429
    body = request.get_json(silent=True) or {}
    key, picks = _review_key(body), body.get("picks")
    if key is None:
        return jsonify({"ok": False, "error": "not a system that can be reviewed"}), 400
    if not isinstance(picks, list) or not picks or not all(isinstance(p, str) for p in picks):
        return jsonify({"ok": False, "error": "Nothing was ticked."}), 400
    import connections
    from importers import review
    ok, answer = _survey(key)
    if not ok:
        return jsonify({"ok": False, "error": answer}), 502
    ctx = atlas()
    try:
        data, stamp = ctx.store.read()
    except ds.RejectedError as e:
        return _fail(e, 409)
    rows = review.annotate(answer[0], data, discovery.ignored())
    name = connections.label(key)
    fallback = str(body.get("zone") or "")
    if fallback and fallback not in {z.get("id") for z in data.get("zones", []) or []}:
        return jsonify({"ok": False, "error": "That realm is not on the map any more."}), 422
    try:
        ops = review.plan(rows, picks, data, label=name, fallback=fallback)
    except review.PlanError as e:
        return jsonify({"ok": False, "error": str(e), "problems": e.problems}), 422
    # `expect` is the stamp the review was drawn from: a map that moved since is refused
    result, refused = _commit(ctx, ops, body.get("expect") or stamp, f"imported from {name}")
    log.info("v2: connection import %s by %s: %d picks, ok=%s", key, actor(), len(picks), not refused)
    return refused or jsonify({**result, "added": len(picks)})


bp.register_blueprint(admin_bp)
