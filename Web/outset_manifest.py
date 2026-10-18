"""The Outset app manifest — vocabulary, builders and validator (version 1).

One document per app, served at ``GET api/manifest``, that the Hub reads on
registration and re-reads on a schedule: the card, how the app authenticates,
every scheduled block, every model lane, and where the call log is. The
contract text is ``docs/APP_MANIFEST.md``; this module is the machine half —
the words a manifest may use, small builders so every app spells them the
same way, ``validate()`` so a test can pin an app's manifest to the contract,
and ``public_view()`` for the anonymous shape.

Standard library only, so it vendors anywhere unchanged (the Feed keeps a
byte-identical copy at ``feed/outset_manifest.py`` and tests that it matches).

Standing rules the shape encodes (the calendar build plan, 2026-09-05):

* **Standalone first.** Nothing here needs a Hub. An app publishes its manifest
  whether or not anything reads it.
* **Per-app settings are authoritative.** The manifest DESCRIBES a block or a
  lane; the app's own settings own it. ``run_endpoint`` / ``toggle_endpoint``
  forward a person's request to the app, which decides.
* **Never widen a schedule.** A block appears in the manifest before it ever
  runs; the manifest has no way to express "run more often than the app does".
* **No new ``suite*`` names.** This is the Outset contract.
"""

MANIFEST_VERSION = 1

#: ``auth.mode``. ``ad-builtin``: the app authenticates against a directory
#: itself (hybrid local+AD counts) and can accept the Hub's signed claims, so
#: it federates. ``own-login``: the app has its own accounts and keeps its own
#: login screen; the Hub links to it and never pretends to sign anyone in.
AUTH_MODES = ("ad-builtin", "own-login")

#: ``cadence.kind``. One vocabulary for the Feed's chain (daily/weekly/interval),
#: the Ledger's APScheduler entries (cron/interval) and Atlas rites
#: (daily/weekly/monthly→cron, continuous→interval, parked).
#:   daily       at HH:MM in tz, optional days ("Mon-Fri", "Sun")
#:   weekly      day + at HH:MM in tz
#:   interval    every_min minutes, optionally only inside the active window
#:   cron        a five-field expression in tz
#:   on-request  never on a timer — Run now, a user action, or a peer's call
#:   parked      defined, deliberately not running
CADENCE_KINDS = ("daily", "weekly", "interval", "cron", "on-request", "parked")

#: ``lane.needs.speed``. Interactive = a person is waiting (beats batch in a
#: broker queue); batch = a scheduled block that may wait its turn.
SPEED_CLASSES = ("interactive", "batch")

#: Sections an app serves only to an identified operator. Anonymous callers get
#: ``card`` and ``auth`` plus the list of what they did not get.
GATED_SECTIONS = ("schedule", "lanes", "usage")

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# ─── builders ────────────────────────────────────────────────────────────────

def cadence(kind, *, at=None, tz=None, day=None, days=None, every_min=None,
            expr=None, within_window=False):
    """A block's timer. Only the fields the kind uses are meaningful; the rest
    stay None so every cadence has the same keys."""
    return {"kind": kind, "at": at, "tz": tz, "day": day, "days": days,
            "every_min": every_min, "expr": expr,
            "within_window": bool(within_window)}


def block(key, label, what, *, lane=None, chain=None, cadence=None,
          condition=None, enabled=True, last_run=None, ok=None, result=None,
          ms=None, next_run=None, pending=False, budget=None, hold_min=None):
    """One scheduled job. ``lane`` names the model lane it spends (None = no
    model calls). ``chain`` names the chain it runs inside, in which case its
    timer is the chain's and ``cadence`` is None."""
    return {"key": key, "label": label, "what": what, "lane": lane,
            "chain": chain, "cadence": cadence, "condition": condition,
            "enabled": bool(enabled), "last_run": last_run, "ok": ok,
            "result": result, "ms": ms, "next_run": next_run,
            "pending": bool(pending), "budget": budget, "hold_min": hold_min}


def chain(key, label, cadence, blocks, *, last_run=None, ran=None,
          next_run=None, pending=False):
    """An ordered run of blocks on one timer (the Feed's daily chain)."""
    return {"key": key, "label": label, "cadence": cadence,
            "blocks": list(blocks), "last_run": last_run, "ran": list(ran or []),
            "next_run": next_run, "pending": bool(pending)}


def needs(*, min_ctx=None, speed="batch", json=True):
    return {"min_ctx": min_ctx, "speed": speed, "json": bool(json)}


def lane(key, label, what, *, needs, provider, model, ctx=None, override=True,
         per_user=False):
    """One model-using job class. ``provider`` is the app's provider key
    (``local`` = its Ollama/OpenAI-compatible server; ``anthropic``, ``openai``,
    ``google``, ``deepseek``, ``custom`` as the Ledger names them). ``ctx`` is
    the context the lane actually runs at. ``override``: the app lets the Hub
    pre-populate this lane's provider+model. ``per_user``: signed-in readers
    may bring their own API for it (the Feed's reader lane)."""
    return {"key": key, "label": label, "what": what, "needs": needs,
            "provider": provider, "model": model, "ctx": ctx,
            "override": bool(override), "per_user": bool(per_user)}


