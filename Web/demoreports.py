from datetime import datetime, timedelta, timezone

import demofigures

NAMES = ("security", "uptime")

_STATE_WORD = {"healthy": "up", "degraded": "degraded", "down": "DOWN",
               "maintenance": "maintenance", "slumbering": "asleep"}


def enabled():
    return demofigures.enabled()


def _now(now):
    return now or datetime.now(timezone.utc)


def security(now=None):
    now = _now(now)
    monday = (now - timedelta(days=now.weekday())).date()
    week = f"{monday - timedelta(days=7)} to {monday - timedelta(days=1)}"
    return f"""# WEEKLY SECURITY REPORT

_An invented report for the demo lab. Nothing here describes a real network._

- week of {week}
- compiled for the Fernhill Workshop committee when this page was opened
- the weather at WEB BOX: ordinary

## The hosted box

CrowdSec on WEB BOX read 640,000 log lines and raised 73 alerts.

    alerts  scenario
      38    http-probing
      22    ssh-slow-bruteforce
      13    http-bad-user-agent

27 addresses are banned now. No ban was lifted by hand.

## The building

- members' Wi-Fi tried to reach a machine 4 times and was refused each time
- the decoy share on MINI B was touched once, by a committee member's scanner
- every door opening matched a booking and a fob

## Exposed services

Two names answer from the internet: the website and the newsletter, both on
WEB BOX. The building publishes nothing.

## Updates

All five guests took the update evening's packages. PRINT FARM waits until
the current print ends.

## Backups

Both servers' snapshots arrived every night. One drawing was restored from
the backup box as a test and opened correctly.

## To do

1. Move PRINT FARM onto the newer firmware.
2. Remove the fob of the member who moved away.
"""


def uptime(data, feed, now=None):
    now = _now(now)
    nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict) and n.get("id")]
    told = feed.get("nodes") if isinstance(feed.get("nodes"), dict) else {}
    services = feed.get("services") if isinstance(feed.get("services"), dict) else {}

    def state(entry):
        return entry.get("state") if isinstance(entry, dict) else None

    rows, tally = [], {}
    for n in nodes:
        entry = told.get(n["id"])
        word = _STATE_WORD.get(state(entry), "not watched")
        tally[word] = tally.get(word, 0) + 1
        days = entry.get("uptime_30d") if isinstance(entry, dict) else None
        share = f"{days:6.2f}%" if isinstance(days, (int, float)) and not isinstance(days, bool) else "      —"
        rows.append(f"  {str(n.get('name') or n['id']):<18} {word:<12} {share}")
    watched = [f"  {str(name):<28} {_STATE_WORD.get(state(entry), 'not known')}"
               for name, entry in sorted(services.items(), key=lambda kv: str(kv[0]).lower())]

    order = ("up", "degraded", "DOWN", "maintenance", "asleep", "not watched")
    summary = " · ".join(f"{tally[w]} {w}" for w in order if tally.get(w)) or "nothing is watched"
    lines = [
        "# UPTIME BOARD",
        "",
        "_An invented status page for the demo lab, read from the same feed the map wears._",
        "",
        f"- as of {now.strftime('%Y-%m-%d %H:%M')} UTC",
        f"- {len(nodes)} places: {summary}",
        "",
        "## Places",
        "",
        f"  {'place':<18} {'now':<12} 30 days",
        *rows,
    ]
    if watched:
        lines += ["", "## Services", "", f"  {'monitor':<28} now", *watched]
    return "\n".join(lines) + "\n"
