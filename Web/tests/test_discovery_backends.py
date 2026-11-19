"""Discovery merges by one rule in both backends (2026-11-19, the 11-12 audit's
Live 6). db mode matched a row on address AND MAC, so a scan (no MAC) and a
lease (a MAC) of one device were two rows, and it let a controller's client
list overwrite what a scan had found. The file store is the oracle: the same
sightings go into both, and the two listings must say the same thing.

Its own engine on a temp file and its own inbox file: no app, no env.
"""

import copy
import json
import os
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

import discovery  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
from store.labdata import load_labdata  # noqa: E402

with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as fh:
    BUNDLED = json.load(fh)

# what the survey hears, in order: each batch is one call to record()
SIGHTINGS = [
    # a scan finds a device: no MAC, its ports, the name DNS gave it
    [{"ip": "10.9.0.10", "hostname": "nas", "vendor": "Synology", "ports": [22, 80, 443],
      "source": "nmap"}],
    # a lease of the same device adds the MAC and keeps the scan's name
    [{"ip": "10.9.0.10", "mac": "aa:bb:cc:00:00:10", "hostname": "diskstation",
      "source": "dhcp"}],
    # the controller's client list may only fill blanks, never overwrite
    [{"ip": "10.9.0.10", "mac": "aa:bb:cc:00:00:10", "hostname": "unifi-name",
      "vendor": "Somebody Else", "source": "unifi"}],
    # a rescan replaces what a scan found, and keeps what it did not see
    [{"ip": "10.9.0.10", "ports": [22], "source": "nmap"}],
    # a device known only by its MAC, and one seen by a lease first
    [{"mac": "aa:bb:cc:00:00:20", "hostname": "watch", "source": "unifi"},
     {"ip": "10.9.0.11", "mac": "aa:bb:cc:00:00:11", "hostname": "phone", "source": "dhcp"}],
    # then scanned, then seen by the controller: three sources on one device
    [{"ip": "10.9.0.11", "vendor": "Apple", "ports": [], "source": "nmap"}],
    [{"ip": "10.9.0.11", "mac": "aa:bb:cc:00:00:11", "source": "unifi"}],
]

FIELDS = ("key", "ip", "mac", "hostname", "vendor", "ports", "source")


@pytest.fixture
def both(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OBSERVED_PATH", str(tmp_path / "observed.json"))
    monkeypatch.setenv("ATLAS_DB_URL", f"sqlite:///{(tmp_path / 'd.db').as_posix()}")
    store.reset_engine_for_tests()
    store.init_db()
    with store.session_scope() as s:
        load_labdata(s, copy.deepcopy(BUNDLED), site_slug="parity")
    yield
    store.reset_engine_for_tests()


def _listing(backend):
    rows = discovery.listing(copy.deepcopy(BUNDLED), backend=backend, site="parity")
    return sorted(({f: r.get(f) for f in FIELDS} for r in rows), key=lambda r: r["key"])


def test_both_backends_list_the_same_devices_after_the_same_sightings(both):
    for batch in SIGHTINGS:
        new_file = discovery.record(copy.deepcopy(batch), backend="file")
        new_db = discovery.record(copy.deepcopy(batch), backend="db", site="parity")
        assert new_db == new_file, batch
    file_rows, db_rows = _listing("file"), _listing("db")
    assert db_rows == file_rows

    by_key = {r["key"]: r for r in db_rows}
    nas = by_key["10.9.0.10"]
    # one device, not a scan's row and a lease's row
    assert sum(1 for r in db_rows if r["ip"] == "10.9.0.10") == 1
    assert nas["mac"] == "aa:bb:cc:00:00:10"
    assert nas["hostname"] == "nas" and nas["vendor"] == "Synology"
    assert nas["ports"] == [22]
    assert nas["source"] == "nmap, dhcp, unifi"
    assert by_key["aa:bb:cc:00:00:20"]["ip"] is None
    assert by_key["10.9.0.11"]["source"] == "dhcp, nmap, unifi"


def test_a_device_seen_by_every_source_keeps_the_whole_source_line(both):
    """Three sources read "nmap, dhcp, unifi", 17 characters: the column was 16
    wide, which SQLite ignores and a typed database refuses."""
    from store.models import ObservedNode
    assert ObservedNode.__table__.c.source.type.length >= len("nmap, dhcp, unifi, relay")