def card(*, summary_endpoint="api/status", health_endpoint="api/status",
         lab_url=None, production_url=None, icon=None, accent_color=None):
    """Where the Hub's card reads from. It keeps reading ``summary`` from
    ``api/status`` (the hub-card contract); the manifest only says where."""
    return {"summary_endpoint": summary_endpoint, "health_endpoint": health_endpoint,
            "lab_url": lab_url or None, "production_url": production_url or None,
            "icon": icon, "accent_color": accent_color}


def auth(mode, *, honours_hub_claims=False, accounts=None):
    """``accounts``: free text for the matrix (``local``, ``hybrid``, ``ldap``)."""
    return {"mode": mode, "honours_hub_claims": bool(honours_hub_claims),
            "federated": mode == "ad-builtin" and bool(honours_hub_claims),
            "accounts": accounts}


def schedule(*, tz, active_from=None, active_to=None, blocks, chains=(),
             run_endpoint=None, toggle_endpoint=None, now=None):
    return {"tz": tz, "active_window": {"from": active_from or None,
                                        "to": active_to or None},
            "run_endpoint": run_endpoint, "toggle_endpoint": toggle_endpoint,
            "chains": list(chains), "blocks": list(blocks), "now": now}


def usage(endpoint=None, note=None):
    """``endpoint`` is None until the app keeps a per-call log (the core call
    log, work-queue step 2). Saying so honestly beats an endpoint that 404s."""
    return {"endpoint": endpoint, "note": note}


def manifest(app, name, version, *, card, auth, schedule=None, lanes=(), usage=None):
    return {"manifest_version": MANIFEST_VERSION, "app": app, "name": name,
            "version": version, "card": card, "auth": auth,
            "schedule": schedule, "lanes": list(lanes), "usage": usage}


def public_view(m):
    """The anonymous shape: identity + card + auth, and which sections were
    withheld. Same rule as ``/api/status``: the anonymous body must not leak
    operational shape (chain hours, models, last results)."""
    out = {k: v for k, v in m.items() if k not in GATED_SECTIONS}
    out["gated"] = [s for s in GATED_SECTIONS if s in m]
    return out


# ─── validator ───────────────────────────────────────────────────────────────

def _hhmm(s):
    if not isinstance(s, str) or s.count(":") != 1:
        return False
    h, m = s.split(":")
    return h.isdigit() and m.isdigit() and 0 <= int(h) <= 23 and 0 <= int(m) <= 59


def _relative(p):
    return isinstance(p, str) and p != "" and not p.startswith("/") and "://" not in p


def _absolute(u):
    return isinstance(u, str) and (u.startswith("http://") or u.startswith("https://"))


def _slug(s):
    return isinstance(s, str) and s != "" and all(c.isalnum() or c in "-_" for c in s) \
        and s == s.lower()


def _check_cadence(c, where, out):
    if not isinstance(c, dict):
        out.append(f"{where}: cadence must be an object")
        return
    kind = c.get("kind")
    if kind not in CADENCE_KINDS:
        out.append(f"{where}: cadence.kind {kind!r} not in {CADENCE_KINDS}")
        return
    if kind in ("daily", "weekly"):
        if not _hhmm(c.get("at")):
            out.append(f"{where}: {kind} cadence needs at=HH:MM")
        if not c.get("tz"):
            out.append(f"{where}: {kind} cadence needs tz")
    if kind == "weekly" and str(c.get("day") or "").lower()[:3] not in _DAYS:
        out.append(f"{where}: weekly cadence needs day (Mon…Sun)")
    if kind == "interval":
        n = c.get("every_min")
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            out.append(f"{where}: interval cadence needs every_min > 0")
    if kind == "cron":
        expr = c.get("expr")
        if not isinstance(expr, str) or len(expr.split()) != 5:
            out.append(f"{where}: cron cadence needs a five-field expr")
        if not c.get("tz"):
            out.append(f"{where}: cron cadence needs tz")


