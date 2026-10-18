"""The per-app objects the blueprints share.

Built once by `create_app()` and hung on `app.extensions["atlas"]`, so a route
reaches them through `current_app` rather than importing a module global. That
is what lets the test suite build two apps with different backends in one
process — the thing that module-level config made impossible, and the reason
The suite currently only passes one file at a time.
"""

from flask import current_app


class AtlasContext:
    """Everything a request might need that isn't the request itself."""

    def __init__(self, *, reader, store, overlays, signals, config, backend, site):
        self.reader = reader        # labdata.FileLabData | labdata.DbLabData
        self.store = store          # dataset.FileDatasetStore | DbDatasetStore
        self.overlays = overlays    # {"positions": Overlay, "rack": Overlay}
        self.signals = signals      # signals hub
        self.config = config        # the settings module
        # Which backend and site *this app* was built for. Reading
        # `settings.DATA_BACKEND` at request time asks a process-wide question
        # instead of an app-wide one — fine in production, wrong the moment a
        # second app exists, which is exactly what the tests now do.
        self.backend = backend
        self.site = site

    def dataset(self):
        """(data, mtime, problems) — raises OSError/ValueError like the reader."""
        return self.reader.get()

    def with_overlays(self, data):
        """The dataset as a viewer sees it, plus the ETag fragments."""
        tags = ""
        for overlay in self.overlays.values():
            data, tag = overlay.apply(data)
            tags += tag
        return data, tags

    def overlay_mtimes(self):
        """Each overlay's mtime, so a layout save invalidates the ETag."""
        import os
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
    """The context for the app handling this request."""
    return current_app.extensions["atlas"]
