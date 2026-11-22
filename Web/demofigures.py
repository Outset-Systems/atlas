import json
import logging
import os
import threading

import settings

log = logging.getLogger("atlas.live.demo")

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo-figures.json")

_lock = threading.Lock()
_cache = {"mtime": None, "data": {}}


def enabled():
    return (os.environ.get("ATLAS_DEMO_FIGURES", "").strip() == "1"
            and os.path.isfile(PATH)
            and settings.FALLBACK == "bundled" and settings.DATA_BACKEND == "file"
            and not os.path.exists(settings.DATA_PATH))


def _figures():
    try:
        mtime = os.path.getmtime(PATH)
    except OSError:
        return {}
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                with open(PATH, encoding="utf-8") as fh:
                    _cache["data"] = json.load(fh)
            except (OSError, ValueError):
                log.warning("demo figures unreadable at %s", PATH, exc_info=True)
                _cache["data"] = {}
            _cache["mtime"] = mtime
        return _cache["data"]


def chart_keys():
    return set((_figures().get("charts") or {}).keys())


_DAY, _WEEK = 86400, 7 * 86400


def _first(count, seed_step, now):
    monday = now - (now - 4 * _DAY) % _WEEK
    return monday + _WEEK - count * seed_step


def _along(values, seed_step, start, end, step, per_step):
    if not values:
        return []
    first = _first(len(values), seed_step, end)
    scale = step / seed_step if per_step else 1.0
    out = []
    t = end - ((end - start) // step) * step
    while t <= end:
        if t >= first:
            pos = (t - first) / seed_step
            i = min(int(pos), len(values) - 1)
            j = min(i + 1, len(values) - 1)
            v = values[i] + (values[j] - values[i]) * (pos - i)
            out.append([int(t), round(v * scale, 3)])
        t += step
    return out


def chart(key, start, end, step):
    spec = (_figures().get("charts") or {}).get(key)
    if not isinstance(spec, dict):
        return None
    if "rows" in spec:
        return {"rows": [dict(r) for r in spec["rows"]]}
    seed_step = int(_figures().get("step") or 3600)
    return {"series": [{"name": s["name"],
                        "points": _along(s["values"], seed_step, start, end, step,
                                         bool(spec.get("per_step")))}
                       for s in spec.get("series", [])]}


def vitals(node_id, end):
    v = (_figures().get("vitals") or {}).get(node_id)
    if not isinstance(v, dict):
        return None
    step = 3600
    end = end - end % step
    return {part: [[t, round(x, 1)] for t, x in
                   _along(v.get(part) or [], step, end - 7 * _DAY, end, step, False)]
            for part in ("cpu", "ram")}
