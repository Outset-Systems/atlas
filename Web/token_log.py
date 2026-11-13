"""THE TOKEN READ LOG — what each API token read, when, and from where.

A token's `last_used` says a tool was here recently. It cannot answer the
question that matters after a vendor incident or a leaked token: what left.
This is that record. One line per request a token made, appended to
`token-reads.jsonl` beside the dataset:

    when · which token · the address it came from · the route or the MCP tool
    and its arguments · the answer's status, size and SHA-256 · how many
    charted places the answer named

The answer itself is not kept. The hash proves what a given answer was if the
same question is asked of the same map again; the size and the place count say
how much left without storing a second copy of the map.

WHAT IS AND IS NOT WRITTEN
  * Every request a valid token made, served or refused (wrong kind for the
    route, outside its networks, over the rate limit). A refusal names its
    reason, because a good token used from the wrong place is the signal.
  * Nothing for a request with no token or a bad one. An unauthenticated caller
    must not be able to grow a file on this disk.
  * Tool arguments are a client's words. They are cut to a short length here
    and are shown to admins as text, never as markup.

IT NEVER FAILS A READ. If the line cannot be written the request is still
answered and a warning is logged: a full disk must not turn the map dark. The
price is that the log is evidence of what happened, not a gate on it.

KEPT FOR `ATLAS_AGENT_LOG_DAYS` (90 unless set), and never more than
`MAX_ROWS` lines. Pruning rewrites the file under the same lock an append
takes, so two workers cannot lose each other's lines.

It is also the one thing both gunicorn workers and the stdio pipe write for
every token request, which is why the shared rate limit reads it
(`recent_elsewhere`) instead of keeping a second shared counter.
"""

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
#: A tool argument is a search word or a place id. Anything longer is cut.
MAX_ARG = 200
MAX_ARGS = 12
PRUNE_EVERY_S = 3600
#: How much of the file's end a listing or the rate window will read.
TAIL_BYTES = 4 * 1024 * 1024
RATE_TAIL_BYTES = 256 * 1024
LOCK_WAIT_S = 0.5

#: This process, so a worker can tell its own lines from the other's.
WORKER = secrets.token_hex(3)

_WORD = re.compile(r"[A-Za-z0-9_.\-]+")
_state = threading.Lock()
_pruned_at = 0.0
_seen = {"path": None, "offset": 0, "rows": deque()}


def path():
    return os.path.join(settings.DATA_DIR, FILE)


def keep_days():
    """How long a line is kept. A value that is not a whole number of days, or
    is under one, falls back to the default instead of stopping the app."""
    raw = (envnames.env(DAYS_ENV) or "").strip()
    try:
        days = int(raw) if raw else DEFAULT_DAYS
    except ValueError:
        log.warning("%s=%r is not a number of days; keeping %d", DAYS_ENV, raw, DEFAULT_DAYS)
        return DEFAULT_DAYS
    return days if days >= 1 else DEFAULT_DAYS


def note(**fields):
    """Add what only the route knows (the MCP method, the tool, its arguments)
    to the line this request will write."""
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
    """Every charted place id, hidden ones included: the log is the admin's, and
    it should count a place even where the answer had it scrubbed to a name."""
    try:
        from context import atlas
        data = atlas().dataset()[0]
        return {str(n["id"]) for n in data.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    except Exception:  # noqa: BLE001 — a count is a convenience; the line is still written
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
    """How many distinct charted places an answer names. A place counts when its
    id appears as a whole word anywhere in the JSON, key or value; `None` when
    the answer is not JSON."""
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
    """Write this request's line. `rec` is the token's stored record, `refused`
    the reason when the gate turned a valid token away. Never raises."""
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
    except Exception as e:  # noqa: BLE001 — see IT NEVER FAILS A READ
        log.warning("token read not logged: %s: %s", e.__class__.__name__, e)


def _append(row):
    target = path()
    # ASCII only, on purpose. A client chooses its arguments: a lone surrogate
    # cannot be written as UTF-8 at all (the line would be lost and the read
    # still served), and U+2028 or U+0085 inside a string would split the line
    # for whoever reads the file back. Escaped, neither can happen.
    line = json.dumps(row, separators=(",", ":")) + "\n"
    with exclusive(lock_for(target), timeout=LOCK_WAIT_S):
        fresh = not os.path.exists(target)
        with open(target, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
        if fresh:
            try:
                os.chmod(target, 0o600)
            except OSError:      # a share that will not take modes
                pass
        _prune_if_due(target)


def _prune_if_due(target, force=False):
    """Drop lines past their keep, at most once an hour per process. Called with
    the lock held."""
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
    """Whether a prune would drop anything, told from the oldest line and the
    file's size without reading the rest. Every process asks on its first
    append (each stdio launch is one), and reading a large log whole while
    holding the lock would make the other worker's appends time out."""
    try:
        if os.path.getsize(target) > MAX_ROWS * 300:      # near the row ceiling
            return True
        with open(target, encoding="utf-8") as fh:
            return _stamp(fh.readline()) < cutoff
    except OSError:
        return False


def _stamp(line):
    try:
        return float(json.loads(line).get("t") or 0)
    except (ValueError, AttributeError, TypeError):
        return 0.0       # a line nobody can read is not worth keeping


def prune():
    """Prune now. For the CLI and the tests."""
    target = path()
    if os.path.exists(target):
        with exclusive(lock_for(target), timeout=LOCK_WAIT_S):
            _prune_if_due(target, force=True)


def _tail(target, limit_bytes):
    """The end of the file as whole lines, oldest first."""
    try:
        size = os.path.getsize(target)
        with open(target, "rb") as fh:
            if size > limit_bytes:
                fh.seek(size - limit_bytes)
                fh.readline()            # the cut landed mid-line
            return fh.read().decode("utf-8", "replace").split("\n")
    except OSError:
        return []


def rows(token=None, limit=200):
    """The newest lines first, for one token or for all. Reads at most the last
    few megabytes: a listing is for looking, and the file is the full record."""
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
    """How many requests this token was SERVED in the last `window` seconds by
    other processes: the other worker, or a stdio pipe. This process counts its
    own in memory, before the line exists.

    Reads only what was appended since the last call. A prune makes the file
    shorter than the place we stopped, and then the end is read again.
    """
    target = path()
    now = time.time()
    with _state:
        try:
            size = os.path.getsize(target)
        except OSError:
            return 0
        if _seen["path"] != target or size < _seen["offset"]:
            _seen.update(path=target, offset=max(0, size - RATE_TAIL_BYTES), rows=deque())
        if size > _seen["offset"]:
            try:
                with open(target, "rb") as fh:
                    fh.seek(_seen["offset"])
                    chunk = fh.read(size - _seen["offset"])
            except OSError:
                return 0
            end = chunk.rfind(b"\n") + 1          # only whole lines; the rest next time
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
