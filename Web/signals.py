"""Live-signals layer for the Atlas — the glass over Kuma/Prometheus, never the engine.

Principle: *the map never dies with its sources.* Every adapter here
is built to fail silent — a timeout, a 500, a bad payload, a missing key all resolve to
"no signal" (an empty dict), never to an exception that could break the render. The
front-end treats an absent feed as the v1.0.0 static behaviour ("the watchers are silent").

Architecture: one small adapter per source, each exposing `fetch() -> dict`
with a hard 3s timeout and a guarantee never to raise. Each is a module in `engines/`
(2026-11-16) and is imported back here, so `signals.KumaAdapter` and the rest read as
before. `SignalsHub` merges the enabled adapters into one cached feed (30s TTL) that
`/api/v2/signals` serves and the front-end polls.

Sources are chosen in the settings file first (`integrations.py`), then by
env, so going live is config-only:

    ATLAS_SIGNALS_SOURCES   comma list: "static", "kuma", "prometheus", "unifi",
                            "checks", "relay", "deception" (default: "" = none)
    ATLAS_SIGNALS_FILE      static/mock feed path (default /data/signals.json)
    ATLAS_SITE              site slug the "relay" source reads (default "default")
    ATLAS_KUMA_URL          e.g. http://edge:3001
    ATLAS_KUMA_API_KEY      Kuma API key  (or ATLAS_KUMA_API_KEY_FILE -> docker secret)
    ATLAS_PROM_URL          e.g. http://monitor:9090
    ATLAS_UNIFI_URL         the UniFi connection's own address and credential
                            (Settings → Connections); the "unifi" source reads them
    ATLAS_DECOYS_URL       e.g. http://decoys:5013
    ATLAS_DECOYS_KEY       the decoy feed's read key (or ATLAS_DECOYS_KEY_FILE -> docker secret)
    ATLAS_DECOYS_PATH      where it serves its roster (default /api/stones)

Secrets come from env or a *_FILE docker-secret path — never the dataset, never the client.
"""

import logging
import os
import threading
import time

import settings

# The adapters and what they share live in `engines/`. Every name below is
# still read as `signals.<name>` by the app, the relay and the tests.
from engines.base import (  # noqa: F401
    DEGRADED, DOWN, HEALTHY, MAINTENANCE, NODE_STATES, SILENT, SLUMBERING, SPEAKING,
    STIRRED, STONE_STATES, _Adapter, _STATE_RANK, _TIMEOUT, _VALID_STATES,
    _VALID_STONE_STATES, _coerce_feed, _read_secret, _states_only, _worse, monitor_map,
)
from engines.checks import (  # noqa: F401
    CHECKS_BUDGET, CHECKS_FRESH, CHECKS_MAX_AGE, ChecksAdapter, _check_url, _checks_adapter,
)
from engines.deception import DeceptionAdapter, _deception_adapter  # noqa: F401
from engines.demo import DemoFeedAdapter  # noqa: F401
from engines.kuma import (  # noqa: F401
    KumaAdapter, _KUMA_STATE, _kuma_adapter, _parse_kuma_metrics,
)
from engines.prometheus import PrometheusAdapter, _prometheus_adapter, ip_map  # noqa: F401
import engines.authority as authority
from engines.registry import builders as _registered_builders, find as _registered
from engines.relay import (  # noqa: F401
    RELAY_MAX_AGE, RelayAdapter, _as_utc, _latest_relay, relay_age_seconds,
)
import engines.runtime as runtime  # noqa: F401  # the HTTP sources' one call
from engines.static import StaticFileAdapter  # noqa: F401
from engines.unifi import (  # noqa: F401
    UniFiAdapter, _UNIFI_GATEWAYS, _unifi_adapter, unifi_places,
)

log = logging.getLogger("atlas.live.signals")


