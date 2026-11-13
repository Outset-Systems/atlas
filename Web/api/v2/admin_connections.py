"""CONNECTIONS — `/api/v2/admin/tokens*`, `/connections*`: API tokens, and the
systems an Atlas can be pointed at (test, review, import).

Split out of `admin.py` (2026-11-09); same blueprint, same gate.
"""

import logging

from flask import jsonify, request

import discovery
import token_log
from context import atlas
from security import actor

from . import _body
from .admin import (
    _commit, _probe_allowed, _read, _secret_stays_home, _valid_url, admin_bp,
)
from .auth import write_required

log = logging.getLogger("atlas.api.v2")


# ── CONNECTIONS: API tokens and the systems an Atlas can be pointed at ───────

@admin_bp.route("/tokens")
def tokens_get():
    import api_tokens
    kinds = {}
    for profile in api_tokens.PROFILES:
        offered, default = api_tokens.lifetimes(profile)
        kinds[profile] = {"lifetimes": list(offered), "default_days": default}
    # how much of this map a cloud token would read, said where the token is made
    import cloud_view
    try:
        standing = cloud_view.standing(atlas().dataset()[0])
    except (OSError, ValueError):
        standing = None
    # the address this Atlas sees the admin at, said where a binding is chosen: if
    # it is a proxy's and not their own, "the local network" means less than it says
    import atlas_auth
    seen = atlas_auth.client_ip()
    return jsonify({"tokens": api_tokens.listing(), "lifetimes": list(api_tokens.LIFETIMES),
                    "default_days": api_tokens.DEFAULT_DAYS, "access": api_tokens.access(),
                    "profiles": kinds, "cloud_view": standing,
                    "you": {"ip": seen, "local": api_tokens.allowed_from({"networks": [api_tokens.LAN]}, seen)},
                    "log_days": token_log.keep_days()})


@admin_bp.route("/tokens/reads")
def tokens_reads():
    """What tokens read, newest first: `?token=<id>` for one, `?limit=` up to 500.
    Admins only, like everything on this blueprint. The lines outlive the token:
    revoking one does not erase what it read."""
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        return jsonify({"error": "limit must be a number"}), 400
    token = (request.args.get("token") or "").strip()[:16] or None
    return jsonify({"reads": token_log.rows(token=token, limit=max(1, min(limit, 500))),
                    "keep_days": token_log.keep_days()})


@admin_bp.route("/tokens/access", methods=["POST"])
@write_required
def tokens_access():
    """The switch for agent access as a whole: `{"on": true|false}`. Off refuses
    every token at once and keeps them; on is refused while the deployment says
    `ATLAS_AGENT_API=0`."""
    import api_tokens
    body = _body()
    if not isinstance(body.get("on"), bool):
        return jsonify({"error": "Send on: true or on: false."}), 422
    try:
        state = api_tokens.set_access(body["on"], actor())
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    return jsonify({"ok": True, "access": state})


@admin_bp.route("/tokens", methods=["POST"])
@write_required
def tokens_issue():
    import api_tokens
    body = _body()
    try:
        # a client from before the kinds existed sends none, and gets what it always got
        # and one that says nothing about networks is bound to the local one: the
        # narrower answer is the default, `"networks": null` asks for any address
        record, raw = api_tokens.issue(body.get("name"), body.get("days"), actor(),
                                       profile=body.get("profile", api_tokens.FULL),
                                       networks=body.get("networks", api_tokens.LAN))
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    # the only time the plaintext exists outside the caller's hands
    return jsonify({"ok": True, "token": record, "secret": raw})


@admin_bp.route("/tokens/<tid>", methods=["DELETE"])
@write_required
def tokens_revoke(tid):
    import api_tokens
    if not api_tokens.revoke(tid, actor()):
        return jsonify({"error": "no such token"}), 404
    return jsonify({"ok": True})


@admin_bp.route("/connections")
def connections_get():
    import connections
    return jsonify({"systems": connections.describe()})


@admin_bp.route("/connections/test", methods=["POST"])
@write_required
def connections_test():
    """One read-only call to one system, with the values as typed. A blank secret
    means the one in force, so a stored key can be tested without retyping it, at
    the address it was saved with and nowhere else."""
    if not _probe_allowed(actor()):
        return jsonify({"ok": False, "error": "Too many tests in a minute. Wait a moment."}), 429
    import connections
    import integrations
    body = _body()
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
    return connections.survey(key, *connections.saved(key))


def _review_key(body):
    import connections
    key = str(body.get("key") or "").strip().lower()
    return key if connections.known(key) else None


@admin_bp.route("/connections/review", methods=["POST"])
@write_required
def connections_review():
    """Discovery and the results list, in one read-only pass. Nothing is written:
    the rows go to a person, who ticks what to add."""
    if not _probe_allowed(actor()):
        return jsonify({"ok": False, "error": "Too many requests in a minute. Wait a moment."}), 429
    key = _review_key(_body())
    if key is None:
        return jsonify({"ok": False, "error": "not a system that can be reviewed"}), 400
    from importers import review
    ok, answer = _survey(key)
    log.info("v2: connection review %s by %s: ok=%s", key, actor(), ok)
    if not ok:
        return jsonify({"ok": False, "error": answer})
    data, stamp, refusal = _read(atlas())
    if refusal:
        return refusal
    candidates, notes = answer
    return jsonify({"ok": True, "stamp": stamp, "notes": notes,
                    "rows": review.annotate(candidates, data, discovery.ignored()),
                    "zones": [{"id": z.get("id"), "name": z.get("name")}
                              for z in data.get("zones", []) or []]})


@admin_bp.route("/connections/import", methods=["POST"])
@write_required
def connections_import():
    """Write the ticked rows through the store, so they land in the change log and
    can be undone. The system is read again first: what is written is what it says
    now, and a browser can only choose among those rows, not supply them."""
    if not _probe_allowed(actor()):
        return jsonify({"ok": False, "error": "Too many requests in a minute. Wait a moment."}), 429
    body = _body()
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
    data, stamp, refusal = _read(ctx)
    if refusal:
        return refusal
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
