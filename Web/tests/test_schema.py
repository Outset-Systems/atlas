"""The field catalogue and the validator built on it.

The catalogue is the single definition of what the dataset is — the forms, the
strict write check and the warnings on `/api/status` all read it. So the thing
worth guarding is that it still describes the *real* dataset: the day a field
is added to the map and not to the catalogue, the editor silently cannot edit
it, and that must fail here rather than in someone's browser.
"""

import json
import os
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

import schema  # noqa: E402
from validation import validate  # noqa: E402

REAL = os.path.join(os.path.dirname(WEB), "Data", "lab-data.json")
BUNDLED = os.path.join(WEB, "default-lab-data.json")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ── the catalogue describes the shipped datasets ────────────────────────────

@pytest.mark.parametrize("path", [BUNDLED, REAL])
def test_shipped_datasets_validate_clean(path):
    if not os.path.exists(path):
        pytest.skip(f"{path} not present in this checkout")
    assert validate(load(path)) == [], f"{os.path.basename(path)} must validate clean"


@pytest.mark.parametrize("path", [BUNDLED, REAL])
def test_every_shipped_service_says_what_it_is(path):
    """Every charted service carries its own description.

    `links[].desc` is deliberately *optional* in the catalogue — a service
    discovered by the NetBox or nmap importer has no prose and must not be
    warned about for it, and the service pane falls back to stating where the
    thing runs. This is the stricter bar the hand-charted map holds itself to:
    the pane's whole job is to say what a service is *for*, and the fallback
    sentence only repeats the epigraph above it and the host line below it.

    If this fails because a service was just charted, the fix is to write the
    sentence, not to relax the test.
    """
    if not os.path.exists(path):
        pytest.skip(f"{path} not present in this checkout")
    vague = [f"{node['id']}.{link.get('label')}"
             for node in load(path).get("nodes") or []
             for link in node.get("links") or []
             if not (link.get("desc") or "").strip()]
    assert vague == [], "these services have no description"


@pytest.mark.parametrize("path", [BUNDLED, REAL])
def test_every_service_road_is_built_of_real_roads(path):
    """`links[].path` may only walk routes the map already charts.

    The chain drawn for a service is a claim about how traffic actually
    travels, and it is drawn in the same ink as the roads themselves — so a hop
    between two places with no route between them is the map inventing
    infrastructure. That is worse than the star it replaced, which at least
    only claimed "these are related".

    Checked as an undirected pair against routes[], starting from the service's
    own place, because a road is walkable both ways and the dataset charts each
    one once.
    """
    if not os.path.exists(path):
        pytest.skip(f"{path} not present in this checkout")
    data = load(path)
    ids = {n["id"] for n in data.get("nodes") or []}
    roads = set()
    for route in data.get("routes") or []:
        roads.add((route["from"], route["to"]))
        roads.add((route["to"], route["from"]))

    invented = []
    for node in data.get("nodes") or []:
        for link in node.get("links") or []:
            hops = link.get("path")
            if not hops:
                continue
            chain = [node["id"], *hops]
            for a, b in zip(chain, chain[1:]):
                where = f"{node['id']}.{link.get('label')}"
                if b not in ids:
                    invented.append(f"{where}: unknown place {b!r}")
                elif (a, b) not in roads:
                    invented.append(f"{where}: {a} -> {b} is not a charted route")
    assert invented == [], "these service roads cross ground with no route on it"


def test_catalogue_covers_every_key_the_real_dataset_uses():
    """No field may exist on the map that the editor cannot show.

    An unmodelled key still round-trips — the dataset is allowed to be richer
    than the catalogue — but it becomes invisible in the form, which is how a
    field quietly stops being maintained.
    """
    if not os.path.exists(REAL):
        pytest.skip("the real dataset is not in this checkout")
    data = load(REAL)
    missing = []
    for key, section in schema.SECTIONS.items():
        entries = data.get(key)
        if section["kind"] == "object":
            entries = [entries] if isinstance(entries, dict) else []
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            known = {f["name"] for f in section["fields"]}
            missing += [f"{key}.{k}" for k in entry if k not in known]
            for field in section["fields"]:
                if field["type"] != "objects":
                    continue
                subknown = {f["name"] for f in field.get("of", [])}
                for sub in entry.get(field["name"]) or []:
                    missing += [f"{key}.{field['name']}.{k}"
                                for k in sub if k not in subknown]
    assert sorted(set(missing)) == [], "these keys are on the map but not in schema.py"


def test_every_section_in_the_order_exists():
    for key in schema.SECTION_ORDER:
        assert key in schema.SECTIONS, f"{key} is ordered but not defined"


def test_catalogue_serializes_for_the_browser():
    """The editor fetches this verbatim; anything unserializable breaks it."""
    blob = json.dumps(schema.catalogue())
    assert '"nodes"' in blob and '"fields"' in blob


def test_references_point_at_real_sections():
    for key in schema.SECTIONS:
        for path, target in schema.refs_of(key):
            assert target in schema.SECTIONS, f"{key}.{path} points at unknown {target!r}"


