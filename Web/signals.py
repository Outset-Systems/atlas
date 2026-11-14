"""Live-signals layer for the Atlas — the glass over Kuma/Prometheus, never the engine.

Principle: *the map never dies with its sources.* Every adapter here
is built to fail silent — a timeout, a 500, a bad payload, a missing key all resolve to
"no signal" (an empty dict), never to an exception that could break the render. The
front-end treats an absent feed as the v1.0.0 static behaviour ("the watchers are silent").

Architecture: one small adapter per source, each exposing `fetch() -> dict`
with a hard 3s timeout and a guarantee never to raise. `SignalsHub` merges the enabled
adapters into one cached feed (30s TTL) that `/api/v2/signals` serves and the front-end polls.

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
MAINTENANCE = "maintenance"  # planned quiet — Kuma's own state 3
#: Every marker state. `events` and the feed coercion below read this one set.
NODE_STATES = frozenset((HEALTHY, DEGRADED, DOWN, SLUMBERING, MAINTENANCE))
_VALID_STATES = NODE_STATES

# ── decoy voices (the decoy feed) ─────────────────────────────────────────────
# A DIFFERENT vocabulary from the marker states above, on purpose. A stone is
# not up or down — it is quiet, or it has been disturbed, or it is speaking
# right now. Reusing `healthy`/`down` here would say something false: a silent
# stone is not "healthy", it is unvisited, which is the ordinary state and the
# one we hope for.
SILENT = "silent"        # nothing has touched it
STIRRED = "stirred"      # touched recently, below the escalation line
SPEAKING = "speaking"    # a live trip — the one time the quiet map raises its voice
#: Every decoy voice. `tripwires` reads this one set too.
STONE_STATES = frozenset((SILENT, STIRRED, SPEAKING))
_VALID_STONE_STATES = STONE_STATES

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
    return envnames.secret(name) or None


class _Adapter:
    """Base: a named source that yields a partial feed and never raises."""

    name = "adapter"

    def use_map(self, data):
        """Take what this source needs from the dataset. Called with the
        dataset before each feed read; most sources need nothing from it."""

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
    sidecar writing JSON to a path the Atlas can read.
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


class DemoFeedAdapter(StaticFileAdapter):
    """The bundled demo's own status feed, for a first look that moves.

    Only `make_adapters` adds it: no source configured, ATLAS_FALLBACK=bundled,
    and an image that ships `demo-signals.json` beside the code. It goes silent
    the moment the instance is seeded with a real dataset, so a first save never
    leaves the demo's states painted over someone's own map. Adapters are only
    rebuilt when the settings file changes, hence the check on every fetch.
    """

    name = "demo"

    def __init__(self, path, data_path):
        super().__init__(path)
        self.data_path = data_path

    def _fetch(self):
        if os.path.exists(self.data_path):
            return {}
        return super()._fetch()


def demo_feed_path():
    """The demo feed the public image bundles, or None (the private tree has none)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo-signals.json")
    return path if os.path.isfile(path) else None


