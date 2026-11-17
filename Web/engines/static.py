"""The `static` source: a feed file already in merged shape."""

import json
import os

from engines.base import _Adapter, _coerce_feed


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
