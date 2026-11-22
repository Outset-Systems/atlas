import json
import logging
import os
import time

import engines.authority as authority
import settings
from engines.base import DEGRADED, DOWN, HEALTHY

log = logging.getLogger("atlas.live.shadow")

FILE = "shadow.json"
KEEP = 20
COUNTED = (HEALTHY, DEGRADED, DOWN)


def on(data):
    meta = data.get("meta") if isinstance(data, dict) else None
    return isinstance(meta, dict) and meta.get("shadow_kuma") is True


def path_of(path=None):
    return path or os.path.join(settings.DATA_DIR, FILE)


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _when(value):
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 32503680000
    return value if ok else None


def _clean(rec):
    last = [d for d in (rec.get("last") if isinstance(rec.get("last"), list) else [])
            if isinstance(d, dict) and _when(d.get("at")) is not None][:KEEP]
    out = {k: rec[k] for k in ("key", "kind", "place", "name", "of") if isinstance(rec.get(k), str)}
    out.update(agree=_count(rec.get("agree")), differ=_count(rec.get("differ")), last=last)
    if _when(rec.get("counted")) is not None:
        out["counted"] = rec["counted"]
    return out


def load(path=None):
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
    if t.kind == "shadow":
        info = (feed.get("services") or {}).get(t.key)
        return info.get("state") if isinstance(info, dict) else None
    if (feed.get("confirmed_by") or {}).get(t.place) != authority.MONITOR:
        return None
    info = (feed.get("nodes") or {}).get(t.place)
    return info.get("state") if isinstance(info, dict) else None


def _names(data):
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
    try:
        return _observe(feed, data, path, watch_path, now)
    except Exception as e:
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
            out = {"since": doc["since"] or now, "things": things}
            if counted or out != doc:
                save(out)
            return counted
    except filelock.LockTimeout:
        return None


def summary(data, path=None):
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
    except Exception:
        asking = True
    return {"on": on(data), "asking": asking, "since": doc["since"], "agree": agree,
            "differ": differ, "things": things}
