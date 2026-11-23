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

KEEP_REVISIONS = 50

OPS = ("upsert", "insert", "delete", "move", provenance.REVIEW)


def site_lock_path(site, revisions_dir=None):
    if revisions_dir is None:
        import settings
        revisions_dir = settings.REVISIONS_DIR
    return os.path.join(revisions_dir, f"{site}-write.lock")


def site_lock(site, revisions_dir=None):
    path = site_lock_path(site, revisions_dir)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return exclusive(path)


class ConflictError(Exception):
    pass


class BusyError(Exception):
    pass


class RejectedError(Exception):

    def __init__(self, problems):
        self.problems = problems if isinstance(problems, list) else [str(problems)]
        super().__init__("; ".join(self.problems))



def _section_or_reject(key):
    s = schema.get(key)
    if s is None:
        raise RejectedError(f"unknown section {key!r}")
    if s["store"] != "dataset":
        raise RejectedError(
            f"{key} is not part of the dataset — it is edited through its own "
            f"endpoint (/api/admin/{key})")
    return s


def _find_index(data, section_key, entry_id):
    s = _section_or_reject(section_key)
    id_field = s["id_field"]
    if not id_field:
        return -1
    for i, entry in enumerate(data.get(section_key) or []):
        if isinstance(entry, dict) and entry.get(id_field) == entry_id:
            return i
    return -1


def _target_index(data, op):
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



def dependents(data, section_key, entry_id):
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
    s = schema.get(section_key)
    for field_name in (s["id_field"], s["title_field"]):
        if field_name and isinstance(entry, dict) and entry.get(field_name):
            return str(entry[field_name])
    return f"#{index + 1}"


def _cascade_delete(data, section_key, entry_id):
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
                    if fld and (fld.get("required") or fld.get("follows")):
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
    if section_key == "nodes":
        _unpin(data, entry_id)
    return removed


def _unpin(data, place_id):
    for region in data.get("regions") or []:
        pins = region.get("places") if isinstance(region, dict) else None
        if isinstance(pins, dict) and place_id in pins:
            region["places"] = {k: v for k, v in pins.items() if k != place_id}
    signals = data.get("signals")
    kuma = signals.get("kuma") if isinstance(signals, dict) else None
    if isinstance(kuma, dict):
        signals["kuma"] = {name: target for name, target in kuma.items() if target != place_id}


def _carry_rename(data, section_key, old_id, new_id):
    if not (isinstance(old_id, str) and isinstance(new_id, str)) or not old_id \
            or not new_id or old_id == new_id:
        return 0
    moved = 0
    for other_key, name in schema.followers(section_key):
        entries = data.get(other_key)
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or entry.get(name) != old_id:
                continue
            if not any(entry.get(n) == new_id for o, n in schema.followers(section_key)
                       if o == other_key and n != name):
                moved += 1
            entry[name] = new_id
    return moved



def _place_section(data, section_key):
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
        if not placed and key in order and order.index(key) > want:
            rebuilt[section_key] = []
            placed = True
        rebuilt[key] = data[key]
    if not placed:
        rebuilt[section_key] = []
    data.clear()
    data.update(rebuilt)


def _apply_review(data, op, s):
    section_key = op.get("section")
    if section_key != provenance.SECTION:
        raise RejectedError(f"only a place can be marked as checked, not a {s['singular']}")
    index = _find_index(data, section_key, op.get("id")) if isinstance(op.get("id"), str) else -1
    if index < 0:
        raise RejectedError(f"{section_key}: there is no such place to mark as checked")
    return f"checked {s['noun']} {_entry_label(section_key, data[section_key][index], index)}"


def _refuse_url_credentials(section_key, body):
    if schema.carries_credentials(body):
        raise RejectedError(f"{section_key}: {schema.URL_CREDENTIALS}")


def _apply_object(data, op, s):
    kind, section_key = op.get("op"), op.get("section")
    if kind != "upsert":
        raise RejectedError(f"{section_key} can only be updated, not {kind}ed")
    body = op.get("body")
    if not isinstance(body, dict):
        raise RejectedError(f"{section_key}: body must be an object")
    _refuse_url_credentials(section_key, body)
    merged = dict(data.get(section_key) or {})
    merged.update(body)
    for key, value in body.items():
        if value is None:
            merged.pop(key, None)
    data[section_key] = merged
    return f"updated {s['singular']}"


