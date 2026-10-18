"""The Calendar's planner — one day of every app's manifest blocks, laid out,
overlaps found. Pure: manifests in, drawable items out. No HTTP.

Shared by the Hub (`/api/calendar`, which adds the actual-calls overlay and
the Run now / on-off forwarding) and by Atlas (`/api/v2/calendar`, its own
rites as blocks, the Hub's fleet view when one is configured). Vendored
unchanged; the CONTRACT mirror rule applies.

Input: registry-style entries — `{"key": app, "manifest": <manifest dict>}`.
Output: the view the shared `outset-calendar.js` draws:
  {day, zones, rows[], planned[], overlaps[], listed[]}
`rows` is one entry per thing (every block, every day, plus a placeholder
row for an app with no schedule); `planned` the instances on this day.
Each planned item: {app, app_name, block, label, chain, lane, model (bool),
provider, model_name, speed, enabled, start, end, hold_min, last_ok,
last_run, pending}. Width of a block = `hold_min`, else its last `ms`, else
10 minutes. Overlap = two enabled model blocks on the same provider+model
whose windows intersect (the shared-GPU collision the 2026-09-04 the GPU box
Calendar found by hand).
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_HOLD_MIN = 10
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _tz(name):
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def day_matches(spec, local_dt):
    """`days` like 'Mon-Fri', 'Sun', 'Sat,Sun', 'weekdays', '' (every day)."""
    s = (spec or "").strip().lower()
    if not s:
        return True
    wd = local_dt.weekday()
    if s in ("weekdays", "mon-fri"):
        return wd < 5
    if s in ("weekends", "sat-sun"):
        return wd >= 5
    if "-" in s:
        a, b = (x.strip()[:3] for x in s.split("-", 1))
        if a in _DAYS and b in _DAYS:
            ia, ib = _DAYS.index(a), _DAYS.index(b)
            return ia <= wd <= ib if ia <= ib else (wd >= ia or wd <= ib)
    return any(part.strip()[:3] == _DAYS[wd] for part in s.split(","))


def hold_of(block):
    if block.get("hold_min"):
        return float(block["hold_min"])
    if block.get("ms"):
        return max(1.0, float(block["ms"]) / 60000.0)
    return float(DEFAULT_HOLD_MIN)


def instances(cadence, day, tz_default="UTC", within=None):
    """Aware UTC start instants of a cadence on `day` (a date in the app's
    zone). `within` = (from, to) HH:MM local window for interval blocks.
    cron / on-request / parked yield nothing (listed, not drawn)."""
    if not cadence:
        return []
    kind = cadence.get("kind")
    tz = _tz(cadence.get("tz") or tz_default)
    midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
    if kind == "daily":
        if not day_matches(cadence.get("days"), midnight):
            return []
        h, m = (int(x) for x in str(cadence.get("at") or "00:00").split(":"))
        return [midnight.replace(hour=h, minute=m).astimezone(timezone.utc)]
    if kind == "weekly":
        if str(cadence.get("day") or "")[:3].lower() != _DAYS[midnight.weekday()]:
            return []
        h, m = (int(x) for x in str(cadence.get("at") or "00:00").split(":"))
        return [midnight.replace(hour=h, minute=m).astimezone(timezone.utc)]
    if kind == "interval":
        every = int(cadence.get("every_min") or 0)
        if every <= 0:
            return []
        start, end = midnight, midnight + timedelta(days=1)
        if cadence.get("within_window") and within and within[0] and within[1]:
            fh, fm = (int(x) for x in within[0].split(":"))
            th, tm = (int(x) for x in within[1].split(":"))
            start = midnight.replace(hour=fh, minute=fm)
            end = midnight.replace(hour=th, minute=tm)
            if end <= start:
                end += timedelta(days=1)
        out, t = [], start
        while t < end:
            out.append(t.astimezone(timezone.utc))
            t += timedelta(minutes=every)
        return out[:288]
    return []


def _item(app, manifest, block, lanes, start, hold_min, chain=None):
    lane = lanes.get(block.get("lane")) if block.get("lane") else None
    return {"app": app, "app_name": manifest.get("name") or app, "block": block["key"],
            "label": block.get("label") or block["key"], "chain": chain,
            "lane": block.get("lane"), "model": bool(block.get("lane")),
            "provider": lane.get("provider") if lane else None,
            "model_name": lane.get("model") if lane else None,
            "speed": (lane.get("needs") or {}).get("speed") if lane else None,
            "enabled": bool(block.get("enabled", True)),
            "start": start.isoformat(timespec="minutes"),
            "end": (start + timedelta(minutes=hold_min)).isoformat(timespec="minutes"),
            "hold_min": hold_min, "last_ok": block.get("ok"), "last_run": block.get("last_run"),
            "pending": bool(block.get("pending"))}


def planned(entries, day):
    """Every drawable block instance on `day`. Chain blocks run end to end
    from the chain's instant (a disabled block takes no time)."""
    out = []
    for entry in entries:
        m = entry.get("manifest") or {}
        s = m.get("schedule")
        if not s:
            continue
        app = entry["key"]
        lanes = {ln["key"]: ln for ln in (m.get("lanes") or []) if isinstance(ln, dict)}
        window = ((s.get("active_window") or {}).get("from"), (s.get("active_window") or {}).get("to"))
        blocks = {b["key"]: b for b in (s.get("blocks") or []) if isinstance(b, dict)}
        for ch in s.get("chains") or []:
            for start in instances(ch.get("cadence"), day, s.get("tz"), window):
                t = start
                for k in ch.get("blocks") or []:
                    b = blocks.get(k)
                    if not b:
                        continue
                    hold = hold_of(b)
                    out.append(_item(app, m, b, lanes, t, hold, chain=ch["key"]))
                    if b.get("enabled", True):
                        t = t + timedelta(minutes=hold)
        for b in blocks.values():
            if b.get("chain"):
                continue
            for start in instances(b.get("cadence"), day, s.get("tz"), window):
                out.append(_item(app, m, b, lanes, start, hold_of(b)))
    out.sort(key=lambda x: x["start"])
    return out


