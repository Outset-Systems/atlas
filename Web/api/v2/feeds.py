"""Live feeds — `GET /api/v2/signals`, `/api/v2/rites`, `/api/v2/events`.

Side-effectful, clock-stamped reads: `signals` sweeps the beat drop-dir,
rewrites adapter maps and appends transitions to the annals; `rites` sweeps
too. The bodies are dynamic per viewer and are not modelled.

The four private helpers at the top (`_apply_kuma_map`, `_label_for`,
`_drift`, `_redact_feed`) are the shared machinery of the signals feed. They
lived in the v1 route module and were imported from it while both surfaces
were live; they moved here whole at the v1 removal (v1.41.0).
"""

import logging

from flask import jsonify, make_response, request

import dependencies
import events
import heartbeats
import maintenance
import tripwires
from context import atlas
from redaction import (redact_for_groups, cleared, hidden_node_ids, sees_everything, vary_on_viewer,
                       viewer_groups, visible_monitors)

from . import bp

log = logging.getLogger("atlas.api.v2")


# ── The signals feed's machinery ─────────────────────────────────────────────
def _apply_kuma_map(ctx):
    """Push what each live adapter needs from the dataset onto it: the
    hand-editable Kuma monitor→node map, so `signals.kuma` drives which monitor
    lights which marker; the address→node map for Prometheus; the places for
    UniFi. All of it hot-reloads with the dataset."""
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        return
    for adapter in getattr(ctx.signals, "adapters", []):
        use_map = getattr(adapter, "use_map", None)
        if use_map is not None:
            use_map(data)     # each adapter takes its own (signals.py)


def _label_for(ctx):
    """A namer for the annals — a place's display name beats its id."""
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        return lambda kind, target: target
    names = {n.get("id"): n.get("name") for n in data.get("nodes", [])}
    rites = {heartbeats.key_for(r): (r.get("name") or "")
             for r in (data.get("rites") or []) if isinstance(r, dict)}

    def label(kind, target):
        if kind == "node":
            return names.get(target) or target
        if kind == "rite":
            return rites.get(target) or target
        return target
    return label


def _drift(ctx, feed):
    """Survey drift: monitors Kuma watches that the map hasn't
    charted. Silence deliberate omissions via `signals.drift_ignore`."""
    services = feed.get("services") or {}
    if not services:
        return None
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        return None
    # a link with no monitor is charted under its own key, which is what a
    # built-in check reports it by: its result is not an uncharted monitor
    import signals
    charted = {signals.service_key(node.get("id"), link)
               for node in data.get("nodes", [])
               for link in (node.get("links") or [])}
    ignore = set(((data.get("signals") or {}).get("drift_ignore")) or [])
    uncharted = sorted(n for n in services if n not in charted and n not in ignore)
    return {"count": len(uncharted), "uncharted": uncharted}


