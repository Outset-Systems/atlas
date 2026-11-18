"""One check (2026-11-16): `GET /api/v2/checks/<key>` and
`POST /api/v2/admin/checks/run`.

Atlas's own checks (watch.py) answered only through the merged feed, so
nothing could say what one check last answered, when, in how long, or why it
failed, and nothing could ask one now. These two can. The logic is plain
functions in `watch.py` (`find`, `answer_for`, `not_asked`, `ask_now`); this
module decides who may see what.

* `GET /checks/<key>`: the last answer of the check the map gives `key` (a
  place id, or a service key: `<place id>/<label>`, or the monitor a link
  names). Gated like the feed: the app-wide sign-in gate fronts it, and a
  look-only standalone Atlas answers every visitor. Cut like the feed: a place
  or service this viewer may not see answers exactly the 404 an unknown key
  answers, and so does a thing with no check; a certificate's `names` are for
  a viewer who sees everything; a shadow answer (beside a monitor) is for an
  admin. Not one of an API token's doors (`api_tokens.READ_PATHS`).
* `POST /admin/checks/run` with `{"key": ...}`: ask that check now, inside
  the worker's budget, and store the answer where a round would. Admin only,
  with the write rules of every admin POST (`write_required`). The address
  asked comes only from `watch.targets(map)`, never from the request.
* `POST /admin/diagnose` with `{"id": ...}` (2026-11-17): where does it
  break? One place's chain, asked in order and stopped at the first failure
  (`diagnose.py`). Admin only, refused as `checks/run` is refused.
"""

import logging

from flask import jsonify, make_response, request

import engines.authority as authority
import integrations
import watch
from context import atlas
from engines.places import service_key
from redaction import (cleared, hidden_node_ids, no_store, sees_everything, viewer_groups,
                       visible_monitors)
from security import is_admin

from . import bp
from .admin import admin_bp
from .auth import write_required

log = logging.getLogger("atlas.api.v2")

#: The longest key either route reads. A place id or a service key is far
#: shorter; anything longer is no key on any map.
KEY_MAX = 512

#: The one body of every "no such check": an unknown key, a thing with no
#: check, and a thing this viewer may not see all answer exactly this.
NOT_FOUND = {"error": "no such check"}

BAD_BODY = {"error": 'expected {"key": "<a place id or a service key>"} and nothing else'}
UNREADABLE = {"error": "lab data unreadable"}
OFF = {"error": "Atlas's own checks are off: turn the checks source on to ask one", "why": "off"}
UNMANAGED = {"error": "this is marked unmanaged: Atlas does not watch it", "why": "unmanaged"}
KUMA = {"error": "a Kuma monitor watches this: Atlas asks it only with Check beside Kuma on",
        "why": "kuma", "watched_by": "kuma"}
SOON = {"error": "this check was asked a moment ago: ask again shortly", "why": "soon"}
SPENT = {"error": "the checks' budget for this minute is spent: ask again shortly", "why": "spent"}


def _not_found():
    return no_store(make_response(jsonify(NOT_FOUND), 404))


def _visible(data, t, groups, hidden, monitors):
    """Whether this viewer may read `t`'s answer. A place: the place is one
    they may see. A service: its place is, and its key is among the monitors
    they may see (`visible_monitors`, the feed's own cut), and every link on
    that place filed under the key is cleared for them. A shadow answer: an
    admin only, as the comparison it feeds is."""
    if t is None:
        return False
    if t.kind in watch.SHADOW_KINDS and not is_admin():
        return False
    if t.place in hidden:
        return False
    node = next((n for n in data.get("nodes") or []
                 if isinstance(n, dict) and n.get("id") == t.place), None)
    if node is None or not cleared(node, groups):
        return False
    if t.kind in (authority.PLACE, authority.SHADOW_PLACE):
        return True
    if t.key not in monitors:
        return False
    links = [link for link in (node.get("links") if isinstance(node.get("links"), list) else [])
             if isinstance(link, dict) and service_key(t.place, link) == t.key]
    return bool(links) and all(cleared(link, groups) for link in links)


def _for_viewer(answer, groups):
    """An answer cut for this viewer: a certificate's names, which can name a
    place they may not see, go unless they see everything (as in the feed)."""
    if not sees_everything(groups) and isinstance(answer.get("tls"), dict):
        answer = {**answer, "tls": {k: v for k, v in answer["tls"].items() if k != "names"}}
    return answer


def _checks_on():
    return "checks" in integrations.enabled_sources()


