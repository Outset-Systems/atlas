"""The write path — one way to change the map, whichever backend holds it.

Until now the Atlas could write exactly two things: `positions.json` and
`rack.json`. Everything else — places, realms, roads, the rack, the vassals,
the rites — was a text editor and a reload. This module is what the editors
write through.

Three things make it safe enough to put behind a button:

**Ops, not documents.** A save is a list of small typed operations
(`upsert` / `delete` / `insert` / `move` / `set`), never "here is the whole
file". That is what makes a change describable in the log, reversible, and
checkable field by field — and it means a buggy client can't blank the map by
POSTing `{}`.

**Strict before it lands.** `validation.validate(..., strict=True)` runs on
the *result*, and a write that would introduce problems is refused whole. The
read path keeps its historic warnings-only tolerance: a human hand-editing
JSON gets a loud log, a form submission gets a refusal, because there a
refusal is actionable and the file on disk stays good.

**Every change is a revision.** The document as it was is snapshotted before
each write and the change is appended to a journal, so `revisions()` answers
"who changed what, when" and `revert()` puts it back. This is the one NetBox
feature worth having at any scale — the day you can't remember what you
changed at 01:00 is the day it pays for itself.

The ops engine is backend-agnostic: it mutates a plain dict. Only loading and
saving differ, so file mode and db mode cannot drift apart in what an edit
*means* — the db backend deliberately re-uses `store.load_labdata`, the same
full-replace path the golden round-trip test already guards.
"""

import copy
import hashlib
import json
import logging
import os

import schema
import validation
from filelock import LockTimeout, exclusive
from jsonio import iso_utc, read_json, write_json_atomic

log = logging.getLogger("atlas.data.dataset")

# How many revisions of history to keep. The dataset is ~40 KB, so 50
# generations is ~2 MB — cheap enough that pruning is about tidiness, not space.
KEEP_REVISIONS = 50

OPS = ("upsert", "insert", "delete", "move", "set")


class ConflictError(Exception):
    """The dataset moved under the client between read and write."""


class BusyError(Exception):
    """Another save is in progress and would not let go."""


class RejectedError(Exception):
    """The write was refused. `problems` says why, in the user's language."""

    def __init__(self, problems):
        self.problems = problems if isinstance(problems, list) else [str(problems)]
        super().__init__("; ".join(self.problems))


# ── Identity helpers ─────────────────────────────────────────────────────────

def _section_or_reject(key):
    s = schema.get(key)
    if s is None:
        raise RejectedError(f"unknown section {key!r}")
    if s["store"] != "dataset":
        # Catalogued, but owned by another store — maintenance windows live in
        # their own file precisely so a 2am schedule change isn't a map commit.
        raise RejectedError(
            f"{key} is not part of the dataset — it is edited through its own "
            f"endpoint (/api/admin/{key})")
    return s


def _find_index(data, section_key, entry_id):
    """Index of the entry with this id, or -1. Only for sections that have ids."""
    s = _section_or_reject(section_key)
    id_field = s["id_field"]
    if not id_field:
        return -1
    for i, entry in enumerate(data.get(section_key) or []):
        if isinstance(entry, dict) and entry.get(id_field) == entry_id:
            return i
    return -1


def _target_index(data, op):
    """Resolve an op's target to a list index, or -1 when it names a new entry.

    Sections with an `id_field` are addressed by id — stable, and what the UI
    shows. The id-less ones (roads, rack slots, rites, watchings) are addressed
    by index, which is only safe because every batch carries the stamp of the
    document it was composed against; a concurrent write makes the whole batch
    a conflict rather than letting an index land on the wrong row.
    """
    section_key = op["section"]
    s = _section_or_reject(section_key)
    if s["id_field"] and op.get("id") is not None:
        return _find_index(data, section_key, op["id"])
    if op.get("index") is not None:
        try:
            index = int(op["index"])
        except (TypeError, ValueError):
            raise RejectedError(f"{section_key}: index must be a whole number")
        entries = data.get(section_key) or []
        if not (0 <= index < len(entries)):
            raise RejectedError(
                f"{section_key}: there is no entry #{index + 1} to change")
        return index
    return -1


