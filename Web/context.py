import os

from flask import current_app


class AtlasContext:

    def __init__(self, *, reader, store, overlays, signals, config, backend, site):
        self.reader = reader
        self.store = store
        self.overlays = overlays
        self.signals = signals
        self.config = config
        self.backend = backend
        self.site = site

    def dataset(self):
        return self.reader.get()

    def with_overlays(self, data):
        tags = ""
        for overlay in self.overlays.values():
            data, tag = overlay.apply(data)
            tags += tag
        return data, tags

    def overlay_mtimes(self):
        out = []
        for overlay in self.overlays.values():
            try:
                out.append(os.path.getmtime(overlay.path))
            except OSError:
                out.append(0)
        return out

    def invalidate(self):
        self.reader.invalidate()


def atlas():
    return current_app.extensions["atlas"]