@bp.route("/checks/<path:key>")
def check_read(key):
    try:
        data, _, _ = atlas().dataset()
    except (OSError, ValueError) as e:
        log.error("v2 checks: lab data unreadable: %s", type(e).__name__)
        return no_store(make_response(jsonify(UNREADABLE), 500))
    groups = viewer_groups()
    # the same work for every key, known or not, seen or hidden: one answer
    # and no shortcut tells them apart
    hidden = hidden_node_ids(data, groups)
    monitors = visible_monitors(data, groups)
    ts = watch.targets(data)
    t = watch.find(data, key, ts) if len(key) <= KEY_MAX else None
    if not _visible(data, t, groups, hidden, monitors):
        return _not_found()
    answer = watch.answer_for(watch.load(), t, factor=watch.stretch(ts))
    answer["on"] = _checks_on()
    return no_store(make_response(jsonify(_for_viewer(answer, groups))))


@admin_bp.route("/checks/run", methods=["POST"])
@write_required
def check_run():
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or set(body) != {"key"} or not isinstance(body["key"], str)
            or not 0 < len(body["key"]) <= KEY_MAX):
        return jsonify(BAD_BODY), 400
    key = body["key"]
    try:
        data, _, _ = atlas().dataset()
    except (OSError, ValueError) as e:
        log.error("v2 checks: lab data unreadable: %s", type(e).__name__)
        return jsonify(UNREADABLE), 500
    groups = viewer_groups()
    ts = watch.targets(data)
    t = watch.find(data, key, ts)
    if t is None:
        why = watch.not_asked(data, key)
        if why and why["why"] == "unmanaged":
            return jsonify(UNMANAGED), 409
        if why and why["why"] == authority.MONITOR:
            return jsonify({**KUMA, "monitor": why["monitor"]}), 409
        return _not_found()
    if not _visible(data, t, groups, hidden_node_ids(data, groups), visible_monitors(data, groups)):
        return _not_found()
    if not _checks_on():
        return jsonify(OFF), 409
    outcome, value = watch.ask_now(data, key, ts=ts)
    if outcome in ("soon", "spent"):
        resp = make_response(jsonify({**(SOON if outcome == "soon" else SPENT), "retry_after": value}), 429)
        resp.headers["Retry-After"] = str(value)
        return resp
    if outcome == "none":            # the map changed between the two reads
        return _not_found()
    answer = {**_for_viewer(value, groups), "on": True, "asked": outcome == "asked"}
    if outcome == "held":
        answer["stored"] = True      # another worker holds the store: its answer, not a new one
    return jsonify(answer)


# ── where does it break? (2026-11-17) ───────────────────────────────────────
#
# `POST /admin/diagnose` with `{"id": <place id>}`: the place's chain asked in
# order (diagnose.py), stopping at the first step that fails. Admin only, with
# the write rules of every admin POST, refused as `checks/run` is refused.
# The body names a place, never an address: every address asked is the map's
# own, or the one outside address the operator named.

DIAGNOSE_BAD_BODY = {"error": 'expected {"id": "<a place id>"} and nothing else'}
NO_PLACE = {"error": "no such place"}
PLANNED = {"error": "this place is planned, not built: there is nothing to ask yet", "why": "planned"}
DIAGNOSE_SOON = {"error": "this place was asked a moment ago: ask again shortly", "why": "soon"}
DIAGNOSE_SPENT = {"error": "the checks' budget for this minute cannot cover these steps: ask again shortly",
                  "why": "spent"}


@admin_bp.route("/diagnose", methods=["POST"])
@write_required
def diagnose_place():
    import diagnose
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or set(body) != {"id"} or not isinstance(body["id"], str)
            or not 0 < len(body["id"]) <= KEY_MAX):
        return jsonify(DIAGNOSE_BAD_BODY), 400
    pid = body["id"]
    try:
        data, _, _ = atlas().dataset()
    except (OSError, ValueError) as e:
        log.error("v2 diagnose: lab data unreadable: %s", type(e).__name__)
        return jsonify(UNREADABLE), 500
    hidden = hidden_node_ids(data, viewer_groups())
    known = any(isinstance(n, dict) and n.get("id") == pid for n in data.get("nodes") or [])
    if not known or pid in hidden:
        return jsonify(NO_PLACE), 404
    if not _checks_on():
        return jsonify(OFF), 409
    outcome, value = diagnose.diagnose(data, pid, hidden=hidden)
    if outcome in ("soon", "spent"):
        resp = make_response(jsonify({**(DIAGNOSE_SOON if outcome == "soon" else DIAGNOSE_SPENT),
                                      "retry_after": value}), 429)
        resp.headers["Retry-After"] = str(value)
        return resp
    if outcome == "unmanaged":
        return jsonify(UNMANAGED), 409
    if outcome == "planned":
        return jsonify(PLANNED), 409
    if outcome != "asked":
        return jsonify(NO_PLACE), 404
    return jsonify(value)
