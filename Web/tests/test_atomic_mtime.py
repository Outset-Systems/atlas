"""An atomic save moves the file's time, and keeps its mode.

`write_json_atomic` carried permissions over with `shutil.copystat`, which also
carries the old mtime. Every reader that reloads on a new mtime (labdata, the
integrations settings and the signals hub that rebuilds from them, auth_config)
then went on serving what it had: a Kuma source saved in Settings lit nothing
until a restart, and the second gunicorn worker kept the dataset it first read.
"""
import os
import stat
import sys
import time

import pytest

from appfixture import fresh_app  # noqa: F401  (puts Web/ on the path)


def test_a_save_moves_the_time_and_keeps_the_mode(tmp_path):
    from jsonio import write_json_atomic
    p = tmp_path / "x.json"
    write_json_atomic(str(p), {"a": 1})
    old = time.time() - 3600
    os.utime(p, (old, old))
    if sys.platform != "win32":
        os.chmod(p, 0o640)
    write_json_atomic(str(p), {"a": 2})
    assert os.path.getmtime(p) > old + 60
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o640


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_INTEGRATIONS", str(tmp_path / "integrations.json"))
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", "")
    return tmp_path / "integrations.json"


def test_a_saved_source_reaches_the_hub_without_a_restart(settings_file):
    import integrations
    import signals
    integrations.save({"ATLAS_KUMA_URL": "http://kuma.example:3001"})
    old = time.time() - 3600
    os.utime(settings_file, (old, old))      # an older first save, as a long-running lab has
    hub = signals.SignalsHub(factory=signals.make_adapters)
    assert hub.enabled == []
    integrations.save({"ATLAS_SIGNALS_SOURCES": "kuma"})
    hub.feed()
    assert hub.enabled == ["kuma"]


# ── a save that fails leaves nothing behind (audit 2026-11-12, Foundations 2 and 12) ──

def test_a_save_whose_rename_fails_leaves_no_temp_file(tmp_path, monkeypatch):
    """The temp file was left when the last retry failed, and in the maps
    folder it was then listed as a render."""
    import jsonio
    target = tmp_path / "x.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(jsonio, "_REPLACE_BACKOFF", 0)

    def refuse(src, dst):
        raise PermissionError("locked")
    monkeypatch.setattr(jsonio.os, "replace", refuse)
    import pytest
    with pytest.raises(PermissionError):
        jsonio.write_json_atomic(str(target), {"a": 1})
    assert sorted(p.name for p in tmp_path.iterdir() if not p.name.endswith(".bak")) == ["x.json"]
    assert target.read_text(encoding="utf-8") == "{}"


def test_an_unlock_that_fails_does_not_fail_a_save_that_succeeded(tmp_path, monkeypatch):
    import filelock

    def broken(fd):
        raise OSError(95, "not supported")
    real = filelock._unlock
    calls = []
    monkeypatch.setattr(filelock, "_unlock", lambda fd: (calls.append(fd), real(fd)))
    with filelock.exclusive(str(tmp_path / "x.lock")):
        pass
    assert calls
    if hasattr(filelock, "fcntl"):
        monkeypatch.setattr(filelock.fcntl, "flock", lambda fd, op: broken(fd) if op == filelock.fcntl.LOCK_UN else None)
        with filelock.exclusive(str(tmp_path / "y.lock")):
            pass
