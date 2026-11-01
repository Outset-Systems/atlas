"""TRIPWIRES — the webhook any tool can trip, and the two admin reads.

  POST /api/v2/ingest/tripwires     a trip (or a ping) from OpenCanary,
                                    Canarytokens, or anything that speaks the
                                    generic `{tripwire_id, at, kind}`
  GET  /api/v2/tripwires            the charted tripwires, their trips, and
                                    per-source contact (admin)
  GET  /api/v2/tripwires/setup      what to paste into each sender (admin)

The webhook is a nested blueprint of its own under the ingest prefix, so it
inherits the ONE gate exemption that prefix already has (`create_app`,
`api_v2.INGEST_URL_PREFIX`) and nothing else — but not the relay ingest's
`before_request`, which 404s off the db backend. A trip needs no database
(tripwires.py), so its fence is its own: off unless ATLAS_TRIPWIRES_WEBHOOK=1
with a usable credential, and then 404 per request exactly like the relay's.

Every answer is plain JSON built from allow-listed fields; nothing a sender
wrote is echoed back.
"""

import logging

from flask import Blueprint, abort, jsonify, make_response, request

import tripwires
from context import atlas
from redaction import vary_on_viewer

from . import bp
from .auth import whole_map_required

log = logging.getLogger("atlas.api.v2")

hook_bp = Blueprint("tripwires_ingest", __name__, url_prefix="/ingest/tripwires")


@hook_bp.before_request
def _fence():
    if not tripwires.enabled():
        abort(404)
    return None


@hook_bp.route("", methods=["POST"], strict_slashes=False)
def trip():
    length = request.content_length
    if length is not None and length > tripwires.MAX_BYTES:
        return jsonify({"error": f"payload too large (max {tripwires.MAX_BYTES} bytes)"}), 413
    raw = request.stream.read(tripwires.MAX_BYTES + 1)
    if len(raw) > tripwires.MAX_BYTES:
        return jsonify({"error": f"payload too large (max {tripwires.MAX_BYTES} bytes)"}), 413

    credential, refusal = tripwires.authenticate(raw)
    if refusal:
        return refusal
    if not tripwires.limiter.hit(credential):
        return jsonify({"error": f"rate limit: {tripwires.RATE_LIMIT} requests/minute"}), 429

    payload = tripwires.parse_body(raw)
    if payload is None:
        return jsonify({"error": "expected a JSON object (or OpenCanary's form body)"}), 422
    reading = tripwires.interpret(payload)
    if reading is None:
        return jsonify({"error": "not an OpenCanary, Canarytokens or "
                                 "{tripwire_id, at, kind} payload"}), 422

    if reading["contact_only"]:
        tripwires.touch(reading["source"], tripped=False)
        return jsonify({"ok": True, "trip": False, "source": reading["source"]})

    try:
        data, _, _ = atlas().dataset()
        stones = data.get("stones") or []
    except (OSError, ValueError):
        stones = []          # never drop a trip: it lands unmatched instead
    stone = tripwires.match(reading, stones)
    event, coalesced = tripwires.record(reading, stone)
    tripwires.touch(reading["source"], tripped=True)
    return jsonify({"ok": True, "trip": True, "source": reading["source"],
                    "matched": stone is not None,
                    "tripwire": str(stone["id"]) if stone else None,
                    "event": event["id"], "coalesced": coalesced})


bp.register_blueprint(hook_bp)


def _private(payload):
    resp = make_response(jsonify(payload))
    resp.headers["Cache-Control"] = "no-store, private"
    return vary_on_viewer(resp)


@bp.route("/tripwires")
@whole_map_required
def tripwires_read():
    """The scene's one read. Builds the feed the way the signals route does
    (`build_feed` — so a fresh build still writes THE ANNALS) and reads the
    trips back out of them."""
    from .feeds import build_feed
    ctx = atlas()
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        data = {}
    try:
        feed = build_feed(ctx)
    except Exception as e:      # noqa: BLE001 — a dead source must not blank the scene
        log.warning("tripwires: feed unavailable: %s", e)
        feed = {}
    return _private(tripwires.overview(data, feed))


@bp.route("/tripwires/setup")
@whole_map_required
def tripwires_setup():
    return _private(tripwires.setup(request.url_root))
