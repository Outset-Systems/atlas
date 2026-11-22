from engines.base import _Adapter, _TIMEOUT, _coerce_feed, _read_secret, log
import engines.runtime as runtime


class DeceptionAdapter(_Adapter):

    name = "deception"

    def __init__(self, url, read_key):
        import envnames
        self.url = url.rstrip("/")
        self.read_key = read_key
        self.key_header = envnames.env("ATLAS_DECOYS_KEY_HEADER")
        import integrations
        self.path = integrations.decoys_path()

    def _fetch(self):
        if not self.read_key:
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
