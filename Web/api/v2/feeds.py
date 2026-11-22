import logging

from flask import jsonify, make_response, request

import dependencies
import events
import heartbeats
import maintenance
import shadow
import signals
import tripwires
from context import atlas
import redaction
from engines.base import NODE_STATES, monitor_map
from engines.places import service_places, services_of, unmanaged_ids, unmanaged_service_keys
from redaction import (redact_for_groups, cleared, hidden_node_ids, hidden_slugs, hidden_words,
                       sees_everything, vary_on_viewer, viewer_groups, visible_monitors)

from . import _count, bp

log = logging.getLogger("atlas.api.v2")


def _apply_kuma_map(ctx):
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        return
    signals.push_map(getattr(ctx.signals, "adapters", []), data)


def _label_for(ctx):
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        return lambda kind, target: target
    names = {n.get("id"): n.get("name") for n in data.get("nodes") or [] if isinstance(n, dict)}
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
    services = feed.get("services") or {}
    if not services:
        return None
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        return None
    from engines.places import service_key
    charted = {service_key(node.get("id"), link)
               for node in data.get("nodes") or [] if isinstance(node, dict)
               for link in (node.get("links") or []) if isinstance(link, dict)}
    block = data.get("signals") if isinstance(data.get("signals"), dict) else {}
    listed = block.get("drift_ignore")
    ignore = {n for n in listed if isinstance(n, str)} if isinstance(listed, list) else set()
    uncharted = sorted(n for n in services if n not in charted and n not in ignore)
    return {"count": len(uncharted), "uncharted": uncharted}


def _redact_feed(ctx, feed, groups, data=None):
    sources = {k: v for k, v in (feed.get("sources") or {}).items() if k != "deception"}
    sources_at = {k: v for k, v in (feed.get("sources_at") or {}).items() if k != "deception"}
    try:
        if data is None:
            data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        return {"nodes": {}, "services": {}, "sources": sources, "sources_at": sources_at,
                "generated": feed.get("generated"),
                "cached": feed.get("cached", False)}

    hidden = hidden_node_ids(data, groups)
    monitors = visible_monitors(data, groups)
    out = dict(feed)
    out.pop("stones", None)
    out["sources"] = sources
    out["sources_at"] = sources_at
    if isinstance(out.get("metrics"), dict):
        out["metrics"] = {k: v for k, v in out["metrics"].items()
                          if k not in ("unattributed_trips", "undelivered_alerts")}

    below = not sees_everything(groups)
    if below:
        on_map = {n["id"] for n in data.get("nodes") or []
                  if isinstance(n, dict) and isinstance(n.get("id"), str) and cleared(n, groups)}
    nodes = {}
    for node_id, info in (feed.get("nodes") or {}).items():
        if node_id in hidden or (below and node_id not in on_map):
            continue
        if below and isinstance(info, dict) and info.get("state") not in NODE_STATES:
            info = {k: v for k, v in info.items() if k != "state"}
        if isinstance(info, dict) and (info.get("cause") in hidden
                                       or info.get("via") in hidden):
            info = {k: v for k, v in info.items() if k not in ("cause", "via")}
        nodes[node_id] = info
    out["nodes"] = nodes
    if isinstance(feed.get("confirmed_by"), dict):
        out["confirmed_by"] = {k: v for k, v in feed["confirmed_by"].items()
                               if k not in hidden and v != "deception"}

    out["services"] = {name: info for name, info in (feed.get("services") or {}).items()
                       if name in monitors}
    if below:
        out["services"] = {name: ({k: v for k, v in info.items() if k != "state"}
                                  if isinstance(info, dict) and info.get("state") not in NODE_STATES
                                  else info)
                           for name, info in out["services"].items()}
    if not sees_everything(groups):
        out["services"] = {name: ({**info, "tls": {k: v for k, v in info["tls"].items() if k != "names"}}
                                  if isinstance(info, dict) and isinstance(info.get("tls"), dict) else info)
                           for name, info in out["services"].items()}
    if hidden:
        seen = {n["id"] for n in data.get("nodes") or []
                if isinstance(n, dict) and isinstance(n.get("id"), str) and cleared(n, groups)}
        keep = lambda key: [n for n in (feed.get(key) or []) if n in seen]
    else:
        keep = lambda key: list(feed.get(key) or [])
    out["maintenance"] = keep("maintenance")
    out["unmanaged"] = keep("unmanaged")
    out["maintenance_services"] = [k for k in (feed.get("maintenance_services") or []) if k in monitors]
    out.pop("unmanaged_services", None)
    if hidden:
        out.pop("repairs", None)
    if isinstance(out.get("rites"), dict):
        seen = heartbeats.keys_of(redact_for_groups(data)[0].get("rites"))
        out["rites"] = {k: v for k, v in out["rites"].items() if k in seen}
    causes = feed.get("causes")
    if isinstance(causes, dict):
        out["causes"] = {cause: [i for i in ids if i not in hidden]
                         for cause, ids in causes.items() if cause not in hidden}
    out.pop("drift", None)
    return out


