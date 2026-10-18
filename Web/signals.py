"""Live-signals layer for the Atlas — the glass over Kuma/Prometheus, never the engine.

Principle (ALIVE.md §0.2): *the map never dies with its sources.* Every adapter here
is built to fail silent — a timeout, a 500, a bad payload, a missing key all resolve to
"no signal" (an empty dict), never to an exception that could break the render. The
front-end treats an absent feed as the v1.0.0 static behaviour ("the watchers are silent").

Architecture (ALIVE.md §1): one small adapter per source, each exposing `fetch() -> dict`
with a hard 3s timeout and a guarantee never to raise. `SignalsHub` merges the enabled
adapters into one cached feed (30s TTL) that `/api/signals` serves and the front-end polls.

Sources are chosen by env so going live is config-only:

    ATLAS_SIGNALS_SOURCES   comma list: "static", "kuma", "prometheus", "relay",
                            "deception" (default: "" = none)
    ATLAS_SIGNALS_FILE      static/mock feed path (default /data/signals.json)
    ATLAS_SITE              site slug the "relay" source reads (default "default")
    ATLAS_KUMA_URL          e.g. http://edge:3001
    ATLAS_KUMA_API_KEY      Kuma API key  (or ATLAS_KUMA_API_KEY_FILE -> docker secret)
    ATLAS_PROM_URL          e.g. http://monitor:9090
    ATLAS_DECOYS_URL       e.g. http://decoys:5013
    ATLAS_DECOYS_KEY       the decoy feed's read key (or ATLAS_DECOYS_KEY_FILE -> docker secret)

Secrets come from env or a *_FILE docker-secret path — never the dataset, never the client.
"""

import json
import logging
import os
import threading
import time

import settings

log = logging.getLogger("atlas.live.signals")

# ── Marker states (must match the CSS classes the front-end swaps) ──────────────
HEALTHY = "healthy"      # breathing gold
DEGRADED = "degraded"    # amber
DOWN = "down"            # slow red pulse
SLUMBERING = "slumbering"  # grey (e.g. The standby host, intentionally off)
_VALID_STATES = frozenset((HEALTHY, DEGRADED, DOWN, SLUMBERING))

# ── decoy voices (the decoy feed) ─────────────────────────────────────────────
# A DIFFERENT vocabulary from the marker states above, on purpose. A stone is
# not up or down — it is quiet, or it has been disturbed, or it is speaking
# right now. Reusing `healthy`/`down` here would say something false: a silent
# stone is not "healthy", it is unvisited, which is the ordinary state and the
# one we hope for.
SILENT = "silent"        # nothing has touched it
STIRRED = "stirred"      # touched recently, below the escalation line
SPEAKING = "speaking"    # a live trip — the one time the quiet map raises its voice
_VALID_STONE_STATES = frozenset((SILENT, STIRRED, SPEAKING))

_TIMEOUT = 3.0  # hard per-source timeout; a slow source must never stall the feed


def _read_secret(name):
    """Resolve a secret: THE SOURCES settings first (v1.37.0, encrypted at
    rest), then ATLAS_<NAME> or ATLAS_<NAME>_FILE (docker secret). None if absent."""
    try:
        import integrations
        stored = integrations.get(name) if name in integrations.SECRETS else ""
        if stored:
            return stored
    except Exception:  # noqa: BLE001 — the settings layer never silences a source
        log.warning("integrations unreadable while resolving %s", name, exc_info=True)
    import envnames
    val = envnames.env(name)
    if val:
        return val.strip()
    path = envnames.env(name + "_FILE")
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        except OSError as e:  # pragma: no cover - defensive
            log.warning("could not read secret file %s: %s", path, e)
    return None


class _Adapter:
    """Base: a named source that yields a partial feed and never raises."""

    name = "adapter"

    def _fetch(self):  # pragma: no cover - overridden
        return {}

    def fetch(self):
        """Return a partial feed dict; swallow every failure into an empty dict."""
        start = time.monotonic()
        try:
            out = self._fetch() or {}
            log.debug("%s: ok in %.0fms", self.name, (time.monotonic() - start) * 1000)
            return out
        except Exception as e:  # noqa: BLE001 - fail-silent is the whole contract
            log.warning("%s: silent (%s: %s)", self.name, type(e).__name__, e)
            return {}


