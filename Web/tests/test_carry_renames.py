"""CARRYING RENAMES (2026-11-15; the owner: "a toggle to carry renames").

With `meta.carry_service_renames` on, a write that renames a service takes
the collections, repair windows and alert rules naming it along. Off, they
keep the old key (and Atlas says what was left behind).
"""

import json

import alertkit
import viewers

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file"}

UI = {"label": "UI", "url": "https://a.example"}
SSH = {"label": "SSH", "url": "https://a.example/ssh"}
MON = {"label": "Mon", "url": "https://m.example", "kuma": "Alpha Mon"}


def test_which_keys_move():
    import renames
    before = {"id": "alpha", "links": [UI, SSH, MON]}
    # a label renamed, paired by its address
    assert renames.key_moves(before, [{**UI, "label": "Web UI"}, SSH, MON], "alpha", "alpha") == {
        "alpha/UI": "alpha/Web UI"}
    # a monitor renamed
    assert renames.key_moves(before, [UI, SSH, {**MON, "kuma": "Alpha Monitor"}], "alpha", "alpha") == {
        "Alpha Mon": "Alpha Monitor"}
    # the place renamed: every built-in key follows; a monitor's does not change
    assert renames.key_moves(before, None, "alpha", "alfa") == {"alpha/UI": "alfa/UI", "alpha/SSH": "alfa/SSH"}
    # a link removed and the rest reordered: paired by address, nothing invented
    assert renames.key_moves(before, [MON, UI], "alpha", "alpha") == {}
    # an address changed too, the list kept its length: paired by position
    assert renames.key_moves({"links": [UI]}, [{"label": "Panel", "url": "https://b.example"}], "alpha", "alpha") == {
        "alpha/UI": "alpha/Panel"}
    # an address changed and the list grew: no pairing, nothing moves
    assert renames.key_moves({"links": [UI]}, [{"label": "Panel", "url": "https://b.example"}, SSH], "alpha", "alpha") == {}


def test_what_is_carried_where():
    import renames
    moves = {"alpha/UI": "alpha/Web UI"}
    data = {"collections": [{"id": "c", "services": ["alpha/UI", "x", "alpha/Web UI"]}, {"id": "d", "services": ["x"]}]}
    assert renames.collection_ops(data, moves) == [
        {"op": "upsert", "section": "collections", "id": "c", "body": {"services": ["alpha/Web UI", "x"]}}]
    assert renames.carried_windows([{"services": ["alpha/UI"]}, {"nodes": ["a"]}], moves) == [
        {"services": ["alpha/Web UI"]}, {"nodes": ["a"]}]
    assert renames.carried_windows([{"nodes": ["a"]}], moves) is None
    doc = {"rules": [{"id": "r", "target": {"kind": "service", "id": "alpha/UI"}},
                     {"id": "p", "target": {"kind": "place", "id": "alpha/UI"}}]}
    out = renames.carried_rules(doc, moves)
    assert out["rules"][0]["target"]["id"] == "alpha/Web UI" and out["rules"][1]["target"]["id"] == "alpha/UI"


def _realm(tmp_path, monkeypatch, on):
    data = viewers.dataset(collections=[{"id": "web", "name": "Web", "services": ["alpha/UI"]}])
    data["meta"]["carry_service_renames"] = on
    data["nodes"][0]["links"] = [UI, SSH]
    handle = alertkit.build(tmp_path, monkeypatch, data, windows=[
        {"id": "w", "reason": "r", "services": ["alpha/UI"], "starts": "2020-01-01T00:00:00Z",
         "ends": "2099-01-01T00:00:00Z"}])
    alertkit.store([alertkit.rule("r-ui", "service", "alpha/UI")])
    return handle, viewers.signed_in(handle, "ops")


def _rename(admin):
    return admin.post("/api/v2/admin/ops", headers=viewers.W, json={"ops": [
        {"op": "upsert", "section": "nodes", "id": "alpha", "body": {"links": [{**UI, "label": "Web UI"}, SSH]}}]})


