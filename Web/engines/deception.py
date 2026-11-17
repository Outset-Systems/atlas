"""The `deception` source: the decoy feed's roster, read and never written."""

from engines.base import _Adapter, _TIMEOUT, _coerce_feed, _read_secret, log
import engines.runtime as runtime


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

        resp = runtime.get(
            self.url + self.path,
            headers={self.key_header: self.read_key},
            timeout=_TIMEOUT,
        )
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


def _deception_adapter(url):
    return DeceptionAdapter(url, _read_secret("ATLAS_DECOYS_KEY"))