def overlaps(items):
    """Pairs of enabled model blocks on the same provider+model whose windows
    intersect. Same-app chain siblings never overlap by construction."""
    model_items = [i for i in items if i["model"] and i["enabled"]]
    found = []
    for a_i, a in enumerate(model_items):
        for b in model_items[a_i + 1:]:
            if (a["provider"], a["model_name"]) != (b["provider"], b["model_name"]):
                continue
            if a["app"] == b["app"] and a.get("chain") and a["chain"] == b.get("chain"):
                continue
            if a["start"] < b["end"] and b["start"] < a["end"]:
                found.append({"a": f"{a['app']}:{a['block']}", "b": f"{b['app']}:{b['block']}",
                              "provider": a["provider"], "model": a["model_name"],
                              "at": max(a["start"], b["start"])})
    return found


def listed(entries):
    """Blocks that are not drawn (cron / on-request / parked): the legend."""
    out = []
    for entry in entries:
        s = ((entry.get("manifest") or {}).get("schedule")) or {}
        for b in s.get("blocks") or []:
            if b.get("chain"):
                continue
            kind = (b.get("cadence") or {}).get("kind")
            if kind in ("cron", "on-request", "parked"):
                out.append({"app": entry["key"], "block": b["key"], "label": b.get("label"),
                            "kind": kind, "expr": (b.get("cadence") or {}).get("expr"),
                            "lane": b.get("lane"), "enabled": bool(b.get("enabled", True))})
    return out