def test_with_the_toggle_on_a_rename_takes_everything_along(tmp_path, monkeypatch):
    import alerts
    import maintenance
    handle, admin = _realm(tmp_path, monkeypatch, True)
    r = _rename(admin)
    assert r.status_code == 200, r.get_json()
    carried = r.get_json()["carried"]
    assert carried["services"] == ["alpha/UI -> alpha/Web UI"] and carried["windows"] == 1 and carried["rules"] == 1
    lab = admin.get("/api/v2/lab-data").get_json()
    assert lab["collections"][0]["services"] == ["alpha/Web UI"]
    assert maintenance.read()["windows"][0]["services"] == ["alpha/Web UI"]
    assert alerts.read()[0]["rules"][0]["target"]["id"] == "alpha/Web UI"
    monkeypatch.undo()


def test_with_the_toggle_off_nothing_follows(tmp_path, monkeypatch):
    import alerts
    import maintenance
    handle, admin = _realm(tmp_path, monkeypatch, False)
    r = _rename(admin)
    assert r.status_code == 200 and "carried" not in r.get_json()
    assert admin.get("/api/v2/lab-data").get_json()["collections"][0]["services"] == ["alpha/UI"]
    assert maintenance.read()["windows"][0]["services"] == ["alpha/UI"]
    assert alerts.read()[0]["rules"][0]["target"]["id"] == "alpha/UI"
    monkeypatch.undo()


# ── A MONITOR NAME TAKEN OFF A LINK (2026-11-18) ─────────────────────────────
# Leaving Kuma: a link stops naming its monitor, address and label unchanged,
# and its key goes from the monitor's name to `<place id>/<label>`.

BARE = {"label": "Mon", "url": "https://m.example"}
SHARED = {"label": "Web", "url": "https://w.example", "kuma": "Shared"}
UNSHARED = {"label": "Web", "url": "https://w.example"}


def _map(**links):
    """A map of places in the order given, each with the links given."""
    return {"nodes": [{"id": pid, "links": list(ls)} for pid, ls in links.items()]}


def test_a_monitor_name_removed_moves_the_key_to_the_place():
    import renames
    before = {"id": "alpha", "links": [UI, SSH, MON]}
    assert renames.key_moves(before, [UI, SSH, BARE], "alpha", "alpha") == {"Alpha Mon": "alpha/Mon"}
    # and named again, it goes back
    assert renames.key_moves({"id": "alpha", "links": [UI, SSH, BARE]}, [UI, SSH, MON], "alpha", "alpha") == {
        "alpha/Mon": "Alpha Mon"}
    # the whole map says the same of the simple case
    assert renames.map_moves(_map(alpha=[UI, SSH, MON]), _map(alpha=[UI, SSH, BARE])) == (
        {"Alpha Mon": ["alpha/Mon"]}, [])


def test_a_key_another_link_still_has_does_not_move():
    import renames
    before = _map(alpha=[SHARED], beta=[SHARED], gamma=[UI])
    # one place of two stops naming the monitor: the key is still beta's
    assert renames.map_moves(before, _map(alpha=[UNSHARED], beta=[SHARED], gamma=[UI])) == ({}, ["Shared"])
    # two links on one place, one of them un-named
    twice = [SHARED, {"label": "Api", "url": "https://w.example/api", "kuma": "Shared"}]
    assert renames.map_moves(_map(alpha=twice), _map(alpha=[UNSHARED, twice[1]])) == ({}, ["Shared"])
    # a link added in the same write that takes the old key keeps it in use too
    assert renames.map_moves(_map(alpha=[UI]), _map(alpha=[{**UI, "label": "Web UI"}],
                                                  beta=[{"label": "x", "url": "https://x.example",
                                                         "kuma": "alpha/UI"}])) == ({}, ["alpha/UI"])
    # a place nobody touched is never paired at all
    assert renames.map_moves(before, before) == ({}, [])


