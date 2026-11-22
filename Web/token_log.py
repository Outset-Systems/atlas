import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import deque

from flask import g, has_request_context, request

import envnames
import settings
from filelock import exclusive, lock_for
from jsonio import iso_utc

log = logging.getLogger("atlas.api.token_log")

FILE = "token-reads.jsonl"
DAYS_ENV = "ATLAS_AGENT_LOG_DAYS"
DEFAULT_DAYS = 90
MAX_ROWS = 200_000
MAX_ARG = 200
MAX_ARGS = 12
PRUNE_EVERY_S = 3600
TAIL_BYTES = 4 * 1024 * 1024
RATE_TAIL_BYTES = 256 * 1024
LOCK_WAIT_S = 0.5

WORKER = secrets.token_hex(3)

_WORD = re.compile(r"[A-Za-z0-9_.\-]+")
_state = threading.Lock()
_pruned_at = 0.0
_seen = {"path": None, "offset": 0, "rows": deque()}


def path():
    return os.path.join(settings.DATA_DIR, FILE)


def keep_days():
    raw = (envnames.env(DAYS_ENV) or "").strip()
    try:
        days = int(raw) if raw else DEFAULT_DAYS
    except ValueError:
        log.warning("%s=%r is not a number of days; keeping %d", DAYS_ENV, raw, DEFAULT_DAYS)
        return DEFAULT_DAYS
    return days if days >= 1 else DEFAULT_DAYS


def note(**fields):
    if has_request_context():
        g.token_read = {**(g.get("token_read") or {}), **fields}


def _short(value):
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= MAX_ARG else text[:MAX_ARG] + "…"


def _args(raw):
    if not isinstance(raw, dict):
        return None
    return {str(k)[:40]: _short(v) for k, v in list(raw.items())[:MAX_ARGS]}


def _place_ids():
    try:
        from context import atlas
        data = atlas().dataset()[0]
        return {str(n["id"]) for n in data.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    except Exception:
        return set()


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def places_named(body, ids):
    if not ids:
        return 0
    try:
        doc = json.loads(body)
    except ValueError:
        return None
    found = set()
    for text in _strings(doc):
        for word in _WORD.findall(text):
            if word in ids:
                found.add(word)
    return len(found)


def record(rec, kind, ip, resp, refused=None):
    try:
        now = time.time()
        said = g.get("token_read") or {}
        row = {"t": round(now, 3), "at": iso_utc(now), "token": rec.get("id"),
               "name": rec.get("name"), "kind": kind, "ip": ip,
               "door": "mcp" if request.path.endswith("/mcp") else "rest",
               "path": request.path, "status": resp.status_code, "w": WORKER}
        for key in ("method", "tool"):
            if said.get(key):
                row[key] = str(said[key])[:80]
        args = _args(said.get("args"))
        if args:
            row["args"] = args
        if refused:
            row["refused"] = refused
        else:
            body = resp.get_data()
            row["bytes"] = len(body)
            row["sha256"] = hashlib.sha256(body).hexdigest()
            if resp.status_code < 400 and resp.mimetype == "application/json":
                row["places"] = places_named(body, _place_ids())
        _append(row)
    except Exception as e:
        log.warning("token read not logged: %s: %s", e.__class__.__name__, e)


def _append(row):
    target = path()
    line = json.dumps(row, separators=(",", ":")) + "\n"
    with exclusive(lock_for(target), timeout=LOCK_WAIT_S):
        fresh = not os.path.exists(target)
        with open(target, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
        if fresh:
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
        _prune_if_due(target)


def _prune_if_due(target, force=False):
    global _pruned_at
    now = time.time()
    if not force and now - _pruned_at < PRUNE_EVERY_S:
        return
    _pruned_at = now
    cutoff = now - keep_days() * 86400
    if not force and not _worth_pruning(target, cutoff):
        return
    with open(target, encoding="utf-8") as fh:
        lines = fh.readlines()
    kept = [ln for ln in lines if _stamp(ln) >= cutoff][-MAX_ROWS:]
    if len(kept) == len(lines):
        return
    tmp = f"{target}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(kept)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, target)
    log.info("token read log pruned: %d of %d lines kept", len(kept), len(lines))


def _worth_pruning(target, cutoff):
    try:
        if os.path.getsize(target) > MAX_ROWS * 300:
            return True
        with open(target, encoding="utf-8") as fh:
            return _stamp(fh.readline()) < cutoff
    except OSError:
        return False


def _stamp(line):
    try:
        return float(json.loads(line).get("t") or 0)
    except (ValueError, AttributeError, TypeError):
        return 0.0


def prune():
    target = path()
    if os.path.exists(target):
        with exclusive(lock_for(target), timeout=LOCK_WAIT_S):
            _prune_if_due(target, force=True)


def _tail(target, limit_bytes):
    try:
        size = os.path.getsize(target)
        with open(target, "rb") as fh:
            if size > limit_bytes:
                fh.seek(size - limit_bytes)
                fh.readline()
            return fh.read().decode("utf-8", "replace").split("\n")
    except OSError:
        return []


def rows(token=None, limit=200):
    out = []
    for line in reversed(_tail(path(), TAIL_BYTES)):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or (token and row.get("token") != token):
            continue
        row.pop("w", None)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def recent_elsewhere(token, window=60.0):
    target = path()
    now = time.time()
    with _state:
        try:
            st = os.stat(target)
        except OSError:
            return 0
        size, ident = st.st_size, (st.st_dev, st.st_ino)
        if _seen["path"] != target or size < _seen["offset"] or _seen.get("ident") != ident:
            _seen.update(path=target, ident=ident,
                         offset=max(0, size - RATE_TAIL_BYTES), rows=deque())
        if size > _seen["offset"]:
            try:
                with open(target, "rb") as fh:
                    fh.seek(_seen["offset"])
                    chunk = fh.read(size - _seen["offset"])
            except OSError:
                return 0
            end = chunk.rfind(b"\n") + 1
            _seen["offset"] += end
            for line in chunk[:end].decode("utf-8", "replace").split("\n"):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(row, dict) and row.get("w") != WORKER
                        and not row.get("refused") and isinstance(row.get("t"), (int, float))):
                    _seen["rows"].append((row["t"], row.get("token")))
        seen = _seen["rows"]
        while seen and now - seen[0][0] > window:
            seen.popleft()
        return sum(1 for _, tid in seen if tid == token)