def _apply_upsert(data, op, s, entries):
    kind, section_key = op.get("op"), op.get("section")
    body = op.get("body")
    if not isinstance(body, dict):
        raise RejectedError(f"{section_key}: body must be an object")
    _refuse_url_credentials(section_key, body)
    index = -1 if kind == "insert" else _target_index(data, op)
    label = _entry_label(section_key,
                         entries[index] if index >= 0 else body,
                         index if index >= 0 else len(entries))
    if index >= 0:
        was = entries[index]
        merged = dict(was)
        merged.update(body)
        for key, value in body.items():
            if value is None:
                merged.pop(key, None)
        entries[index] = merged
        note = ""
        id_field = s["id_field"]
        if id_field:
            carried = _carry_rename(data, section_key, was.get(id_field), merged.get(id_field))
            if carried:
                note = (f" (and {carried} thing{'s' if carried != 1 else ''} that pointed "
                        "at it, carried to the new id)")
        return f"changed {s['noun']} {label}{note}"
    if (section_key == "nodes" and body.get("device") in schema.ENDPOINT_DEVICES
            and "unmanaged" not in body):
        body = {**body, "unmanaged": True}
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


_LIST_OPS = {
    "upsert": _apply_upsert,
    "insert": _apply_upsert,
    "delete": _apply_delete,
    "move": _apply_move,
}


def _apply_one(data, op):
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
    try:
        return json.loads(json.dumps(data, ensure_ascii=False))
    except (TypeError, ValueError):
        return copy.deepcopy(data)



def _port_name(value):
    return value.strip().casefold() if isinstance(value, str) else ""


def _port_row(data, op):
    rows = data.get("interfaces")
    if op.get("section") != "interfaces" or op.get("op") != "upsert" or not isinstance(rows, list):
        return None
    try:
        index = _target_index(data, op)
    except RejectedError:
        return None
    if index < 0 or not isinstance(rows[index], dict):
        return None
    return index, rows[index]


def _note_port(data, seen, ports, at):
    index, was = seen
    now = data["interfaces"][index]
    for entry in ports:
        if entry[0] is was:
            entry[0], entry[3] = now, at
            return
    ports.append([now, was.get("device"), was.get("name"), at])


def _carry_ports(before, data, ports, summaries):
    rows = data.get("interfaces") if isinstance(data.get("interfaces"), list) else []
    cables = data.get("cables") if isinstance(data.get("cables"), list) else []
    had = before.get("interfaces") if isinstance(before.get("interfaces"), list) else []
    renamed = {}
    for row, place, name, at in ports:
        new = row.get("name")
        old = _port_name(name)
        if (not cables or not old or not isinstance(place, str) or row.get("device") != place
                or not isinstance(new, str) or not new.strip() or name.strip() == new.strip()
                or not any(r is row for r in rows)):
            continue
        if sum(1 for r in had if isinstance(r, dict) and r.get("device") == place
               and _port_name(r.get("name")) == old) != 1:
            continue
        renamed[(place, old)] = (new.strip(), at)
    if not renamed:
        return
    laid = before.get("cables") if isinstance(before.get("cables"), list) else []
    was = {c["id"]: c for c in laid if isinstance(c, dict) and isinstance(c.get("id"), str)}
    counts = {}
    for cable in cables:
        prior = was.get(cable.get("id")) if isinstance(cable, dict) and isinstance(cable.get("id"), str) else None
        if prior is None:
            continue
        for side in ("a", "b"):
            place, port = cable.get(side), cable.get(side + "_port")
            hit = renamed.get((place, _port_name(port))) if isinstance(place, str) else None
            if hit and prior.get(side) == place and prior.get(side + "_port") == port:
                cable[side + "_port"] = hit[0]
                counts[hit[1]] = counts.get(hit[1], 0) + 1
    for at, n in counts.items():
        summaries[at] += (f" (and {n} cable{'s' if n != 1 else ''} that named it, "
                          "carried to the new name)")


def apply_ops(data, ops):
    if not isinstance(ops, list) or not ops:
        raise RejectedError("no changes were sent")
    if len(ops) > 500:
        raise RejectedError("too many changes in one save (max 500)")
    out = _copy(data)
    summaries = []
    ports = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise RejectedError(f"change #{i + 1} is not an operation")
        try:
            seen = _port_row(out, op)
            summaries.append(_apply_one(out, op))
            if seen:
                _note_port(out, seen, ports, i)
        except RejectedError as e:
            raise RejectedError([f"change #{i + 1}: {p}" for p in e.problems])
    if ports:
        _carry_ports(data, out, ports, summaries)
    return out, summaries



def _by_label(data):
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
    blob = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


