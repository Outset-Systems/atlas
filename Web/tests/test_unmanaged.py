"""UNMANAGED (2026-11-14, the owner's Q4 answer): "not ours to watch".

A place marked `unmanaged: true`, or in a collection marked so, stays on the
map and in the table, takes no state from any source and raises nothing. It
beats maintenance. The annals forget its last state, so taking it back is a
first sighting, never a stale "down -> healthy".
"""

import json

import pytest

import viewers

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file"}

OPEN = {"id": "w", "reason": "patching", "nodes": ["alpha", "beta"],
        "starts": "2020-01-01T00:00:00Z", "ends": "2099-01-01T00:00:00Z"}


def _realm(tmp_path, monkeypatch, **edits):
    data = viewers.dataset(**edits)
    return viewers.build(tmp_path, monkeypatch, data, windows=[OPEN])


def test_which_places_are_unmanaged():
    import signals
    data = viewers.dataset(collections=[{"id": "c", "name": "C", "places": ["beta"], "unmanaged": True},
                                        {"id": "d", "name": "D", "places": "solo", "unmanaged": True},
                                        {"id": "e", "name": "E", "places": ["alpha"], "unmanaged": "yes"}])
    data["nodes"][0]["unmanaged"] = True
    assert signals.unmanaged_ids(data) == {"alpha", "beta", "solo"}
    data["nodes"][0]["unmanaged"] = "true"          # a hand edit's text is not True
    assert signals.unmanaged_ids(data) == {"beta", "solo"}
    assert signals.unmanaged_ids(None) == set()
    assert signals.unmanaged_ids({"nodes": 5, "collections": {"x": 1}}) == set()


def test_its_services_are_found_by_monitor_and_by_its_own_links():
    import signals
    data = viewers.dataset()
    data["nodes"][0]["links"] = [{"label": "UI", "url": "https://a.example", "kuma": "Alpha UI"},
                                 {"label": "SSH", "url": "ssh://a.example"}]
    data["nodes"][1]["monitors"] = ["Beta ping"]
    assert signals.services_of(data, {"alpha"}) == {"Alpha UI", "alpha/SSH"}
    assert signals.services_of(data, {"beta"}) == {"Beta ping"}
    assert signals.services_of(data, set()) == set()


def test_an_unmanaged_place_has_no_state_and_beats_maintenance(tmp_path, monkeypatch):
    nodes = [viewers.place("alpha", "Alpha", unmanaged=True), viewers.place("beta", "Beta")]
    handle = _realm(tmp_path, monkeypatch, nodes=nodes)
    feed = viewers.signed_in(handle, "ops").get("/api/v2/signals").get_json()
    assert "alpha" not in feed["nodes"]
    assert feed["maintenance"] == ["beta"]
    assert feed["unmanaged"] == ["alpha"]
    assert "unmanaged_services" not in feed, "the annals' bookkeeping is never served"
    rows = {r["id"]: r for r in viewers.signed_in(handle, "ops").get("/api/v2/places/roster").get_json()["rows"]}
    assert rows["alpha"]["unmanaged"] is True and rows["alpha"]["state"] is None
    assert rows["alpha"]["maintenance"]["now"] is False
    assert rows["beta"]["unmanaged"] is False and rows["beta"]["state"] == "maintenance"
    monkeypatch.undo()


def test_a_collection_marked_unmanaged_takes_its_members_out(tmp_path, monkeypatch):
    handle = _realm(tmp_path, monkeypatch,
                    collections=[{"id": "c", "name": "C", "places": ["beta"], "unmanaged": True}])
    admin = viewers.signed_in(handle, "ops")
    feed = admin.get("/api/v2/signals").get_json()
    assert feed["unmanaged"] == ["beta"] and feed["maintenance"] == ["alpha"]
    roster = admin.get("/api/v2/places/roster").get_json()
    assert roster["collections"][0]["unmanaged"] is True
    monkeypatch.undo()


def test_a_reader_without_the_group_never_learns_of_a_hidden_unmanaged_place(tmp_path, monkeypatch):
    nodes = [viewers.place("alpha", "Alpha"),
             viewers.place("secret-place", "Secret", require_group=viewers.GROUP, unmanaged=True)]
    handle = _realm(tmp_path, monkeypatch, nodes=nodes)
    alice = viewers.signed_in(handle, "alice")
    assert alice.get("/api/v2/signals").get_json()["unmanaged"] == []
    assert "secret" not in json.dumps(alice.get("/api/v2/places/roster").get_json()).lower()
    assert viewers.signed_in(handle, "ops").get("/api/v2/signals").get_json()["unmanaged"] == ["secret-place"]
    monkeypatch.undo()


@pytest.fixture
def annals(tmp_path, monkeypatch):
    import events
    import settings
    monkeypatch.setattr(settings, "EVENTS_PATH", str(tmp_path / "events.json"))
    return events


def test_taking_it_back_is_a_first_sighting_not_a_stale_recovery(annals):
    annals.record({"nodes": {"a": {"state": "healthy"}}})
    assert [e["to"] for e in annals.record({"nodes": {"a": {"state": "down"}}})] == ["down"]
    # unmanaged: no state in the feed, and the annals forget the last one
    assert annals.record({"nodes": {}, "unmanaged": ["a"]}) == []
    assert "node:a" not in annals.load()["state"]
    # back under watch and healthy: seeded quietly, no "down -> healthy"
    assert annals.record({"nodes": {"a": {"state": "healthy"}}, "unmanaged": []}) == []
    assert annals.load()["state"]["node:a"] == "healthy"


def test_its_services_are_forgotten_too(annals):
    annals.record({"services": {"Alpha UI": {"state": "down"}}})
    annals.record({"services": {}, "unmanaged": ["alpha"], "unmanaged_services": ["Alpha UI"]})
    assert "service:Alpha UI" not in annals.load()["state"]


def test_a_member_written_another_way_never_reaches_a_reader_without_the_group(tmp_path, monkeypatch):
    """Stage 3 review: a collection's members flow into the feed's lists as
    written, so "SECRET-PLACE" for the hidden secret-place passed a blocklist."""
    handle = viewers.build(tmp_path, monkeypatch, viewers.dataset(collections=[
        {"id": "c", "name": "C", "places": ["SECRET-PLACE", "alpha"], "unmanaged": True}]), windows=[
        {"id": "w", "reason": "r", "collections": ["c"], "starts": "2020-01-01T00:00:00Z",
         "ends": "2099-01-01T00:00:00Z"}])
    feed = viewers.signed_in(handle, "alice").get("/api/v2/signals").get_json()
    assert "SECRET" not in json.dumps({k: feed.get(k) for k in ("unmanaged", "maintenance")})
    assert feed["unmanaged"] == ["alpha"]
    monkeypatch.undo()
