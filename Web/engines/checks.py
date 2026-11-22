import time

from engines.base import _Adapter

CHECKS_BUDGET = 8.0
CHECKS_FRESH = 30.0
CHECKS_MAX_AGE = 300.0


def _check_url(value):
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw.lower().startswith(("http://", "https://")):
        return None
    import redaction
    from urllib.parse import urlsplit
    url = redaction.bare_url(raw)
    try:
        if not urlsplit(url).hostname:
            return None
    except ValueError:
        return None
    return url


class ChecksAdapter(_Adapter):

    name = "checks"

    def __init__(self, path=None, budget=CHECKS_BUDGET, fresh=CHECKS_FRESH,
                 max_age=CHECKS_MAX_AGE):
        self.path = path
        self.budget = budget
        self.fresh = fresh
        self.max_age = max_age
        self._data = None

    def use_map(self, data):
        self._data = data

    def _fetch(self):
        data = self._data
        if not isinstance(data, dict):
            return {}
        import watch
        ts = watch.targets(data)
        if not ts:
            return {"nodes": {}}
        path = watch.path_of(self.path)
        store = watch.load(path)
        at = store.get("at")
        age = None if at is None else time.time() - at
        if age is None or age < 0 or age >= self.fresh:
            heard = watch.tick(data, path, budget=self.budget, ts=ts)
            if heard is not None:
                store = heard
            elif age is None or age < 0 or age > self.max_age:
                return {}
        return watch.as_feed(store, ts)


def _checks_adapter(_url=None):
    return ChecksAdapter()
