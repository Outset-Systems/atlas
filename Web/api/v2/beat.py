import hmac
import logging

from flask import jsonify, request

import heartbeats
import security
import settings

from . import _body, bp

log = logging.getLogger("atlas.api.v2")


@bp.route("/rites/<key>/beat", methods=["POST"])
def rite_beat(key):
    if settings.READ_ONLY:
        return jsonify({
            "error": "this Atlas is read-only",
            "reason": "beats are writes — set ATLAS_READONLY=0 to accept them",
        }), 403

    expected = settings.beat_token()
    if not expected:
        return jsonify({
            "error": "the beat endpoint is not configured",
            "reason": "set ATLAS_BEAT_TOKEN or ATLAS_BEAT_TOKEN_FILE — until "
                      "then rites report by dropping a file in the beats "
                      "directory instead",
        }), 503

    presented = security.bearer_token(request) or request.headers.get("X-Atlas-Beat", "")
    if not presented or not hmac.compare_digest(
            presented.encode("utf-8", "surrogateescape"), expected.encode()):
        log.warning("v2: refused a beat for %s: bad token", key[:64])
        return jsonify({"error": "bad or missing beat token"}), 403

    body = _body()
    try:
        beat = heartbeats.record_beat(
            key,
            status=body.get("status", request.args.get("status", "ok")),
            note=body.get("note", request.args.get("note", "")),
            duration_s=body.get("duration_s"),
            source=body.get("source") or request.remote_addr or "",
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "key": heartbeats.key_for({"key": key}),
                    "at": beat["at"], "status": beat["status"]})