# ── Referential integrity ────────────────────────────────────────────────────

def dependents(data, section_key, entry_id):
    """Everything that would dangle if this entry were removed.

    Returned as a list of `{section, index, label, field}` so the UI can say
    "removing the app host also breaks 4 roads and a rack slot" *before* the user
    commits to it, rather than leaving a map full of arrows into nothing.
    """
    out = []
    for other_key in schema.SECTIONS:
        other = schema.get(other_key)
        if other["kind"] != "list":
            continue
        for path, target in schema.refs_of(other_key):
            if target != section_key:
                continue
            for i, entry in enumerate(data.get(other_key) or []):
                if not isinstance(entry, dict):
                    continue
                if "." in path:
                    outer, inner = path.split(".", 1)
                    hit = any(
                        isinstance(sub, dict) and entry_id in _as_list(sub.get(inner))
                        for sub in (entry.get(outer) or []))
                else:
                    hit = entry_id in _as_list(entry.get(path))
                if hit:
                    out.append({
                        "section": other_key,
                        "index": i,
                        "field": path,
                        "label": _entry_label(other_key, entry, i),
                    })
    return out


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _entry_label(section_key, entry, index):
    """How one entry is named in a log line. Falls back to its position, since
    roads and rack slots have no name of their own."""
    s = schema.get(section_key)
    for field_name in (s["id_field"], s["title_field"]):
        if field_name and isinstance(entry, dict) and entry.get(field_name):
            return str(entry[field_name])
    return f"#{index + 1}"


def _cascade_delete(data, section_key, entry_id):
    """Remove or unhook everything that referenced a deleted entry.

    Whole entries whose *required* reference is gone (a road to nowhere, a
    vassal with no host) are removed. Optional references (`reaches`,
    `children`, a rack slot's `node`) are merely unhooked — the rack slot is
    still a real slot with a real device in it once its map marker is gone.
    """
    removed = []
    for other_key in list(schema.SECTIONS):
        other = schema.get(other_key)
        if other["kind"] != "list":
            continue
        refs = [(p, t) for p, t in schema.refs_of(other_key) if t == section_key]
        if not refs:
            continue
        kept = []
        for i, entry in enumerate(data.get(other_key) or []):
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            drop = False
            for path, _ in refs:
                fld = schema.field(other_key, path.split(".")[0])
                if "." in path:
                    outer, inner = path.split(".", 1)
                    for sub in entry.get(outer) or []:
                        if isinstance(sub, dict) and inner in sub:
                            sub[inner] = [v for v in _as_list(sub[inner]) if v != entry_id]
                    continue
                if entry.get(path) == entry_id or entry_id in _as_list(entry.get(path)):
                    if fld and fld.get("required"):
                        drop = True
                    elif isinstance(entry.get(path), list):
                        entry[path] = [v for v in entry[path] if v != entry_id]
                    else:
                        entry.pop(path, None)
            if drop:
                removed.append({"section": other_key,
                                "label": _entry_label(other_key, entry, i)})
            else:
                kept.append(entry)
        if other_key in data:
            data[other_key] = kept
    return removed


# ── The ops engine ───────────────────────────────────────────────────────────

def _place_section(data, section_key):
    """Ensure a section exists, inserted where the catalogue says it belongs.

    A brand-new section (the first prefix, the first port) must not land at
    the bottom of the file just because it was added last — the dataset is
    read by humans, and its order is part of how it reads.
    """
    if section_key in data:
        return
    order = schema.FILE_ORDER
    if section_key not in order:
        data[section_key] = []
        return
    want = order.index(section_key)
    rebuilt = {}
    placed = False
    for key in data:
        # slot it in front of the first section that belongs after it; keys the
        # order doesn't know about never trigger a placement
        if not placed and key in order and order.index(key) > want:
            rebuilt[section_key] = []
            placed = True
        rebuilt[key] = data[key]
    if not placed:
        rebuilt[section_key] = []
    data.clear()
    data.update(rebuilt)


