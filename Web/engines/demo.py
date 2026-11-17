"""The `demo` source: the bundled demo's own feed, silent once a real dataset
is saved. `signals.demo_feed_path` says where the image keeps that feed."""

import os

from engines.static import StaticFileAdapter


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
