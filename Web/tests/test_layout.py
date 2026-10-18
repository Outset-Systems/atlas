"""Auto-layout tests — run directly, no pytest needed:

    python Web/tests/test_layout.py

Guards the properties the map depends on: fills only what's missing, never
moves a hand-placed or locked node, rings children around their parent, stays
on the table, and is stable across re-runs.
"""

import os
import sys
import tempfile

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

TMP = tempfile.mkdtemp(prefix="atlas-layout-test-")
DB_URL = "sqlite:///" + os.path.join(TMP, "layout.db").replace("\\", "/")
# Declared once so conftest can re-apply it before every test in this
# module. pytest imports all test modules before running any of them, so
# without this the last module imported owns os.environ for the whole run.
ATLAS_TEST_ENV = {
    "ATLAS_DB_URL": DB_URL,
}
os.environ.update(ATLAS_TEST_ENV)

from store import init_db, session_scope  # noqa: E402
from store.layout import auto_layout  # noqa: E402
from store.models import Node, Site, Zone  # noqa: E402

init_db()


def _scope():
    os.environ["ATLAS_DB_URL"] = DB_URL
    return session_scope()


def _site(session, slug, zones=(), nodes=()):
    site = Site(slug=slug, name=slug)
    session.add(site)
    session.flush()
    for i, z in enumerate(zones):
        session.add(Zone(site_id=site.id, slug=z["slug"], name=z["slug"], vlan=z.get("vlan"),
                         subnet=z.get("subnet"), label_x=z.get("label_x"),
                         label_y=z.get("label_y"), sort_order=i, extra_json={}))
    for i, n in enumerate(nodes):
        session.add(Node(site_id=site.id, slug=n["slug"], name=n["slug"],
                         kind=n.get("kind", "unknown"), zone_slug=n.get("zone"),
                         x=n.get("x"), y=n.get("y"),
                         layout_locked=n.get("locked", False),
                         parent_slug=n.get("parent"), sort_order=i, extra_json={}))
    session.flush()
    return site


def _nodes(session, site):
    return {n.slug: n for n in session.query(Node).filter(Node.site_id == site.id)}


def test_places_only_missing_and_respects_locks():
    with _scope() as s:
        site = _site(
            s,
            "only-missing",
            zones=[{"slug": "a", "vlan": 10, "label_x": 30.0, "label_y": 40.0}],
            nodes=[
                {"slug": "hand", "zone": "a", "x": 11.0, "y": 12.0},
                {"slug": "locked", "zone": "a", "locked": True},
                {"slug": "fresh", "zone": "a"},
            ],
        )
        placed = auto_layout(s, site)
        n = _nodes(s, site)
    assert placed == 1, f"expected only the unplaced node to move, got {placed}"
    assert (n["hand"].x, n["hand"].y) == (11.0, 12.0), "hand-placed node moved"
    assert n["locked"].x is None, "locked node must never be positioned"
    assert n["fresh"].x is not None and n["fresh"].y is not None


def test_children_ring_their_parent():
    with _scope() as s:
        site = _site(
            s,
            "rings",
            zones=[{"slug": "a", "vlan": 10, "label_x": 50.0, "label_y": 50.0}],
            nodes=[{"slug": "host", "zone": "a"}]
            + [{"slug": f"guest{i}", "zone": "a", "parent": "host"} for i in range(6)],
        )
        auto_layout(s, site)
        n = _nodes(s, site)
    px, py = n["host"].x, n["host"].y
    dists = [((n[f"guest{i}"].x - px) ** 2 + (n[f"guest{i}"].y - py) ** 2) ** 0.5
             for i in range(6)]
    assert max(dists) - min(dists) < 0.01, f"children not equidistant from parent: {dists}"
    assert 4.0 < dists[0] < 13.0, f"ring radius unreasonable: {dists[0]}"
    xs = {round(n[f"guest{i}"].x, 3) for i in range(6)}
    ys = {round(n[f"guest{i}"].y, 3) for i in range(6)}
    assert len(xs) > 1 and len(ys) > 1, "children stacked on one point"


def test_grandchildren_and_cycles_resolve():
    with _scope() as s:
        site = _site(
            s,
            "deep",
            zones=[{"slug": "a", "vlan": 10, "label_x": 50.0, "label_y": 50.0}],
            nodes=[
                {"slug": "root", "zone": "a"},
                {"slug": "mid", "zone": "a", "parent": "root"},
                {"slug": "leaf", "zone": "a", "parent": "mid"},
                # a cycle must not hang or vanish
                {"slug": "loop-a", "zone": "a", "parent": "loop-b"},
                {"slug": "loop-b", "zone": "a", "parent": "loop-a"},
            ],
        )
        placed = auto_layout(s, site)
        n = _nodes(s, site)
    assert placed == 5
    for slug in ("root", "mid", "leaf", "loop-a", "loop-b"):
        assert n[slug].x is not None and n[slug].y is not None, f"{slug} left unplaced"
    d = ((n["leaf"].x - n["mid"].x) ** 2 + (n["leaf"].y - n["mid"].y) ** 2) ** 0.5
    assert d < 13.0, "grandchild should ring its own parent"


def test_fresh_site_gets_vlan_ordered_bands_and_stays_on_table():
    with _scope() as s:
        site = _site(
            s,
            "fresh-site",
            zones=[{"slug": "high", "vlan": 90}, {"slug": "low", "vlan": 4},
                   {"slug": "novlan"}],
            nodes=[{"slug": f"{z}-{i}", "zone": z}
                   for z in ("high", "low", "novlan") for i in range(3)],
        )
        auto_layout(s, site)
        zones = {z.slug: z for z in s.query(Zone).filter(Zone.site_id == site.id)}
        n = _nodes(s, site)
    assert zones["low"].label_y < zones["high"].label_y < zones["novlan"].label_y, \
        "bands must run in VLAN order with un-VLANed zones last"
    for node in n.values():
        assert 0 <= node.x <= 100 and -40 <= node.y <= 140, f"{node.slug} off the table"


def test_rerun_is_stable():
    with _scope() as s:
        site = _site(
            s,
            "stable",
            zones=[{"slug": "a", "vlan": 10}],
            nodes=[{"slug": f"n{i}", "zone": "a"} for i in range(8)]
            + [{"slug": f"c{i}", "zone": "a", "parent": "n0"} for i in range(3)],
        )
        auto_layout(s, site)
        first = {k: (v.x, v.y) for k, v in _nodes(s, site).items()}
        again = auto_layout(s, site)
        second = {k: (v.x, v.y) for k, v in _nodes(s, site).items()}
    assert again == 0, "a second run must have nothing left to place"
    assert first == second, "layout drifted between runs"


if __name__ == "__main__":
    failures = 0
    for name in sorted(n for n in globals() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"  ok   {name}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {name}: {e}")
    print("PASS" if not failures else f"{failures} FAILURE(S)")
    sys.exit(1 if failures else 0)
