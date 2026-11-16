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