class KumaAdapter(_Adapter):
    """Uptime-Kuma metrics/status → node & service states.

    Live (the wiring was Wave 2): given a Kuma URL and an API key it makes a
    real, fully fail-silent HTTP call. It never imports at module load so a
    missing `requests` in some minimal image can't break the app.
    """

    name = "kuma"

    def __init__(self, url, api_key, monitor_map=None, verify=True):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.monitor_map = monitor_map or {}
        self.verify = verify

    def use_map(self, data):
        self.monitor_map = monitor_map(data)

    def _fetch(self):
        import requests  # local import: optional dep, never at module load

        # Kuma's /metrics is Prometheus format behind HTTP Basic auth: the username
        # is ignored, the password is the API key (NOT a Bearer token).
        resp = requests.get(
            self.url + "/metrics",
            auth=("", self.api_key) if self.api_key else None,
            timeout=_TIMEOUT,
            verify=self.verify,
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

    def __init__(self, url, read_key):
        import envnames
        self.url = url.rstrip("/")
        self.read_key = read_key
        self.key_header = envnames.env("ATLAS_DECOYS_KEY_HEADER")
        import integrations
        # TRIPWIRES: one source among several, and its roster path is the
        # operator's (ATLAS_DECOYS_PATH, default /api/stones).
        self.path = integrations.decoys_path()

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
            self.url + self.path,
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

    def __init__(self, site_slug):
        self.site_slug = site_slug
        self.max_age = RELAY_MAX_AGE

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
    """Whitelisted PromQL → plaque numbers & sparklines.

    Never a free-form proxy: only the queries in `_PROM_QUERIES` and
    `_PATCH_QUERIES` are ever issued. Live (the wiring was Wave 2); it needs
    only a route from the app to the Prometheus address.
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

    def __init__(self, url):
        self.url = url.rstrip("/")
        self.ip_map = {}   # "10.0.20.5" -> node id (set from the dataset)

    def use_map(self, data):
        self.ip_map = ip_map(data)

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


#: UniFi device types that are a gateway: their `ip` is the WAN address.
_UNIFI_GATEWAYS = ("ugw", "udm", "uxg")


class UniFiAdapter(_Adapter):
    """A UniFi Network controller's "connected now" → marker states, for charted
    places nothing else watches.

    Three rules keep it honest:

    * Only a charted place is ever reported. The place maps come from the
      dataset (`unifi_places`, pushed by `api.v2.feeds._apply_kuma_map`), and a
      client that is on no map leaves no trace in the feed: not its address,
      not its name, not a count.
    * Absent is unknown, never down. The client list is "connected now", so a
      laptop asleep is simply not in it; reporting that as an outage would fill
      the annals with fiction. Only a UniFi device the controller itself lists
      as disconnected (`state` 0) is `down`, and only when the place is known
      by that device's MAC: an address may have passed to something else, and
      a device that is upgrading or adopting is not an outage.
    * Kuma is the authority where it watches. A place with a monitor tied to it
      is left alone, so the two sources never argue over one marker.

    One controller session per fetch: open, read the two lists, close.
    """

    name = "unifi"

    def __init__(self, url, creds, verify=True):
        self.url = url.rstrip("/")
        self.creds = list(creds)          # [site, api key, user, password]
        self.verify = verify
        self._places = ({}, {}, frozenset())
        self._site = None                 # the resolved site, looked up once

    def set_places(self, by_mac, by_ip, watched):
        """{mac: node id}, {ip: node id} and the node ids Kuma already watches."""
        self._places = (dict(by_mac or {}), dict(by_ip or {}), frozenset(watched or ()))

    def use_map(self, data):
        self.set_places(*unifi_places(data))

    def _fetch(self):
        by_mac, by_ip, watched = self._places
        if not (by_mac or by_ip):
            return {}                     # nothing charted to report on: do not ask
        from importers import unifi       # local import: needs `requests`, never at module load

        conn = unifi.Controller(self.url, self.creds, self.verify)   # a user session logs in here
        try:
            if self._site is None:
                site, _ = unifi._site(conn, self.creds[0])
                unifi.site_path(site)     # a site is one path segment, or it is refused
                self._site = site
            base = f"/api/s/{self._site}"
            devices = conn.get(f"{base}/stat/device") or []
            try:
                clients = conn.get(f"{base}/stat/sta") or []
            except Exception as e:  # noqa: BLE001 — the devices still stand; absent is unknown
                log.warning("unifi: no client list this poll (%s)", type(e).__name__)
                clients = []
        finally:
            conn.close()

        states = {}

        def seen(mac, ip, state):
            # MAC first, then address — and one thing lights one place only
            nid = by_mac.get(unifi._mac(mac))
            if nid is None and state == HEALTHY:
                nid = by_ip.get(str(ip or "").strip())
            if nid is None or nid in watched:
                return
            states[nid] = _worse(states.get(nid), state)

        for d in devices:
            if not isinstance(d, dict):
                continue
            ip = d.get("ip")
            if d.get("type") in _UNIFI_GATEWAYS:
                ip = unifi._gateway_addresses(d, [])[0]   # its LAN address, not the WAN one
            if d.get("state") in (0, 1):               # anything else is mid-change: say nothing
                seen(d.get("mac"), ip, HEALTHY if d.get("state") == 1 else DOWN)
        for c in clients:
            if isinstance(c, dict):
                seen(c.get("mac"), c.get("ip"), HEALTHY)
        return {"nodes": {nid: {"state": state} for nid, state in states.items()}}


#: The built-in checks' limits: how many charted addresses one round asks, how
#: many at once, how long the whole round may take, how long a stored round is
#: served before a new one, and the age past which a stored round is not served.
CHECKS_MAX_TARGETS = 200
CHECKS_WORKERS = 8
CHECKS_BUDGET = 8.0
CHECKS_FRESH = 60.0
CHECKS_MAX_AGE = 300.0
CHECKS_FILE = "checks.json"


def service_key(node_id, link):
    """The feed key of one service link: the Kuma monitor it names, else
    `<place id>/<label>`. The page computes the same key (`svcKey` in
    config.js), which is how a built-in check finds its dot."""
    return link.get("kuma") or f"{node_id}/{link.get('label') or ''}"


def _check_url(value):
    """The address a built-in check asks for a charted URL, or None when the URL
    is not an absolute http(s) one with a host. Any `user:pass@` and the query
    string are left off: a check sends no credentials, and a key charted as
    `?token=` is one. The path is kept, because a service may only answer at
    the page that was charted."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw.lower().startswith(("http://", "https://")):
        return None
    import redaction                      # local import: it needs the web stack
    from urllib.parse import urlsplit
    url = redaction.bare_url(raw)         # scheme, host, port and path only
    try:
        if not urlsplit(url).hostname:
            return None
    except ValueError:
        return None
    return url


def _check_one(url):
    """Ask one charted address once: (state, milliseconds).

    Any answer below 500 is `healthy`: a sign-in wall or a redirect still means
    the service is up. 500 and above is `degraded`. No connection, or no answer
    in time, is `down`. Anything else that stops the request (an address that
    cannot be asked at all) is no state: it says nothing about the service.

    The certificate is not verified on purpose: a service with a self-signed
    certificate is still up, and the request carries no credentials to protect.
    The body is never read and no redirect is followed.
    """
    import requests  # local import: optional dep, never at module load

    start = time.monotonic()
    resp, state = None, None
    try:
        resp = requests.get(url, timeout=_TIMEOUT, allow_redirects=False, verify=False,
                            stream=True, headers={"User-Agent": "Atlas-check"})
        state = HEALTHY if resp.status_code < 500 else DEGRADED
    except (requests.ConnectionError, requests.Timeout):
        state = DOWN
    except Exception as e:  # noqa: BLE001 - one bad address never stops the round
        log.debug("checks: one address could not be asked (%s)", type(e).__name__)
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001 - closing is a courtesy
                pass
    return state, int(round((time.monotonic() - start) * 1000))


class ChecksAdapter(_Adapter):
    """Built-in checks: does each charted service URL answer?

    A fallback for an install with no monitoring of its own, and deliberately
    small. Three rules keep it inside what the map promises:

    * Only a charted address is ever asked: the `url` of a service link on a
      place. Nothing is discovered, no port is tried, no range is walked.
    * Kuma is the authority where it watches. A link that names a monitor is
      not asked, and a place a monitor is mapped to gets no marker state here.
    * No answer inside the round's budget is unknown, never down.

    Two gunicorn workers share one stored round (`checks.json` beside the
    dataset) and a lock, so the charted addresses are asked once a minute and
    not once per worker.
    """

    name = "checks"

    def __init__(self, path=None, budget=CHECKS_BUDGET, fresh=CHECKS_FRESH,
                 max_age=CHECKS_MAX_AGE):
        self.path = path                  # None = beside the dataset, read at each fetch
        self.budget = budget
        self.fresh = fresh
        self.max_age = max_age
        self._data = None                 # the dataset, once the feed has handed it over
        self._over = 0                    # the target count the cap was last logged for

    def use_map(self, data):
        # called before every feed read, cached ones too: keep it, work it out later
        self._data = data

    @staticmethod
    def _targets(data):
        """[(key, place id, address)] for every link a check may ask."""
        out, seen = [], set()
        for node in data.get("nodes") or []:
            if not isinstance(node, dict) or not node.get("id") or node.get("planned"):
                continue
            for link in node.get("links") or []:
                if not isinstance(link, dict) or link.get("planned") or link.get("kuma"):
                    continue
                url = _check_url(link.get("url"))
                key = service_key(node["id"], link)
                if url and key not in seen:
                    seen.add(key)
                    out.append((key, node["id"], url))
        return out

    def _stored(self, path):
        """(the stored round, its age in seconds), or (None, None) when there is
        none that can be read."""
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            age = time.time() - float(raw["at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None, None
        if age < 0:                       # written by a clock that has since gone back
            return None, None
        feed = _coerce_feed(raw)
        return {"services": feed.get("services", {}), "nodes": feed.get("nodes", {})}, age

    @staticmethod
    def _charted(result, targets, watched):
        """A stored round cut to what the map charts now: a link removed, or a
        place a monitor was tied to since the round, is no longer reported."""
        keys = {key for key, _, _ in targets}
        places = {nid for _, nid, _ in targets} - watched
        return {"services": {k: v for k, v in result["services"].items() if k in keys},
                "nodes": {k: v for k, v in result["nodes"].items() if k in places}}

    def _probe(self, targets, watched):
        """Ask every target once, in a small pool, inside the budget."""
        import warnings
        from concurrent.futures import ThreadPoolExecutor, wait

        import requests  # noqa: F401 - fail here, once, when it is missing
        from urllib3.exceptions import InsecureRequestWarning

        if len(targets) > CHECKS_MAX_TARGETS:
            if self._over != len(targets):
                self._over = len(targets)
                log.warning("checks: %d service addresses are charted; asking the first %d",
                            len(targets), CHECKS_MAX_TARGETS)
            targets = targets[:CHECKS_MAX_TARGETS]

        # Start somewhere else each round. With a fixed order, a run of addresses
        # that time out at the head of the list spends the whole budget every
        # time and the ones behind them are never asked.
        start = int(time.time() // max(self.fresh, 1)) % len(targets)
        targets = targets[start:] + targets[:start]
        pool = ThreadPoolExecutor(max_workers=CHECKS_WORKERS, thread_name_prefix="atlas-check")
        try:
            # Not verifying a certificate makes urllib3 warn on every request.
            # The filter is set here, in the calling thread, and only while the
            # round runs, so every other request in the app keeps its warning.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                asked = {pool.submit(_check_one, url): key for key, _, url in targets}
                done, _ = wait(asked, timeout=self.budget)
        finally:
            # never wait for a slow address: what has not answered is unknown
            pool.shutdown(wait=False, cancel_futures=True)

        services = {}
        for future in done:
            try:
                state, ms = future.result()
            except Exception:  # noqa: BLE001 - a check that broke says nothing
                continue
            if state:
                services[asked[future]] = {"state": state, "ms": ms}

        answered = {}
        for key, nid, _ in targets:
            if key in services and nid not in watched:
                answered.setdefault(nid, []).append(services[key]["state"])
        nodes = {}
        for nid, states in answered.items():
            if all(s == HEALTHY for s in states):
                nodes[nid] = {"state": HEALTHY}
            elif all(s == DOWN for s in states):
                nodes[nid] = {"state": DOWN}
            else:
                nodes[nid] = {"state": DEGRADED}
        return {"services": services, "nodes": nodes}

    def _fetch(self):
        data = self._data
        if not isinstance(data, dict):
            return {}                     # no dataset yet: nothing to say, nothing to store
        targets = self._targets(data)
        if not targets:
            return {"nodes": {}}          # it ran, and the map charts nothing to ask
        watched = {nid for nid in monitor_map(data).values() if nid}
        path = self.path or os.path.join(settings.DATA_DIR, CHECKS_FILE)

        stored, age = self._stored(path)
        if stored is not None and age < self.fresh:
            return self._charted(stored, targets, watched)

        import filelock
        import jsonio
        try:
            with filelock.exclusive(filelock.lock_for(path), timeout=0):
                # another worker may have finished a round while this one looked
                stored, age = self._stored(path)
                if stored is not None and age < self.fresh:
                    return self._charted(stored, targets, watched)
                result = self._probe(targets, watched)
                try:
                    jsonio.write_json_atomic(path, {"at": time.time(), **result},
                                             keep_backup=False)
                except OSError as e:
                    log.warning("checks: the round could not be stored (%s)", type(e).__name__)
                return result
        except OSError as e:
            # A data directory that cannot be written (read-only mount): there is
            # no round to share, so this worker asks for itself.
            log.debug("checks: no shared round here (%s); asking without one", type(e).__name__)
            return self._probe(targets, watched)
        except filelock.LockTimeout:
            # Another worker is asking right now. Its last round stands meanwhile,
            # unless it is so old that the worker holding the lock must be stuck.
            if stored is not None and age <= self.max_age:
                return self._charted(stored, targets, watched)
            return {}


# Kuma monitor_status values → Atlas marker states (0 down · 1 up · 2 pending · 3 maint)
_KUMA_STATE = {0: DOWN, 1: HEALTHY, 2: DEGRADED, 3: MAINTENANCE}


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
_STATE_RANK = {HEALTHY: 0, SLUMBERING: 1, MAINTENANCE: 2, DEGRADED: 3, DOWN: 4}


def _worse(a, b):
    """The more alarming of two states — see _STATE_RANK."""
    if a is None:
        return b
    return b if _STATE_RANK.get(b, 0) > _STATE_RANK.get(a, 0) else a


def monitor_map(data):
    """{monitor name: place id} from a dataset: each place's own `monitors` (what a
    connection review ties), then `signals.kuma`, which wins where both name a
    monitor because a hand-kept line is the more deliberate of the two."""
    out = {}
    for node in data.get("nodes", []) or []:
        # an entry that is not an object, or names no place, lights nothing
        # (11-12 audit: one such entry stopped every feed build)
        if not isinstance(node, dict) or not node.get("id"):
            continue
        for name in node.get("monitors") or []:
            if isinstance(name, str) and name:
                out.setdefault(name, node.get("id"))
    out.update((data.get("signals") or {}).get("kuma") or {})
    return out


def ip_map(data):
    """{address: place id} from a dataset: which place a Prometheus `instance`
    belongs to."""
    return {n["ip"]: n["id"] for n in data.get("nodes", []) or []
            if isinstance(n, dict) and n.get("id") and n.get("ip") and n["ip"] != "—"}


def unifi_places(data):
    """({mac: place id}, {ip: place id}, {place ids Kuma already watches}) from a
    dataset: what the `unifi` source may report on, and what it must leave alone.

    Several places can be drawn at one address: a machine, and the software on
    it that someone gave a marker of its own. The address belongs to the machine
    (`kind` vm or physical). A place that *is* a network (a prefix) has no
    address to be connected at.
    """
    by_mac, by_ip, machine_at = {}, {}, set()
    nodes = [n for n in data.get("nodes", []) or [] if isinstance(n, dict) and n.get("id")]
    watched = {nid for nid in monitor_map(data).values() if nid}
    for node in nodes:
        nid = node["id"]
        if node.get("monitors") or any(isinstance(link, dict) and link.get("kuma")
                                       for link in node.get("links") or []):
            watched.add(nid)
        mac = str(node.get("mac") or "").strip().lower()
        if mac:
            by_mac.setdefault(mac, nid)
        ip = str(node.get("ip") or "").strip()
        if not ip or ip == "—" or "/" in ip:
            continue
        machine = node.get("kind") in ("vm", "physical")
        if ip not in by_ip or (machine and ip not in machine_at):
            by_ip[ip] = nid
        if machine:
            machine_at.add(ip)
    return by_mac, by_ip, watched


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


def _states_only(section, valid):
    """One section of a feed ({id: info}) with junk dropped: an entry that is
    not a dict goes, and a `state` that is not one of `valid` is left off the
    entry while the rest of it is kept."""
    clean = {}
    for key, info in section.items():
        if not isinstance(info, dict):
            continue
        state = info.get("state")
        entry = {k: v for k, v in info.items() if k != "state"}
        if state in valid:
            entry["state"] = state
        clean[key] = entry
    return clean


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
        out["nodes"] = _states_only(nodes, _VALID_STATES)
    services = raw.get("services")
    if isinstance(services, dict):
        out["services"] = {
            sid: info for sid, info in services.items() if isinstance(info, dict)
        }
    stones = raw.get("stones")
    if isinstance(stones, dict):
        # Same rule as nodes: an unrecognised voice is DROPPED, not passed
        # through. The front-end swaps a CSS class on this value, so a junk
        # state would render an unstyled marker — a stone that is neither
        # visibly quiet nor visibly shouting, which is the worst of both.
        out["stones"] = _states_only(stones, _VALID_STONE_STATES)
    metrics = raw.get("metrics")
    if isinstance(metrics, dict):
        out["metrics"] = {
            k: v for k, v in metrics.items() if isinstance(v, (int, float))
        }
    return out


def _merge(feeds, names=None):
    """Deep-merge partial feeds. Later feeds win per-key (order = adapter priority).

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
            if names is not None and isinstance(info, dict) and info.get("state"):
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


def _kuma_adapter(url):
    import integrations
    return KumaAdapter(url, _read_secret("ATLAS_KUMA_API_KEY"),
                       verify=not integrations.flag("ATLAS_KUMA_INSECURE", False))


def _prometheus_adapter(url):
    return PrometheusAdapter(url)


def _deception_adapter(url):
    return DeceptionAdapter(url, _read_secret("ATLAS_DECOYS_KEY"))


def _unifi_adapter(url):
    """The `unifi` source from the UniFi connection's saved credential, or None
    (said in the log) when it has none."""
    import connections
    _, creds, insecure = connections.saved("unifi")
    if not connections.ready("unifi", creds):
        log.warning("unifi source requested but the UniFi connection has no credential "
                    "(an API key, or a user and its password) — skipping")
        return None
    return UniFiAdapter(url, creds, verify=not insecure)


def _checks_adapter(_url=None):
    """The `checks` source. It has no address of its own: it asks the ones the
    map charts."""
    return ChecksAdapter()


#: The sources that are built by name: source -> builder(url). Which setting
#: holds that URL is `integrations.SOURCE_NEEDS`; a source that is not listed
#: there (`checks`) needs none. What each adapter needs from the dataset is
#: pushed later, by `api.v2.feeds._apply_kuma_map`.
_BUILDERS = {"kuma": _kuma_adapter, "prometheus": _prometheus_adapter,
             "deception": _deception_adapter, "unifi": _unifi_adapter,
             "checks": _checks_adapter}


def _from_url(name, integrations):
    """The adapter for a source in `_BUILDERS`, or None (said in the log) when
    its URL is unset."""
    need = integrations.SOURCE_NEEDS.get(name)
    if need is None:
        return _BUILDERS[name](None)       # a source with no address of its own
    url = integrations.get(need)
    if not url:
        log.warning("%s source requested but %s unset — skipping", name, need)
        return None
    return _BUILDERS[name](url)


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
        if name == "static":
            adapters.append(StaticFileAdapter(
                os.environ.get("ATLAS_SIGNALS_FILE", "/data/signals.json")))
        elif name == "relay":
            adapters.append(RelayAdapter(settings.SITE_SLUG))
        elif name in _BUILDERS:
            try:
                adapter = _from_url(name, integrations)
            except Exception as e:  # noqa: BLE001 — a source that cannot be built is skipped, never fatal
                if name != "unifi":
                    raise                  # only the unifi build is guarded
                log.warning("unifi source could not be built (%s) — skipping", type(e).__name__)
                adapter = None
            if adapter is not None:
                adapters.append(adapter)
        else:
            log.warning("unknown signals source %r — ignoring", name)
    log.info("signals: %d source(s) enabled: %s", len(adapters),
             ", ".join(a.name for a in adapters) or "(none — static/degraded map)")
    return adapters


def build_hub_from_env():
    """The app's hub: built from THE SOURCES now, and self-rebuilding when the
    settings file changes (the name is kept — app.py and the tests call it)."""
    return SignalsHub(factory=make_adapters)
