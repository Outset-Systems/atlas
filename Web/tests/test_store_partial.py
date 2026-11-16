"""The editor's saves in db mode write only what changed (2026-11-15, stage 5).

`load_labdata(only_changed=True)` must leave a site exactly as the import's
full replace does; the full replace is the oracle. Two sites in one database
take the same random sequence of edits, one each way, and their dumps must be
equal after every step. Its own engine on a temp file: no app, no env.
"""

import copy
import json
import os
import random
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from store.labdata import dump_labdata, load_labdata  # noqa: E402
from store.models import Base, Node, Site  # noqa: E402

with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as fh:
    BUNDLED = json.load(fh)


def _fixture():
    """The bundled map with the shapes the round trip has to keep: an
    explicit null, an empty service list, and a section under its old name."""
    data = copy.deepcopy(BUNDLED)
    data["nodes"][0]["hw"] = None
    data["nodes"][1]["links"] = []
    data["sets"] = [{"id": "c-old", "name": "Old name", "places": [data["nodes"][2]["id"]]}]
    data.pop("collections", None)
    return data


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'p.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    yield engine, factory
    engine.dispose()


def _write(factory, data, site, partial):
    with factory() as s:
        load_labdata(s, copy.deepcopy(data), site_slug=site, only_changed=partial)
        s.commit()


def _dump(factory, site):
    with factory() as s:
        return dump_labdata(s, site)


def _row_text(row, skip):
    """A row's every column but its id, its site and `skip`, as JSON text,
    so a change of type alone shows (8080 vs 8080.0)."""
    cols = {c.key: getattr(row, c.key) for c in row.__table__.columns
            if c.key not in ("id", "site_id", "node_id", *skip)}
    return json.dumps(cols, sort_keys=True, default=str)


def _rows(factory, site):
    """Everything stored for a site, as the dump does not show it: retired
    rows, provenance columns, raw sort orders, links per place (review,
    2026-11-15: the dump alone hid most of what could differ). Row ids,
    `first_seen` and `last_imported` are when a row was made, not what it says."""
    from store.models import NodeLink, Route, Zone
    with factory() as s:
        sid = s.scalar(select(Site.id).where(Site.slug == site))
        out = {"zones": sorted(_row_text(z, ()) for z in s.scalars(select(Zone).where(Zone.site_id == sid))),
               "routes": sorted(_row_text(r, ()) for r in s.scalars(select(Route).where(Route.site_id == sid))),
               "nodes": {}}
        for n in s.scalars(select(Node).where(Node.site_id == sid)):
            if n.status == "retired":
                continue   # the one difference on purpose: a save keeps it, the import removes it
            links = sorted(_row_text(link, ()) for link in s.scalars(select(NodeLink).where(NodeLink.node_id == n.id)))
            out["nodes"][n.slug] = (_row_text(n, ("first_seen", "last_imported")), links)
        return out


