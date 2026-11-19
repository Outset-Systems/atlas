"""THE REPAIRS — scheduled maintenance windows.

Maintenance used to be a flat list of node ids in `maintenance.json`: true
until somebody remembered to delete it. That is the shape the ops tooling's
`maintenance_prep` flow writes, and it still works — but a list cannot say
"the app host is down for patching between 02:00 and 04:00 on Sunday", so in
practice a window was opened by hand and closed by memory. A forgotten entry
suppresses a real outage indefinitely, which is the one failure a maintenance
feature must not have.

Windows carry a start, an end and an optional recurrence. They switch
themselves on and off, so nothing has to be remembered, and an expired window
stops suppressing anything the moment it ends.

**Backward compatible on purpose.** `read()` accepts all three shapes:

    ["downloads"]                          the oldest hand-edit
    {"nodes": ["downloads"]}               what the ops tooling writes today
    {"nodes": [...], "windows": [...]} what this module writes

The `nodes` list is preserved verbatim through every write, so the MCP and the
editor can both own part of the same file without fighting. Anything in it is
treated as an open-ended window with no end — because that is exactly what it
has always meant.

**Collections and maintenance mode (2026-11-14, the owner's Q4 answer).** A
window may name collections as well as places (`collections: [...]`), and
reaches whatever is in them whenever it is read (`window_places`), so a
place added to a collection later is covered. A window marked `open: true`
is MAINTENANCE MODE: it starts when it is made and has no end, on until
someone turns it off. That reverses "an end is required" for that one kind
on purpose; `problems` still requires an end of every other window, and the
daily digest names a mode left on more than a week.

Deliberately NOT part of `lab-data.json`: a window is operational state that
changes at 2am, not inventory. Putting it in the dataset would make every
scheduled reboot a git commit and let a map revert resurrect a stale window.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import settings
from jsonstore import JsonStore

log = logging.getLogger("atlas.live.maintenance")

#: Windows already warned about, by (id or reason, start, end): a window is
#: evaluated on every feed read, and the same incoherent one was warned about
#: every time (2026-11-19, the 11-12 audit's Live 15). Bounded by how many
#: distinct broken windows anyone writes.
_warned = set()

REPEATS = ("none", "daily", "weekly", "monthly")

#: Bounds the walk that settles a repeating window on its current occurrence
#: (`occurrence`): at most this many steps and four more, then it reads as ended.
HORIZON_DAYS = 60


def _now():
    return datetime.now(timezone.utc)


def parse_when(value):
    """Parse an ISO-8601 timestamp, tolerating the 'Z' suffix and a bare
    'YYYY-MM-DDTHH:MM' (what <input type=datetime-local> submits)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # A datetime-local field has no zone. Treat it as UTC rather than as the
    # server's local time: the dataset is timestamped in UTC everywhere else,
    # and guessing a zone is how a window opens an hour late.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso(when):
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if when else None


