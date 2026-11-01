"""THE RITES, told the truth — what actually turned, and when.

The rites have always been a promise. Twenty automations listed with the hour
they are supposed to run, and nothing anywhere checking whether one ever did.
That is this lab's recurring failure, not a hypothetical: the suite database
backup was dead from April to July and looked exactly like a backup that
worked, and the download host's Watchtower is running right now, healthy in `docker ps`,
having not updated an image in months. A schedule is intent. This is the
record of what happened.

**The shape.** A rite touches something when it succeeds. The Atlas keeps the
newest beat and a short tail behind it, then compares the age of the newest
against how often the rite claims to turn. Past that interval it is late; past
the interval *and* its grace it is missed. A missed rite is an event in THE
ANNALS like any other fault, so it inherits acknowledgement — "yes, I know,
The download host is off this week" is a thing you can say to it.

**Two ways to report, because one is never enough.** A job that can reach the
app POSTs to `/api/rites/<key>/beat` carrying the shared token. A job that
cannot — in the suite deployment the port is unpublished and the app lives
behind the Hub — touches a file under `/data/beats/`, which anything holding
the volume can do, including `ssh app-host touch …` from another host. Both
land in the same store and are indistinguishable afterwards.

**What is deliberately not here.** No parsing of `when` into a schedule.
"Sun 03:00 UTC" and "nightly, after the sweep" are what make the scene
readable by a human, and a half-working cron parser that silently misreads one
rite in twenty is worse than no parser: it would report confidently and be
wrong. A rite states `expect_every`, or it inherits the interval its cadence
implies. Both are visible in the Desk, so a wrong answer is an edit away.

**Why beats are not events themselves.** A rite that runs every five minutes
would write 288 rows a day and drown the annals. Only *transitions* are
narrated — kept → missed, missed → kept — which is the same rule the map's
own history follows.
"""

import logging
import math
import os
import re
import time

import settings
from jsonio import iso_utc
from jsonstore import JsonStore

log = logging.getLogger("atlas.live.heartbeats")

#: How many previous turnings to keep per rite. Enough to see "it has failed
#: the last three nights" in the scene; small enough that the file stays a
#: few tens of KB with a hundred rites.
KEEP_RUNS = 20

#: What a cadence implies when a rite doesn't say `expect_every`. Deliberately
#: generous — the point is catching *dead*, not policing punctuality.
CADENCE_SECONDS = {
    "continuous": 3600,          # an hour of silence from something continuous
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2678400,          # 31 days
}

#: Grace before a late rite is called missed, when it doesn't set its own:
#: a quarter of its interval, never less than fifteen minutes.
GRACE_FRACTION = 0.25
GRACE_FLOOR = 900

#: Verdicts, and the marker state each maps onto so THE ANNALS can record a
#: rite exactly like it records a place. `awaited` has no state on purpose —
#: a rite that has never reported is not yet a fault, it is unwired, and
#: narrating forty of them the day this ships would bury the real ones.
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
    """`"6h"` → 21600. Bare numbers are minutes. Unparseable → `default`.

    Lenient on purpose: this reads a hand-typed field, and the cost of
    rejecting `"24 h"` is a rite that silently never checks.
    """
    if text is None or text == "":
        return default
    if isinstance(text, (int, float)):
        return float(text) * 60 if text else default
    match = _DURATION.match(str(text))
    if not match:
        return default
    return float(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]


def key_for(rite):
    """The stable name a rite reports under.

    An explicit `key` wins. Otherwise the name is slugified, so a rite works
    the moment it is charted and only needs a key if it is ever renamed — at
    which point the old beats belong to the old slug, which is why `key`
    exists at all.
    """
    explicit = (rite.get("key") or "").strip()
    if explicit:
        return _slug(explicit)
    return _slug(rite.get("name") or "")


def _slug(text):
    out = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return out[:64]


# ── The store ────────────────────────────────────────────────────────────────
def _shape(stored):
    if not isinstance(stored, dict):
        return {"beats": {}}
    beats = stored.get("beats")
    return {"beats": beats if isinstance(beats, dict) else {}}


#: THE RITES: {beats: {key: {...}}}. Path read live so a settings reload lands.
_STORE = JsonStore(lambda: settings.BEATS_PATH, _shape)


def record_beat(key, status="ok", note="", duration_s=None, source=""):
    """Write down that a rite turned. Returns the stored beat.

    `status` is `ok` or `fail` — a rite that reports its own failure is more
    useful than one that only ever reports success, because the difference
    between "did not run" and "ran and broke" is the difference between
    looking at the scheduler and looking at the job.
    """
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
        # The field is named in seconds, so a bare "4.2" is 4.2 s. Only a
        # unit-suffixed string ("4m", "1.5h") goes through `parse_duration`,
        # whose bare-number-means-minutes rule is for the hand-typed
        # `expect_every`, not for this.
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
    """Adopt any file dropped in `/data/beats/` as a beat, then remove it.

    The file's *name* is the rite key and its mtime is the turning, so the
    entire client side of this is `touch /data/beats/suite-db-backup` — no
    token, no curl, no dependency on the app being up at that instant. If the
    file has content, its first line becomes the note, and a first word of
    `fail` reports a failure.

    Returns the keys adopted. Never raises: a rite that cannot report must not
    be able to take the map down with it.
    """
    directory = settings.BEATS_DIR
    adopted = []
    try:
        names = os.listdir(directory)
    except OSError:
        return adopted                      # no drop directory — nothing to do

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
                # `fail: rsync exited 24` is how a person writes this, so the
                # marker is read without its punctuation rather than missed.
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
                runs.append(run)
                store["beats"][key] = {
                    "at": _stamp(mtime), "epoch": mtime, "status": status,
                    "note": note, "source": "file", "runs": runs[-KEEP_RUNS:],
                }
                _STORE.save(store)
        except OSError as e:
            # The file stays for the next sweep: removing it first and then
            # failing to write the beat lost the turning entirely.
            log.warning("could not record dropped beat %s: %s", key, e)
            continue
        adopted.append(key)
        try:
            os.remove(path)
        except OSError as e:
            log.warning("recorded beat %s but could not remove its file: %s", name, e)
    return adopted


def forget_all():
    """Clear every beat. Tests, and a deliberate operator reset."""
    with _STORE.locked():
        _STORE.save({"beats": {}})


# ── The verdict ──────────────────────────────────────────────────────────────
def expectations(rite):
    """`(interval_seconds, grace_seconds)` for one rite, or `(None, None)`.

    `None` means this rite is not watched — a cadence the map doesn't know how
    to time, and no explicit interval. It stays listed and stays uncoloured
    rather than being guessed at.
    """
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
    """Every rite with what actually happened to it, in dataset order.

    Pure: reads the store once and answers, so the scene, the events recorder
    and the tests all see the identical verdict for the identical instant.
    """
    now = now if now is not None else _now()
    store = _STORE.load()
    out = []
    for rite in rites or []:
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


def as_feed(rites, now=None):
    """`{key: {"state": …, "name": …}}` for the rites THE ANNALS should watch.

    Only verdicts with a marker state appear, so `awaited` and `unwatched`
    never reach the history.
    """
    feed = {}
    by_key = {}
    for rite in rites or []:
        if isinstance(rite, dict):
            by_key.setdefault(key_for(rite), rite.get("name") or "")
    for row in status_for(rites, now=now):
        state = VERDICT_STATE.get(row["verdict"])
        if state:
            feed[row["key"]] = {"state": state, "name": by_key.get(row["key"], row["key"]),
                                "verdict": row["verdict"]}
    return feed
