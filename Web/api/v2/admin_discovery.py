"""Discovery and bulk import — `/api/v2/admin/discovery*`, `/import/csv`.

What a scan, a lease file or a connected system saw on the network, the
decisions taken on it, and the two ways a list of devices becomes node drafts
for the editor to review. Nothing here writes the dataset: a draft is an
answer to the page, not a change to the map.

Split out of `admin.py` (2026-11-12); same blueprint, same gate.
"""

import logging

from flask import jsonify

import discovery
from context import atlas
from security import actor

from . import _body
from .admin import _probe_allowed, _read, admin_bp
from .auth import write_required

log = logging.getLogger("atlas.api.v2")

#: The largest scan or lease file one request may carry, in characters.
_MAX_FILE_CHARS = 4_000_000


# ── Discovery inbox ──────────────────────────────────────────────────────────
@admin_bp.route("/discovery")
def discovery_list():
    ctx = atlas()
    data, _, refusal = _read(ctx)
    if refusal:
        return refusal
    rows = discovery.listing(data, ctx.backend, ctx.site)
    return jsonify({
        "observed": rows,
        "undocumented": sum(1 for r in rows if r["undocumented"] and not r["ignored"]),
    })


def _nmap():
    from importers.scan import NmapError, parse_nmap_xml
    return (lambda text: (None, parse_nmap_xml(text))), NmapError


def _leases():
    from importers.leases import LeaseError, parse_leases
    return parse_leases, LeaseError


def _file_survey(field, ask, too_large, importer):
    """A scan or a lease file from the request body, filed into the survey.

    `field` is where the text rides in the body; `ask` answers a body without
    it and `too_large` one over the limit. `importer()` returns the parser and
    the error it raises for a file it cannot read, and is called only once the
    text has passed those two checks. The parser answers `(format, hosts)`,
    with `format` None for a file that comes in one format only.
    """
    body = _body()
    text = body.get(field) or ""
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": ask}), 400
    if len(text) > _MAX_FILE_CHARS:
        return jsonify({"error": too_large}), 413
    parse, unreadable = importer()
    try:
        fmt, hosts = parse(text)
    except unreadable as e:
        return jsonify({"error": str(e)}), 422
    new = discovery.record(hosts, atlas().backend, atlas().site)
    if fmt is None:
        log.info("v2 discovery: %d hosts filed (%d new) by %s", len(hosts), new, actor())
        return jsonify({"ok": True, "seen": len(hosts), "new": new})
    log.info("v2 discovery: %d %s leases filed (%d new) by %s", len(hosts), fmt, new, actor())
    return jsonify({"ok": True, "format": fmt, "seen": len(hosts), "new": new})


@admin_bp.route("/discovery/scan", methods=["POST"])
@write_required
def discovery_scan():
    return _file_survey("nmap_xml", "send {nmap_xml: '<nmaprun>…'}",
                        "that scan is too large (max 4 MB)", _nmap)


@admin_bp.route("/discovery/leases", methods=["POST"])
@write_required
def discovery_leases():
    """A router's DHCP lease file, filed into the same survey as a scan: the
    devices that asked for an address, with the names they gave themselves.
    Read from what the operator hands over, never fetched from the router."""
    return _file_survey("leases", "send {leases: '<the lease file>'}",
                        "that lease file is too large (max 4 MB)", _leases)


@admin_bp.route("/discovery/connection", methods=["POST"])
@write_required
def discovery_connection():
    """What a connected system sees on the network now, filed into THE SURVEY
    beside a scan and a lease file. Saved settings only, so there is no address
    here for a stored credential to be sent to. Nothing is charted."""
    if not _probe_allowed(actor()):
        return jsonify({"ok": False, "error": "Too many requests in a minute. Wait a moment."}), 429
    import connections
    import integrations
    key = str(_body().get("key") or "").strip().lower()
    if not connections.observes(key):
        return jsonify({"ok": False, "error": "not a system that can be read for the survey"}), 400
    url = integrations.get(connections.field(key, "url")[0])
    creds = connections.credentials(key, integrations.get)
    ok, answer = connections.observe(key, url, creds, connections.insecure(key, integrations.get))
    log.info("v2: survey from %s by %s: ok=%s", key, actor(), ok)
    if not ok:
        return jsonify({"ok": False, "error": answer})
    hosts, note = answer
    new = discovery.record(hosts, atlas().backend, atlas().site)
    return jsonify({"ok": True, "source": connections.label(key), "seen": len(hosts), "new": new,
                    "note": note})


@admin_bp.route("/discovery/decide", methods=["POST"])
@write_required
def discovery_decide():
    body = _body()
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
@write_required
def discovery_as_nodes():
    body = _body()
    keys = set(body.get("keys") or [])
    ctx = atlas()
    data, _, refusal = _read(ctx)
    if refusal:
        return refusal
    taken = {n.get("id") for n in data.get("nodes", []) or []}
    drafts = []
    for row in discovery.listing(data, ctx.backend, ctx.site):
        if row["key"] not in keys:
            continue
        node = discovery.as_node(row, data, taken)
        taken.add(node["id"])
        drafts.append(node)
    return jsonify({"nodes": discovery.place_drafts(data, drafts)})


# ── Bulk import ──────────────────────────────────────────────────────────────
@admin_bp.route("/import/csv", methods=["POST"])
@write_required
def import_csv():
    body = _body()
    text = body.get("csv") or ""
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "send {csv: 'name,ip,kind,...'}"}), 400
    from importers.csv_import import node_drafts, parse_csv
    rows, errors = parse_csv(text)
    if errors:
        return jsonify({"error": "that list has problems", "problems": errors}), 422
    data, _, refusal = _read(atlas())
    if refusal:
        return refusal
    drafts = node_drafts(rows, data)
    return jsonify({"nodes": discovery.place_drafts(data, drafts), "count": len(drafts)})
