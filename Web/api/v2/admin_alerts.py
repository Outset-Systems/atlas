"""ALERTS' admin routes — `/api/v2/admin/alerts*` (2026-11-13).

Rules, the daily digest and destinations, read and written by an admin; a test
send; the delivery log. They sit on `admin_bp`, so its `before_request` refuses
anyone `security.is_admin()` does not vouch for, an API token included (a
token reads as a viewer with no groups), and its `after_request` forbids every
cache. Writes take `write_required`: `X-Atlas-Write`, the same-origin check,
and `ATLAS_READONLY`.

Off by default. While `ATLAS_ALERTS` is off, or `ATLAS_ALERT_HOSTS` is empty,
`GET` still answers, so the page can say how to turn alerts on, and the save
and the test send answer 403 with that reason.

A destination's secret is a NAME (`NTFY_LAB`, read from
`ATLAS_ALERT_SECRET_NTFY_LAB` or its `_FILE`), and it is bound to the address
it was named for. No route returns a secret's value, or the origin it is bound
to: only the name and whether it is bound.
"""

import logging

from flask import jsonify, request

import alerts
import settings
from context import atlas
from security import actor
from signals import NODE_STATES

from .admin import _probe_allowed, admin_bp
from .auth import write_required

log = logging.getLogger("atlas.api.v2")

OFF_REASON = ("Alerts are off. To turn them on, set ATLAS_ALERTS=1 and list the hosts "
              "they may send to in ATLAS_ALERT_HOSTS (host:port, comma separated), "
              "then restart Atlas.")


def _sender():
    import alert_send
    return alert_send


def _data():
    """The dataset as it is stored, or {} when it cannot be read: a rule's
    target then reads as not visible, which refuses rather than allows."""
    try:
        data, _, _ = atlas().dataset()
        return data
    except (OSError, ValueError):
        return {}


def _hosts():
    out = []
    for entry in _sender().allowed_hosts() or []:
        if isinstance(entry, (tuple, list)) and len(entry) == 2:
            host, port = entry
            host = f"[{host}]" if ":" in str(host) else str(host)
            out.append(f"{host}:{port}")
        else:
            out.append(str(entry))
    return out


def _status(doc, data):
    import annalist
    return {
        "enabled": bool(settings.ALERTS_ENABLED),
        "on": settings.alerts_on(),
        "hosts": _hosts(),
        "public_url_set": bool(settings.PUBLIC_URL),
        "poll_seconds": annalist.interval(),
        "poll_running": annalist.liveness()["running"],
        "last_tick": alerts.last_tick(),
        "suspended": alerts.suspended(doc, data),
    }


def _off():
    return jsonify({"error": OFF_REASON, "problems": [OFF_REASON]}), 403


@admin_bp.route("/alerts")
def alerts_read():
    doc, stamp = alerts.read()
    data = _data()
    return jsonify({"doc": alerts.for_reading(doc), "stamp": stamp,
                    "status": _status(doc, data), "states": sorted(NODE_STATES)})


def _bind(incoming, stored_by_id):
    """Each incoming destination with its secret binding worked out on the
    server. A binding is never taken from the client: an existing one is
    carried only while the secret and the origin are unchanged
    (`unbind_if_moved`), and a secret is bound to the current address only when
    the admin names it: a new name, a destination that had none, or `bind: true`
    to name the same secret again after the address moved. Returns
    (destinations, notes)."""
    sender = _sender()
    out, notes = [], []
    for raw, dest in incoming:
        old = stored_by_id.get(dest.get("id"))
        dest, note = sender.unbind_if_moved(old, {**dest, "secret_origin": None})
        if note:
            notes.append(f"destination {dest.get('id')}: {note}")
        named_now = bool(dest.get("secret")) and (
            old is None or dest.get("secret") != old.get("secret")
            or raw.get("bind") is True)
        if named_now and not dest.get("secret_origin"):
            dest = sender.bind_secret(dest)
        if not dest.get("secret"):
            dest["secret"], dest["secret_origin"] = None, None
        out.append(dest)
    return out, notes


@admin_bp.route("/alerts", methods=["POST"])
@write_required
def alerts_save():
    if not settings.alerts_on():
        return _off()
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("doc"), dict):
        return jsonify({"error": "expected {doc, expect}"}), 400
    # the stamp the page read the alerts with (2026-11-13): without it a save
    # could never be refused as stale, and would write over another admin's
    if not isinstance(body.get("expect"), str) or not body["expect"]:
        return jsonify({"error": "expected {doc, expect}: expect is the stamp "
                                 "the alerts were read with"}), 400
    raw_dests = body["doc"].get("destinations")
    doc = alerts.normalize(body["doc"])
    data = _data()
    problems = alerts.validate(doc, data)
    if problems:
        return jsonify({"error": "those alerts have problems", "problems": problems}), 422

    sender = _sender()
    stored, _ = alerts.read()
    stored_by_id = {d.get("id"): d for d in stored["destinations"]}
    raws = [r for r in raw_dests if isinstance(r, dict)] if isinstance(raw_dests, list) else []
    pairs = list(zip(raws, [sender.normalised(d) for d in doc["destinations"]]))
    doc["destinations"], notes = _bind(pairs, stored_by_id)
    try:
        stamp = alerts.save(doc, expect=body.get("expect"))
    except alerts.StaleError:
        return jsonify({"error": "someone else changed the alerts while you were editing; "
                                 "reload and try again"}), 409
    log.info("alerts saved by %s: %d rule(s), %d destination(s)", actor(),
             len(doc["rules"]), len(doc["destinations"]))
    saved, _ = alerts.read()
    return jsonify({"ok": True, "stamp": stamp, "doc": alerts.for_reading(saved),
                    "notes": notes, "status": _status(saved, data)})


@admin_bp.route("/alerts/destinations/<dest_id>/test", methods=["POST"])
@write_required
def alerts_test(dest_id):
    if not settings.alerts_on():
        return _off()
    doc, _ = alerts.read()
    dest = next((d for d in doc["destinations"] if d.get("id") == dest_id), None)
    if dest is None:
        return jsonify({"error": "no such destination"}), 404
    # the limiter every outward probe shares: ten a minute per admin
    if not _probe_allowed(actor()):
        return jsonify({"error": "Too many tests in a minute. Wait a moment."}), 429
    data = _data()
    message = alerts.trial_message(data)
    hidden = alerts.hidden_pattern(data)
    sender = _sender()
    if hidden and any(hidden.search(t) for t in (message["title"], message["body"])):
        result = {"outcome": "blocked", "status": None, "why": "would name a hidden place"}
    else:
        result = sender.send(dest, message) or {}
    outcome = {"outcome": result.get("outcome") or "unreachable",
               "status": result.get("status"), "why": result.get("why")}
    from jsonio import iso_utc
    sender.log_delivery({"at": iso_utc(), "rule": "test", "destination": dest.get("name"),
                         "events": [], **outcome})
    return jsonify(outcome)


@admin_bp.route("/alerts/deliveries")
def alerts_deliveries():
    limit = request.args.get("limit", type=int) or 100
    rows = _sender().read_deliveries(max(1, min(limit, 1000))) or []
    rows = sorted(rows, key=lambda r: str(r.get("at") or ""), reverse=True)
    return jsonify({"deliveries": rows})