def _apply_one(data, op):
    """Apply a single op in place. Returns a human sentence describing it."""
    kind = op.get("op")
    if kind not in OPS:
        raise RejectedError(f"unknown operation {kind!r}")

    if kind == "set":
        path = str(op.get("path") or "")
        if not path:
            raise RejectedError("set needs a path")
        parts = path.split(".")
        target = data
        for part in parts[:-1]:
            nxt = target.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                target[part] = nxt
            target = nxt
        target[parts[-1]] = op.get("value")
        return f"set {path}"

    section_key = op.get("section")
    s = _section_or_reject(section_key)

    if s["kind"] == "object":
        if kind != "upsert":
            raise RejectedError(f"{section_key} can only be updated, not {kind}ed")
        body = op.get("body")
        if not isinstance(body, dict):
            raise RejectedError(f"{section_key}: body must be an object")
        merged = dict(data.get(section_key) or {})
        merged.update(body)
        data[section_key] = merged
        return f"updated {s['singular']}"

    _place_section(data, section_key)
    entries = data[section_key]
    if not isinstance(entries, list):
        raise RejectedError(f"{section_key} is not a list in this dataset")

    if kind in ("upsert", "insert"):
        body = op.get("body")
        if not isinstance(body, dict):
            raise RejectedError(f"{section_key}: body must be an object")
        index = -1 if kind == "insert" else _target_index(data, op)
        # An edit sends only the fields that changed, so its name comes from the
        # entry already on file — not from the patch, which may carry no name.
        label = _entry_label(section_key,
                             entries[index] if index >= 0 else body,
                             index if index >= 0 else len(entries))
        if index >= 0:
            # Merge, don't replace: keys the editor doesn't know about are the
            # dataset's business, not the form's. An explicit
            # null is how a form says "clear this optional field", which is a
            # different intention from not mentioning it at all.
            merged = dict(entries[index])
            merged.update(body)
            for key, value in body.items():
                if value is None:
                    merged.pop(key, None)
            entries[index] = merged
            return f"changed {s['noun']} {label}"
        entries.append(body)
        return f"added {s['noun']} {label}"

    if kind == "delete":
        index = _target_index(data, op)
        if index < 0:
            raise RejectedError(f"{section_key}: nothing to remove")
        entry = entries.pop(index)
        label = _entry_label(section_key, entry, index)
        note = ""
        if op.get("cascade") and s["id_field"]:
            removed = _cascade_delete(data, section_key, entry.get(s["id_field"]))
            if removed:
                note = f" (and {len(removed)} thing{'s' if len(removed) != 1 else ''} that pointed at it)"
        return f"removed {s['noun']} {label}{note}"

    if kind == "move":
        index = _target_index(data, op)
        if index < 0:
            raise RejectedError(f"{section_key}: nothing to move")
        try:
            to = max(0, min(len(entries) - 1, int(op.get("to"))))
        except (TypeError, ValueError):
            raise RejectedError(f"{section_key}: 'to' must be a position")
        entry = entries.pop(index)
        entries.insert(to, entry)
        return f"moved {s['noun']} {_entry_label(section_key, entry, to)}"

    raise RejectedError(f"unknown operation {kind!r}")


def apply_ops(data, ops):
    """Apply a batch to a copy of `data`. Returns (new_data, [summaries])."""
    if not isinstance(ops, list) or not ops:
        raise RejectedError("no changes were sent")
    if len(ops) > 500:
        raise RejectedError("too many changes in one save (max 500)")
    out = copy.deepcopy(data)
    summaries = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise RejectedError(f"change #{i + 1} is not an operation")
        try:
            summaries.append(_apply_one(out, op))
        except RejectedError as e:
            raise RejectedError([f"change #{i + 1}: {p}" for p in e.problems])
    return out, summaries


# ── Stores ───────────────────────────────────────────────────────────────────

def content_stamp(data):
    """A short, clock-independent version token for optimistic concurrency."""
    blob = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


