import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import settings
from jsonstore import JsonStore

log = logging.getLogger("atlas.live.maintenance")

_warned = set()

REPEATS = ("none", "daily", "weekly", "monthly")

HORIZON_DAYS = 60


def _now():
    return datetime.now(timezone.utc)


def parse_when(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso(when):
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if when else None


def _add_months(when, months):
    month_index = when.month - 1 + months
    year = when.year + month_index // 12
    month = month_index % 12 + 1
    day = min(when.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return when.replace(year=year, month=month, day=day)


def _nth(start, repeat, n):
    if repeat == "daily":
        return start + timedelta(days=n)
    if repeat == "weekly":
        return start + timedelta(weeks=n)
    if repeat == "monthly":
        return _add_months(start, n)
    return None


def occurrence(window, now=None):
    now = now or _now()
    start = parse_when(window.get("starts"))
    end = parse_when(window.get("ends"))

    if window.get("open") is True:
        return "active", start, None

    if end is None:
        if start is not None and now < start:
            return "upcoming", start, None
        return "active", start, None

    if start is None:
        return ("active", None, end) if now < end else ("ended", None, end)

    if end <= start:
        name = window.get("id") or window.get("reason") or "?"
        if (str(name), start, end) not in _warned:
            _warned.add((str(name), start, end))
            log.warning("maintenance window %r ends before it starts — ignoring", name)
        return "invalid", start, end

    duration = end - start
    repeat = window.get("repeat") or "none"
    if repeat not in REPEATS:
        repeat = "none"

    if now < start:
        return "upcoming", start, end
    if repeat == "none":
        return ("active", start, end) if now < end else ("ended", start, end)

    elapsed = now - start
    period = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1),
              "monthly": timedelta(days=31)}[repeat]
    n = max(0, int(elapsed / period) - 1)
    for _ in range(HORIZON_DAYS + 4):
        current = _nth(start, repeat, n)
        nxt = _nth(start, repeat, n + 1)
        if now < current:
            return "upcoming", current, current + duration
        if now < current + duration:
            return "active", current, current + duration
        if now < nxt:
            return "upcoming", nxt, nxt + duration
        n += 1
    return "ended", _nth(start, repeat, n), _nth(start, repeat, n) + duration


def _shape(raw):
    if isinstance(raw, list):
        return {"nodes": [str(n) for n in raw], "windows": []}
    if not isinstance(raw, dict):
        return {"nodes": [], "windows": []}
    nodes = raw.get("nodes")
    windows = raw.get("windows")
    return {
        "nodes": [str(n) for n in nodes] if isinstance(nodes, list) else [],
        "windows": [w for w in windows if isinstance(w, dict)] if isinstance(windows, list) else [],
    }


_STORE = JsonStore(lambda: settings.MAINTENANCE_PATH, _shape)


def read():
    return _STORE.load()


def annotated(now=None):
    now = now or _now()
    out = []
    for window in read()["windows"]:
        state, start, end = occurrence(window, now)
        out.append({**window, "state": state, "occurrence_start": iso(start),
                    "occurrence_end": iso(end)})
    order = {"active": 0, "upcoming": 1, "ended": 2}
    out.sort(key=lambda w: (order.get(w["state"], 3), w.get("occurrence_start") or ""))
    return out


def window_places(window, data=None):
    out = set()
    if not isinstance(window, dict):
        return out
    named = window.get("nodes")
    out.update(str(n) for n in (named if isinstance(named, list) else []))
    wanted = window.get("collections")
    if isinstance(wanted, list) and isinstance(data, dict):
        import schema
        listed = data.get("collections")
        by_id = ({c["id"]: c for c in listed if isinstance(c, dict) and isinstance(c.get("id"), str)}
                 if isinstance(listed, list) else {})
        for cid in wanted:
            found = by_id.get(cid) if isinstance(cid, str) else None
            if found:
                out.update(p for p in schema.as_list(found.get("places")) if isinstance(p, str) and p)
    return out


def window_services(window, data=None):
    out = set()
    if not isinstance(window, dict):
        return out
    named = window.get("services")
    out.update(k for k in (named if isinstance(named, list) else []) if isinstance(k, str) and k)
    wanted = window.get("collections")
    if isinstance(wanted, list) and isinstance(data, dict):
        import schema
        listed = data.get("collections")
        by_id = ({c["id"]: c for c in listed if isinstance(c, dict) and isinstance(c.get("id"), str)}
                 if isinstance(listed, list) else {})
        for cid in wanted:
            found = by_id.get(cid) if isinstance(cid, str) else None
            if found:
                out.update(k for k in schema.as_list(found.get("services")) if isinstance(k, str) and k)
    return out


def services_under_repair(now=None, data=None):
    now = now or _now()
    out = set()
    for window in read()["windows"]:
        if occurrence(window, now)[0] == "active":
            out.update(window_services(window, data))
    return out


def under_repair(now=None, data=None):
    now = now or _now()
    stored = read()
    ids = set(stored["nodes"])
    for window in stored["windows"]:
        state, _start, _end = occurrence(window, now)
        if state == "active":
            ids.update(window_places(window, data))
    return ids


def problems(windows):
    import schema
    found = []
    seen = set()
    for i, window in enumerate(windows):
        if not isinstance(window, dict):
            found.append(f"window #{i + 1}: not an object")
            continue
        label = window.get("id") or f"#{i + 1}"
        found += [f"window {label}: {p}"
                  for p in schema.check_entry("maintenance", window, strict=True)]
        if window.get("id") in seen:
            found.append(f"window {label}: duplicate id")
        seen.add(window.get("id"))
        state, _s, _e = occurrence(window)
        if state == "invalid":
            found.append(f"window {label}: it ends before it starts")
        names = [window.get(k) for k in ("nodes", "collections", "services")]
        if not any(isinstance(v, list) and v for v in names):
            found.append(f"window {label}: it names no place, no collection and no service")
        if window.get("open") is True:
            if window.get("ends"):
                found.append(f"window {label}: maintenance mode has no end; turn it off instead")
            if not window.get("starts"):
                found.append(f"window {label}: maintenance mode starts when it is turned on")
        elif not window.get("ends"):
            found.append(f"window {label}: missing ends (only maintenance mode is on until turned off)")
    return found


class StaleError(Exception):
    pass


def save(windows, actor="unknown", expect=None):
    with _STORE.locked():
        stored = _STORE.load()
        if expect and expect != _stamp_of(stored):
            raise StaleError("the repairs changed since they were read")
        payload = {"nodes": stored["nodes"], "windows": windows}
        _STORE.save(payload)
        after = _stamp_of(_STORE.load())
    log.info("maintenance windows saved by %s: %d window(s), %d legacy node(s)",
             actor, len(windows), len(stored["nodes"]))
    return {"windows": len(windows), "legacy_nodes": len(stored["nodes"]), "stamp": after}


def _stamp_of(stored):
    blob = json.dumps(stored, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def stamp():
    return _stamp_of(read())


def summary(now=None, data=None):
    now = now or _now()
    windows = annotated(now)
    active = [w for w in windows if w["state"] == "active"]
    upcoming = [w for w in windows if w["state"] == "upcoming"]
    return {
        "under_repair": sorted(under_repair(now, data)),
        "services_under_repair": sorted(services_under_repair(now, data)),
        "active": len(active),
        "upcoming": len(upcoming),
        "next": upcoming[0]["occurrence_start"] if upcoming else None,
        "next_reason": upcoming[0].get("reason") if upcoming else None,
    }