def _redact_feed(ctx, feed, groups, data=None):
    """The signals feed, cut down to the places this viewer is cleared for.

    `data` is the dataset to judge by, for a caller that hides more than the
    file says (`cloud_view.withhold`). Left out, the dataset is read here.

    `lab-data` has been redacted since the feature existed and `events`
    filters through `cleared()`, but this feed — the one that is keyed by node
    id and updates live — once applied nothing at all. Any signed-in viewer
    with zero clearance could enumerate every `require_group` place, watch it
    go up and down, and read the names of the monitors watching it.
    """
    # TRIPWIRES are admin-only, wholesale: which bait is speaking, how many
    # trips nobody could attribute, even that a decoy feed is wired at all,
    # is the deception layout read the wrong way round. Same blunt rule as
    # the account roster — cleared to see everything, or none of it.
    sources = {k: v for k, v in (feed.get("sources") or {}).items() if k != "deception"}
    try:
        if data is None:
            data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        # Fail closed. Without the dataset there is no way to know which ids
        # this viewer may see, and every key in this feed is one of those ids.
        return {"nodes": {}, "services": {}, "sources": sources,
                "generated": feed.get("generated"),
                "cached": feed.get("cached", False)}

    hidden = hidden_node_ids(data, groups)
    monitors = visible_monitors(data, groups)
    out = dict(feed)
    out.pop("stones", None)
    out["sources"] = sources
    if isinstance(out.get("metrics"), dict):
        out["metrics"] = {k: v for k, v in out["metrics"].items()
                          if k not in ("unattributed_trips", "undelivered_alerts")}

    nodes = {}
    for node_id, info in (feed.get("nodes") or {}).items():
        if node_id in hidden:
            continue
        # A visible place may name a hidden one as the CAUSE of its outage
        # ("dark behind the gateway") — that is the hidden id arriving by the
        # back door, so the fallout is reported without its explanation.
        if isinstance(info, dict) and (info.get("cause") in hidden
                                       or info.get("via") in hidden):
            info = {k: v for k, v in info.items() if k not in ("cause", "via")}
        nodes[node_id] = info
    out["nodes"] = nodes

    out["services"] = {name: info for name, info in (feed.get("services") or {}).items()
                       if name in monitors}
    out["maintenance"] = [n for n in (feed.get("maintenance") or []) if n not in hidden]
    if hidden:
        out.pop("repairs", None)      # its counts and its next reason span every window
    if isinstance(out.get("rites"), dict):
        seen = heartbeats.keys_of(redact_for_groups(data)[0].get("rites"))
        out["rites"] = {k: v for k, v in out["rites"].items() if k in seen}
    causes = feed.get("causes")
    if isinstance(causes, dict):
        out["causes"] = {cause: [i for i in ids if i not in hidden]
                         for cause, ids in causes.items() if cause not in hidden}
    # THE DRIFT is the survey's own view of what it has not charted yet. It is
    # a list of monitor names that by definition belong to no visible place, so
    # there is no version of it that is safe for a viewer with partial
    # clearance — it is admin-only or it is absent.
    out.pop("drift", None)
    return out


def build_feed(ctx):
    """The full, UNREDACTED live feed, with every once-per-poll side effect:
    repairs, consequences, the rites sweep, THE ANNALS and drift.

    Request-free on purpose (it needs only an app context): the signals route
    redacts it per viewer, and the background annalist (`annalist.py`, started
    from gunicorn.conf.py) drives it on a timer so an outage nobody is watching
    still reaches the annals. Before v1.46.0 the only caller was a browser, so
    the 09-17 and 09-24 fleet outages recorded nothing.
    """
    _apply_kuma_map(ctx)
    feed = dict(ctx.signals.feed())

    # THE REPAIRS: scheduled windows decide who is under repair now, and an
    # expired window stops suppressing the moment it ends. The legacy flat node
    # list still counts — maintenance.under_repair() folds both together.
    repairs = maintenance.summary()
    if repairs["under_repair"]:
        nodes = dict(feed.get("nodes", {}))
        for node_id in repairs["under_repair"]:
            nodes[node_id] = {**nodes.get(node_id, {}), "state": "maintenance"}
        feed["nodes"] = nodes
    feed["maintenance"] = repairs["under_repair"]
    feed["repairs"] = {k: repairs[k] for k in ("active", "upcoming", "next", "next_reason")}

    # One fault, one alarm: a place that is down behind something else that is
    # down is a consequence, not an incident. Runs after maintenance so that a
    # window on the root marks the fallout planned too.
    try:
        data, _, _ = ctx.dataset()
        dependencies.apply_to(data, feed)
        # THE RITES: adopt anything dropped since the last poll, then fold the
        # verdicts in so a rite that stopped turning becomes an event below,
        # exactly like a place that went dark. Swept here rather than on a
        # timer because this is already the once-per-poll path.
        heartbeats.sweep_dropped_files()
        feed["rites"] = heartbeats.as_feed(data.get("rites"))
    except (OSError, ValueError):
        feed["causes"] = {}

    # THE ANNALS: record transitions, but only on a freshly built feed. The hub
    # caches for 30s and flags a cached read, so this runs once per source poll
    # rather than once per browser refresh.
    if not feed.get("cached"):
        try:
            events.record(feed, _label_for(ctx))
        except Exception as e:      # noqa: BLE001 — history must never break the map
            log.warning("could not record events: %s", e)

    drift = _drift(ctx, feed)
    if drift:
        feed["drift"] = drift
    return feed