def test_a_link_that_came_to_a_key_in_the_same_write_does_not_hold_it_back():
    """Two labels swapped, and `UI` renamed `SSH` while `SSH` is renamed
    `Shell`: each old key's link took another, so each key follows its own
    link, and what named the second service is not left naming the first."""
    import renames
    before = _map(alpha=[UI, SSH])
    swapped, stayed = renames.map_moves(before, _map(alpha=[{**UI, "label": "SSH"}, {**SSH, "label": "UI"}]))
    assert swapped == {"alpha/UI": ["alpha/SSH"], "alpha/SSH": ["alpha/UI"]} and stayed == []
    chained, stayed = renames.map_moves(before, _map(alpha=[{**UI, "label": "SSH"}, {**SSH, "label": "Shell"}]))
    assert chained == {"alpha/UI": ["alpha/SSH"], "alpha/SSH": ["alpha/Shell"]} and stayed == []
    doc = {"rules": [{"id": "ui", "target": {"kind": "service", "id": "alpha/UI"}},
                     {"id": "ssh", "target": {"kind": "service", "id": "alpha/SSH"}}]}
    assert [r["target"]["id"] for r in renames.carried_rules(doc, swapped)["rules"]] == ["alpha/SSH", "alpha/UI"]
    assert [r["target"]["id"] for r in renames.carried_rules(doc, chained)["rules"]] == ["alpha/SSH", "alpha/Shell"]
    # each key is moved once, never through the next move as well
    assert renames.carried_windows([{"services": ["alpha/UI", "alpha/SSH"]}], chained) == [
        {"services": ["alpha/SSH", "alpha/Shell"]}]
    assert renames.carried_windows([{"services": ["alpha/UI"]}], chained) == [{"services": ["alpha/SSH"]}]
    # across places too: a monitor handed from one link to another
    handed = renames.map_moves(_map(alpha=[SHARED], beta=[{**UI, "kuma": "Other"}]),
                               _map(alpha=[UNSHARED], beta=[{**UI, "kuma": "Shared"}]))
    assert handed == ({"Shared": ["alpha/Web"], "Other": ["Shared"]}, [])


def test_one_key_that_splits_goes_to_every_new_key_in_map_order():
    import renames
    before = _map(alpha=[SHARED], beta=[UI, SHARED], gamma=[SHARED])
    after = _map(alpha=[UNSHARED], beta=[UI, UNSHARED], gamma=[UNSHARED])
    moves, stayed = renames.map_moves(before, after)
    assert moves == {"Shared": ["alpha/Web", "beta/Web", "gamma/Web"]} and stayed == []
    assert renames.splits(moves) == moves and renames.splits({"a": ["b"], "c": "d"}) == {}
    # a list of services gets them all, where the old key stood, once each
    data = {"collections": [{"id": "c", "services": ["x", "Shared", "beta/Web", "y"]}]}
    assert renames.collection_ops(data, moves) == [{"op": "upsert", "section": "collections", "id": "c", "body": {
        "services": ["x", "alpha/Web", "beta/Web", "gamma/Web", "y"]}}]
    assert renames.carried_windows([{"services": ["Shared"]}], moves) == [
        {"services": ["alpha/Web", "beta/Web", "gamma/Web"]}]
    # a rule names one service: the first in map order
    doc = {"rules": [{"id": "r", "target": {"kind": "service", "id": "Shared"}}]}
    assert renames.carried_rules(doc, moves)["rules"][0]["target"]["id"] == "alpha/Web"
    # and several keys that become one all go to it
    back, _ = renames.map_moves(after, before)
    assert back == {"alpha/Web": ["Shared"], "beta/Web": ["Shared"], "gamma/Web": ["Shared"]}
    assert renames.carried_windows([{"services": ["alpha/Web", "beta/Web", "gamma/Web"]}], back) == [
        {"services": ["Shared"]}]


def test_a_renamed_place_is_paired_by_the_id_it_had():
    import renames
    before = _map(alpha=[UI, MON], beta=[SSH])
    ops = [{"op": "upsert", "section": "nodes", "id": "alpha", "body": {"id": "alfa"}},
           {"op": "upsert", "section": "nodes", "id": "alfa", "body": {"id": "first"}},
           {"op": "upsert", "section": "nodes", "id": "ghost", "body": {"id": "spirit"}},
           {"op": "insert", "section": "nodes", "body": {"id": "new"}}]
    renamed = renames.renamed_places(ops, before)
    assert renamed == {"alpha": "first"}
    after = _map(first=[UI, MON], beta=[SSH])
    assert renames.map_moves(before, after, renamed) == ({"alpha/UI": ["first/UI"]}, [])
    # without the rename nothing is paired, so nothing moves
    assert renames.map_moves(before, after) == ({}, [])
    # a new place under the id another one left is not that place
    after = _map(first=[UI, MON], alpha=[{**UI, "label": "Other"}], beta=[SSH])
    assert renames.map_moves(before, after, renamed) == ({"alpha/UI": ["first/UI"]}, [])


