"""The Atlas's app manifest and its day on the shared Calendar
(the shared framework docs/APP_MANIFEST.md, the calendar build plan).

  GET /api/manifest, /api/v2/manifest   card, auth, schedule (the rites), no lanes
  GET /api/v2/calendar?day=YYYY-MM-DD   the drawable day for outset-calendar.js

The rites ARE the schedule: every rite the map charts becomes a block, its
`cadence` / `at` / `days` / `between` / `when` read into the manifest's one
cadence vocabulary, its heartbeat verdict as the last run. The Atlas itself
calls no model, so it declares no lanes; a rite that `asks` a forge names
the model it uses in its `what`. Run now and on/off are not offered — the
rites are other hosts' timers, charted here, not owned here.

Standalone: `/api/v2/calendar` draws the Atlas's own rites. Combined
(`ATLAS_HUB_URL` set): it asks the Hub for the fleet's day with a machine
identity (`svc:atlas`, signed by the fleet secret) and hands that back —
every registered app's blocks, overlaps flagged — falling back to its own
rites, honestly labelled, when the Hub does not answer.
"""
import datetime as dt
import logging
import os
import re

from flask import jsonify, make_response, request

import atlas_auth
import heartbeats
import outset_calendar
import outset_manifest as om
import settings
from context import atlas
from redaction import no_store, redact_for_groups

from . import bp

log = logging.getLogger("atlas.api.manifest")

_DAY = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)
_HHMM = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_MINUTE_ONLY = re.compile(r"^:(\d{2})$")


def hub_url():
    return os.environ.get("ATLAS_HUB_URL", "").strip().rstrip("/")


