"""SHADOW (2026-11-15): Atlas's own checks asked beside Kuma, and counted.

With the map's `meta.shadow_kuma` on, THE WATCH (watch.py) also asks what a
Kuma monitor watches: a service link that names a monitor, by its own address
or check, and a place a monitor is tied to, when it has a check of its own.
Those answers never reach the live feed — Kuma stands where it watches — but
each one is set beside Kuma's state for the same thing here, once, and kept as
counts: how often the two agreed, how often they did not, and the last few
times they did not, with both states and when.

Up is up and anything else is not: a "pending" Kuma monitor (degraded) and an
Atlas check that says degraded both count as not up. A thing Kuma has in
maintenance, or says nothing about, is not counted; nor is an answer Atlas has
not yet believed (a failure still inside its retries).

Two limits, said here so the numbers are read right: a link whose monitor is
tied to a place (`signals.kuma`) is not shadowed on its own, because Kuma's
answer for it reaches Atlas only folded into its place; and a place's own
check is set beside its place's state, which is the worst of every monitor
tied to it.

The counts are what makes leaving Kuma a measured step (2026-11-15):
they live in `shadow.json` beside the dataset, one writer at a time, and an
answer is counted once however many workers build the feed.
"""

import json
import logging
import os
import time

import engines.authority as authority
import settings
from engines.base import DEGRADED, DOWN, HEALTHY

log = logging.getLogger("atlas.live.shadow")

FILE = "shadow.json"
KEEP = 20            # the last disagreements kept per thing
COUNTED = (HEALTHY, DEGRADED, DOWN)


def on(data):
    meta = data.get("meta") if isinstance(data, dict) else None
    return isinstance(meta, dict) and meta.get("shadow_kuma") is True


def path_of(path=None):
    return path or os.path.join(settings.DATA_DIR, FILE)


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _when(value):
    """An epoch time that can be shown, or None (a hand edit's string, or a
    number no date can hold)."""
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 32503680000
    return value if ok else None


def _clean(rec):
    """One thing's record, every field of the type it is read as."""
    last = [d for d in (rec.get("last") if isinstance(rec.get("last"), list) else [])
            if isinstance(d, dict) and _when(d.get("at")) is not None][:KEEP]
    out = {k: rec[k] for k in ("key", "kind", "place", "name", "of") if isinstance(rec.get(k), str)}
    out.update(agree=_count(rec.get("agree")), differ=_count(rec.get("differ")), last=last)
    if _when(rec.get("counted")) is not None:
        out["counted"] = rec["counted"]
    return out


def load(path=None):
    """{"since", "things": {ckey: {...}}}, or an empty one. A hand edit's
    odd value reads as nothing, never as a reason to stop counting."""
    try:
        with open(path_of(path), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = None
    if not isinstance(raw, dict) or not isinstance(raw.get("things"), dict):
        return {"since": None, "things": {}}
    return {"since": _when(raw.get("since")),
            "things": {k: _clean(v) for k, v in raw["things"].items() if isinstance(v, dict)}}


def _kuma_state(t, feed):
    """What Kuma says about a shadow target, or None."""
    if t.kind == "shadow":
        info = (feed.get("services") or {}).get(t.key)
        return info.get("state") if isinstance(info, dict) else None
    if (feed.get("confirmed_by") or {}).get(t.place) != authority.MONITOR:
        return None                   # the place's state did not come from its monitor
    info = (feed.get("nodes") or {}).get(t.place)
    return info.get("state") if isinstance(info, dict) else None


def _names(data):
    """{place id: name} and {(place id, monitor): service label}."""
    places, labels = {}, {}
    for node in data.get("nodes") or []:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            continue
        places[node["id"]] = node.get("name") or node["id"]
        for link in node.get("links") or []:
            if isinstance(link, dict) and isinstance(link.get("kuma"), str):
                labels.setdefault((node["id"], link["kuma"]), link.get("label") or link["kuma"])
    return places, labels


def observe(feed, data, path=None, watch_path=None, now=None):
    """Count every shadow answer Atlas has heard since it was last counted.
    Never raises: the feed must never fail for this. Returns how many were
    counted (None when off, or when another worker is counting)."""
    try:
        return _observe(feed, data, path, watch_path, now)
    except Exception as e:  # noqa: BLE001 - a comparison must never break the map
        log.warning("shadow: could not compare (%s: %s)", type(e).__name__, e)
        return None


def _observe(feed, data, path, watch_path, now):
    import filelock
    import watch
    if not isinstance(data, dict) or not on(data) or not isinstance(feed, dict):
        return None
    ts = [t for t in watch.targets(data) if t.kind in watch.SHADOW_KINDS]
    if not ts:
        return 0
    heard_store = watch.load(watch_path)["checks"]
    places, labels = _names(data)
    where = path_of(path)
    now = time.time() if now is None else now
    try:
        with filelock.writing_now(where) as save:
            doc = load(where)
            counted = 0
            things = {}
            for t in ts:
                rec = dict(doc["things"].get(t.ckey) or {})
                entry = heard_store.get(t.ckey) or {}
                heard, atlas = entry.get("heard"), entry.get("state")
                kuma = _kuma_state(t, feed)
                # the last answer is believed only when it is what the check
                # now says: a failure still inside its retries is not counted
                believed = entry.get("said") == atlas
                if (isinstance(heard, (int, float)) and heard != rec.get("counted")
                        and believed and atlas in COUNTED and kuma in COUNTED):
                    agree = (atlas == HEALTHY) == (kuma == HEALTHY)
                    key = "agree" if agree else "differ"
                    rec[key] = int(rec.get(key) or 0) + 1
                    if not agree:
                        rec["last"] = ([{"at": heard, "atlas": atlas, "kuma": kuma}]
                                       + list(rec.get("last") or []))[:KEEP]
                    rec["counted"] = heard
                    counted += 1
                rec["place"] = t.place
                rec["name"] = (labels.get((t.place, t.key), t.key) if t.kind == "shadow"
                               else places.get(t.place, t.place))
                rec["of"] = places.get(t.place, t.place) if t.kind == "shadow" else ""
                rec["key"] = t.key
                rec["kind"] = t.kind
                things[t.ckey] = rec
            out = {"since": doc["since"] or now, "things": things}   # what is no longer shadowed is dropped
            if counted or out != doc:
                save(out)
            return counted
    except filelock.LockTimeout:
        return None


def summary(data, path=None):
    """What an admin reads: whether shadow is on, since when, the totals, and
    each thing with its counts and its last disagreements, most differing
    first."""
    doc = load(path)
    things = []
    for rec in doc["things"].values():
        agree, differ = int(rec.get("agree") or 0), int(rec.get("differ") or 0)
        things.append({"key": rec.get("key"), "kind": rec.get("kind"), "place": rec.get("place"),
                       "name": rec.get("name"), "of": rec.get("of") or "",
                       "agree": agree, "differ": differ, "last": list(rec.get("last") or [])[:5]})
    things.sort(key=lambda r: (-r["differ"], -(r["agree"] + r["differ"]), str(r["name"])))
    agree = sum(r["agree"] for r in things)
    differ = sum(r["differ"] for r in things)
    try:
        import integrations
        asking = "checks" in integrations.enabled_sources()
    except Exception:  # noqa: BLE001 - unknown is not off
        asking = True
    return {"on": on(data), "asking": asking, "since": doc["since"], "agree": agree,
            "differ": differ, "things": things}