def _edit(data, rnd, step):
    """One random change of the kind the Desk and NODES make."""
    nodes, zones = data["nodes"], data["zones"]
    kind = rnd.choice(["field", "null", "add", "remove", "move", "ops", "links-empty",
                       "links-add", "zone", "zone-add", "route", "setting", "collection", "retype"])
    if kind == "retype":
        # the same value, another JSON type: a link's and a route's extra
        withlinks = [n for n in nodes if n.get("links")]
        if withlinks:
            link = rnd.choice(withlinks)["links"][0]
            link["port"] = float(link["port"]) if isinstance(link.get("port"), int) else 8080
        routes = data.setdefault("routes", [])
        if routes:
            r = rnd.choice(routes)
            r["w"] = 1 if r.get("w") is True else True
        return
    if kind == "field" and nodes:
        rnd.choice(nodes)["role"] = f"role {step}"
    elif kind == "null" and nodes:
        rnd.choice(nodes)["lore"] = None
    elif kind == "add":
        nodes.insert(rnd.randrange(len(nodes) + 1), {
            "id": f"n-add-{step}", "name": f"Added {step}", "kind": "vm", "zone": zones[0]["id"],
            "x": 10.5, "y": 20.25, "role": "x", "links": [{"label": "ui", "url": f"https://a{step}.example"}]})
    elif kind == "remove" and len(nodes) > 3:
        nodes.pop(rnd.randrange(len(nodes)))
    elif kind == "move" and len(nodes) > 1:
        nodes.insert(rnd.randrange(len(nodes)), nodes.pop(rnd.randrange(len(nodes))))
    elif kind == "ops":
        withlinks = [n for n in nodes if n.get("links")]
        if withlinks:
            n = rnd.choice(withlinks)
            n["links"][0] = {**n["links"][0], "url": f"https://changed{step}.example", "kuma": f"k{step}"}
    elif kind == "links-empty" and nodes:
        rnd.choice(nodes)["links"] = []
    elif kind == "links-add" and nodes:
        n = rnd.choice(nodes)
        n["links"] = list(n.get("links") or []) + [{"label": f"svc{step}", "url": f"https://s{step}.example"}]
    elif kind == "zone":
        rnd.choice(zones)["name"] = f"Zone {step}"
    elif kind == "zone-add":
        zones.append({"id": f"z-add-{step}", "name": f"Z {step}", "vlan": 900 + step,
                      "subnet": f"10.{step % 250}.0.0/24", "hue": "#123456"})
    elif kind == "route":
        routes = data.setdefault("routes", [])
        if routes and rnd.random() < 0.5:
            routes.pop(rnd.randrange(len(routes)))
        elif len(nodes) > 1:
            routes.append({"from": nodes[0]["id"], "to": nodes[-1]["id"], "kind": "lan"})
    elif kind == "setting":
        data.setdefault("meta", {})["title"] = f"Title {step}"
    elif kind == "collection":
        key = "collections" if "collections" in data else "sets"
        data[key] = list(data.get(key) or []) + [{"id": f"c-{step}", "name": f"C {step}", "places": []}]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_partial_save_ends_where_the_full_replace_does(db, seed):
    _, factory = db
    data = _fixture()
    _write(factory, data, "full", partial=False)
    _write(factory, data, "part", partial=False)
    # an importer retired a place in both (kept in the db, off the map)
    with factory() as s:
        for site in ("full", "part"):
            sid = s.scalar(select(Site.id).where(Site.slug == site))
            s.scalars(select(Node).where(Node.site_id == sid).order_by(Node.sort_order)).all()[3].status = "retired"
        s.commit()
    rnd = random.Random(seed)
    for step in range(40):
        _edit(data, rnd, step)
        _write(factory, data, "full", partial=False)
        _write(factory, data, "part", partial=True)
        assert _dump(factory, "part") == _dump(factory, "full"), f"seed {seed}, step {step}"
        assert _rows(factory, "part") == _rows(factory, "full"), f"seed {seed}, step {step}"


def test_a_change_of_type_alone_is_written_as_the_full_replace_writes_it(db):
    """8080 -> 8080.0 and true -> 1 are equal to Python's `==`; the full
    replace writes them anew, so the partial save must too (review,
    2026-11-15), or the next save's stamp would not match the store's."""
    _, factory = db
    data = _fixture()
    node = next(n for n in data["nodes"] if n.get("links"))
    node["links"][0]["port"] = 8080
    data["routes"] = [{"from": data["nodes"][0]["id"], "to": data["nodes"][1]["id"], "kind": "lan", "w": True}]
    for site in ("full", "part"):
        _write(factory, data, site, partial=False)
    node["links"][0]["port"] = 8080.0
    data["routes"][0]["w"] = 1
    _write(factory, data, "full", partial=False)
    _write(factory, data, "part", partial=True)
    assert _rows(factory, "part") == _rows(factory, "full")
    dumped = _dump(factory, "part")
    link = next(n for n in dumped["nodes"] if n["id"] == node["id"])["links"][0]
    assert isinstance(link["port"], float) and dumped["routes"][0]["w"] == 1 and dumped["routes"][0]["w"] is not True


