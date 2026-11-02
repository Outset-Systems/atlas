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
