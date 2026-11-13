"""The staged markdown reports, and the two of them bound into one page.

`views.py` keeps the `/report/<name>` route and asks this module for the
text: which files exist, what one of them says, and the combined body.
Nothing here knows about HTTP.
"""

import os
import re
import time

import settings

#: Reports staged into `Data/reports/` by whatever task generates them.
REPORTS = {
    "security": "security-report-latest.md",
    "crowdsec": "crowdsec-report-latest.md",
}


def _read_report(key):
    """One staged scroll: (text, mtime) — (None, None) when it isn't there."""
    path = os.path.join(settings.REPORTS_DIR, REPORTS[key])
    try:
        # utf-8-sig, not utf-8: the scrolls are written by Windows PowerShell
        # 5.1, whose `Out-File -Encoding utf8` always stamps a BOM — which
        # plain utf-8 keeps as a ﻿ and the <pre> in `views.report` then renders as a
        # stray mark before the headline. Harmless when there is no BOM.
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read(), os.path.getmtime(path)
    except OSError:
        return None, None


# ── THE SECURITY SCROLL — the two reports bound as one (2026-08-15) ──────────
# The Abyss used to offer WEEKLY REPORT and CROWDSEC INSIGHT as two buttons,
# and the weekly's edge attack-surface section retold what the CrowdSec
# writeup already said better. One button now; where the two overlap, the
# CrowdSec insight speaks and the weekly's edge sections are folded away.

#: Weekly-scroll sections that yield to the CrowdSec insight. Matched against
#: `#`, `##` and `###` heading lines; a weekly whose headings never match is shown whole,
#: so a rewritten generator degrades to "everything, twice" rather than to a
#: silently missing section.
_WEEKLY_YIELDS = re.compile(r"crowdsec|attack[- ]?surface|edge attack", re.I)

#: The edge's temperature, read from the 24-hour alert count. Thresholds are a
#: judgment call, tuned to this edge's usual weather — move them freely.
_TEMPERATURE_BANDS = [
    (0, "CALM", "a quiet sea"),
    (30, "USUAL", "the routine rattle"),
    (150, "BRISK", "more knocking than usual"),
    (None, "STORM", "a campaign at the gate"),
]


def _temperature(crowdsec_md):
    """One line of weather from the CrowdSec scroll's 24-hour window.

    Counts the `Alerts by scenario` block under `## Last 24 hours` — the
    writeup's own format (the edge write-up script): five-wide counts in a
    code fence, or `_No alerts in this window._` for a quiet day. A scroll
    this can't read gets an honest "unread", never a made-up calm.
    """
    if not crowdsec_md:
        return "UNREAD — no CrowdSec scroll to take it from"
    day = re.search(r"^## Last 24 hours\n(.*?)(?=^## )", crowdsec_md,
                    re.M | re.S)
    if not day:
        return "UNREAD — the scroll shows no 24-hour window"
    section = day.group(1)
    if "_No alerts in this window._" in section:
        count = 0
    else:
        block = re.search(r"### Alerts by scenario\n+```\n(.*?)```", section, re.S)
        if not block:
            return "UNREAD — the scroll gave no scenario count"
        count = sum(int(m) for m in re.findall(r"^\s*(\d+)\s", block.group(1), re.M))
    for ceiling, label, gloss in _TEMPERATURE_BANDS:
        if ceiling is None or count <= ceiling:
            return f"{label} — {gloss} ({count} alert{'s' if count != 1 else ''} in 24h)"
    return "UNREAD"        # unreachable — the last band has no ceiling


def _fold_weekly(weekly_md):
    """The weekly scroll with its edge sections folded away.

    Split on heading lines, drop any section whose heading matches
    _WEEKLY_YIELDS, keep everything else (the SSH host-cert health above all).
    A section runs from one `#`, `##` or `###` line to the next, so a
    sub-section under a dropped heading stays unless its own heading matches.
    The preamble before the first heading always survives.
    """
    parts = re.split(r"(?=^#{1,3} )", weekly_md, flags=re.M)
    kept = [p for p in parts
            if not (p.startswith("#") and _WEEKLY_YIELDS.search(p.splitlines()[0]))]
    folded = len(parts) - len(kept)
    note = (f"\n_({folded} edge section{'s' if folded != 1 else ''} folded away — "
            "the CrowdSec insight above speaks for the edge.)_\n" if folded else "")
    return "".join(kept).rstrip() + note


def _security_scroll():
    """The combined page body: a concise head, the CrowdSec insight, then the
    weekly scroll minus what the insight already covers."""
    crowdsec, cs_at = _read_report("crowdsec")
    weekly, wk_at = _read_report("security")
    day = lambda t: time.strftime("%Y-%m-%d", time.localtime(t)) if t else "not yet delivered"  # noqa: E731
    head = (
        "# THE SECURITY SCROLL\n\n"
        f"- the edge's temperature: {_temperature(crowdsec)}\n"
        f"- CrowdSec insight of {day(cs_at)} · weekly scroll of {day(wk_at)}\n"
        "- one scroll, two scribes — where they overlap, the CrowdSec insight speaks\n"
    )
    parts = [head]
    parts.append("\n---\n\n" + (crowdsec.rstrip() if crowdsec
                 else "_The CrowdSec scribe has not yet delivered its scroll._"))
    parts.append("\n\n---\n\n# From the weekly scroll\n\n" + (_fold_weekly(weekly) if weekly
                 else "_The weekly scribe has not yet delivered its scroll._"))
    return "\n".join(parts)
