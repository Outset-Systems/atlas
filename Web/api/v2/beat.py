"""The machine beat — `POST /api/v2/rites/<key>/beat`.

A rite reporting that it turned: the one route machines call.

**Why this does not go through `security.write_refusal()`.** That gate is
built for a browser — a custom header no cross-origin page can set, plus the
caller's Hub group membership. Neither exists here: the caller is a cron line
on another host with no session and no origin. So this route carries its own
gate, and it is deliberately the narrowest one in the app:

* A shared token, compared with `hmac.compare_digest`. **No token configured
  means the route is off** — 503, not "open" — so forgetting to set it cannot
  leave an unauthenticated writer exposed.
* It writes to exactly one place, `heartbeats.json`, and the only thing a
  holder of the token can do is claim a rite ran. Worst case is a false green
  on one rite, which is bounded and visible; there is no path from here to
  the dataset, the layout or the change log.
* A read-only Atlas still refuses, because "this instance does not write"
  should not have an exception nobody remembers.

The path is NOT exempt from the app gate: in
accounts/hybrid mode a sessionless cron caller gets the gate's 401 before the
token is read. The fleet's rites report through the beats drop-dir instead
(`Data/beats/`, swept by the signals feed), so nothing depends on this today.

The key is slugified and length-capped before it becomes a dict key, so a
caller cannot invent a path or bloat the store with one long name.
`status`/`note` may arrive in the JSON body or as query params.
"""

import hmac
import logging

from flask import jsonify, request

import heartbeats
import security
import settings

from . import bp

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
    # bytes, not str: compare_digest raises TypeError on non-ASCII str, and
    # `presented` is attacker-controlled header text (werkzeug decodes latin-1)
    # -- a garbage token must be a 403, never a 500. Same class as the decoy feed
    # compare_digest incident (2026-08-15).
    if not presented or not hmac.compare_digest(
            presented.encode("utf-8", "surrogateescape"), expected.encode()):
        log.warning("v2: refused a beat for %s: bad token", key[:64])
        return jsonify({"error": "bad or missing beat token"}), 403

    body = request.get_json(silent=True) or {}
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