# ── The routes ───────────────────────────────────────────────────────────────
@bp.route("/signals")
def signals_feed():
    """Merged live-signals feed for the front-end (auth-gated like the dataset).

    Never fails: an unreachable source degrades to a 'silent' entry so the map
    falls back to its static behaviour rather than erroring.
    """
    ctx = atlas()
    feed = build_feed(ctx)

    groups = viewer_groups()
    if not sees_everything(groups):
        feed = _redact_feed(ctx, feed, groups)

    resp = make_response(jsonify(feed))
    resp.headers["Cache-Control"] = "no-store"   # health is live; never cached
    return vary_on_viewer(resp)


@bp.route("/rites")
def rites_feed():
    """Every rite with what actually happened to it.

    Gated like the map rather than like the editor: a rite is not a person and
    carries no clearance of its own, but it does name hosts, so it rides with
    the dataset's own auth instead of being public.
    """
    ctx = atlas()
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError) as e:
        log.error("lab-data unreadable: %s", e)
        return jsonify({"error": f"lab data unreadable: {e}"}), 500

    heartbeats.sweep_dropped_files()
    rites = redact_for_groups(data)[0].get("rites") or []
    status = {row["key"]: row for row in heartbeats.status_for(rites)}
    # A TOKEN DOES NOT READ WHAT A JOB WROTE (2026-11-11). The MCP tool always
    # left a run's note and the poster's address out; this route handed both to
    # the same token. A person signed in still sees them: the calendar shows them.
    import api_tokens
    if api_tokens.current():
        status = {key: heartbeats.without_job_words(row) for key, row in status.items()}
    out = []
    for rite in rites:
        if isinstance(rite, dict):
            out.append({**rite, **status.get(heartbeats.key_for(rite), {})})
    resp = make_response(jsonify({"rites": out}))
    resp.headers["Cache-Control"] = "no-store"   # last-run truth is never cached
    return vary_on_viewer(resp)


@bp.route("/events")
def events_feed():
    """The annals — auth-gated like the map, and redacted the same way.

    Events are derived from the map, so they inherit its clearance rules: a
    node hidden behind `require_group` must not reappear as a row in the
    history. Acknowledging is admin-only and lives on the admin workstation.
    """
    ctx = atlas()
    groups = viewer_groups()
    visible = services = rites = None
    if not sees_everything(groups):
        try:
            data, _, _ = ctx.dataset()
            visible = {n.get("id") for n in data.get("nodes", []) if cleared(n, groups)}
            # a service row names its monitor, so it takes the monitor gate
            services = visible_monitors(data, groups)
            # a rite row names its rite, so it takes the gate `/rites` takes: one
            # dropped there for naming a hidden place was still listed here
            rites = heartbeats.keys_of(redact_for_groups(data)[0].get("rites"))
        except (OSError, ValueError):
            visible, services, rites = set(), set(), set()
    limit = min(request.args.get("limit", type=int) or 100, events.KEEP)
    unacked = request.args.get("unacked") == "1"
    if sees_everything(groups):
        body = {"events": events.listing(limit=limit, visible=visible, unacked_only=unacked),
                "counts": events.counts(visible=visible)}
    else:
        # TRIPWIRES: a trip row (and its share of the counts) is admin-only, and
        # so is who acknowledged a row and what they wrote (`events.for_viewer`)
        body = {"events": tripwires.listing_without_trips(
                    limit=limit, visible=visible, unacked_only=unacked,
                    visible_services=services, visible_rites=rites),
                "counts": tripwires.counts_without_trips(visible=visible,
                                                         visible_services=services,
                                                         visible_rites=rites)}
    resp = make_response(jsonify(body))
    resp.headers["Cache-Control"] = "no-store"
    return vary_on_viewer(resp)