def _add_months(when, months):
    """Shift by whole months, clamping the day (31 Jan + 1 month = 28/29 Feb)."""
    month_index = when.month - 1 + months
    year = when.year + month_index // 12
    month = month_index % 12 + 1
    day = min(when.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return when.replace(year=year, month=month, day=day)


def _nth(start, repeat, n):
    """The nth occurrence start, always measured from the ORIGINAL start.

    Stepping one period at a time drifts on monthly: 31 Jan clamps to 28 Feb,
    and every later step then walks from the 28th, so a window set for the last
    day of the month silently becomes a window on the 28th forever. Computing
    from the original start clamps only where the target month is short.
    """
    if repeat == "daily":
        return start + timedelta(days=n)
    if repeat == "weekly":
        return start + timedelta(weeks=n)
    if repeat == "monthly":
        return _add_months(start, n)
    return None


def occurrence(window, now=None):
    """Where this window stands right now.

    Returns `(state, start, end)`, state being "active", "upcoming", "ended",
    or "invalid" for a window that cannot be interpreted. For a recurring
    window, start/end describe the occurrence covering `now`, else the next.

    An **open-ended** window (no `ends`) is active until it is removed — the
    same meaning the legacy flat node list has always had, so hand-edits behave
    the way they always did. The editor requires an end, which is what makes
    "somebody forgot to close the window" a thing of the past for anything
    created through the UI.
    """
    now = now or _now()
    start = parse_when(window.get("starts"))
    end = parse_when(window.get("ends"))

    # MAINTENANCE MODE is on from the moment it is turned on: its `starts`
    # is the browser's clock, and a clock a few minutes fast must not leave
    # it "upcoming" while faults raise alerts (stage 3 review)
    if window.get("open") is True:
        return "active", start, None

    if end is None:
        # open-ended, with or without a start
        if start is not None and now < start:
            return "upcoming", start, None
        return "active", start, None

    if start is None:                       # an end but no start: on until then
        return ("active", None, end) if now < end else ("ended", None, end)

    if end <= start:
        # Incoherent. Suppressing alarms on the strength of a window nobody can
        # read is the worst possible reading, so it suppresses nothing.
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

    # Jump straight to roughly the right occurrence, then settle. Bounded, so a
    # window from years ago cannot spin the loop. The jump must UNDER-shoot:
    # the loop only walks forward, so landing past the current occurrence
    # reports an active window as upcoming. 28 days as the monthly period
    # overshot a real month by ~2.5 days each, enough after two years to skip
    # the live one; 31 is the longest month, so it always lands short.
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
    """{"nodes": [...], "windows": [...]} from any of the three stored shapes:
    the oldest was a bare list of node ids, before windows existed."""
    if isinstance(raw, list):                       # oldest shape: a bare list
        return {"nodes": [str(n) for n in raw], "windows": []}
    if not isinstance(raw, dict):
        return {"nodes": [], "windows": []}
    nodes = raw.get("nodes")
    windows = raw.get("windows")
    return {
        "nodes": [str(n) for n in nodes] if isinstance(nodes, list) else [],
        "windows": [w for w in windows if isinstance(w, dict)] if isinstance(windows, list) else [],
    }


#: THE REPAIRS: {nodes (legacy + MCP), windows}. Path read live for reloads.
_STORE = JsonStore(lambda: settings.MAINTENANCE_PATH, _shape)


def read():
    """The stored file, normalised to {"nodes": [...], "windows": [...]}."""
    return _STORE.load()


def annotated(now=None):
    """Every window with its current state, sorted soonest-first."""
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
    """The place ids a window covers: the ones it names, and the members of
    each collection it names as `data` (the map the caller holds) lists them
    now. A collection `data` does not have, or no `data` at all, covers
    nothing: a window naming places still works when the map cannot be read.
    A caller holding a viewer's redacted map gets only that viewer's places."""
    out = set()
    if not isinstance(window, dict):
        return out
    named = window.get("nodes")
    out.update(str(n) for n in (named if isinstance(named, list) else []))   # a hand edit's 5 (round 14)
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
    """The service keys a window covers (stage 3b): the ones it names, and the
    `services` of each collection it names as `data` lists them now."""
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
    """Service keys under an active window now (stage 3b)."""
    now = now or _now()
    out = set()
    for window in read()["windows"]:
        if occurrence(window, now)[0] == "active":
            out.update(window_services(window, data))
    return out


def under_repair(now=None, data=None):
    """Node ids currently suppressed — active windows plus the legacy list.
    `data` resolves the collections a window names (`window_places`)."""
    now = now or _now()
    stored = read()
    ids = set(stored["nodes"])
    for window in stored["windows"]:
        state, _start, _end = occurrence(window, now)
        if state == "active":   # "invalid" deliberately suppresses nothing
            ids.update(window_places(window, data))
    return ids


def problems(windows):
    """What is wrong with a list of windows about to be saved, one sentence
    each: an entry that is not an object, a field the schema refuses, an id
    used twice, a window that ends before it starts. Empty when it can be saved."""
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
        # what it covers: places, collections, or both (2026-11-14)
        names = [window.get(k) for k in ("nodes", "collections", "services")]
        if not any(isinstance(v, list) and v for v in names):
            found.append(f"window {label}: it names no place, no collection and no service")
        # maintenance mode (`open`) is the one window with no end, and has none
        if window.get("open") is True:
            if window.get("ends"):
                found.append(f"window {label}: maintenance mode has no end; turn it off instead")
            if not window.get("starts"):
                found.append(f"window {label}: maintenance mode starts when it is turned on")
        elif not window.get("ends"):
            found.append(f"window {label}: missing ends (only maintenance mode is on until turned off)")
    return found


class StaleError(Exception):
    """The file changed after the editor read it: `expect` no longer matches."""


def save(windows, actor="unknown", expect=None):
    """Replace the window list, preserving whatever owns the `nodes` key.

    Full replace rather than an op stream: the list is short, the editor sends
    all of it, and keeping the ops tooling's `nodes` key untouched matters more
    than fine-grained merges.

    `expect` is the stamp the editor read. It is compared under the same lock
    as the write (2026-11-13; the 11-12 audit found the route comparing it
    before taking the lock, so two editors holding one stamp could both pass
    and the second overwrite the first). Raises StaleError when it differs.
    The returned `stamp` is the file's stamp after this write.
    """
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
    """A cheap version token so two editors don't silently overwrite."""
    return _stamp_of(read())


def summary(now=None, data=None):
    """Counts for the chrome: how many places are under repair, what's next.
    `data` resolves the collections a window names."""
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
