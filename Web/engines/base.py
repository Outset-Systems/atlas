import logging
import time

log = logging.getLogger("atlas.live.signals")

HEALTHY = "healthy"
DEGRADED = "degraded"
DOWN = "down"
SLUMBERING = "slumbering"
MAINTENANCE = "maintenance"
NODE_STATES = frozenset((HEALTHY, DEGRADED, DOWN, SLUMBERING, MAINTENANCE))
_VALID_STATES = NODE_STATES

SILENT = "silent"
STIRRED = "stirred"
SPEAKING = "speaking"
STONE_STATES = frozenset((SILENT, STIRRED, SPEAKING))
_VALID_STONE_STATES = STONE_STATES

_TIMEOUT = 3.0


def _read_secret(name):
    try:
        import integrations
        stored = integrations.get(name) if name in integrations.SECRETS else ""
        if stored:
            return stored
    except Exception:
        log.warning("integrations unreadable while resolving %s", name, exc_info=True)
    import envnames
    return envnames.secret(name) or None


class _Adapter:

    name = "adapter"

    def use_map(self, data):
        pass

    def _fetch(self):
        return {}

    def fetch(self):
        start = time.monotonic()
        try:
            out = self._fetch() or {}
            log.debug("%s: ok in %.0fms", self.name, (time.monotonic() - start) * 1000)
            return out
        except Exception as e:
            log.warning("%s: silent (%s: %s)", self.name, type(e).__name__, e)
            return {}


_STATE_RANK = {HEALTHY: 0, SLUMBERING: 1, MAINTENANCE: 2, DEGRADED: 3, DOWN: 4}


def _worse(a, b):
    if a is None:
        return b
    return b if _STATE_RANK.get(b, 0) > _STATE_RANK.get(a, 0) else a


def monitor_map(data):
    out = {}
    for node in data.get("nodes", []) or []:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        monitors = node.get("monitors")
        for name in monitors if isinstance(monitors, list) else []:
            if isinstance(name, str) and name:
                out.setdefault(name, node.get("id"))
    block = data.get("signals") if isinstance(data.get("signals"), dict) else {}
    kuma = block.get("kuma") if isinstance(block.get("kuma"), dict) else {}
    out.update({k: v for k, v in kuma.items() if isinstance(k, str) and isinstance(v, str)})
    return out


def _states_only(section, valid):
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
        out["stones"] = _states_only(stones, _VALID_STONE_STATES)
    metrics = raw.get("metrics")
    if isinstance(metrics, dict):
        out["metrics"] = {
            k: v for k, v in metrics.items() if isinstance(v, (int, float))
        }
    return out
