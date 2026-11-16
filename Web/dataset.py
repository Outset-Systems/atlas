"""The write path — one way to change the map, whichever backend holds it.

Until now the Atlas could write exactly two things: `positions.json` and
`rack.json`. Everything else — places, realms, roads, the rack, the vassals,
the rites — was a text editor and a reload. This module is what the editors
write through.

Three things make it safe enough to put behind a button:

**Ops, not documents.** A save is a list of small typed operations
(`upsert` / `delete` / `insert` / `move` / `review`), never "here is the
whole file". That is what makes a change describable in the log, reversible,
and checkable field by field — and it means a buggy client can't blank the
map by POSTing `{}`.

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

import provenance
import schema
import validation
from filelock import LockTimeout, exclusive
from jsonio import iso_utc, read_json, write_json_atomic

log = logging.getLogger("atlas.data.dataset")

# How many revisions of history to keep. The dataset is ~40 KB, so 50
# generations is ~2 MB — cheap enough that pruning is about tidiness, not space.
KEEP_REVISIONS = 50

OPS = ("upsert", "insert", "delete", "move", provenance.REVIEW)


def site_lock_path(site, revisions_dir=None):
    """The sidecar every writer of a site's map contends on: the editor's
    saves (`DatasetStore`), and in db mode the importers and the relay ingest,
    which write rows straight into the tables (2026-11-15: they took no lock,
    so a save that loaded before an import and wrote after it put the import
    back as it was)."""
    if revisions_dir is None:
        import settings   # lazy: the CLI imports this before its env is final
        revisions_dir = settings.REVISIONS_DIR
    return os.path.join(revisions_dir, f"{site}-write.lock")


def site_lock(site, revisions_dir=None):
    """Hold a site's write lock (`site_lock_path`). Raises `filelock.LockTimeout`
    when another writer will not let go."""
    path = site_lock_path(site, revisions_dir)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return exclusive(path)


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
        for name, inner, target, _ in schema.ref_fields(other_key):
            if target != section_key:
                continue
            for i, entry in enumerate(data.get(other_key) or []):
                if not isinstance(entry, dict):
                    continue
                if inner is not None:
                    hit = any(
                        isinstance(sub, dict) and entry_id in schema.as_list(sub.get(inner))
                        for sub in (entry.get(name) or []))
                else:
                    hit = entry_id in schema.as_list(entry.get(name))
                if hit:
                    out.append({
                        "section": other_key,
                        "index": i,
                        "field": name if inner is None else f"{name}.{inner}",
                        "label": _entry_label(other_key, entry, i),
                    })
    return out


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
        refs = [(name, inner) for name, inner, target, _ in schema.ref_fields(other_key)
                if target == section_key]
        if not refs:
            continue
        kept = []
        for i, entry in enumerate(data.get(other_key) or []):
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            drop = False
            for path, inner in refs:
                fld = schema.field(other_key, path)
                if inner is not None:
                    for sub in entry.get(path) or []:
                        if isinstance(sub, dict) and inner in sub:
                            sub[inner] = [v for v in schema.as_list(sub[inner]) if v != entry_id]
                    continue
                if entry.get(path) == entry_id or entry_id in schema.as_list(entry.get(path)):
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


def _apply_review(data, op, s):
    # "A person has checked this place." It changes nothing on the place;
    # the stamp is written by provenance.stamp, which reads this same op.
    section_key = op.get("section")
    if section_key != provenance.SECTION:
        raise RejectedError(f"only a place can be marked as checked, not a {s['singular']}")
    index = _find_index(data, section_key, op.get("id")) if isinstance(op.get("id"), str) else -1
    if index < 0:
        raise RejectedError(f"{section_key}: there is no such place to mark as checked")
    return f"checked {s['noun']} {_entry_label(section_key, data[section_key][index], index)}"


def _refuse_url_credentials(section_key, body):
    """Refuse what is being saved if a URL in it carries a user name or password.
    Asked of the op's own body, so it never blocks an unrelated edit of a map
    that already holds one (2026-11-12; see `schema.carries_credentials`)."""
    if schema.carries_credentials(body):
        raise RejectedError(f"{section_key}: {schema.URL_CREDENTIALS}")


def _apply_object(data, op, s):
    """An op on a section that is one mapping (`meta`): only `upsert` means anything."""
    kind, section_key = op.get("op"), op.get("section")
    if kind != "upsert":
        raise RejectedError(f"{section_key} can only be updated, not {kind}ed")
    body = op.get("body")
    if not isinstance(body, dict):
        raise RejectedError(f"{section_key}: body must be an object")
    _refuse_url_credentials(section_key, body)
    merged = dict(data.get(section_key) or {})
    merged.update(body)
    data[section_key] = merged
    return f"updated {s['singular']}"


def _apply_upsert(data, op, s, entries):
    """`upsert` and `insert`: change the entry the op names, or add a new one."""
    kind, section_key = op.get("op"), op.get("section")
    body = op.get("body")
    if not isinstance(body, dict):
        raise RejectedError(f"{section_key}: body must be an object")
    _refuse_url_credentials(section_key, body)
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


def _apply_delete(data, op, s, entries):
    section_key = op.get("section")
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


def _apply_move(data, op, s, entries):
    section_key = op.get("section")
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


#: The ops that work on a list section's entries. `review` and the one-mapping
#: sections are answered before this table is read.
_LIST_OPS = {
    "upsert": _apply_upsert,
    "insert": _apply_upsert,
    "delete": _apply_delete,
    "move": _apply_move,
}


def _apply_one(data, op):
    """Apply a single op in place. Returns a human sentence describing it."""
    kind = op.get("op")
    if kind not in OPS:
        raise RejectedError(f"unknown operation {kind!r}")

    section_key = op.get("section")
    s = _section_or_reject(section_key)

    if kind == provenance.REVIEW:
        return _apply_review(data, op, s)

    if s["kind"] == "object":
        return _apply_object(data, op, s)

    _place_section(data, section_key)
    entries = data[section_key]
    if not isinstance(entries, list):
        raise RejectedError(f"{section_key} is not a list in this dataset")

    handler = _LIST_OPS.get(kind)
    if handler is None:
        raise RejectedError(f"unknown operation {kind!r}")
    return handler(data, op, s, entries)


def _copy(data):
    """A deep copy of a JSON document. Through the C encoder and decoder, a
    fraction of `copy.deepcopy`'s time (2026-11-15: a sixth of every save).
    Exact for what both stores hand it (a document read from JSON: string
    keys, lists, no tuples); a value JSON cannot hold at all falls back to
    deepcopy."""
    try:
        return json.loads(json.dumps(data, ensure_ascii=False))
    except (TypeError, ValueError):
        return copy.deepcopy(data)


def apply_ops(data, ops):
    """Apply a batch to a copy of `data`. Returns (new_data, [summaries])."""
    if not isinstance(ops, list) or not ops:
        raise RejectedError("no changes were sent")
    if len(ops) > 500:
        raise RejectedError("too many changes in one save (max 500)")
    out = _copy(data)
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

def _by_label(data):
    """{how problem lines name an entry: [that entry as JSON text, …]}: a
    list section's entries by `validation.label_of` (an id, a title, or a
    position), an object section by its key."""
    out = {}
    for key in schema.SECTION_ORDER:
        s = schema.get(key)
        if s is None or s["store"] != "dataset" or key not in data:
            continue
        value = data[key]
        if s["kind"] == "object" or not isinstance(value, list):
            out.setdefault(key, []).append(json.dumps(value, sort_keys=True, default=str))
            continue
        for i, entry in enumerate(value):
            out.setdefault(validation.label_of(key, entry, i), []).append(
                json.dumps(entry, sort_keys=True, default=str))
    return out


def _introduced(before, after, problems):
    """(refused, tolerated): the problems a save may not land with, and those
    it may.

    `validation` refuses a *write* that would introduce problems (its own
    doctrine), but this refused any save while any problem stood: one an
    import or a hand edit of the file left (a NetBox device with no role, a
    stone with no severity) made every later editor save fail, though none of
    them could mend more than the one entry it was about (2026-11-15).

    A problem is let through, and logged, only when the map already had it
    (counted: a second identical one is new) AND the entry it names is exactly
    what it was. Anything the save changed, inserted, renamed or moved into
    that name is checked as new, so a form never saves a broken entry because
    it was broken before, and a delete that frees a name (`route #29`) cannot
    hand its old problem to a new entry. An entry named by position whose
    position moved reads as changed: that refuses, the safe way. The map as it
    was is validated only here, when the new one has problems: a clean save
    pays for one validation, as before."""
    from collections import Counter
    old = Counter(validation.validate(before, strict=True))
    was, now = _by_label(before), _by_label(after)
    refused, tolerated = [], []
    for p in problems:
        label = p.split(": ", 1)[0]
        unchanged = label in was and was.get(label) == now.get(label)
        if old[p] > 0 and unchanged:
            old[p] -= 1
            tolerated.append(p)
        else:
            refused.append(p)
    return refused, tolerated


def content_stamp(data):
    """A short, clock-independent version token for optimistic concurrency."""
    blob = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


class DatasetStore:
    """Shared machinery. Subclasses supply `_load` and `_save`."""

    def __init__(self, revisions_dir, site="default"):
        #: where snapshots and the journal live
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
        return site_lock_path(self.site, self.revisions_dir)

    # -- public API ----------------------------------------------------------
    def read(self):
        """(data, stamp) as the editor sees it — no overlays, no redaction.

        Deliberately unlocked. `os.replace` is atomic, so a reader gets the
        whole old document or the whole new one, and making every map load
        queue behind an editor would be a bad trade for no gain.
        """
        data = self._load()
        return data, content_stamp(data)

    def stamp(self):
        """The stamp `read` would give, for a caller that wants only that
        (the roster, the Desk's boot). A backend may remember it; a stale one
        can only make the next save a 409, never a lost write, since `apply`
        stamps the document it loads under the lock."""
        return self.read()[1]

    def apply(self, ops, actor="unknown", expect=None, note="", origin=None):
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
        return self._locked(self._apply_locked, ops, actor, expect, note, origin)

    def _locked(self, fn, *args):
        """Run one read-modify-write under the lock every writer contends on."""
        try:
            with exclusive(self._lock_path()):
                return fn(*args)
        except LockTimeout as e:
            raise BusyError(str(e)) from e

    def _apply_locked(self, ops, actor, expect, note, origin=None):
        before = self._load()
        stamp = content_stamp(before)
        if expect and expect != stamp:
            raise ConflictError(
                "someone else changed the map while you were editing — "
                "reload to see their version, then make your change again")

        after, summaries = apply_ops(before, ops)
        # who charted what, and whether a person has checked it (provenance.py).
        # `origin` is blank for a hand edit and names the import otherwise.
        provenance.stamp(before, after, ops, actor, origin)

        problems = validation.validate(after, strict=True)
        if problems:
            refused, tolerated = _introduced(before, after, problems)
            if refused:
                raise RejectedError(refused)
            log.warning("dataset write by %s saved over %d problem(s) already on the map: %s",
                        actor, len(tolerated), "; ".join(tolerated[:5]))

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

    def _journal(self):
        """Every entry in the journal, newest first. Reads the one file and
        touches no snapshot, which is all the next id and the pruning need."""
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
            # A line that is not an entry, or whose id cannot name a snapshot,
            # stops every reader here, before anything is written, as it did
            # when each of them went through `revisions()`.
            self._snapshot_path(entry.get("id", 0))
        return out

    def _next_revision_id(self):
        entries = self._journal()
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
            # compact (2026-11-15): nobody diffs or hand-edits a snapshot, and
            # with no indent the encoder runs in C, a fraction of the time
            # (the indented one was a quarter of every save)
            write_json_atomic(self._snapshot_path(revision_id), before,
                              indent=None, keep_backup=False)
            with open(self._journal_path(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._prune()
        except OSError as e:
            # History is valuable, but not more valuable than the edit. Losing
            # the journal must not lose the change the user just made.
            log.warning("could not record revision %d: %s", revision_id, e)
        return revision_id

    def _prune(self):
        entries = self._journal()
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
        out = self._journal()
        if limit is not None:
            out = out[:limit]
        for entry in out:
            entry["revertable"] = os.path.exists(self._snapshot_path(entry.get("id", 0)))
        return out

    def revert(self, revision_id, actor="unknown", expect=None):
        """Put the map back to how it was before `revision_id`.

        Recorded as a revision of its own, so an unwanted revert is itself
        undoable — the history only ever grows forwards. Same lock as `apply`:
        a revert is a read-modify-write like any other. `expect` refuses it if the
        map has moved on: an Undo beside one import must not take later edits too.
        """
        return self._locked(self._revert_locked, revision_id, actor, expect)

    def _revert_locked(self, revision_id, actor, expect=None):
        # One load serves both the stamp check and the revert. It happens here
        # only when there is a stamp to check, so a revert without one still
        # hears about a pruned snapshot before an unreadable dataset.
        before = self._load() if expect else None
        if expect and expect != content_stamp(before):
            raise ConflictError("the map has changed since then — use the change log "
                                "in the Desk to see what would be undone")
        snapshot = schema.upgrade(read_json(self._snapshot_path(int(revision_id))))
        if not isinstance(snapshot, dict):
            raise RejectedError(
                f"revision {revision_id} can no longer be undone — its snapshot "
                f"has been pruned (the last {KEEP_REVISIONS} are kept)")
        problems = validation.validate(snapshot, strict=True)
        if before is None and problems:
            before = self._load()
        if problems:
            # what the map has now an undo may bring back (2026-11-15: a save
            # that landed over a problem already there snapshots it, and its
            # undo was refused for it); only what the map does not have refuses
            from collections import Counter
            have = Counter(validation.validate(before, strict=True))
            new = []
            for p in problems:
                if have[p] > 0:
                    have[p] -= 1
                else:
                    new.append(p)
            if new:
                raise RejectedError(
                    [f"that older version no longer validates: {p}" for p in new[:5]])
        if before is None:
            before = self._load()
        provenance.restamp_revert(before, snapshot, actor)
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
        self._stamp_memo = (None, None)   # (the file's (mtime_ns, size, ino), its stamp)

    def stamp(self):
        """Remembered while the file is the same file (2026-11-15, stage 5:
        the roster re-read and hashed the whole map on every request for this
        one string, ~45 ms at 10,000 places). Every save replaces the file,
        which moves its mtime (`write_json_atomic` copies the mode, not the
        times) and its inode."""
        try:
            st = os.stat(self.path)
            key = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return super().stamp()
        if self._stamp_memo[0] != key:
            self._stamp_memo = (key, super().stamp())
        return self._stamp_memo[1]

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
        return schema.upgrade(data)   # an old section name is saved back as today's

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
        self._stamp_memo = (None, None)   # (the site's (data_version, updated_at), its stamp)

    def stamp(self):
        """Remembered while the site's `data_version` and `updated_at` stand
        (2026-11-15, stage 5): every write bumps them (a save, an import, the
        importers). A stale one can only cause a 409."""
        from store import session_scope, site_stamp
        with session_scope() as session:
            key = site_stamp(session, self.site)
        if key is None:
            return super().stamp()
        if self._stamp_memo[0] != key:
            self._stamp_memo = (key, super().stamp())
        return self._stamp_memo[1]

    def _load(self):
        from store import dump_labdata, session_scope
        with session_scope() as session:
            data = schema.upgrade(dump_labdata(session, self.site))
        if data is None:
            raise RejectedError(
                f"site {self.site!r} has not been seeded yet — import a dataset first "
                f"(python cli.py import-json --site {self.site} ...)")
        return data

    def _save(self, data):
        from store import load_labdata, session_scope
        with session_scope() as session:
            # only the rows that differ (2026-11-15): the same end state as
            # the import's full replace, which the tests hold it to
            load_labdata(session, data, site_slug=self.site, source="manual", only_changed=True)


def build_store(backend, *, data_path, default_path, site, revisions_dir):
    """The store for this deployment's configuration."""
    if backend == "db":
        return DbDatasetStore(site, revisions_dir)
    return FileDatasetStore(data_path, default_path, revisions_dir, site)