# ── field checking ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,value,ok", [
    ("slug", "app-host", True), ("slug", "Bad Id", False), ("slug", "a.b-c_d", True),
    ("url", "https://x/y", True), ("url", "ftp://x", False),
    ("link", "report/security", True), ("link", "//evil.example", False),
    ("link", "https://x", True),
    ("color", "#C9A554", True), ("color", "red", False),
    ("ip", "10.0.0.1", True), ("ip", "—", True), ("ip", "100.64.0.0/10", True),
    ("ip", "999.1.1.1", False),
    ("cidr", "10.0.0.0/8", True), ("cidr", "fd00::/64", True), ("cidr", "10.0.0.0/33", False),
    ("scalar", 4, True), ("scalar", "—", True), ("scalar", [], False),
    ("percent", 50, True), ("percent", 130, True), ("percent", 300, False),
])
def test_value_checks(kind, value, ok):
    field = schema.f("thing", kind)
    assert (schema.check_value(field, value) is None) is ok


def test_strict_refuses_a_blank_required_field_but_warnings_do_not():
    entry = {"id": "x", "name": "", "kind": "vm", "zone": "z", "x": 1, "y": 1,
             "role": "r", "lore": "l"}
    assert schema.check_entry("nodes", entry, strict=False) == []
    assert "name cannot be blank" in schema.check_entry("nodes", entry, strict=True)


def test_blank_entry_fills_defaults():
    fresh = schema.blank("routes")
    assert fresh["kind"] == "vlan" and fresh["from"] == "" and fresh["to"] == ""


# ── cross-entry rules ───────────────────────────────────────────────────────

def _map(**over):
    data = {
        "meta": {"title": "T"},
        "zones": [{"id": "z", "name": "Z", "vlan": 1, "subnet": "10.0.0.0/24",
                   "hue": "#ffffff", "lore": "l", "label_x": 1, "label_y": 2}],
        "nodes": [],
        "routes": [],
    }
    data.update(over)
    return data


def node(nid, ip=None, kind="physical"):
    out = {"id": nid, "name": nid.upper(), "kind": kind, "zone": "z",
           "x": 1, "y": 1, "role": "r", "lore": "l"}
    if ip:
        out["ip"] = ip
    return out


def test_two_real_hosts_on_one_address_is_a_problem():
    problems = validate(_map(nodes=[node("a", "10.0.0.5"), node("b", "10.0.0.5")]))
    assert any("already claimed by" in p for p in problems)


def test_a_service_marker_may_share_its_host_address():
    """Traefik and Pangolin both answer on the edge's address, on purpose."""
    problems = validate(_map(nodes=[node("host", "10.0.0.5"),
                                    node("svc", "10.0.0.5", kind="network")]))
    assert problems == [], problems


def test_dangling_references_are_reported_not_fatal():
    problems = validate(_map(nodes=[node("a")], routes=[{"from": "a", "to": "ghost"}]))
    assert any("ghost" in p for p in problems)


def test_a_pool_outside_its_prefix_is_reported():
    data = _map(prefixes=[{"id": "p", "cidr": "10.0.0.0/24",
                           "ranges": [{"start": "10.9.9.1", "end": "10.9.9.2", "kind": "dhcp"}]}])
    problems = validate(data)
    assert any("outside 10.0.0.0/24" in p for p in problems)


def test_a_backwards_range_is_reported():
    data = _map(prefixes=[{"id": "p", "cidr": "10.0.0.0/24",
                           "ranges": [{"start": "10.0.0.9", "end": "10.0.0.2", "kind": "dhcp"}]}])
    assert any("starts after it ends" in p for p in validate(data))


def test_an_empty_map_is_valid():
    """A fresh install must not open unhealthy."""
    from labdata import EMPTY_DATASET
    assert validate(EMPTY_DATASET) == []


# ── one reference is one id, as text (2026-11-13) ────────────────────────────

@pytest.mark.parametrize("value,ok", [
    ("alpha", True), ("", True), ("—", True),
    (["alpha"], False), ({"id": "alpha"}, False), (7, False), (True, False),
])
def test_one_reference_is_one_id_as_text(value, ok):
    fld = schema.field("certs", "place")
    assert fld["type"] == "ref"
    assert (schema.check_value(fld, value) is None) is ok


def test_a_list_where_one_id_belongs_is_reported_not_fatal():
    problems = validate(_map(
        nodes=[node("a")],
        routes=[{"from": ["a"], "to": {"id": "a"}}],
        certs=[{"name": "c", "kind": "tls", "place": [["a"]]}],
        regions=[{"id": "r", "name": "R", "x": 1, "y": 1, "w": 10, "h": 10,
                  "parent": ["r"]}]), strict=True)
    joined = " | ".join(problems)
    assert "from must be one id, as text" in joined
    assert "to must be one id, as text" in joined
    assert "place must be one id, as text" in joined
    assert "parent must be one id, as text" in joined
