import json
import os

from engines.base import _Adapter, _coerce_feed


class StaticFileAdapter(_Adapter):

    name = "static"

    def __init__(self, path):
        self.path = path

    def _fetch(self):
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        return _coerce_feed(raw)
