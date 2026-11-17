"""What every status source shares: the adapter contract, the marker states,
the feed shape, and the helpers more than one source needs.

Every adapter fails silent: a timeout, a 500, a bad payload or a missing key
is "no signal" (an empty dict), never an exception that could break the render.
"""

import logging
import time

log = logging.getLogger("atlas.live.signals")   # one logger for every source, as before the split

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
        monitors = node.get("monitors")
        for name in monitors if isinstance(monitors, list) else []:   # a hand edit's 5 (round 14)
            if isinstance(name, str) and name:
                out.setdefault(name, node.get("id"))
    block = data.get("signals") if isinstance(data.get("signals"), dict) else {}
    kuma = block.get("kuma") if isinstance(block.get("kuma"), dict) else {}
    # a hand edit's list or number for a place is no place: dropped, so a
    # restricted feed never iterates it (round 13)
    out.update({k: v for k, v in kuma.items() if isinstance(k, str) and isinstance(v, str)})
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