class StaticFileAdapter(_Adapter):
    """Reads a hand-editable / mock feed file already in merged shape.

    Doubles as (a) the deterministic mock the framework is tested against and
    (b) a real "source-swappable" backend if signals are ever produced by a
    sidecar writing JSON to a path the Atlas can read (ALIVE.md §0.4).
    """

    name = "static"

    def __init__(self, path):
        self.path = path

    def _fetch(self):
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        return _coerce_feed(raw)


class KumaAdapter(_Adapter):
    """Uptime-Kuma metrics/status → node & service states (ALIVE.md K1–K5).

    Live wiring lands in Wave 2 (needs a Kuma API key + monitors). Until then this
    adapter is exercised via StaticFileAdapter; when configured it makes a real,
    fully fail-silent HTTP call. It never imports at module load so a missing
    `requests` in some minimal image can't break the app.
    """

    name = "kuma"

    def __init__(self, url, api_key, monitor_map=None):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.monitor_map = monitor_map or {}

    def _fetch(self):
        import requests  # local import: optional dep, never at module load

        # Kuma's /metrics is Prometheus format behind HTTP Basic auth: the username
        # is ignored, the password is the API key (NOT a Bearer token).
        resp = requests.get(
            self.url + "/metrics",
            auth=("", self.api_key) if self.api_key else None,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return _parse_kuma_metrics(resp.text, self.monitor_map)


class DeceptionAdapter(_Adapter):
    """the decoy feed's `/api/stones` → which decoys are speaking.

    The engine owns the truth about its tripwires; the Atlas only draws it. So
    this is a read, on the same fail-silent contract as every other adapter: if
    the decoy feed is down, unreachable, or refuses the key, the map keeps its charted
    stones and simply shows none of them speaking.

    ⚠ That failure mode is genuinely ambiguous, and the scene has to be honest
    about it: "no stone is speaking" and "I cannot reach the engine that would
    tell me" look identical in the data. The `sources` block in the feed already
    distinguishes them — `deception: silent` means the adapter got nothing — and
    THE DECOYS scene (task 12) reads that rather than inferring calm from
    an empty dict. A deception layer that cannot say "I have lost contact" is
    exactly as useless as one that never fires.

    The feed carries no attacker-controlled text: `/api/stones` withholds memos,
    source addresses and raw payloads by design, so nothing an intruder wrote
    reaches a browser through this path.
    """

    name = "deception"

    def __init__(self, url, read_key, key_header=None):
        import envnames
        self.url = url.rstrip("/")
        self.read_key = read_key
        self.key_header = key_header or envnames.env("ATLAS_DECOYS_KEY_HEADER")

    def _fetch(self):
        if not self.read_key:
            # Not an exception — a configuration fact, and one worth saying out
            # loud, because the symptom (no stones speaking, ever) looks exactly
            # like a quiet realm.
            log.warning("deception: no ATLAS_DECOYS_KEY configured — the map "
                        "cannot read stone state and will show none speaking")
            return {}

        import requests  # local import: optional dep, never at module load

        resp = requests.get(
            self.url + "/api/stones",
            headers={self.key_header: self.read_key},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()
        if not isinstance(raw, dict):
            return {}

        # Reshape into the canonical feed. The two counts are realm-wide facts
        # with no marker of their own, so they ride as metrics: an unattributed
        # trip lights nothing on the map, which is precisely why its count has
        # to be visible somewhere.
        shaped = {"stones": raw.get("stones")}
        metrics = {}
        for key in ("unattributed_trips", "undelivered_alerts"):
            if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool):
                metrics[key] = raw[key]
        if metrics:
            shaped["metrics"] = metrics
        return _coerce_feed(shaped)


RELAY_MAX_AGE = 300.0  # 5 minutes: past this the relay is stale, not live


def _as_utc(dt):
    """SQLite hands back naive datetimes even for tz-aware columns."""
    from datetime import timezone as _tz
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_tz.utc)


