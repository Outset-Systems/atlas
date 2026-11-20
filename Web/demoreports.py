"""THE DEMO'S REPORTS — an invented security write-up and an uptime board.

The demo lab's Depths offer a "Security report" and its Sky an "Uptime board".
Both pointed at addresses that exist only in the story (a wiki page, a status
page on a private address), so on the hosted demo a press opened a tab that
could not load. A real lab answers those two itself or from its own network;
the demo has neither, so this module writes them, the way `demofigures.py`
writes the charts:

    /report/security   a weekly security write-up for the invented lab
    /report/uptime     a status board, read from the demo's own feed

On only while `demofigures.enabled()` holds (the demo flag, the image's seed,
and the bundled dataset on screen), so it can never stand in for a real lab's
report: there, `/report/security` is the staged scroll or says it has not been
delivered, and `/report/uptime` is not a page at all.

Every figure in the write-up is invented, for the invented lab, and the page
says so in its first line. The board is not invented twice: it reads the same
feed the map's markers wear, so the two cannot disagree. Dates are laid
against the clock (the week that began last Monday), as the charts are, so
the demo never goes stale.
"""

from datetime import datetime, timedelta, timezone

import demofigures

#: The reports this module answers, by the name in `/report/<name>`.
NAMES = ("security", "uptime")

_STATE_WORD = {"healthy": "up", "degraded": "degraded", "down": "DOWN",
               "maintenance": "maintenance", "slumbering": "asleep"}


def enabled():
    return demofigures.enabled()


def _now(now):
    return now or datetime.now(timezone.utc)


def security(now=None):
    """The invented weekly write-up, dated to the week that began last Monday."""
    now = _now(now)
    monday = (now - timedelta(days=now.weekday())).date()
    week = f"{monday - timedelta(days=7)} to {monday - timedelta(days=1)}"
    return f"""# WEEKLY SECURITY REPORT

_An invented report for the demo lab. Nothing here describes a real network._

- week of {week}
- written {monday} 06:00 UTC by the weekly job on MONITOR
- the edge's weather: USUAL, the routine rattle

## The edge

CrowdSec on EDGE read 1.9 million log lines and raised 212 alerts.

    alerts  scenario
      88    http-probing
      51    ssh-bruteforce
      37    http-bad-user-agent
      24    http-crawl-non-statics
      12    http-sensitive-files

41 addresses are banned now, 29 of them from the community list. No ban was
lifted by hand. The busiest source asked 6,104 times in an hour and was
banned on its ninth request.

## Sign-in

- SSH accepted: 14, all from the admin workstation, all by key
- SSH denied: 1,377, none for an account that exists
- DIRECTORY: 3 failed sign-ins, one person, one evening, then a success

## Exposed services

Three names answer from the internet: media, cloud and photos, all through
EDGE. Nothing else is published. The port survey from OFF-SITE on Sunday found
80 and 443 open and nothing more.

## Certificates

No certificate lapses within 14 days. The next is the cloud name, renewed
automatically 30 days before it ends.

## Patching

All eight guests took Sunday's updates. HYPERVISOR and NAS are one kernel
behind and wait for the next quiet window.

## Backups

The nightly snapshot ran seven times out of seven. The copy to OFF-SITE
finished each night; the slowest took 41 minutes. A restore of one folder was
tried on Wednesday and matched.

## To do

1. Reboot HYPERVISOR and NAS into the new kernel.
2. Retire the unused account `svc-old` on DIRECTORY.
"""


def uptime(data, feed, now=None):
    """The status board: every place and every watched service, as the demo's
    own feed has them now. `data` and `feed` are already this reader's."""
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