def test_one_place_edited_is_a_handful_of_statements(db):
    engine, factory = db
    data = _fixture()
    _write(factory, data, "s", partial=False)
    data["nodes"][5]["role"] = "changed"
    seen = []
    listen = lambda conn, cur, statement, *a: seen.append(statement.split()[0].upper())  # noqa: E731
    event.listen(engine, "before_cursor_execute", listen)
    try:
        _write(factory, data, "s", partial=True)
    finally:
        event.remove(engine, "before_cursor_execute", listen)
    writes = [k for k in seen if k in ("INSERT", "UPDATE", "DELETE")]
    assert writes.count("UPDATE") == 2 and len(writes) == 2, seen   # the node and the site
    assert len(seen) < 30, seen


def _retire(factory, slug, source="netbox"):
    with factory() as s:
        row = s.scalar(select(Node).where(Node.slug == slug))
        row.status, row.external_source, row.external_ref = "retired", source, "nb-42"
        s.commit()


def test_a_desk_save_keeps_a_place_an_importer_retired(db):
    """The dump hides a retired place, so the editor's copy lacks it; a save
    used to delete its row (2026-11-15). It stays, hidden, with its identity,
    as the importers keep it. The import's full replace still removes it."""
    _, factory = db
    data = _fixture()
    _write(factory, data, "s", partial=False)
    kept = data["nodes"][4]["id"]
    _retire(factory, kept)
    with factory() as s:
        before = s.scalar(select(Node).where(Node.slug == kept)).id
    data = _dump(factory, "s")
    assert kept not in {n["id"] for n in data["nodes"]}
    data["nodes"][0]["role"] = "an edit"
    _write(factory, data, "s", partial=True)
    with factory() as s:
        row = s.scalar(select(Node).where(Node.slug == kept))
        assert row is not None and row.id == before and row.status == "retired"
    assert kept not in {n["id"] for n in _dump(factory, "s")["nodes"]}
    _write(factory, data, "s", partial=False)   # the import: the file is the truth
    with factory() as s:
        assert s.scalar(select(Node).where(Node.slug == kept)) is None


@pytest.mark.parametrize("partial", [False, True])
def test_a_place_added_under_a_retired_id_comes_back(db, partial):
    """It stayed hidden however often it was added (the dump hides the row it
    landed on). Now it is back on the map as a place charted by hand: its row
    and id survive, the importer's claim on it does not."""
    _, factory = db
    data = _fixture()
    _write(factory, data, "s", partial=False)
    back = data["nodes"][4]["id"]
    _retire(factory, back)
    data = _dump(factory, "s")
    data["nodes"].append({"id": back, "name": "Back again", "kind": "vm", "zone": data["zones"][0]["id"],
                          "x": 1.0, "y": 2.0, "role": "returned"})
    _write(factory, data, "s", partial=partial)
    shown = {n["id"]: n for n in _dump(factory, "s")["nodes"]}
    assert shown[back]["name"] == "Back again"
    with factory() as s:
        row = s.scalar(select(Node).where(Node.slug == back))
        # charted by hand now: the importer's claim goes, or its next run
        # would retire it again (review, 2026-11-15)
        assert row.status == "documented" and row.external_ref is None
        assert row.external_source != "netbox"


def _site(s, slug="s"):
    return s.scalar(select(Site).where(Site.slug == slug))


def test_a_place_added_back_by_hand_survives_the_importers_next_run(db):
    from importers.csv_import import import_rows, parse_csv
    _, factory = db
    data = _fixture()
    _write(factory, data, "s", partial=False)
    back = data["nodes"][4]["id"]
    with factory() as s:
        row = s.scalar(select(Node).where(Node.slug == back))
        row.status, row.external_source, row.external_ref = "retired", "csv", back
        s.commit()
    data = _dump(factory, "s")
    data["nodes"].append({"id": back, "name": "Mine now", "kind": "vm", "zone": data["zones"][0]["id"],
                          "x": 1.0, "y": 2.0, "role": "by hand"})
    _write(factory, data, "s", partial=True)
    rows, errors = parse_csv("name,ip\nsomething-else,10.250.0.9\n")
    assert not errors
    with factory() as s:
        import_rows(s, rows, site_slug="s", retire_missing=True)
        s.commit()
    assert back in {n["id"] for n in _dump(factory, "s")["nodes"]}