def cadence_text(cadence, tz_default="UTC"):
    """A cadence as one short phrase for a row label: 'daily 08:00 CT',
    'weekly Sun 22:00 UTC', 'every 15 min 08:00-20:00', 'cron 0 3 * * *',
    'on request', 'parked', or '' for none."""
    if not cadence:
        return ""
    kind = cadence.get("kind")
    tz = cadence.get("tz") or tz_default or ""
    if kind == "daily":
        days = (cadence.get("days") or "").strip()
        return f"daily{' ' + days if days else ''} {cadence.get('at') or '00:00'} {tz}".strip()
    if kind == "weekly":
        return f"weekly {str(cadence.get('day') or '')[:3].title()} {cadence.get('at') or '00:00'} {tz}".strip()
    if kind == "interval":
        every = int(cadence.get("every_min") or 0)
        return (f"every {every} min" if every else "interval") + (" in window" if cadence.get("within_window") else "")
    if kind == "cron":
        return f"cron {cadence.get('expr') or ''}".strip()
    if kind == "on-request":
        return "on request"
    if kind == "parked":
        return "parked"
    return str(kind or "")


def rows(entries):
    """One row per thing, whether or not it has an instance today: every
    block of every registered app (chain blocks under their chain, with the
    chain's cadence), plus one row for an app that publishes no schedule —
    withheld (the Hub lacks its read token) or simply none. The drawable
    instances come from `planned`; this is the list the page hangs them on,
    so a weekly block is visible on the six days it does not run."""
    out = []
    for entry in entries:
        app = entry["key"]
        m = entry.get("manifest") or {}
        name = (m.get("name") or (entry.get("status") or {}).get("name")   # pre-manifest apps: their status card
                or entry.get("name") or app)
        s = m.get("schedule")
        if not s:
            gated = m.get("gated") or []
            reason = ("withheld — give the Hub this app's read token"
                      if "schedule" in gated else "no schedule published")
            out.append({"app": app, "app_name": name, "block": None, "label": reason,
                        "what": "", "kind": "none", "cadence_text": "", "chain": None,
                        "lane": None, "model": False, "provider": None, "model_name": None,
                        "enabled": False, "last_ok": None, "last_run": None, "pending": False})
            continue
        tz = s.get("tz") or "UTC"
        lanes = {ln["key"]: ln for ln in (m.get("lanes") or []) if isinstance(ln, dict)}
        chains = {c["key"]: c for c in (s.get("chains") or []) if isinstance(c, dict)}
        blocks = [b for b in (s.get("blocks") or []) if isinstance(b, dict)]
        ordered, seen = [], set()
        for c in chains.values():                      # chain members first, in chain order
            for k in c.get("blocks") or []:
                b = next((x for x in blocks if x.get("key") == k), None)
                if b and k not in seen:
                    ordered.append(b); seen.add(k)
        ordered += [b for b in blocks if b.get("key") not in seen]
        for b in ordered:
            chain = chains.get(b.get("chain") or "")
            cad = chain.get("cadence") if chain else b.get("cadence")
            lane = lanes.get(b.get("lane")) if b.get("lane") else None
            kind = (cad or {}).get("kind") or "none"
            out.append({"app": app, "app_name": name, "block": b["key"],
                        "label": b.get("label") or b["key"], "what": b.get("what") or "",
                        "kind": kind, "cadence_text": cadence_text(cad, tz) + (" (chain)" if chain else ""),
                        "chain": chain["key"] if chain else None,
                        "lane": b.get("lane"), "model": bool(b.get("lane")),
                        "provider": lane.get("provider") if lane else None,
                        "model_name": lane.get("model") if lane else None,
                        "enabled": bool(b.get("enabled", True)), "last_ok": b.get("ok"),
                        "last_run": b.get("last_run"), "pending": bool(b.get("pending"))})
    return out


def zones(entries):
    return sorted({((e.get("manifest") or {}).get("schedule") or {}).get("tz") or "UTC"
                   for e in entries if (e.get("manifest") or {}).get("schedule")})


def day_view(entries, day):
    """The drawable day, without the actual-calls overlay (the host adds it)."""
    items = planned(entries, day)
    return {"day": day.isoformat(), "zones": zones(entries), "planned": items,
            "overlaps": overlaps(items), "listed": listed(entries), "rows": rows(entries),
            "actual": []}
