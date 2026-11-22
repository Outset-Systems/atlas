import copy
import json
import logging
import os

import schema
import settings
from validation import validate

log = logging.getLogger("atlas.data.labdata")

EMPTY_DATASET = {
    "meta": {"title": "An uncharted atlas"},
    "zones": [],
    "nodes": [],
    "routes": [],
}


def fallback_dataset(default_path):
    if settings.FALLBACK == "bundled":
        with open(default_path, encoding="utf-8") as fh:
            return schema.upgrade(_object(json.load(fh), default_path))
    return copy.deepcopy(EMPTY_DATASET)


def _object(data, where):
    if not isinstance(data, dict):
        raise ValueError(f"{where}: the map is not a JSON object "
                         f"(it is {type(data).__name__})")
    return data


def _checked(data, prefix, where, *args):
    problems = validate(data)
    for problem in problems:
        log.warning(prefix + ": %s", problem)
    def count(key):
        value = data.get(key)
        return len(value) if isinstance(value, list) else 0

    log.info(
        where + " (%d zones, %d nodes, %d routes%s)",
        *args, count("zones"), count("nodes"), count("routes"),
        f", {len(problems)} PROBLEMS" if problems else "",
    )
    return problems


class FileLabData:

    def __init__(self, path, default_path):
        self.path = path
        self.default_path = default_path
        self._cached = None

    def seeded(self):
        return os.path.exists(self.path)

    def get(self):
        if not self.seeded():
            data = fallback_dataset(self.default_path)
            return data, 0, validate(data)
        path = self.path
        mtime = os.path.getmtime(path)
        cached = self._cached
        if cached is None or cached[0] != mtime:
            with open(path, encoding="utf-8") as fh:
                data = schema.upgrade(_object(json.load(fh), path))
            problems = _checked(data, "lab-data", "lab-data loaded: %s", path)
            schema.servable(data)
            cached = (mtime, data, problems)
            self._cached = cached
        return cached[1], cached[0], cached[2]

    def invalidate(self):
        self._cached = None


class DbLabData:

    def __init__(self, site_slug, default_path):
        from store import dump_labdata, session_scope, site_stamp
        self._dump, self._scope, self._stamp = dump_labdata, session_scope, site_stamp
        self._site = site_slug
        self.default_path = default_path
        self._cached = None

    def seeded(self):
        from sqlalchemy.exc import SQLAlchemyError
        try:
            with self._scope() as session:
                return self._stamp(session, self._site) is not None
        except SQLAlchemyError:
            return False

    def get(self):
        from sqlalchemy.exc import SQLAlchemyError
        try:
            with self._scope() as session:
                stamp = self._stamp(session, self._site)
                if stamp is None:
                    log.warning("db backend: site %r not seeded yet — serving the %s fallback",
                                self._site, settings.FALLBACK)
                    data = fallback_dataset(self.default_path)
                    return data, 0, validate(data)
                cached = self._cached
                if cached is None or stamp != cached[0]:
                    data = schema.upgrade(self._dump(session, self._site))
                    problems = _checked(
                        data, "lab-data(db)",
                        "lab-data loaded from db: site=%s v%d", self._site, stamp[0])
                    schema.servable(data)
                    cached = (stamp, data, problems)
                    self._cached = cached
        except SQLAlchemyError as e:
            raise ValueError(f"db backend unavailable: {e}") from e
        return cached[1], cached[0][1], cached[2]

    def invalidate(self):
        self._cached = None


def build(backend, *, data_path, default_path, site):
    return (DbLabData(site, default_path) if backend == "db"
            else FileLabData(data_path, default_path))
