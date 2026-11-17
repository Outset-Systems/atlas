"""The `checks` source: what the built-in checks (watch.py) heard. `watch` is
imported only when a feed is read, because `watch` imports `signals`."""

import time

from engines.base import _Adapter

#: The built-in checks as a source (THE WATCH, watch.py, 2026-11-15): the
#: most one read inside a request may spend asking, how long the store may sit
#: still before a read asks a round itself (no thread is running), and the age
#: past which a store is not served when another worker holds the round.
CHECKS_BUDGET = 8.0
CHECKS_FRESH = 30.0
CHECKS_MAX_AGE = 300.0


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


class ChecksAdapter(_Adapter):
    """Built-in checks: what THE WATCH (watch.py) heard, as a live source.

    A fallback for an install with no monitoring of its own, and its rules are
    watch.py's: only what the map charts is asked, Kuma stands where it
    watches, no answer in time is unknown, never down. Each check keeps its
    own schedule there; the gunicorn workers' threads ask, and this only reads
    the store they share. With no thread asking (the dev server, a worker that
    lost it) a read whose store has not moved in `fresh` seconds asks a round
    itself, inside `budget` seconds.
    """

    name = "checks"

    def __init__(self, path=None, budget=CHECKS_BUDGET, fresh=CHECKS_FRESH,
                 max_age=CHECKS_MAX_AGE):
        self.path = path                  # None = beside the dataset, read at each fetch
        self.budget = budget
        self.fresh = fresh
        self.max_age = max_age
        self._data = None                 # the dataset, once the feed has handed it over

    def use_map(self, data):
        # called before every feed read, cached ones too: keep it, work it out later
        self._data = data

    def _fetch(self):
        data = self._data
        if not isinstance(data, dict):
            return {}                     # no dataset yet: nothing to say, nothing to store
        import watch
        ts = watch.targets(data)
        if not ts:
            return {"nodes": {}}          # it ran, and the map charts nothing to ask
        path = watch.path_of(self.path)
        store = watch.load(path)
        at = store.get("at")
        age = None if at is None else time.time() - at
        if age is None or age < 0 or age >= self.fresh:
            heard = watch.tick(data, path, budget=self.budget, ts=ts)
            if heard is not None:
                store = heard
            elif age is None or age < 0 or age > self.max_age:
                return {}                 # another worker is asking, and what is stored is too old
        return watch.as_feed(store, ts)


def _checks_adapter(_url=None):
    """The `checks` source. It has no address of its own: it asks the ones the
    map charts."""
    return ChecksAdapter()
