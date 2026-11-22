from contextlib import contextmanager

from filelock import exclusive, lock_for
from jsonio import read_json, write_json_atomic


class JsonStore:
    def __init__(self, path, normalize=lambda raw: raw, *, indent=1, newline=False):
        self._path = path if callable(path) else (lambda: path)
        self._normalize = normalize
        self._indent = indent
        self._newline = newline

    @property
    def path(self):
        return self._path()

    def load(self):
        return self._normalize(read_json(self.path))

    def save(self, data):
        write_json_atomic(self.path, data, indent=self._indent, newline=self._newline)

    @contextmanager
    def locked(self):
        with exclusive(lock_for(self.path)):
            yield self