def _snapshot(*devices):
    return {"vlans": [], "prefixes": [], "vms": [], "devices": [
        {"id": i, "name": name, "primary_ip4": {"address": f"{ip}/24"},
         "role": {"slug": "server", "name": "Server"}} for i, name, ip in devices]}


def _sync(factory, *devices):
    from importers.netbox import DEFAULT_ROLE_MAP, sync
    with factory() as s:
        stats = sync(s, _snapshot(*devices), site_slug="s", role_map=DEFAULT_ROLE_MAP)
        s.commit()
    return stats


def test_netbox_finds_a_device_back_under_its_suffixed_name_without_failing(db):
    """A device named like a hand-charted place at another address gets
    `<name>-device<id>`; retired, charted back by hand, then back in NetBox,
    the sync inserted that slug again unchecked and failed on every run
    (review, 2026-11-15). Now it adopts the row it lands on."""
    _, factory = db
    data = _fixture()
    data["nodes"].append({"id": "webx", "name": "webx", "kind": "vm", "zone": data["zones"][0]["id"],
                          "x": 1.0, "y": 1.0, "role": "hand", "ip": "10.250.0.1"})
    _write(factory, data, "s", partial=False)
    _sync(factory, (12, "webx", "10.250.0.2"))
    _sync(factory)                                    # gone from NetBox: retired
    data = _dump(factory, "s")
    assert "webx-device12" not in {n["id"] for n in data["nodes"]}
    data["nodes"].append({"id": "webx-device12", "name": "webx again", "kind": "vm",
                          "zone": data["zones"][0]["id"], "x": 2.0, "y": 2.0, "role": "hand",
                          "ip": "10.250.0.2"})
    _write(factory, data, "s", partial=True)          # charted back by hand
    for _ in range(2):                                # back in NetBox, twice over
        _sync(factory, (12, "webx", "10.250.0.2"))
    with factory() as s:
        rows = list(s.scalars(select(Node).where(Node.slug.like("webx%"))))
    assert sorted(r.slug for r in rows) == ["webx", "webx-device12"]
    adopted = next(r for r in rows if r.slug == "webx-device12")
    assert (adopted.external_source, adopted.external_ref, adopted.status) == ("netbox", "device:12", "documented")


def test_a_netbox_place_a_csv_brings_back_stays_netboxs(db):
    """NetBox decides for what it owns (review, 2026-11-15): taken over by the
    CSV, the device coming back at another address became a second place,
    and back at its own address a clash on it. Kept NetBox's, its next sync
    without it retires it again, and its return updates the one row."""
    from importers.csv_import import import_rows, parse_csv
    _, factory = db
    _write(factory, _fixture(), "s", partial=False)
    _sync(factory, (7, "nbbox", "10.250.0.7"))
    _sync(factory)                                    # retired
    rows, errors = parse_csv("name,ip\nnbbox,10.250.0.7\n")
    assert not errors
    with factory() as s:
        import_rows(s, rows, site_slug="s")
        s.commit()
    assert "nbbox" in {n["id"] for n in _dump(factory, "s")["nodes"]}
    _sync(factory, (7, "nbbox", "10.250.0.70"))       # back, elsewhere
    _sync(factory, (7, "nbbox", "10.250.0.7"))        # and home again
    with factory() as s:
        rows = list(s.scalars(select(Node).where(Node.slug.like("nbbox%"))))
    assert [(r.slug, r.external_ref, r.ip) for r in rows] == [("nbbox", "device:7", "10.250.0.7")]