def _kuma_realm(tmp_path, monkeypatch, alpha=(MON,), beta=(), key="Alpha Mon", shadow=False):
    """A realm where a collection, a repair window and an alert rule all name `key`."""
    data = viewers.dataset(collections=[{"id": "web", "name": "Web", "services": [key]}])
    data["meta"]["carry_service_renames"] = True
    data["meta"]["shadow_kuma"] = shadow
    data["nodes"][0]["links"] = list(alpha)
    data["nodes"][1]["links"] = list(beta)
    handle = alertkit.build(tmp_path, monkeypatch, data, windows=[
        {"id": "w", "reason": "r", "services": [key], "starts": "2020-01-01T00:00:00Z",
         "ends": "2099-01-01T00:00:00Z"}])
    alertkit.store([alertkit.rule("r-mon", "service", key)])
    return handle, viewers.signed_in(handle, "ops")


def _links(admin, **places):
    return admin.post("/api/v2/admin/ops", headers=viewers.W, json={"ops": [
        {"op": "upsert", "section": "nodes", "id": pid, "body": {"links": ls}} for pid, ls in places.items()]})


def _held(admin):
    """(the collection's services, the window's, the rule's target) as stored now."""
    import alerts
    import maintenance
    return (admin.get("/api/v2/lab-data").get_json()["collections"][0]["services"],
            maintenance.read()["windows"][0]["services"],
            alerts.read()[0]["rules"][0]["target"]["id"])


def test_taking_the_monitor_name_off_a_link_carries_its_key(tmp_path, monkeypatch):
    handle, admin = _kuma_realm(tmp_path, monkeypatch)
    r = _links(admin, alpha=[BARE])
    assert r.status_code == 200, r.get_json()
    carried = r.get_json()["carried"]
    assert carried["services"] == ["Alpha Mon -> alpha/Mon"]
    assert carried["windows"] == 1 and carried["rules"] == 1
    assert "split" not in carried and "stayed" not in carried
    assert _held(admin) == (["alpha/Mon"], ["alpha/Mon"], "alpha/Mon")
    monkeypatch.undo()


def test_a_monitor_another_place_still_names_stays_where_it_is(tmp_path, monkeypatch):
    handle, admin = _kuma_realm(tmp_path, monkeypatch, alpha=[SHARED], beta=[SHARED], key="Shared")
    r = _links(admin, alpha=[UNSHARED])
    assert r.status_code == 200, r.get_json()
    carried = r.get_json()["carried"]
    assert carried["services"] == [] and carried["stayed"] == ["Shared"]
    assert carried["windows"] == 0 and carried["rules"] == 0
    assert _held(admin) == (["Shared"], ["Shared"], "Shared")
    # the last link to name it takes everything along
    r = _links(admin, beta=[UNSHARED])
    assert r.get_json()["carried"]["services"] == ["Shared -> beta/Web"]
    assert _held(admin) == (["beta/Web"], ["beta/Web"], "beta/Web")
    monkeypatch.undo()


def test_a_monitor_two_places_named_splits_in_one_save_and_says_so(tmp_path, monkeypatch):
    handle, admin = _kuma_realm(tmp_path, monkeypatch, alpha=[SHARED], beta=[SHARED], key="Shared")
    r = _links(admin, beta=[UNSHARED], alpha=[UNSHARED])      # the ops' order is not the map's
    assert r.status_code == 200, r.get_json()
    carried = r.get_json()["carried"]
    assert carried["services"] == ["Shared -> alpha/Web", "Shared -> beta/Web"]
    assert carried["split"] == [{"key": "Shared", "to": ["alpha/Web", "beta/Web"],
                                 "rule_to": "alpha/Web", "rules": 1}]
    assert carried["windows"] == 1 and carried["rules"] == 1
    assert _held(admin) == (["alpha/Web", "beta/Web"], ["alpha/Web", "beta/Web"], "alpha/Web")
    monkeypatch.undo()