class DatasetStore:

    def __init__(self, revisions_dir, site="default"):
        self.revisions_dir = revisions_dir
        self.site = site

    def _load(self):
        raise NotImplementedError

    def _save(self, data):
        raise NotImplementedError

    def writable(self):
        return True

    def _lock_path(self):
        return site_lock_path(self.site, self.revisions_dir)

    def read(self):
        data = self._load()
        return data, content_stamp(data)

    def stamp(self):
        return self.read()[1]

    def apply(self, ops, actor="unknown", expect=None, note="", origin=None):
        return self._locked(self._apply_locked, ops, actor, expect, note, origin)

    def _locked(self, fn, *args):
        try:
            with exclusive(self._lock_path()):
                return fn(*args)
        except LockTimeout as e:
            raise BusyError(str(e)) from e

    def _apply_locked(self, ops, actor, expect, note, origin=None):
        before = self._load()
        stamp = content_stamp(before)
        if not expect and any(isinstance(op, dict) and op.get("index") is not None for op in ops):
            raise RejectedError("a change to a row addressed by its position needs the "
                                "stamp of the map it was made against: reload and try again")
        if expect and expect != stamp:
            raise ConflictError(
                "someone else changed the map while you were editing — "
                "reload to see their version, then make your change again")

        after, summaries = apply_ops(before, ops)
        provenance.stamp(before, after, ops, actor, origin)

        problems = validation.validate(after, strict=True)
        if problems:
            refused, tolerated = _introduced(before, after, problems)
            if refused:
                raise RejectedError(refused)
            log.warning("dataset write by %s saved over %d problem(s) already on the map: %s",
                        actor, len(tolerated), "; ".join(tolerated[:5]))

        self._save(after)
        revision = self._record(before, actor, summaries, ops, note)
        log.info("dataset write by %s: %s", actor, "; ".join(summaries))
        return {
            "ok": True,
            "stamp": content_stamp(after),
            "revision": revision,
            "changed": summaries,
        }

    def _journal_path(self):
        return os.path.join(self.revisions_dir, f"{self.site}-journal.jsonl")

    def _snapshot_path(self, revision_id):
        return os.path.join(self.revisions_dir, f"{self.site}-r{revision_id:05d}.json")

    def _journal(self):
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
            self._snapshot_path(entry.get("id", 0))
        return out

    def _next_revision_id(self):
        entries = self._journal()
        return (entries[0]["id"] + 1) if entries else 1

    def _record(self, before, actor, summaries, ops, note):
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
                              indent=None, keep_backup=False)
            with open(self._journal_path(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._prune()
        except OSError as e:
            log.warning("could not record revision %d: %s", revision_id, e)
            return None
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
        out = self._journal()
        if limit is not None:
            out = out[:limit]
        for entry in out:
            entry["revertable"] = os.path.exists(self._snapshot_path(entry.get("id", 0)))
        return out

    def revert(self, revision_id, actor="unknown", expect=None):
        return self._locked(self._revert_locked, revision_id, actor, expect)

    def _revert_locked(self, revision_id, actor, expect=None):
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
        self._save(snapshot)
        new_id = self._record(before, actor, summary,
                              [{"op": "revert", "to": int(revision_id)}], "")
        log.info("dataset reverted to r%s by %s", revision_id, actor)
        return {"ok": True, "stamp": content_stamp(snapshot),
                "revision": new_id, "changed": summary}


class FileDatasetStore(DatasetStore):

    def __init__(self, path, default_path, revisions_dir, site="default"):
        super().__init__(revisions_dir, site)
        self.path = path
        self.default_path = default_path
        self._stamp_memo = (None, None)

    def stamp(self):
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
        if not os.path.exists(self.path):
            from labdata import fallback_dataset
            return fallback_dataset(self.default_path)
        data = read_json(self.path)
        if not isinstance(data, dict):
            raise RejectedError(f"the dataset at {self.path} is unreadable")
        return schema.upgrade(data)

    def _save(self, data):
        write_json_atomic(self.path, data, indent=2)


class DbDatasetStore(DatasetStore):

    def __init__(self, site, revisions_dir):
        super().__init__(revisions_dir, site)
        self._stamp_memo = (None, None)

    def stamp(self):
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
            load_labdata(session, data, site_slug=self.site, source="manual", only_changed=True)


def build_store(backend, *, data_path, default_path, site, revisions_dir):
    if backend == "db":
        return DbDatasetStore(site, revisions_dir)
    return FileDatasetStore(data_path, default_path, revisions_dir, site)