class DatasetStore:
    """Shared machinery. Subclasses supply `_load` and `_save`."""

    #: where snapshots and the journal live
    def __init__(self, revisions_dir, site="default"):
        self.revisions_dir = revisions_dir
        self.site = site

    # -- backend hooks -------------------------------------------------------
    def _load(self):
        raise NotImplementedError

    def _save(self, data):
        raise NotImplementedError

    def writable(self):
        """False when this deployment cannot accept writes at all."""
        return True

    def _lock_path(self):
        """The sidecar every writer of this dataset contends on."""
        return os.path.join(self.revisions_dir, f"{self.site}-write.lock")

    # -- public API ----------------------------------------------------------
    def read(self):
        """(data, stamp) as the editor sees it — no overlays, no redaction.

        Deliberately unlocked. `os.replace` is atomic, so a reader gets the
        whole old document or the whole new one, and making every map load
        queue behind an editor would be a bad trade for no gain.
        """
        data = self._load()
        return data, content_stamp(data)

    def apply(self, ops, actor="unknown", expect=None, note=""):
        """Validate and commit a batch. Returns a result dict for the client.

        `expect` is the stamp the client last read. When it doesn't match, the
        batch is refused rather than merged — the ops address rows by position,
        so "apply anyway" would land edits on the wrong rows.

        The whole load → check → journal → save cycle runs under an exclusive
        lock. The stamp alone is not enough: it catches a client working from a
        stale copy, but two clients that both read the same fresh copy would
        both pass it and the second would overwrite the first. Worse, both
        would compute the same next revision id and the second's snapshot would
        replace the first's, so the change log would offer an undo that
        restored the wrong state. Measured, not theorized — see
        tests/test_concurrency.py.
        """
        try:
            with exclusive(self._lock_path()):
                return self._apply_locked(ops, actor, expect, note)
        except LockTimeout as e:
            raise BusyError(str(e)) from e

    def _apply_locked(self, ops, actor, expect, note):
        before = self._load()
        stamp = content_stamp(before)
        if expect and expect != stamp:
            raise ConflictError(
                "someone else changed the map while you were editing — "
                "reload to see their version, then make your change again")

        after, summaries = apply_ops(before, ops)

        problems = validation.validate(after, strict=True)
        if problems:
            raise RejectedError(problems)

        revision = self._record(before, actor, summaries, ops, note)
        self._save(after)
        log.info("dataset write by %s: %s", actor, "; ".join(summaries))
        return {
            "ok": True,
            "stamp": content_stamp(after),
            "revision": revision,
            "changed": summaries,
        }

    # -- history -------------------------------------------------------------
    def _journal_path(self):
        return os.path.join(self.revisions_dir, f"{self.site}-journal.jsonl")

    def _snapshot_path(self, revision_id):
        return os.path.join(self.revisions_dir, f"{self.site}-r{revision_id:05d}.json")

    def _next_revision_id(self):
        entries = self.revisions()
        return (entries[0]["id"] + 1) if entries else 1

    def _record(self, before, actor, summaries, ops, note):
        """Snapshot the document as it was, and append to the journal.

        The snapshot is of the state *before* the change, so reverting to
        revision N restores what the map looked like before N happened.
        """
        revision_id = self._next_revision_id()
        entry = {
            "id": revision_id,
            "at": iso_utc(),
            "actor": actor,
            "summary": summaries,
            "note": note,
            "ops": ops,
        }
        try:
            os.makedirs(self.revisions_dir, exist_ok=True)
            write_json_atomic(self._snapshot_path(revision_id), before,
                              keep_backup=False)
            with open(self._journal_path(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._prune()
        except OSError as e:
            # History is valuable, but not more valuable than the edit. Losing
            # the journal must not lose the change the user just made.
            log.warning("could not record revision %d: %s", revision_id, e)
        return revision_id

    def _prune(self):
        entries = self.revisions(limit=None)
        for old in entries[KEEP_REVISIONS:]:
            path = self._snapshot_path(old["id"])
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    def revisions(self, limit=25):
        """The change log, newest first. Entries whose snapshot has been
        pruned are still listed — the *record* of a change outlives the
        ability to undo it, and saying so is better than hiding it."""
        out = []
        try:
            with open(self._journal_path(), encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        out.reverse()
        for entry in out:
            entry["revertable"] = os.path.exists(self._snapshot_path(entry.get("id", 0)))
        return out if limit is None else out[:limit]

    def revert(self, revision_id, actor="unknown", expect=None):
        """Put the map back to how it was before `revision_id`.

        Recorded as a revision of its own, so an unwanted revert is itself
        undoable — the history only ever grows forwards. Same lock as `apply`:
        a revert is a read-modify-write like any other. `expect` refuses it if the
        map has moved on: an Undo beside one import must not take later edits too.
        """
        try:
            with exclusive(self._lock_path()):
                return self._revert_locked(revision_id, actor, expect)
        except LockTimeout as e:
            raise BusyError(str(e)) from e

    def _revert_locked(self, revision_id, actor, expect=None):
        if expect and expect != content_stamp(self._load()):
            raise ConflictError("the map has changed since then — use the change log "
                                "in the Desk to see what would be undone")
        snapshot = read_json(self._snapshot_path(int(revision_id)))
        if not isinstance(snapshot, dict):
            raise RejectedError(
                f"revision {revision_id} can no longer be undone — its snapshot "
                f"has been pruned (the last {KEEP_REVISIONS} are kept)")
        problems = validation.validate(snapshot, strict=True)
        if problems:
            raise RejectedError(
                [f"that older version no longer validates: {p}" for p in problems[:5]])
        before = self._load()
        summary = [f"reverted to the state before revision {revision_id}"]
        new_id = self._record(before, actor, summary,
                              [{"op": "revert", "to": int(revision_id)}], "")
        self._save(snapshot)
        log.info("dataset reverted to r%s by %s", revision_id, actor)
        return {"ok": True, "stamp": content_stamp(snapshot),
                "revision": new_id, "changed": summary}


class FileDatasetStore(DatasetStore):
    """The hand-edited `lab-data.json` — still hand-editable after every save.

    Writes at the same 2-space indent and real UTF-8 the file already uses, so
    a save produces a diff of the lines that changed and nothing else. That is
    what keeps the dataset sync script and the git history useful.
    """

    def __init__(self, path, default_path, revisions_dir, site="default"):
        super().__init__(revisions_dir, site)
        self.path = path
        self.default_path = default_path

    def writable(self):
        directory = os.path.dirname(self.path) or "."
        if os.path.exists(self.path):
            return os.access(self.path, os.W_OK)
        return os.path.isdir(directory) and os.access(directory, os.W_OK)

    def _load(self):
        # An unseeded instance starts from the *fallback*, which is empty
        # unless someone asked for the bundled map. Reading the bundled map
        # here regardless is what made a first save fork 17 places nobody
        # charted into a brand-new install.
        if not os.path.exists(self.path):
            from labdata import fallback_dataset
            return fallback_dataset(self.default_path)
        data = read_json(self.path)
        if not isinstance(data, dict):
            raise RejectedError(f"the dataset at {self.path} is unreadable")
        return data

    def _save(self, data):
        write_json_atomic(self.path, data, indent=2)


class DbDatasetStore(DatasetStore):
    """The SQLAlchemy backbone (`ATLAS_DATA_BACKEND=db`).

    Saving goes through `store.load_labdata`, the same full-replace path the
    golden round-trip test guards — which is why an edit means exactly the
    same thing in both backends. Node identity (pk, `first_seen`,
    `layout_locked`, importer provenance) survives, because that path upserts
    by slug rather than rebuilding the table.
    """

    def __init__(self, site, revisions_dir):
        super().__init__(revisions_dir, site)

    def _load(self):
        from store import dump_labdata, session_scope
        with session_scope() as session:
            data = dump_labdata(session, self.site)
        if data is None:
            raise RejectedError(
                f"site {self.site!r} has not been seeded yet — import a dataset first "
                f"(python cli.py import-json --site {self.site} ...)")
        return data

    def _save(self, data):
        from store import load_labdata, session_scope
        with session_scope() as session:
            load_labdata(session, data, site_slug=self.site, source="manual")


def build_store(backend, *, data_path, default_path, site, revisions_dir):
    """The store for this deployment's configuration."""
    if backend == "db":
        return DbDatasetStore(site, revisions_dir)
    return FileDatasetStore(data_path, default_path, revisions_dir, site)
