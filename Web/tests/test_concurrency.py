"""Concurrent writers must not lose edits, collide, or corrupt the change log.

Real subprocesses, because that is the production topology: gunicorn runs 2
worker processes × 4 threads and every one of them can be handed a save. An
in-process test with threads would miss exactly the bug this guards.

Before `filelock` existed, 8 concurrent writers against one dataset produced:
two accepted, one edit actually on disk, and six `FileNotFoundError` crashes —
both writers built the same `<path>.tmp` and the first rename consumed it. The
`If-Match` stamp does not help: it catches a client working from a stale copy,
not two clients that read the same fresh copy microseconds apart.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

WORKERS = 8

# Each worker is its own interpreter, lined up on a shared start time so they
# genuinely contend rather than politely queueing behind process startup.
_WORKER_SRC = '''
import os, sys, time
sys.path.insert(0, os.environ["WEB"])
from dataset import FileDatasetStore, BusyError, ConflictError, RejectedError
store = FileDatasetStore(os.environ["DATA"],
                         os.path.join(os.environ["WEB"], "default-lab-data.json"),
                         os.environ["REV"])
index = sys.argv[1]
while time.time() < float(os.environ["START_AT"]):
    pass
try:
    store.apply([{"op": "insert", "section": "rites", "body": {
        "name": "RITE-" + index, "cadence": "daily",
        "when": "x", "host": "h"}}], actor="worker" + index)
    print("ok")
except (BusyError, ConflictError, RejectedError) as e:
    print(type(e).__name__)
'''


@pytest.fixture
def arena(tmp_path):
    data = tmp_path / "lab-data.json"
    shutil.copy(os.path.join(WEB, "default-lab-data.json"), data)
    worker = tmp_path / "worker.py"
    worker.write_text(_WORKER_SRC, encoding="utf-8")
    return {"data": str(data), "rev": str(tmp_path / "rev"), "worker": str(worker)}


def run_workers(arena, n=WORKERS):
    env = {**os.environ, "WEB": WEB, "DATA": arena["data"], "REV": arena["rev"],
           "START_AT": str(time.time() + 2.0)}
    procs = [subprocess.Popen([sys.executable, arena["worker"], str(i)], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for i in range(n)]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        results.append((out.strip(), err.strip()))
    return results


def test_concurrent_writers_do_not_lose_edits_or_crash(arena):
    results = run_workers(arena)
    accepted = [o for o, _ in results if o == "ok"]
    crashed = [(o, e) for o, e in results if o not in ("ok", "BusyError",
                                                       "ConflictError", "RejectedError")]
    assert not crashed, f"a writer died instead of being serialized: {crashed[:1]}"

    with open(arena["data"], encoding="utf-8") as fh:
        landed = json.load(fh)
    rites = [r["name"] for r in landed.get("rites", []) if r["name"].startswith("RITE-")]

    assert len(accepted) == WORKERS, (
        f"every writer should get its turn; {len(accepted)}/{WORKERS} did")
    assert len(rites) == len(accepted), (
        f"{len(accepted)} writes were accepted but only {len(rites)} are on disk "
        "— an edit was lost")
    assert len(set(rites)) == len(rites), "a rite landed twice"


def test_the_change_log_survives_concurrent_writers(arena):
    """Two writers computing the same next id would overwrite one another's
    snapshot, leaving the log offering an undo that restores the wrong state."""
    run_workers(arena)
    journal = os.path.join(arena["rev"], "default-journal.jsonl")
    with open(journal, encoding="utf-8") as fh:
        entries = [json.loads(line) for line in fh if line.strip()]

    ids = [e["id"] for e in entries]
    assert len(set(ids)) == len(ids), f"duplicate revision ids: {ids}"

    snapshots = {f for f in os.listdir(arena["rev"]) if f.endswith(".json")}
    assert len(snapshots) == len(entries), (
        f"{len(entries)} journal rows but {len(snapshots)} snapshots — one was "
        "overwritten, so its undo is gone")
    for entry in entries:
        snap = os.path.join(arena["rev"], f"default-r{entry['id']:05d}.json")
        with open(snap, encoding="utf-8") as fh:
            json.load(fh)   # every snapshot must be complete, parseable JSON


def test_the_dataset_is_never_left_torn(arena):
    """os.replace is atomic, so a reader always sees a whole document."""
    run_workers(arena)
    with open(arena["data"], encoding="utf-8") as fh:
        data = json.load(fh)
    from validation import validate
    assert validate(data) == [], "concurrent writers left the dataset invalid"


def test_no_temp_files_are_left_behind(arena):
    run_workers(arena)
    for directory in (os.path.dirname(arena["data"]), arena["rev"]):
        strays = [f for f in os.listdir(directory) if f.endswith(".tmp")]
        assert not strays, f"leftover temp files in {directory}: {strays}"


def test_a_wedged_lock_times_out_instead_of_hanging(tmp_path):
    """A held lock must free the worker with a BusyError, not block forever."""
    import filelock
    from filelock import LockTimeout, exclusive
    lock = str(tmp_path / "held.lock")
    with exclusive(lock):
        started = time.monotonic()
        with pytest.raises(LockTimeout):
            with exclusive(lock, timeout=0.3):
                pass
        waited = time.monotonic() - started
    assert waited < 5, f"timeout took {waited:.1f}s — it is not honouring its deadline"
    assert filelock.LOCK_TIMEOUT >= 5, "the production timeout should not be this short"