def demo_feed_path():
    """The demo feed the public image bundles, or None (the private tree has none)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo-signals.json")
    return path if os.path.isfile(path) else None


def service_key(node_id, link):
    """The feed key of one service link: the Kuma monitor it names, else
    `<place id>/<label>`. The page computes the same key (`svcKey` in
    config.js), which is how a built-in check finds its dot."""
    monitor = link.get("kuma")
    if isinstance(monitor, str) and monitor:
        return monitor
    # a hand edit's list or number names no monitor: the place's own key (round 15)
    label = link.get("label")
    return f"{node_id}/{label if isinstance(label, str) else ''}"


def _merge(feeds, names=None):
    """Deep-merge partial feeds. Later feeds win per-key (order = adapter priority:
    `engines/authority.py` holds the rule, 2026-11-16).

    With `names` (one adapter name per feed), the merged feed also says which
    adapter supplied each place's state: `confirmed_by` = {place id: name}
    (2026-11-13, for the places table). Only an entry that carries a `state`
    counts, so an adapter that adds another key to a place does not take the
    credit for its state. In memory only: nothing stores it.
    """
    merged = {"nodes": {}, "services": {}, "stones": {}, "metrics": {}}
    confirmed = {}
    for i, feed in enumerate(feeds):
        for nid, info in feed.get("nodes", {}).items():
            merged["nodes"].setdefault(nid, {}).update(info)
            if names is not None and authority.gives_state(info):
                confirmed[nid] = names[i]
        for sid, info in feed.get("services", {}).items():
            merged["services"].setdefault(sid, {}).update(info)
        for tid, info in feed.get("stones", {}).items():
            merged["stones"].setdefault(tid, {}).update(info)
        merged["metrics"].update(feed.get("metrics", {}))
    if names is not None:
        merged["confirmed_by"] = confirmed
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
        # {adapter name: when its fetch last came back with something, UTC}.
        # Keyed by name, not by adapter, so it outlives a rebuild of the set.
        self._last_ok = {}
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

    def reload(self):
        """Rebuild now if the settings file has moved, without waiting for the
        next poll. Says whether it did."""
        return self._refresh_adapters()

    def last_sources(self):
        """How each source answered the last time the feed was built
        ({name: "ok" or "silent"}), or {} before the first build."""
        feed = self._cache or {}
        return dict(feed.get("sources") or {})

    def last_ok(self):
        """When each source last answered with something ({name: UTC stamp}),
        in this worker, since it started. A source that has not answered here
        yet is absent. In memory only, like `last_sources`: nothing stores it,
        and each gunicorn worker keeps its own (2026-11-13, for OVERVIEW)."""
        return dict(self._last_ok)

    def _sources_at(self):
        return {a.name: self._last_ok.get(a.name) for a in self.adapters}

    @property
    def enabled(self):
        return [a.name for a in self.adapters]

    def _build(self):
        feeds, sources, names = [], {}, []
        for a in self.adapters:
            partial = a.fetch()
            feeds.append(partial)
            names.append(a.name)
            sources[a.name] = "ok" if partial else "silent"
            if partial:
                # `jsonio.iso_utc`'s spelling, written out: a relay box imports
                # this module with nothing beside the standard library and settings
                self._last_ok[a.name] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        merged = _merge(feeds, names)
        merged["sources"] = sources
        # beside `sources`, whose shape stays {name: "ok"|"silent"}: when each
        # one last answered in this worker, null if it has not yet
        merged["sources_at"] = self._sources_at()
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
                         "confirmed_by": {},
                         "sources": {a.name: "silent" for a in self.adapters},
                         "sources_at": self._sources_at(),
                         "generated": time.time()}
            self._cache, self._cache_at = built, now
            fresh = dict(built)
            fresh["cached"] = False
            return fresh


#: The sources that ask a system themselves: source -> builder(url). Read
#: from the registry (`engines/registry.py`, 2026-11-16), where each source
#: declares itself once: its builder, the setting that holds its URL (also
#: `integrations.SOURCE_NEEDS`; `checks` needs none) and the rest. What each
#: adapter needs from the dataset is pushed later, by
#: `api.v2.feeds._apply_kuma_map`.
_BUILDERS = _registered_builders()


def _handed(name):
    """What a source that needs no setting is built from: the feed file for
    `static`, this site for `relay`, nothing for the rest (`checks`)."""
    if name == "static":
        return os.environ.get("ATLAS_SIGNALS_FILE", "/data/signals.json")
    if name == "relay":
        return settings.SITE_SLUG
    return None


def _build(source, integrations):
    """The adapter for one listed source, or None (said in the log) when the
    setting it needs is unset."""
    if source.needs is None:
        return source.build(_handed(source.name))   # a source with no address of its own
    url = integrations.get(source.needs)
    if not url:
        log.warning("%s source requested but %s unset — skipping", source.name, source.needs)
        return None
    return source.build(url)


def make_adapters():
    """The adapters THE SOURCES currently name (`integrations`: the settings
    file first, ATLAS_SIGNALS_* env second). Empty = degraded (no live data)."""
    import integrations
    adapters = []
    names = integrations.enabled_sources()
    if not names and settings.FALLBACK == "bundled" and settings.DATA_BACKEND == "file":
        demo = demo_feed_path()
        if demo:
            adapters.append(DemoFeedAdapter(demo, settings.DATA_PATH))
    for name in names:
        source = _registered(name)
        if source is None or not source.listed:
            # `demo` too: the hub adds it by itself, above, and nobody lists it
            log.warning("unknown signals source %r — ignoring", name)
            continue
        try:
            adapter = _build(source, integrations)
        except Exception as e:  # noqa: BLE001 — a source that cannot be built is skipped, never fatal
            if name != "unifi":
                raise                  # only the unifi build is guarded
            log.warning("unifi source could not be built (%s) — skipping", type(e).__name__)
            adapter = None
        if adapter is not None:
            adapters.append(adapter)
    log.info("signals: %d source(s) enabled: %s", len(adapters),
             ", ".join(a.name for a in adapters) or "(none — static/degraded map)")
    return adapters


def build_hub_from_env():
    """The app's hub: built from THE SOURCES now, and self-rebuilding when the
    settings file changes (the name is kept — app.py and the tests call it)."""
    return SignalsHub(factory=make_adapters)


# ── UNMANAGED (2026-11-14, the owner's Q4 answer) ────────────────────────────
def unmanaged_ids(data):
    """The places not ours to watch: marked `unmanaged: true` themselves, or
    in a collection marked so. Only `True` counts (a hand edit's "yes" is not)."""
    import schema
    data = data if isinstance(data, dict) else {}
    nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    out = {n["id"] for n in nodes
           if isinstance(n, dict) and isinstance(n.get("id"), str) and n.get("unmanaged") is True}
    listed = data.get("collections")
    for c in listed if isinstance(listed, list) else []:
        if isinstance(c, dict) and c.get("unmanaged") is True:
            out.update(p for p in schema.as_list(c.get("places")) if isinstance(p, str) and p)
    return out


def services_of(data, place_ids):
    """The service keys (monitor names, or `<place>/<label>`) the feed files
    under these places: a place's own links and the monitors charted on it."""
    if not place_ids or not isinstance(data, dict):
        return set()
    out = {m for m, pid in monitor_map(data).items() if pid in place_ids}
    for node in data.get("nodes") if isinstance(data.get("nodes"), list) else []:
        if isinstance(node, dict) and node.get("id") in place_ids:
            for link in node.get("links") if isinstance(node.get("links"), list) else []:
                if isinstance(link, dict):
                    out.add(service_key(node["id"], link))
    return out


# ── SERVICES AS WATCHED THINGS (2026-11-15, stage 3b) ────────────────────────
def service_places(data):
    """{service key: place id} for every service link on the map: the key the
    feed files it under (`service_key`). Two links naming one monitor share
    a key, and the first place keeps it."""
    out = {}
    data = data if isinstance(data, dict) else {}
    for node in data.get("nodes") if isinstance(data.get("nodes"), list) else []:
        if not (isinstance(node, dict) and isinstance(node.get("id"), str)):
            continue
        for link in node.get("links") if isinstance(node.get("links"), list) else []:
            if isinstance(link, dict):
                out.setdefault(service_key(node["id"], link), node["id"])
    return out


def unmanaged_service_keys(data):
    """The services not ours to watch on their own: a link marked
    `unmanaged: true`, or a service in a collection marked so. (A service on
    an unmanaged place goes with it: `services_of`.)"""
    import schema
    out = set()
    data = data if isinstance(data, dict) else {}
    for node in data.get("nodes") if isinstance(data.get("nodes"), list) else []:
        if not (isinstance(node, dict) and isinstance(node.get("id"), str)):
            continue
        for link in node.get("links") if isinstance(node.get("links"), list) else []:
            if isinstance(link, dict) and link.get("unmanaged") is True:
                out.add(service_key(node["id"], link))
    listed = data.get("collections")
    for c in listed if isinstance(listed, list) else []:
        if isinstance(c, dict) and c.get("unmanaged") is True:
            out.update(k for k in schema.as_list(c.get("services")) if isinstance(k, str) and k)
    return out