def compose(ctx, before_rites=None):
    _apply_kuma_map(ctx)
    feed = dict(ctx.signals.feed())

    try:
        map_now, _, _ = ctx.dataset()
    except (OSError, ValueError):
        map_now = None
    repairs = maintenance.summary(data=map_now)
    if repairs["under_repair"]:
        nodes = dict(feed.get("nodes", {}))
        for node_id in repairs["under_repair"]:
            nodes[node_id] = {**nodes.get(node_id, {}), "state": "maintenance"}
        feed["nodes"] = nodes
        if isinstance(feed.get("confirmed_by"), dict):
            feed["confirmed_by"] = {k: v for k, v in feed["confirmed_by"].items()
                                    if k not in repairs["under_repair"]}
    feed["maintenance"] = repairs["under_repair"]
    feed["repairs"] = {k: repairs[k] for k in ("active", "upcoming", "next", "next_reason")}

    unmanaged = unmanaged_ids(map_now) if map_now is not None else set()
    quiet = services_of(map_now, unmanaged) | (
        unmanaged_service_keys(map_now) if map_now is not None else set())
    feed["unmanaged"] = sorted(unmanaged)
    feed["unmanaged_services"] = sorted(quiet)
    if unmanaged:
        feed["nodes"] = {k: v for k, v in (feed.get("nodes") or {}).items() if k not in unmanaged}
        feed["maintenance"] = [n for n in feed["maintenance"] if n not in unmanaged]
        if isinstance(feed.get("confirmed_by"), dict):
            feed["confirmed_by"] = {k: v for k, v in feed["confirmed_by"].items() if k not in unmanaged}
    if quiet and isinstance(feed.get("services"), dict):
        feed["services"] = {k: v for k, v in feed["services"].items() if k not in quiet}

    charted = (set(service_places(map_now)) | set(monitor_map(map_now))) if map_now is not None else set()
    fixing = [k for k in repairs.get("services_under_repair") or [] if k not in quiet and k in charted]
    feed["maintenance_services"] = sorted(fixing)
    if fixing:
        services = dict(feed.get("services") or {})
        for key in fixing:
            services[key] = {**(services.get(key) or {}), "state": "maintenance"}
        feed["services"] = services

    try:
        data, _, _ = ctx.dataset()
        dependencies.apply_to(data, feed)
        if before_rites is not None:
            before_rites()
        feed["rites"] = heartbeats.as_feed(data.get("rites"))
    except (OSError, ValueError):
        feed["causes"] = {}
    return feed, map_now


def record(ctx, feed, map_now):
    if not feed.get("cached"):
        try:
            events.record(feed, _label_for(ctx))
        except Exception as e:
            log.warning("could not record events: %s", e)
    if not feed.get("cached") and map_now is not None:
        shadow.observe(feed, map_now)


def build_feed(ctx):
    feed, map_now = compose(ctx, before_rites=heartbeats.sweep_dropped_files)
    record(ctx, feed, map_now)
    feed.pop("unmanaged_services", None)

    drift = _drift(ctx, feed)
    if drift:
        feed["drift"] = drift
    return feed


@bp.route("/signals")
def signals_feed():
    ctx = atlas()
    feed = build_feed(ctx)

    groups = viewer_groups()
    if not sees_everything(groups):
        feed = _redact_feed(ctx, feed, groups)

    resp = make_response(jsonify(feed))
    resp.headers["Cache-Control"] = "no-store"
    return vary_on_viewer(resp)


@bp.route("/rites")
def rites_feed():
    ctx = atlas()
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError) as e:
        log.error("lab-data unreadable: %s", e)
        return jsonify({"error": f"lab data unreadable: {e}"}), 500

    heartbeats.sweep_dropped_files()
    rites = redact_for_groups(data)[0].get("rites") or []
    status = {row["key"]: row for row in heartbeats.status_for(rites)}
    import api_tokens
    if api_tokens.current():
        status = {key: heartbeats.without_job_words(row) for key, row in status.items()}
    else:
        groups = viewer_groups()
        names, slugs = hidden_words(data, groups), hidden_slugs(data, groups)
        if names or slugs:
            def says_hidden(row):
                last = row.get("last") if isinstance(row.get("last"), dict) else {}
                return any(redaction._names_hidden(last.get(k), "words", names, slugs)
                           for k in heartbeats.JOB_WORDS)
            status = {key: heartbeats.without_job_words(row) if says_hidden(row) else row
                      for key, row in status.items()}
    out = []
    for rite in rites:
        if isinstance(rite, dict):
            out.append({**rite, **status.get(heartbeats.key_for(rite), {})})
    resp = make_response(jsonify({"rites": out}))
    resp.headers["Cache-Control"] = "no-store"
    return vary_on_viewer(resp)


@bp.route("/events")
def events_feed():
    ctx = atlas()
    groups = viewer_groups()
    visible = services = rites = None
    if not sees_everything(groups):
        try:
            data, _, _ = ctx.dataset()
            visible = {n.get("id") for n in data.get("nodes", []) if cleared(n, groups)}
            services = visible_monitors(data, groups)
            rites = heartbeats.keys_of(redact_for_groups(data)[0].get("rites"))
        except (OSError, ValueError):
            visible, services, rites = set(), set(), set()
    limit = _count("limit", 100, events.KEEP)
    unacked = request.args.get("unacked") == "1"
    if sees_everything(groups):
        body = {"events": events.listing(limit=limit, visible=visible, unacked_only=unacked),
                "counts": events.counts(visible=visible)}
    else:
        body = {"events": tripwires.listing_without_trips(
                    limit=limit, visible=visible, unacked_only=unacked,
                    visible_services=services, visible_rites=rites),
                "counts": tripwires.counts_without_trips(visible=visible,
                                                         visible_services=services,
                                                         visible_rites=rites)}
    resp = make_response(jsonify(body))
    resp.headers["Cache-Control"] = "no-store"
    return vary_on_viewer(resp)
