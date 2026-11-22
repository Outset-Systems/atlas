import logging
import math
import os
import re
import time

import settings
from jsonio import iso_utc
from jsonstore import JsonStore

log = logging.getLogger("atlas.live.heartbeats")

KEEP_RUNS = 20

CADENCE_SECONDS = {
    "continuous": 3600,
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2678400,
}

GRACE_FRACTION = 0.25
GRACE_FLOOR = 900

VERDICT_STATE = {
    "kept": "healthy",
    "late": "degraded",
    "missed": "down",
    "failed": "down",
    "awaited": None,
}

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhdw]?)\s*$", re.I)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "": 60}


def _now():
    return time.time()


def _stamp(epoch):
    return iso_utc(epoch)


def parse_duration(text, default=None):
    if text is None or text == "":
        return default
    if isinstance(text, (int, float)):
        return float(text) * 60 if text else default
    match = _DURATION.match(str(text))
    if not match:
        return default
    return float(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]


def key_for(rite):
    explicit = (rite.get("key") or "").strip()
    if explicit:
        return _slug(explicit)
    return _slug(rite.get("name") or "")


def _slug(text):
    out = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return out[:64]


def _shape(stored):
    if not isinstance(stored, dict):
        return {"beats": {}}
    beats = stored.get("beats")
    return {"beats": beats if isinstance(beats, dict) else {}}


_STORE = JsonStore(lambda: settings.BEATS_PATH, _shape)


def record_beat(key, status="ok", note="", duration_s=None, source=""):
    key = _slug(key)
    if not key:
        raise ValueError("a beat needs a rite key")
    status = "fail" if str(status).lower() in ("fail", "failed", "error", "1") else "ok"
    now = _now()
    beat = {
        "at": _stamp(now),
        "epoch": now,
        "status": status,
        "note": str(note or "")[:300],
        "source": str(source or "")[:64],
    }
    seconds = duration_s
    if isinstance(duration_s, str):
        try:
            seconds = float(duration_s)
        except ValueError:
            seconds = parse_duration(duration_s)
    if isinstance(seconds, (int, float)) and math.isfinite(seconds) and seconds >= 0:
        beat["duration_s"] = round(float(seconds), 2)

    with _STORE.locked():
        store = _STORE.load()
        entry = store["beats"].get(key)
        if not isinstance(entry, dict):
            entry = {"runs": []}
        runs = entry.get("runs")
        runs = runs if isinstance(runs, list) else []
        runs.append({k: beat[k] for k in ("at", "status") if k in beat}
                    | ({"duration_s": beat["duration_s"]} if "duration_s" in beat else {}))
        entry = dict(beat)
        entry["runs"] = runs[-KEEP_RUNS:]
        store["beats"][key] = entry
        _STORE.save(store)

    log.info("rite %s reported %s%s", key, status, f" ({note})" if note else "")
    return entry


def sweep_dropped_files():
    directory = settings.BEATS_DIR
    adopted = []
    try:
        names = os.listdir(directory)
    except OSError:
        return adopted

    for name in sorted(names):
        path = os.path.join(directory, name)
        key = _slug(name)
        if not key or name.startswith("."):
            continue
        try:
            if not os.path.isfile(path):
                continue
            mtime = os.path.getmtime(path)
            status, note = "ok", ""
            if os.path.getsize(path) > 0:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    note = handle.readline().strip()[:300]
                first = note.split(" ", 1)[0].strip(":,-—").lower()
                if first in ("fail", "failed", "error"):
                    status = "fail"
        except OSError as e:
            log.warning("could not adopt beat file %s: %s", name, e)
            continue

        try:
            with _STORE.locked():
                store = _STORE.load()
                entry = store["beats"].get(key)
                entry = entry if isinstance(entry, dict) else {"runs": []}
                runs = entry.get("runs")
                runs = runs if isinstance(runs, list) else []
                run = {"at": _stamp(mtime), "status": status}
                already = (entry.get("source") == "file"
                           and any(isinstance(r, dict) and r.get("at") == run["at"] for r in runs))
                if not already:
                    runs.append(run)
                store["beats"][key] = {
                    "at": _stamp(mtime), "epoch": mtime, "status": status,
                    "note": note, "source": "file", "runs": runs[-KEEP_RUNS:],
                }
                _STORE.save(store)
        except OSError as e:
            log.warning("could not record dropped beat %s: %s", key, e)
            continue
        adopted.append(key)
        try:
            os.remove(path)
        except OSError as e:
            log.warning("recorded beat %s but could not remove its file: %s", name, e)
    return adopted


def forget_all():
    with _STORE.locked():
        _STORE.save({"beats": {}})


def expectations(rite):
    interval = parse_duration(rite.get("expect_every"))
    if interval is None:
        interval = CADENCE_SECONDS.get((rite.get("cadence") or "").strip().lower())
    if not interval:
        return None, None
    grace = parse_duration(rite.get("grace"))
    if grace is None:
        grace = max(interval * GRACE_FRACTION, GRACE_FLOOR)
    return float(interval), float(grace)


def _verdict(beat, interval, grace, now):
    if interval is None:
        return "unwatched", None
    if not beat or not beat.get("epoch"):
        return "awaited", None
    age = now - float(beat["epoch"])
    if beat.get("status") == "fail":
        return "failed", age
    if age <= interval:
        return "kept", age
    if age <= interval + grace:
        return "late", age
    return "missed", age


def status_for(rites, now=None):
    now = now if now is not None else _now()
    store = _STORE.load()
    out = []
    for rite in rites if isinstance(rites, list) else []:
        if not isinstance(rite, dict):
            continue
        key = key_for(rite)
        beat = store["beats"].get(key) if key else None
        beat = beat if isinstance(beat, dict) else None
        interval, grace = expectations(rite)
        verdict, age = _verdict(beat, interval, grace, now)
        row = {
            "key": key,
            "verdict": verdict,
            "expect_every": interval,
            "grace": grace,
        }
        if age is not None:
            row["age_s"] = round(age, 1)
        if beat:
            row["last"] = {k: beat[k] for k in
                           ("at", "status", "note", "source", "duration_s") if k in beat}
            runs = beat.get("runs")
            if isinstance(runs, list) and runs:
                row["runs"] = runs[-KEEP_RUNS:]
        out.append(row)
    return out


JOB_WORDS = ("note", "source")


def without_job_words(row):
    last = row.get("last")
    if not isinstance(last, dict):
        return row
    return {**row, "last": {k: v for k, v in last.items() if k not in JOB_WORDS}}


def keys_of(rites):
    return {key_for(r) for r in rites or [] if isinstance(r, dict)}


def as_feed(rites, now=None):
    rites = rites if isinstance(rites, list) else []
    feed = {}
    by_key = {}
    for rite in rites:
        if isinstance(rite, dict):
            by_key.setdefault(key_for(rite), rite.get("name") or "")
    for row in status_for(rites, now=now):
        state = VERDICT_STATE.get(row["verdict"])
        if state:
            feed[row["key"]] = {"state": state, "name": by_key.get(row["key"], row["key"]),
                                "verdict": row["verdict"]}
    return feed