def test_netbox_bringing_a_place_back_heals_its_network_and_a_retired_parent(db):
    import validation
    _, factory = db
    _write(factory, _fixture(), "s", partial=False)
    _sync(factory, (8, "hostp", "10.250.0.8"), (9, "guestc", "10.250.0.9"))
    with factory() as s:
        child = s.scalar(select(Node).where(Node.slug == "guestc"))
        child.zone_slug, child.parent_slug = "a-network-since-removed", "hostp"
        s.commit()
    _sync(factory)                                    # both retired
    _sync(factory, (9, "guestc", "10.250.0.9"))       # only the child comes back
    dumped = _dump(factory, "s")
    back = next(n for n in dumped["nodes"] if n["id"] == "guestc")
    assert back["zone"] in {z["id"] for z in dumped["zones"]} and "parent" not in back
    assert not [p for p in validation.validate(dumped, strict=True) if "guestc" in p]


def test_nmap_does_not_match_a_device_to_a_retired_place(db):
    from importers.nmap import import_observations
    _, factory = db
    data = _fixture()
    _write(factory, data, "s", partial=False)
    gone = next(n for n in data["nodes"] if n.get("ip") not in (None, "", "—"))
    with factory() as s:
        s.scalar(select(Node).where(Node.slug == gone["id"])).status = "retired"
        s.commit()
    with factory() as s:
        stats = import_observations(s, [{"ip": gone["ip"]}], site_slug="s", source="nmap", promote=False)
        s.commit()
    assert stats["undocumented"] == 1 and stats["matched"] == 0


def test_an_importer_bringing_a_place_back_heals_a_network_or_parent_that_went(db):
    """Revived as it was, a place in a removed network fails validation and
    every save after it is refused (review, 2026-11-15)."""
    import validation
    from importers.csv_import import import_rows, parse_csv
    _, factory = db
    data = _fixture()
    _write(factory, data, "s", partial=False)
    back = next(n for n in data["nodes"] if n.get("ip") not in (None, "", "—"))
    with factory() as s:
        row = s.scalar(select(Node).where(Node.slug == back["id"]))
        row.status, row.external_source, row.external_ref = "retired", "csv", back["id"]
        row.zone_slug, row.parent_slug = "a-network-since-removed", "a-host-since-removed"
        s.commit()
    rows, errors = parse_csv(f"name,ip\n{back['id']},{back['ip']}\n")
    assert not errors
    with factory() as s:
        import_rows(s, rows, site_slug="s")
        s.commit()
    dumped = _dump(factory, "s")
    revived = next(n for n in dumped["nodes"] if n["id"] == back["id"])
    assert revived["zone"] in {z["id"] for z in dumped["zones"]} and "parent" not in revived
    assert not [p for p in validation.validate(dumped, strict=True) if back["id"] in p]


def test_rows_an_importer_left_tied_in_order_dump_by_their_age(db):
    """The importers number what they add in sequence, but nothing in the
    schema stops two rows sharing a `sort_order`; the dump breaks a tie by row
    id (the order they were added), every time, and a save keeps it."""
    _, factory = db
    data = _fixture()
    _write(factory, data, "s", partial=False)
    with factory() as s:
        sid = s.scalar(select(Site.id).where(Site.slug == "s"))
        for slug in ("tie-b", "tie-a"):
            s.add(Node(site_id=sid, slug=slug, name=slug, sort_order=999, extra_json={}))
        s.commit()
    ids = [n["id"] for n in _dump(factory, "s")["nodes"]]
    assert ids[-2:] == ["tie-b", "tie-a"]
    data = _dump(factory, "s")
    _write(factory, data, "s", partial=True)
    assert [n["id"] for n in _dump(factory, "s")["nodes"]] == ids


def test_an_unchanged_place_keeps_its_row_and_its_import_time(db):
    _, factory = db
    data = _fixture()
    _write(factory, data, "s", partial=False)
    with factory() as s:
        before = {n.slug: (n.id, n.last_imported) for n in s.scalars(select(Node))}
    data["nodes"][0]["role"] = "changed"
    _write(factory, data, "s", partial=True)
    with factory() as s:
        after = {n.slug: (n.id, n.last_imported) for n in s.scalars(select(Node))}
    changed = data["nodes"][0]["id"]
    assert {k: v for k, v in after.items() if k != changed} == {k: v for k, v in before.items() if k != changed}
    assert after[changed][0] == before[changed][0] and after[changed][1] != before[changed][1]