def cadence_of(rite):
    """A rite's clock in the manifest's vocabulary. Unclocked rites are
    listed as on-request rather than guessed at."""
    cad = (rite.get("cadence") or "").strip().lower()
    if cad == "parked":
        return om.cadence("parked")
    at = (rite.get("at") or "").strip()
    when = rite.get("when") or ""
    days = (rite.get("days") or "").strip() or None
    m = _MINUTE_ONLY.match(at)
    if m:                                                   # ':35' = hourly at :35
        return om.cadence("cron", expr=f"{int(m.group(1))} * * * *", tz="UTC")
    hhmm = None
    m = _HHMM.match(at)
    if m:                                                   # '13:45', also '13:45:00' / '13:45 UTC'
        hhmm = f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    else:
        found = _HHMM.search(when)
        if found:
            hhmm = f"{int(found.group(1)):02d}:{found.group(2)}"
    if cad == "continuous":
        every = heartbeats.parse_duration(rite.get("expect_every")) or 3600
        return om.cadence("interval", every_min=max(1, int(every // 60)),
                          within_window=bool(rite.get("between")))
    if hhmm is None:
        return om.cadence("on-request")
    if cad == "weekly":
        day = (days or "").split(",")[0].strip()[:3].title() or None
        if not day:
            d = _DAY.search(when)
            day = d.group(1).title() if d else None
        if day:
            return om.cadence("weekly", day=day, at=hhmm, tz="UTC")
        return om.cadence("on-request")
    if cad == "monthly":
        return om.cadence("cron", expr=f"{int(hhmm[3:])} {int(hhmm[:2])} 1 * *", tz="UTC")
    return om.cadence("daily", at=hhmm, tz="UTC", days=days)


def _blocks(rites):
    verdicts = {row["key"]: row for row in heartbeats.status_for(rites)}
    out, seen = [], set()
    for rite in rites:
        if not isinstance(rite, dict):
            continue
        key = heartbeats.key_for(rite) or ""
        if not key or key in seen:
            continue
        seen.add(key)
        v = verdicts.get(key) or {}
        last = v.get("last") or {}
        what = " · ".join(x for x in (rite.get("note"), rite.get("host") and f"on {rite['host']}",
                                       rite.get("asks") and f"asks {rite['asks']} for {rite.get('model') or 'a model'}")
                          if x) or rite.get("name") or key
        hold = rite.get("hold")
        out.append(om.block(
            key, rite.get("name") or key, what,
            cadence=cadence_of(rite), enabled=(rite.get("cadence") != "parked"),
            last_run=last.get("at"), ok=(last.get("status") != "fail") if last else None,
            result=(last.get("note") or v.get("verdict")) or None,
            ms=int(last["duration_s"] * 1000) if isinstance(last.get("duration_s"), (int, float)) else None,
            hold_min=int(hold) if isinstance(hold, (int, float)) and hold > 0 else None))
    return out


def _auth():
    mode = atlas_auth.mode()
    import hub_auth.auth as ka
    if mode in ("hub", "hybrid"):
        return om.auth("ad-builtin", honours_hub_claims=bool(ka.AUTH_SECRET),
                       accounts="hybrid" if mode == "hybrid" else "hub")
    if mode == "accounts":
        # The directory is on when the LDAP backend says so — the same check the
        # sign-in path uses (env OR the Settings file). This read a knob that
        # never existed (ATLAS_LDAP_SERVER), so accounts mode always claimed
        # "own-login" even with AD sign-in working (fixed v1.47.1).
        import ldap_backend
        return om.auth("ad-builtin" if ldap_backend.enabled() else "own-login",
                       honours_hub_claims=False, accounts="accounts")
    return om.auth("own-login", honours_hub_claims=False, accounts="none")


def build():
    ctx = atlas()
    try:
        data, _, _ = ctx.dataset()
        rites = redact_for_groups(data)[0].get("rites") or []
    except (OSError, ValueError) as e:
        log.error("manifest: lab-data unreadable: %s", e)
        rites = []
    return om.manifest(
        settings.APP_KEY, settings.APP_BRAND, settings.APP_VERSION,
        card=om.card(lab_url=os.environ.get("ATLAS_LAB_URL", "").strip() or None,
                     production_url=os.environ.get("ATLAS_PRODUCTION_URL", "").strip() or None,
                     icon="map", accent_color=settings.ACCENT_COLOR),
        auth=_auth(),
        schedule=om.schedule(tz="UTC", blocks=_blocks(rites), chains=[],
                             run_endpoint=None, toggle_endpoint=None,
                             now=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
        lanes=[],
        usage=om.usage(None, "The Atlas calls no model; the rites chart other apps' calls."))


def _is_operator():
    """Any viewer the gate let through to the map sees the rites already; the
    manifest's schedule is the same rows, so the same rule. This path is
    exempt from the gate, so it asks for itself, in hub mode too."""
    return atlas_auth.has_viewer()


def manifest_response():
    doc = build()
    resp = make_response(jsonify(doc if _is_operator() else om.public_view(doc)))
    return no_store(resp)


@bp.route("/manifest")
def manifest_v2():
    return manifest_response()


@bp.route("/calendar")
def calendar_day():
    """The drawable day. Fleet-wide through the Hub when one is configured
    and answers; the Atlas's own rites otherwise."""
    raw = request.args.get("day") or ""
    try:
        day = dt.date.fromisoformat(raw) if raw else dt.datetime.now(dt.timezone.utc).date()
    except ValueError:
        return jsonify({"error": "day must be YYYY-MM-DD"}), 400
    own = outset_calendar.day_view([{"key": settings.APP_KEY, "manifest": build()}], day)
    hub = hub_url()
    if not hub:
        return no_store(jsonify({**own, "fleet": False, "hub": None}))
    import requests
    import hub_auth.auth as ka
    token = ka.mint_token("svc:" + settings.APP_KEY)
    if not token:
        return no_store(jsonify({**own, "fleet": False, "hub": hub,
                                 "hub_error": "no fleet secret configured (ATLAS_HUB_SECRET)"}))
    try:
        r = requests.get(f"{hub}/api/calendar", params={"day": day.isoformat(), "actual": "0"},
                         headers={ka.SIGNED_HEADER: token}, timeout=6)
        r.raise_for_status()
        view = r.json()
        if not isinstance(view, dict) or "planned" not in view:
            raise ValueError("not a calendar view")
        return no_store(jsonify({**view, "fleet": True, "hub": hub}))
    except Exception as e:                                     # noqa: BLE001
        log.warning("calendar: the Hub did not answer (%s); drawing our own rites", e)
        return no_store(jsonify({**own, "fleet": False, "hub": hub, "hub_error": str(e)[:200]}))
