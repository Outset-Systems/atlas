"""CONNECTIONS — `/api/v2/admin/tokens*`, `/connections*`: API tokens, and the
systems an Atlas can be pointed at (test, review, import).

Split out of `admin.py` (2026-11-09); same blueprint, same gate.
"""

import logging

from flask import jsonify, request

import dataset as ds
import discovery
from context import atlas
from security import actor, write_refusal


log = logging.getLogger("atlas.api.v2")
from .admin import (  # noqa: E402
    _commit, _fail, _probe_allowed, _secret_stays_home, _valid_url, admin_bp,
)


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
    creds = connections.credentials(key, value)
    insecure = connections.insecure(
        key, lambda name: typed[name] if name in typed else integrations.get(name))
    ok, detail = connections.probe(key, url, creds, insecure)
    log.info("v2: connection test %s by %s: ok=%s", key, actor(), ok)
    return jsonify({"ok": ok, "detail": detail if ok else "", "error": "" if ok else detail})


def _survey(key):
    """What a system knows, read with its SAVED settings. A review takes nothing
    typed, so there is no address here for `moves_secret` to judge."""
    import connections
    import integrations
    url = integrations.get(connections.field(key, "url")[0])
    creds = connections.credentials(key, integrations.get)
    return connections.survey(key, url, creds, connections.insecure(key, integrations.get))


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
    result, refused = _commit(ctx, ops, body.get("expect") or stamp, f"imported from {name}",
                              origin=key)
    log.info("v2: connection import %s by %s: %d picks, ok=%s", key, actor(), len(picks), not refused)
    return refused or jsonify({**result, "added": len(picks)})
