"""One write lock per site, for every writer (2026-11-15, stage 5).

In db mode the importers write rows straight into the tables. They took no
lock, while an editor's save loads the map and writes it back under the
site's lock, so an import landing between the two was put back as it was.
Now the CLI's imports and the relay ingest take the same lock as the store.
"""

import json
import os
import sys
import threading
import time
from types import SimpleNamespace

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

import dataset  # noqa: E402


def test_every_writer_names_the_same_lock(tmp_path):
    file_store = dataset.FileDatasetStore(str(tmp_path / "m.json"), None, str(tmp_path / "rev"), "s1")
    db_store = dataset.DbDatasetStore("s1", str(tmp_path / "rev"))
    want = dataset.site_lock_path("s1", str(tmp_path / "rev"))
    assert file_store._lock_path() == db_store._lock_path() == want


def test_a_cli_import_waits_for_a_save_in_progress(tmp_path, monkeypatch):
    import settings
    import store
    monkeypatch.setenv("ATLAS_DB_URL", f"sqlite:///{(tmp_path / 'a.db').as_posix()}")
    monkeypatch.setattr(settings, "REVISIONS_DIR", str(tmp_path / "rev"))
    store.reset_engine_for_tests()
    store.init_db()
    import cli
    src = tmp_path / "map.json"
    with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as fh:
        src.write_text(fh.read(), encoding="utf-8")
    args = SimpleNamespace(path=str(src), site="s1", name=None, strict=False, keep_stamps=False)

    held = threading.Event()
    release = threading.Event()

    def a_save():
        with dataset.site_lock("s1"):
            held.set()
            release.wait(5)
    saver = threading.Thread(target=a_save)
    saver.start()
    held.wait(5)
    done = {}

    def an_import():
        done["code"] = cli.cmd_import_json(args)
        done["at"] = time.monotonic()
    importer = threading.Thread(target=an_import)
    importer.start()
    time.sleep(0.4)
    assert importer.is_alive(), "the import ran while a save held the map"
    released_at = time.monotonic()
    release.set()
    importer.join(10)
    saver.join(5)
    assert done.get("code") == 0 and done["at"] >= released_at
    with store.session_scope() as s:
        assert len(store.dump_labdata(s, "s1")["nodes"]) == len(json.loads(src.read_text("utf-8"))["nodes"])
    store.reset_engine_for_tests()