def _latest_relay(site_slug):
    """(payload, age_seconds) of the newest relay snapshot, or (None, None).

    Imports the store lazily: file mode must keep working with no DB stack.
    """
    from datetime import datetime, timezone as _tz

    from sqlalchemy import select

    from store import session_scope
    from store.models import SignalSnapshot, Site

    with session_scope() as session:
        site = session.scalar(select(Site).where(Site.slug == site_slug))
        if site is None:
            return None, None
        row = session.scalar(
            select(SignalSnapshot)
            .where(SignalSnapshot.site_id == site.id)
            .order_by(SignalSnapshot.received_at.desc(), SignalSnapshot.id.desc())
            .limit(1)
        )
        if row is None:
            return None, None
        age = (datetime.now(_tz.utc) - _as_utc(row.received_at)).total_seconds()
        return row.payload_json, age


def relay_age_seconds(site_slug):
    """Age of the newest relay push, or None (never pushed / DB unreachable).
    Never raises — a status page must not die because a relay did."""
    try:
        _, age = _latest_relay(site_slug)
        return age
    except Exception as e:  # noqa: BLE001 - status must never fail
        log.warning("relay age unavailable: %s", e)
        return None


class RelayAdapter(_Adapter):
    """Signals pushed in by an on-prem `atlas-relay`.

    Same contract as every other source: a relay that stopped reporting goes
    silent and the map falls back to static, rather than showing stale health
    as though it were live.
    """

    name = "relay"

    def __init__(self, site_slug, max_age=RELAY_MAX_AGE):
        self.site_slug = site_slug
        self.max_age = max_age

    def _fetch(self):
        payload, age = _latest_relay(self.site_slug)
        if payload is None or age is None:
            return {}
        if age > self.max_age:
            log.warning("relay feed for %s is %.0fs old (>%.0fs) — treating as silent",
                        self.site_slug, age, self.max_age)
            return {}
        return _coerce_feed(payload)