def validate(m):
    """Every way the manifest departs from the contract, as strings. Empty
    means valid. Never raises on junk — the Hub validates what apps send."""
    out = []
    if not isinstance(m, dict):
        return ["manifest must be an object"]
    if m.get("manifest_version") != MANIFEST_VERSION:
        out.append(f"manifest_version must be {MANIFEST_VERSION}")
    if not _slug(m.get("app")):
        out.append("app must be a lowercase slug")
    if not isinstance(m.get("name"), str) or not m.get("name"):
        out.append("name required")
    if not isinstance(m.get("version"), str) or not m.get("version"):
        out.append("version required")

    c = m.get("card")
    if not isinstance(c, dict):
        out.append("card required")
    else:
        for k in ("summary_endpoint", "health_endpoint"):
            if not _relative(c.get(k)):
                out.append(f"card.{k} must be a relative path (no leading /)")
        for k in ("lab_url", "production_url"):
            if c.get(k) is not None and not _absolute(c.get(k)):
                out.append(f"card.{k} must be an absolute http(s) URL or null")

    a = m.get("auth")
    if not isinstance(a, dict):
        out.append("auth required")
    else:
        if a.get("mode") not in AUTH_MODES:
            out.append(f"auth.mode must be one of {AUTH_MODES}")
        if not isinstance(a.get("honours_hub_claims"), bool):
            out.append("auth.honours_hub_claims must be a bool")
        if a.get("mode") == "own-login" and a.get("federated"):
            out.append("auth: an own-login app is never federated")

    lanes = m.get("lanes")
    lane_keys = set()
    if not isinstance(lanes, list):
        out.append("lanes must be a list (may be empty)")
    else:
        for i, ln in enumerate(lanes):
            where = f"lanes[{i}]"
            if not isinstance(ln, dict):
                out.append(f"{where}: must be an object")
                continue
            key = ln.get("key")
            if not _slug(key):
                out.append(f"{where}: key must be a lowercase slug")
            elif key in lane_keys:
                out.append(f"{where}: duplicate lane key {key!r}")
            lane_keys.add(key)
            nd = ln.get("needs")
            if not isinstance(nd, dict):
                out.append(f"{where}: needs required")
            else:
                if nd.get("speed") not in SPEED_CLASSES:
                    out.append(f"{where}: needs.speed must be one of {SPEED_CLASSES}")
                if not isinstance(nd.get("json"), bool):
                    out.append(f"{where}: needs.json must be a bool")
                mc = nd.get("min_ctx")
                if mc is not None and (not isinstance(mc, int) or isinstance(mc, bool) or mc <= 0):
                    out.append(f"{where}: needs.min_ctx must be a positive int or null")
            if not isinstance(ln.get("provider"), str) or not ln.get("provider"):
                out.append(f"{where}: provider required")
            if not isinstance(ln.get("model"), str):
                out.append(f"{where}: model must be a string (may be empty)")

    s = m.get("schedule")
    if s is not None:
        if not isinstance(s, dict):
            out.append("schedule must be an object or null")
        else:
            if not isinstance(s.get("tz"), str) or not s.get("tz"):
                out.append("schedule.tz required")
            win = s.get("active_window") or {}
            for k in ("from", "to"):
                v = win.get(k) if isinstance(win, dict) else None
                if v is not None and not _hhmm(v):
                    out.append(f"schedule.active_window.{k} must be HH:MM or null")
            for k in ("run_endpoint", "toggle_endpoint"):
                if s.get(k) is not None and not _relative(s.get(k)):
                    out.append(f"schedule.{k} must be a relative path or null")
            chain_keys = set()
            chains = s.get("chains")
            if not isinstance(chains, list):
                out.append("schedule.chains must be a list")
                chains = []
            for i, ch in enumerate(chains):
                where = f"schedule.chains[{i}]"
                if not isinstance(ch, dict) or not _slug(ch.get("key")):
                    out.append(f"{where}: key must be a lowercase slug")
                    continue
                if ch["key"] in chain_keys:
                    out.append(f"{where}: duplicate chain key {ch['key']!r}")
                chain_keys.add(ch["key"])
                _check_cadence(ch.get("cadence"), where, out)
                if not isinstance(ch.get("blocks"), list) or not ch.get("blocks"):
                    out.append(f"{where}: blocks must be a non-empty list of block keys")
            blocks = s.get("blocks")
            if not isinstance(blocks, list):
                out.append("schedule.blocks must be a list")
                blocks = []
            block_keys = set()
            for i, b in enumerate(blocks):
                where = f"schedule.blocks[{i}]"
                if not isinstance(b, dict):
                    out.append(f"{where}: must be an object")
                    continue
                key = b.get("key")
                if not _slug(key):
                    out.append(f"{where}: key must be a lowercase slug")
                elif key in block_keys:
                    out.append(f"{where}: duplicate block key {key!r}")
                block_keys.add(key)
                for k in ("label", "what"):
                    if not isinstance(b.get(k), str) or not b.get(k):
                        out.append(f"{where}: {k} required")
                if b.get("lane") is not None and b.get("lane") not in lane_keys:
                    out.append(f"{where}: lane {b.get('lane')!r} is not a declared lane")
                if b.get("chain") is not None:
                    if b.get("chain") not in chain_keys:
                        out.append(f"{where}: chain {b.get('chain')!r} is not a declared chain")
                    if b.get("cadence") is not None:
                        out.append(f"{where}: a chain block inherits the chain's cadence")
                else:
                    _check_cadence(b.get("cadence"), where, out)
                if not isinstance(b.get("enabled"), bool):
                    out.append(f"{where}: enabled must be a bool")
            for ch in chains:
                for k in (ch.get("blocks") or []) if isinstance(ch, dict) else []:
                    if k not in block_keys:
                        out.append(f"schedule.chains[{ch.get('key')}]: block {k!r} not declared")

    u = m.get("usage")
    if u is not None:
        if not isinstance(u, dict):
            out.append("usage must be an object or null")
        elif u.get("endpoint") is not None and not _relative(u.get("endpoint")):
            out.append("usage.endpoint must be a relative path or null")
    return out