def test_a_save_the_store_refuses_carries_nothing(tmp_path, monkeypatch):
    handle, admin = _kuma_realm(tmp_path, monkeypatch)
    r = admin.post("/api/v2/admin/ops", headers=viewers.W, json={"ops": [
        {"op": "upsert", "section": "nodes", "id": "alpha", "body": {"links": [BARE]}},
        {"op": "upsert", "section": "nodes", "id": "alpha", "body": {"zone": "nowhere"}}]})
    assert r.status_code == 422 and "carried" not in r.get_json()
    assert _held(admin) == (["Alpha Mon"], ["Alpha Mon"], "Alpha Mon")
    monkeypatch.undo()


# ── what a check last heard ──────────────────────────────────────────────────

def _checks(tmp_path, checks=None):
    path = tmp_path / "checks.json"
    if checks is not None:
        path.write_text(json.dumps({"v": 2, "at": 1000, "checks": checks}), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))["checks"]


HEARD = {"state": "healthy", "said": "healthy", "since": 500, "heard": 1000, "asked": 1000, "ms": 7, "fails": 0}


def test_a_check_keeps_what_it_heard_when_its_link_stops_naming_a_monitor(tmp_path):
    import watch
    on = {"title": "t", "shadow_kuma": True}
    before = {"meta": on, "nodes": [{"id": "alpha", "links": [MON]}]}
    after = {"meta": on, "nodes": [{"id": "alpha", "links": [BARE]}]}
    path = str(tmp_path / "checks.json")
    moves = {"Alpha Mon": ["alpha/Mon"]}
    _checks(tmp_path, {"k:Alpha Mon": HEARD, "s:other/x": {"state": "down"}})
    assert watch.carry(before, after, moves, path) == 1
    assert _checks(tmp_path) == {"s:alpha/Mon": HEARD, "s:other/x": {"state": "down"}}
    # and the feed serves it at once, under the new key
    assert watch.as_feed(watch.load(path), watch.targets(after), now=1001, factor=1.0)["services"] == {
        "alpha/Mon": {"state": "healthy", "ms": 7}}
    # put back, the entry goes back to the shadow's key
    assert watch.carry(after, before, {"alpha/Mon": ["Alpha Mon"]}, path) == 1
    assert "k:Alpha Mon" in _checks(tmp_path)
    # an answer already heard under the new key is never written over
    _checks(tmp_path, {"k:Alpha Mon": HEARD, "s:alpha/Mon": {"state": "down", "heard": 1001}})
    assert watch.carry(before, after, moves, path) == 0
    assert _checks(tmp_path)["s:alpha/Mon"] == {"state": "down", "heard": 1001}
    # a check that asks another address after the write starts fresh
    moved = {"meta": on, "nodes": [{"id": "alpha", "links": [{**BARE, "url": "https://other.example"}]}]}
    _checks(tmp_path, {"k:Alpha Mon": HEARD})
    assert watch.carry(before, moved, moves, path) == 0
    # with "Check beside Kuma" off nothing was asked, so nothing is carried
    off = {"meta": {"title": "t"}, "nodes": before["nodes"]}
    assert watch.carry(off, after, moves, path) == 0
    # one key that went to several: the first that asks what the old one asked
    two = {"meta": on, "nodes": [{"id": "alpha", "links": [{**BARE, "url": "https://other.example"}]},
                                 {"id": "beta", "links": [BARE]}]}
    assert watch.carry(before, two, {"Alpha Mon": ["alpha/Mon", "beta/Mon"]}, path) == 1
    assert list(_checks(tmp_path)) == ["s:beta/Mon"]
    # two services that swap their labels each keep their own answer
    a, b = {"label": "A", "url": "https://a.example"}, {"label": "B", "url": "https://b.example"}
    was = {"nodes": [{"id": "alpha", "links": [a, b]}]}
    now = {"nodes": [{"id": "alpha", "links": [{**a, "label": "B"}, {**b, "label": "A"}]}]}
    _checks(tmp_path, {"s:alpha/A": {**HEARD, "ms": 1}, "s:alpha/B": {**HEARD, "ms": 2}})
    assert watch.carry(was, now, {"alpha/A": ["alpha/B"], "alpha/B": ["alpha/A"]}, path) == 2
    assert {k: v["ms"] for k, v in _checks(tmp_path).items()} == {"s:alpha/B": 1, "s:alpha/A": 2}