class PrometheusAdapter(_Adapter):
    """Whitelisted PromQL → plaque numbers & sparklines (ALIVE.md P1/P2).

    Never a free-form proxy: only the queries in `_PROM_QUERIES` are ever issued.
    Live wiring is Wave 2 (needs one UDM rule the app host→the monitoring host:9090).
    """

    name = "prometheus"

    # label -> instant PromQL. Whitelist only; the client can never inject a query.
    _PROM_QUERIES = {
        "watchfires_up": "count(up == 1)",
        "watchfires_total": "count(up)",
    }
    # per-instance patch survey (weekly textfile collector, 2026-07-11)
    _PATCH_QUERIES = {
        "patches_pending": "apt_upgrades_pending",
        "patches_security": "apt_upgrades_security_pending",
        "reboot_required": "node_reboot_required",
        "patch_surveyed": "patch_survey_timestamp_seconds",
    }

    def __init__(self, url, ip_map=None):
        self.url = url.rstrip("/")
        self.ip_map = ip_map or {}   # "10.0.20.5" -> node id (set from the dataset)

    def _query(self, q):
        import requests
        r = requests.get(self.url + "/api/v1/query", params={"query": q}, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json().get("data", {}).get("result", [])

    def _fetch(self):
        metrics = {}
        for label, q in self._PROM_QUERIES.items():
            result = self._query(q)
            if result:
                metrics[label] = float(result[0]["value"][1])
        nodes = {}
        for key, q in self._PATCH_QUERIES.items():
            for r in self._query(q):
                ip = (r.get("metric", {}).get("instance") or "").split(":")[0]
                nid = self.ip_map.get(ip)
                if nid:
                    nodes.setdefault(nid, {})[key] = float(r["value"][1])
        out = {"metrics": metrics}
        if nodes:
            out["nodes"] = nodes
        return out


# Kuma monitor_status values → Atlas marker states (0 down · 1 up · 2 pending · 3 maint)
_KUMA_STATE = {0: DOWN, 1: HEALTHY, 2: DEGRADED, 3: "maintenance"}


#: When two monitors map to the SAME place, the worse state wins.
#:
#: This used to be last-writer-wins, which is only invisible while every place
#: has one monitor. The moment a second one is mapped — the domain controller has
#: both `DC LDAP` and `DC LDAPS`, the edge has both `Step CA` and `Edge` —
#: the marker showed whichever Kuma happened to emit last in its /metrics text.
#: A down monitor could be overwritten by a healthy one and the map would say
#: the place was fine. Ordering in that output is not something to rely on, and
#: "a place is healthy only if everything watching it is" is the answer that
#: cannot go wrong. `maintenance` outranks healthy so a place under a known
#: window still says so.
_STATE_RANK = {HEALTHY: 0, SLUMBERING: 1, "maintenance": 2, DEGRADED: 3, DOWN: 4}


def _worse(a, b):
    """The more alarming of two states — see _STATE_RANK."""
    if a is None:
        return b
    return b if _STATE_RANK.get(b, 0) > _STATE_RANK.get(a, 0) else a


def _parse_kuma_metrics(text, monitor_map):
    """Turn Kuma's Prometheus-format /metrics into node + service states.

    Mapped monitors (in monitor_map) → `nodes` under their node id (K1 marker states).
    Unmapped monitors → `services` keyed by monitor name (K4 per-service dots); a
    service link in the dataset opts into a dot via its own `kuma` field. With no
    map configured at all, every monitor is treated as a node (mock / name-match).

    Several monitors may point at one place; the place takes the worst of them.
    """
    nodes, services = {}, {}
    for line in text.splitlines():
        if not line.startswith("monitor_status{"):
            continue
        try:
            name = line.split('monitor_name="', 1)[1].split('"', 1)[0]
            value = int(float(line.rsplit(" ", 1)[1]))
        except (IndexError, ValueError):
            continue
        state = {"state": _KUMA_STATE.get(value, DOWN)}
        target = monitor_map.get(name)
        if target is not None:
            prior = (nodes.get(target) or {}).get("state")
            nodes[target] = {"state": _worse(prior, state["state"])}
        elif monitor_map:
            services[name] = state       # unmapped → per-service (keyed by monitor name)
        else:
            nodes[name] = state          # no map → name-match (mock / identity)
    out = {"nodes": nodes}
    if services:
        out["services"] = services
    return out


def _coerce_feed(raw):
    """Normalise an arbitrary payload into the canonical feed shape, dropping junk.

    Canonical shape (all keys optional):
        {"nodes": {id: {"state","uptime_30d",...}},
         "services": {id: {"state",...}},
         "stones": {id: {"state","last_spoke",...}},
         "metrics": {label: number}}
    """
    out = {}
    nodes = raw.get("nodes")
    if isinstance(nodes, dict):
        clean = {}
        for nid, info in nodes.items():
            if not isinstance(info, dict):
                continue
            state = info.get("state")
            entry = {k: v for k, v in info.items() if k != "state"}
            if state in _VALID_STATES:
                entry["state"] = state
            clean[nid] = entry
        out["nodes"] = clean
    services = raw.get("services")
    if isinstance(services, dict):
        out["services"] = {
            sid: info for sid, info in services.items() if isinstance(info, dict)
        }
    stones = raw.get("stones")
    if isinstance(stones, dict):
        clean = {}
        for sid, info in stones.items():
            if not isinstance(info, dict):
                continue
            state = info.get("state")
            entry = {k: v for k, v in info.items() if k != "state"}
            # Same rule as nodes: an unrecognised voice is DROPPED, not passed
            # through. The front-end swaps a CSS class on this value, so a junk
            # state would render an unstyled marker — a stone that is neither
            # visibly quiet nor visibly shouting, which is the worst of both.
            if state in _VALID_STONE_STATES:
                entry["state"] = state
            clean[sid] = entry
        out["stones"] = clean
    metrics = raw.get("metrics")
    if isinstance(metrics, dict):
        out["metrics"] = {
            k: v for k, v in metrics.items() if isinstance(v, (int, float))
        }
    return out


def _merge(feeds):
    """Deep-merge partial feeds. Later feeds win per-key (order = adapter priority)."""
    merged = {"nodes": {}, "services": {}, "stones": {}, "metrics": {}}
    for feed in feeds:
        for nid, info in feed.get("nodes", {}).items():
            merged["nodes"].setdefault(nid, {}).update(info)
        for sid, info in feed.get("services", {}).items():
            merged["services"].setdefault(sid, {}).update(info)
        for tid, info in feed.get("stones", {}).items():
            merged["stones"].setdefault(tid, {}).update(info)
        merged["metrics"].update(feed.get("metrics", {}))
    return merged


class SignalsHub:
    """Owns the enabled adapters; serves one merged, cached feed.

    Thread-safe within a worker. In-process cache (30s) means each gunicorn worker
    polls sources independently — deliberate: at 1 rack / a handful of monitors the
    extra hits are negligible and it keeps the design dependency-free (no Redis).
    """

    def __init__(self, adapters=None, ttl=30.0, factory=None):
        """`adapters` fixes the set for good (tests, static). `factory` builds
        it and REBUILDS it whenever THE SOURCES settings file moves
        (`integrations.stamp()`, v1.37.0) — so a save in one gunicorn worker
        reaches every worker on its next poll, with no restart."""
        self._factory = factory
        self._stamp = None
        if factory is not None:
            self._refresh_adapters(force=True)
        else:
            self.adapters = list(adapters or [])
        self.ttl = ttl
        self._lock = threading.Lock()
        self._cache = None
        self._cache_at = 0.0

    def _refresh_adapters(self, force=False):
        """Rebuild from the factory when the settings file has changed."""
        if self._factory is None:
            return False
        import integrations
        now = integrations.stamp()
        if not force and now == self._stamp:
            return False
        self._stamp = now
        self.adapters = list(self._factory())
        self._cache = None
        return True

    @property
    def enabled(self):
        return [a.name for a in self.adapters]

    def _build(self):
        feeds, sources = [], {}
        for a in self.adapters:
            partial = a.fetch()
            feeds.append(partial)
            sources[a.name] = "ok" if partial else "silent"
        merged = _merge(feeds)
        merged["sources"] = sources
        merged["generated"] = time.time()
        try:
            import metrics
            metrics.record_sources(sources)   # the Atlas's own watchfire (v1.38.0)
        except Exception:  # noqa: BLE001 — bookkeeping never stalls the feed
            pass
        return merged

    def feed(self):
        """Return the merged feed, rebuilding at most once per TTL. Never raises."""
        now = time.monotonic()
        with self._lock:
            try:
                self._refresh_adapters()   # THE SOURCES changed? new adapters, cache dropped
            except Exception as e:  # noqa: BLE001 — never let a settings hiccup stall the feed
                log.warning("signals: could not refresh adapters: %s", e)
            if self._cache is not None and (now - self._cache_at) < self.ttl:
                cached = dict(self._cache)
                cached["cached"] = True
                return cached
            try:
                built = self._build()
            except Exception as e:  # noqa: BLE001 - the hub must never raise either
                log.error("signals build failed, serving empty feed: %s", e)
                built = {"nodes": {}, "services": {}, "stones": {}, "metrics": {},
                         "sources": {a.name: "silent" for a in self.adapters},
                         "generated": time.time()}
            self._cache, self._cache_at = built, now
            fresh = dict(built)
            fresh["cached"] = False
            return fresh


def make_adapters():
    """The adapters THE SOURCES currently name (`integrations`: the settings
    file first, ATLAS_SIGNALS_* env second). Empty = degraded (no live data)."""
    import integrations
    adapters = []
    for name in integrations.enabled_sources():
        if name == "static":
            adapters.append(StaticFileAdapter(
                os.environ.get("ATLAS_SIGNALS_FILE", "/data/signals.json")))
        elif name == "kuma":
            url = integrations.get("ATLAS_KUMA_URL")
            if url:
                adapters.append(KumaAdapter(url, _read_secret("ATLAS_KUMA_API_KEY")))
            else:
                log.warning("kuma source requested but ATLAS_KUMA_URL unset — skipping")
        elif name == "relay":
            adapters.append(RelayAdapter(settings.SITE_SLUG))
        elif name == "deception":
            url = integrations.get("ATLAS_DECOYS_URL")
            if url:
                adapters.append(DeceptionAdapter(
                    url, _read_secret("ATLAS_DECOYS_KEY")))
            else:
                log.warning("deception source requested but ATLAS_DECOYS_URL "
                            "unset — skipping")
        elif name == "prometheus":
            url = integrations.get("ATLAS_PROM_URL")
            if url:
                adapters.append(PrometheusAdapter(url))   # ip_map pushed by app._apply_kuma_map
            else:
                log.warning("prometheus source requested but ATLAS_PROM_URL unset — skipping")
        else:
            log.warning("unknown signals source %r — ignoring", name)
    log.info("signals: %d source(s) enabled: %s", len(adapters),
             ", ".join(a.name for a in adapters) or "(none — static/degraded map)")
    return adapters


def build_hub_from_env():
    """The app's hub: built from THE SOURCES now, and self-rebuilding when the
    settings file changes (the name is kept — app.py and the tests call it)."""
    return SignalsHub(factory=make_adapters)
