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

REPEATS = ("none", "daily", "weekly", "monthly")

#: How far ahead "upcoming" looks when annotating a window.
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
        log.warning("maintenance window %r ends before it starts — ignoring",
                    window.get("id") or window.get("reason") or "?")
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


def under_repair(now=None):
    """Node ids currently suppressed — active windows plus the legacy list."""
    now = now or _now()
    stored = read()
    ids = set(stored["nodes"])
    for window in stored["windows"]:
        state, _start, _end = occurrence(window, now)
        if state == "active":   # "invalid" deliberately suppresses nothing
            ids.update(str(n) for n in (window.get("nodes") or []))
    return ids


def save(windows, actor="unknown"):
    """Replace the window list, preserving whatever owns the `nodes` key.

    Full replace rather than an op stream: the list is short, the editor sends
    all of it, and keeping the ops tooling's `nodes` key untouched matters more
    than fine-grained merges.
    """
    with _STORE.locked():
        stored = _STORE.load()
        payload = {"nodes": stored["nodes"], "windows": windows}
        _STORE.save(payload)
    log.info("maintenance windows saved by %s: %d window(s), %d legacy node(s)",
             actor, len(windows), len(stored["nodes"]))
    return {"windows": len(windows), "legacy_nodes": len(stored["nodes"])}


def stamp():
    """A cheap version token so two editors don't silently overwrite."""
    blob = json.dumps(read(), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def summary(now=None):
    """Counts for the chrome: how many places are under repair, what's next."""
    now = now or _now()
    windows = annotated(now)
    active = [w for w in windows if w["state"] == "active"]
    upcoming = [w for w in windows if w["state"] == "upcoming"]
    return {
        "under_repair": sorted(under_repair(now)),
        "active": len(active),
        "upcoming": len(upcoming),
        "next": upcoming[0]["occurrence_start"] if upcoming else None,
        "next_reason": upcoming[0].get("reason") if upcoming else None,
    }
