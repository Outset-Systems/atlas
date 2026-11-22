import logging
import os
import threading
import time

import settings

from engines.base import (
    DEGRADED, DOWN, HEALTHY, MAINTENANCE, NODE_STATES, STONE_STATES, _Adapter, _TIMEOUT,
    _VALID_STATES, _VALID_STONE_STATES, _coerce_feed, _read_secret, monitor_map,
)
from engines.checks import (
    ChecksAdapter, _check_url, _checks_adapter,
)
from engines.deception import DeceptionAdapter, _deception_adapter
from engines.demo import DemoFeedAdapter
from engines.kuma import (
    KumaAdapter, _KUMA_STATE, _kuma_adapter, _parse_kuma_metrics,
)
from engines.places import (
    service_key, service_places, services_of, unmanaged_ids, unmanaged_service_keys,
)
from engines.prometheus import PrometheusAdapter, _prometheus_adapter
import engines.authority as authority
from engines.registry import builders as _registered_builders, find as _registered
from engines.relay import (
    RELAY_MAX_AGE, RelayAdapter, relay_age_seconds,
)
import engines.runtime as runtime
from engines.static import StaticFileAdapter
from engines.unifi import (
    UniFiAdapter, _unifi_adapter, unifi_places,
)

log = logging.getLogger("atlas.live.signals")


def demo_feed_path():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo-signals.json")
    return path if os.path.isfile(path) else None


_merge = authority.merge


_map_log = logging.getLogger("atlas.api.v2")


def push_map(adapters, data):
    for adapter in adapters:
        use_map = getattr(adapter, "use_map", None)
        if use_map is not None:
            try:
                use_map(data)
            except Exception as e:
                _map_log.warning("signals: %s could not read the map (%s: %s)",
                                 getattr(adapter, "name", "a source"), type(e).__name__, e)


class SignalsHub:

    def __init__(self, adapters=None, ttl=30.0, factory=None):
        self._factory = factory
        self._stamp = None
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
        return self._refresh_adapters()

    def last_sources(self):
        feed = self._cache or {}
        return dict(feed.get("sources") or {})

    def last_ok(self):
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
                self._last_ok[a.name] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        merged = _merge(feeds, names)
        merged["sources"] = sources
        merged["sources_at"] = self._sources_at()
        merged["generated"] = time.time()
        try:
            import metrics
            metrics.record_sources(sources)
        except Exception:
            pass
        return merged

    def feed(self):
        now = time.monotonic()
        with self._lock:
            try:
                self._refresh_adapters()
            except Exception as e:
                log.warning("signals: could not refresh adapters: %s", e)
            if self._cache is not None and (now - self._cache_at) < self.ttl:
                cached = dict(self._cache)
                cached["cached"] = True
                return cached
            try:
                built = self._build()
            except Exception as e:
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


_BUILDERS = _registered_builders()


def _handed(name):
    if name == "static":
        return os.environ.get("ATLAS_SIGNALS_FILE", "/data/signals.json")
    if name == "relay":
        return settings.SITE_SLUG
    return None


def _build(source, integrations):
    if source.needs is None:
        return source.build(_handed(source.name))
    url = integrations.get(source.needs)
    if not url:
        log.warning("%s source requested but %s unset — skipping", source.name, source.needs)
        return None
    return source.build(url)


def make_adapters():
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
            log.warning("unknown signals source %r — ignoring", name)
            continue
        try:
            adapter = _build(source, integrations)
        except Exception as e:
            if not source.guarded:
                raise
            log.warning("unifi source could not be built (%s) — skipping", type(e).__name__)
            adapter = None
        if adapter is not None:
            adapters.append(adapter)
    log.info("signals: %d source(s) enabled: %s", len(adapters),
             ", ".join(a.name for a in adapters) or "(none — static/degraded map)")
    return adapters


def build_hub_from_env():
    return SignalsHub(factory=make_adapters)
