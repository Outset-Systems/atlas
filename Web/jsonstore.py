"""One small JSON file, read-modify-written under its own lock.

The `_lock_path / _load / _save` trio, plus the `with exclusive(...): load;
mutate; save` dance around it, was written four times — THE ANNALS (events),
THE RITES (heartbeats), the discovery inbox, and THE REPAIRS (maintenance)
(ALIVE.md THE LIST #9). `overlays.Overlay` was already this shape for the two
layout files; this is the same idea for the operational stores.

Deliberately NOT for the dataset (`dataset.py`): its writer locks a whole
directory of revisions under a `<site>-write.lock`, not a single file, and
carries a journal and conflict/expect semantics none of these four want.

Each store keeps its OWN `normalize` — the shape it guarantees a caller,
applied to whatever `read_json` returns (including `None` for a missing file).
The shapes stay where they are understood; only the file plumbing moves here.

The path is taken as a callable and resolved on EVERY access, never captured
once, because the suite reloads `settings` between apps (appfixture.fresh_app)
and the stores must see the reloaded `settings.<X>_PATH` — exactly the
module-level-constant trap that made the suite pass one file at a time. A
plain string is accepted too, for a path that never moves.
"""

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
        """The file parsed and normalised to this store's shape. Never raises
        on a missing or corrupt file — `read_json` returns None and the store's
        own `normalize` decides what empty looks like. No lock: a read is a
        snapshot, exactly as the four hand-rolled `_load`s were."""
        return self._normalize(read_json(self.path))

    def save(self, data):
        """Atomic whole-file write. `indent=1, newline=False` by default —
        the shape THE ANNALS / RITES / inbox / REPAIRS are already written in;
        the git-tracked overlays and dataset keep their own via `Overlay` and
        `dataset.py`."""
        write_json_atomic(self.path, data, indent=self._indent, newline=self._newline)

    @contextmanager
    def locked(self):
        """Hold the file's writer lock for a read-modify-write. Yields the
        store, so the body reads `with s.locked(): d = s.load(); …; s.save(d)`.
        `load()` inside here does NOT re-lock (the sidecar lock is not
        reentrant), so this composes cleanly with a read done under the lock."""
        with exclusive(lock_for(self.path)):
            yield self
