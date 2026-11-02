"""THE DEMO'S FIGURES — invented charts and card vitals for a look-only demo.

A hosted demo has no Prometheus and no Loki, so the Sky's and the Depths'
watchings fell back to a dark button and the cards drew no pulse: the two parts
of the Atlas that move were the two a visitor never saw move. This module
answers both from `demo-figures.json`, which the public image carries beside the
code (the publish build script copies it from `demo-lab/seed/figures.demo.json`,
written by `demo-lab/build.py`). Every number in it is invented, for the
invented demo lab.

On only when all three hold, so it can never paint over a real map:

  * `ATLAS_DEMO_FIGURES=1`, set by `hosted/compose.demo.yaml` and nothing else;
  * the image carries the file (the private tree does not);
  * the Atlas is showing its bundled dataset: `ATLAS_FALLBACK=bundled`, the file
    backend, and no dataset of its own on disk, the same test the bundled demo
    feed makes (`signals.DemoFeedAdapter`).

While it is on, `api/v2/charts` and `api/v2/vitals` answer from here and never
ask Prometheus or Loki, even if one is configured.

The seed holds values only, on a fixed step, covering whole weeks that start
on a Monday at 00:00 UTC. Each answer lays them against the clock so the last
week of the seed is this week: the evening peaks fall in the evening and the
Sunday patching on a Sunday, and the demo never goes stale.
"""

import json
import logging
import os
import threading

import settings

log = logging.getLogger("atlas.live.demo")   # a sibling of the bundled demo feed in atlas.live.signals

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
    """When the seed's first value falls: its span ends with this week, Sunday
    night UTC. 1970-01-01 was a Thursday, so a Monday is 4 days into a week."""
    monday = now - (now - 4 * _DAY) % _WEEK
    return monday + _WEEK - count * seed_step


def _along(values, seed_step, start, end, step, per_step):
    """`values` (seed_step apart, see `_first`) as [[ts, v]…] from `start` to `end`
    at `step`: linear between seed points, nothing outside them. A count per step
    is rescaled to the asked step, so a finer window reads lower, not wrong."""
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
    """{series} or {rows} for one watching, or None when the demo has no figures for it."""
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
    """The card's {cpu, ram} week for one place, or None."""
    v = (_figures().get("vitals") or {}).get(node_id)
    if not isinstance(v, dict):
        return None
    step = 3600
    end = end - end % step
    return {part: [[t, round(x, 1)] for t, x in
                   _along(v.get(part) or [], step, end - 7 * _DAY, end, step, False)]
            for part in ("cpu", "ram")}
