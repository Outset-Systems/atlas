"""Pages: the atlas itself, and the staged markdown reports the Abyss iframes."""

import html
import logging
import os
import re
import time

from flask import Blueprint, jsonify, make_response, render_template

import mapart
import settings
from context import atlas
from security import is_admin

log = logging.getLogger("atlas.web.views")

bp = Blueprint("views", __name__)

#: Reports staged into `Data/reports/` by whatever task generates them.
REPORTS = {
    "security": "security-report-latest.md",
    "crowdsec": "crowdsec-report-latest.md",
}


@bp.route("/")
def index():
    """The map. `editable` decides whether the editing chrome is even rendered.

    Server-side rather than a client check: a viewer who can't write should
    never be shown a pencil that 403s when they press it.
    """
    title = _realm_title()
    seeded = atlas().reader.seeded()
    return render_template(
        "index.html",
        editable=settings.writes_enabled() and is_admin(),
        seeded=seeded,
        # an unseeded instance on ATLAS_FALLBACK=bundled is showing the demo,
        # not an empty realm: the first-survey invite says so (first run, W8)
        demo=not seeded and settings.FALLBACK == "bundled",
        client_config=settings.client_config(),
        map_image=_map_image(),
        realm_title=title,
        veil_title=_veil_title(title),
    )


def _realm_title():
    """The realm's own name, for the tab and the veil — `meta.title` of the
    dataset being served, never a constant. Both used to be hard-coded
    "the lab", which the hosted the demo realm instance then wore too
    (2026-09-27). Signed-in only (this view is behind the gate), so naming
    the realm here is what settings.APP_BRAND's rule allows."""
    try:
        data, _, _ = atlas().dataset()
        title = str((data.get("meta") or {}).get("title") or "").strip()
    except (OSError, ValueError):
        title = ""
    return title or settings.APP_BRAND


def _veil_title(title):
    """The veil's short form: "Home Lab Atlas" -> "HOME LAB", the way it
    has always read; a realm not named "... Atlas" is shown whole."""
    short = title[:-len(" Atlas")] if title.endswith(" Atlas") else title
    return (short or title).upper()


def _map_image():
    """Which base render this map is drawn on.

    Resolved server-side so the browser makes one request for the right
    picture — a client-side swap would paint the default first and then
    replace it, which on a 4 MB render is a visible flash of somebody else's
    map. Falls back to the bundled default whenever the dataset is unreadable
    or names art that isn't there: an unconfigured backdrop is recoverable, a
    broken <img> on the only screen is not.
    """
    try:
        data, _, _ = atlas().dataset()
        name = (data.get("meta") or {}).get("map_image") or mapart.DEFAULT
    except (OSError, ValueError):
        name = mapart.DEFAULT
    path, bundled = mapart.resolve(name)
    if path and bundled:
        return f"static/map/{os.path.basename(path)}"
    if path:
        return f"map-art/{os.path.basename(path)}"
    return f"static/map/{mapart.DEFAULT}"


@bp.route("/map-art/<name>")
def map_art(name):
    """Serve an uploaded base render.

    Gated exactly like the map it backs: `/` is already behind the Hub in the
    deployment that matters, and a floor plan of the building is not less
    sensitive than the markers drawn on it. `Content-Type` is set from the
    bytes rather than the extension, and `nosniff` stops the browser
    second-guessing that.
    """
    safe = mapart.safe_name(name)
    if not safe:
        return jsonify({"error": "no such render"}), 404
    path = os.path.join(settings.MAPS_DIR, safe)
    if not os.path.isfile(path):
        return jsonify({"error": "no such render"}), 404
    try:
        with open(path, "rb") as handle:
            head = handle.read(16)
            handle.seek(0)
            blob = handle.read()
    except OSError:
        return jsonify({"error": "no such render"}), 404

    kind = mapart.sniff(head)
    if not kind:
        # stored before a validator existed, or tampered with on the volume
        log.warning("refusing to serve map art %s: not a raster image", safe)
        return jsonify({"error": "that render is not a usable image"}), 415

    resp = make_response(blob)
    resp.headers["Content-Type"] = f"image/{'jpeg' if kind == 'jpg' else kind}"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Disposition"] = "inline"
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


def _read_report(key):
    """One staged scroll: (text, mtime) — (None, None) when it isn't there."""
    path = os.path.join(settings.REPORTS_DIR, REPORTS[key])
    try:
        # utf-8-sig, not utf-8: the scrolls are written by Windows PowerShell
        # 5.1, whose `Out-File -Encoding utf8` always stamps a BOM — which
        # plain utf-8 keeps as a ﻿ and the <pre> below then renders as a
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
#: `#`/`##` heading lines; a weekly whose headings never match is shown whole,
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


@bp.route("/report/<name>")
def report(name):
    """Serve a staged markdown report as a dark page the Abyss can iframe.

    Raw markdown in a styled <pre> — readable, zero dependencies, and the vault's
    original stays the artifact of record. `security` is the bound scroll —
    both reports combined behind one head (see _security_scroll); `crowdsec`
    still serves the insight alone for anyone linking straight to it.
    """
    status = 200
    if name == "security":
        body = _security_scroll()
    elif name in REPORTS:
        body, _ = _read_report(name)
        if body is None:
            body = "_The scribes have not yet delivered this report._"
    else:
        # A page answers as a page. This was the one route that spoke HTML on
        # success and JSON on failure; the Abyss frames
        # it, and a frame that lands on a JSON document shows the viewer a
        # bare string.
        body, status = "_No such scroll._", 404
    page = (
        "<!doctype html><meta charset='utf-8'>"
        f"<title>{html.escape(name)} report</title>"
        "<style>body{background:#1d2021;color:#ebdbb2;margin:0;padding:1.2rem 1.6rem;}"
        "pre{font:12.5px/1.55 'Cascadia Code',Consolas,monospace;white-space:pre-wrap;"
        "word-break:break-word;margin:0;}</style>"
        f"<pre>{html.escape(body)}</pre>"
    )
    resp = make_response(page, status)
    resp.headers["Cache-Control"] = "no-cache"
    # The app-wide default is `DENY`, which is right for the map and wrong for
    # the one page that exists to be drawn inside it: DENY blocks *same-origin*
    # framing too, so the Abyss and THE VIEWING GLASS could never show this.
    # Set here rather than relaxed globally — this is the only frameable page.
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    return resp