def test_the_save_carries_what_the_check_heard(tmp_path, monkeypatch):
    handle, admin = _kuma_realm(tmp_path, monkeypatch, shadow=True)
    _checks(tmp_path, {"k:Alpha Mon": HEARD})
    r = _links(admin, alpha=[BARE])
    assert r.status_code == 200 and r.get_json()["carried"]["checks"] == 1
    assert _checks(tmp_path) == {"s:alpha/Mon": HEARD}
    monkeypatch.undo()


def test_a_checks_store_that_cannot_be_written_is_said_and_the_save_stands(tmp_path, monkeypatch):
    import watch
    handle, admin = _kuma_realm(tmp_path, monkeypatch, shadow=True)

    def broken(*a, **kw):
        raise OSError("read-only")
    monkeypatch.setattr(watch, "carry", broken)
    r = _links(admin, alpha=[BARE])
    carried = r.get_json()["carried"]
    assert r.status_code == 200 and carried["checks_failed"] is True and carried["checks"] == 0
    assert _held(admin) == (["alpha/Mon"], ["alpha/Mon"], "alpha/Mon")
    monkeypatch.undo()


# ── an undo puts the carry back ──────────────────────────────────────────────

def _undo(admin, revision):
    return admin.post(f"/api/v2/admin/revisions/{revision}/revert", headers=viewers.W, json={})


def test_an_undo_carries_the_keys_back(tmp_path, monkeypatch):
    handle, admin = _kuma_realm(tmp_path, monkeypatch, shadow=True)
    _checks(tmp_path, {"k:Alpha Mon": HEARD})
    saved = _links(admin, alpha=[BARE]).get_json()
    assert _held(admin) == (["alpha/Mon"], ["alpha/Mon"], "alpha/Mon")
    r = _undo(admin, saved["revision"])
    assert r.status_code == 200, r.get_json()
    carried = r.get_json()["carried"]
    assert carried["services"] == ["alpha/Mon -> Alpha Mon"]
    assert carried["windows"] == 1 and carried["rules"] == 1 and carried["checks"] == 1
    assert _held(admin) == (["Alpha Mon"], ["Alpha Mon"], "Alpha Mon")
    assert list(_checks(tmp_path)) == ["k:Alpha Mon"]
    monkeypatch.undo()


def test_an_undo_of_a_split_brings_every_key_back_to_the_one(tmp_path, monkeypatch):
    handle, admin = _kuma_realm(tmp_path, monkeypatch, alpha=[SHARED], beta=[SHARED], key="Shared")
    saved = _links(admin, alpha=[UNSHARED], beta=[UNSHARED]).get_json()
    assert _held(admin) == (["alpha/Web", "beta/Web"], ["alpha/Web", "beta/Web"], "alpha/Web")
    carried = _undo(admin, saved["revision"]).get_json()["carried"]
    assert carried["services"] == ["alpha/Web -> Shared", "beta/Web -> Shared"]
    assert _held(admin) == (["Shared"], ["Shared"], "Shared")
    monkeypatch.undo()


def test_an_undo_of_a_renamed_place_carries_its_services_back(tmp_path, monkeypatch):
    handle, admin = _realm(tmp_path, monkeypatch, True)
    saved = admin.post("/api/v2/admin/ops", headers=viewers.W, json={"ops": [
        {"op": "upsert", "section": "nodes", "id": "alpha", "body": {"id": "alfa"}}]})
    assert saved.status_code == 200, saved.get_json()
    assert _held(admin) == (["alfa/UI"], ["alfa/UI"], "alfa/UI")
    r = _undo(admin, saved.get_json()["revision"])
    assert sorted(r.get_json()["carried"]["services"]) == ["alfa/SSH -> alpha/SSH", "alfa/UI -> alpha/UI"]
    assert _held(admin) == (["alpha/UI"], ["alpha/UI"], "alpha/UI")
    monkeypatch.undo()


def test_an_undo_with_the_toggle_off_leaves_the_other_stores_alone(tmp_path, monkeypatch):
    handle, admin = _realm(tmp_path, monkeypatch, False)
    saved = _rename(admin).get_json()
    r = _undo(admin, saved["revision"])
    assert r.status_code == 200 and "carried" not in r.get_json()
    assert _held(admin) == (["alpha/UI"], ["alpha/UI"], "alpha/UI")
    monkeypatch.undo()
