"""The read path: the dataset, cached, validated, hot-reloaded on change.

Moved out of `app.py` unchanged in behaviour. Both readers answer the same
`get() -> (data, mtime, problems)` contract, so nothing downstream knows or
cares which backend is live — that is the compatibility bar the design notes
sets, and the reason `/api/lab-data` looks identical in both modes.

Validation stays **warnings, not rejections** here. A hand-edited file should
render as much of itself as it can; every deviation is logged, counted in
`X-Atlas-Data-Problems`, and flips `/api/status` unhealthy so a bad edit is
loud rather than silent. The strict counterpart lives in `dataset.py`, and
only the write path uses it.
"""

import copy
import json
import logging
import os

import settings
from validation import validate

log = logging.getLogger("atlas.data.labdata")

#: What an unseeded instance serves under ATLAS_FALLBACK=empty. Valid on
#: purpose — it must pass validation, or a fresh install would open unhealthy.
EMPTY_DATASET = {
    "meta": {"title": "An uncharted realm"},
    "zones": [],
    "nodes": [],
    "routes": [],
}


def fallback_dataset(default_path):
    """The dataset for an instance that has never been seeded."""
    if settings.FALLBACK == "bundled":
        with open(default_path, encoding="utf-8") as fh:
            return json.load(fh)
    return copy.deepcopy(EMPTY_DATASET)


class FileLabData:
    """mtime-cached view of the dataset; falls back to the bundled default."""

    def __init__(self, path, default_path):
        self.path = path
        self.default_path = default_path
        self._resolved = None
        self._mtime = None
        self._data = None
        self._problems = []

    def seeded(self):
        """True once a real dataset exists — false means show the wizard."""
        return os.path.exists(self.path)

    def get(self):
        """Return (data, mtime, problems). Raises on unreadable/invalid JSON."""
        if not self.seeded():
            data = fallback_dataset(self.default_path)
            return data, 0, validate(data)
        path = self.path
        mtime = os.path.getmtime(path)
        if self._data is None or self._resolved != path or self._mtime != mtime:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            problems = validate(data)
            for problem in problems:
                log.warning("lab-data: %s", problem)
            log.info(
                "lab-data loaded: %s (%d zones, %d nodes, %d routes%s)",
                path, len(data.get("zones", [])), len(data.get("nodes", [])),
                len(data.get("routes", [])),
                f", {len(problems)} PROBLEMS" if problems else "",
            )
            self._resolved, self._mtime = path, mtime
            self._data, self._problems = data, problems
        return self._data, self._mtime, self._problems

    def invalidate(self):
        """Drop the cache after a write, so the next read sees it immediately.

        mtime alone would usually do it, but a save and a read inside the same
        filesystem timestamp granularity is exactly the sequence the editor
        produces — save, then re-fetch to redraw.
        """
        self._data = None
        self._mtime = None


class DbLabData:
    """DB-backed twin (ATLAS_DATA_BACKEND=db) — same get() contract.

    Rebuilds only when the site's data_version/updated_at stamp moves (the DB
    analogue of file mtime). A site that doesn't exist yet falls back to the
    bundled default, mirroring file mode's keep-the-app-alive-before-seeding
    doctrine. DB errors surface as ValueError so the existing
    unreadable-dataset paths (500 + unhealthy /api/status) apply.
    """

    def __init__(self, site_slug, default_path):
        from store import dump_labdata, session_scope, site_stamp  # lazy: db mode only
        self._dump, self._scope, self._stamp = dump_labdata, session_scope, site_stamp
        self._site = site_slug
        self.default_path = default_path
        self._stamp_seen = None
        self._data = None
        self._problems = []

    def seeded(self):
        from sqlalchemy.exc import SQLAlchemyError
        try:
            with self._scope() as session:
                return self._stamp(session, self._site) is not None
        except SQLAlchemyError:
            return False

    def get(self):
        """Return (data, mtime, problems). Raises ValueError if the DB is down."""
        from sqlalchemy.exc import SQLAlchemyError
        try:
            with self._scope() as session:
                stamp = self._stamp(session, self._site)
                if stamp is None:
                    log.warning("db backend: site %r not seeded yet — serving the %s fallback",
                                self._site, settings.FALLBACK)
                    data = fallback_dataset(self.default_path)
                    return data, 0, validate(data)
                if self._data is None or stamp != self._stamp_seen:
                    data = self._dump(session, self._site)
                    problems = validate(data)
                    for problem in problems:
                        log.warning("lab-data(db): %s", problem)
                    log.info(
                        "lab-data loaded from db: site=%s v%d (%d zones, %d nodes, %d routes%s)",
                        self._site, stamp[0], len(data.get("zones", [])),
                        len(data.get("nodes", [])), len(data.get("routes", [])),
                        f", {len(problems)} PROBLEMS" if problems else "",
                    )
                    self._stamp_seen, self._data, self._problems = stamp, data, problems
        except SQLAlchemyError as e:
            raise ValueError(f"db backend unavailable: {e}") from e
        return self._data, self._stamp_seen[1], self._problems

    def invalidate(self):
        self._data = None
        self._stamp_seen = None


def build(backend, *, data_path, default_path, site):
    return (DbLabData(site, default_path) if backend == "db"
            else FileLabData(data_path, default_path))
