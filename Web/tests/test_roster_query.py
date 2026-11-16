"""The roster's filter, sort and page on the server (2026-11-15, stage 5).

`roster_query.py` ports NODES' own rules (`static/js/roster-model.js`). The
two are held to the same answers by `roster_query_cases.json`, whose
expectations the browser model made and `test_roster_query.mjs` re-checks.
"""

import datetime
import json
import os
import shutil
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

import roster_query  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "roster_query_cases.json"), encoding="utf-8") as fh:
    CASES = json.load(fh)
NOW_MS = datetime.datetime.fromisoformat(CASES["now"].replace("Z", "+00:00")).timestamp() * 1000

# the browser's filter names, as the server's parameters
_NAMES = {"staleDays": "stale_days"}


def _server_filter(f):
    out = {"text": "", "state": "", "zone": "", "kind": "", "collection": "", "unchecked": False,
           "stale_days": 0}
    out.update({_NAMES.get(k, k): v for k, v in f.items()})
    return out


@pytest.mark.parametrize("case", CASES["cases"],
                         ids=[f"{json.dumps(c['filter'])}-{c['sort']}-{c['dir']}" for c in CASES["cases"]])
def test_the_server_gives_every_shared_case_the_browsers_answer(case):
    rows = roster_query.filter_rows(CASES["rows"], _server_filter(case["filter"]), NOW_MS)
    rows = roster_query.sort_rows(rows, case["sort"], case["dir"], CASES["collections"])
    assert [r["id"] for r in rows] == case["expect"]


def test_every_sort_key_of_the_browser_is_here():
    assert {c["sort"] for c in CASES["cases"]} <= set(roster_query.SORT_KEYS)


def test_a_page_is_cut_after_the_sort_and_says_how_many_matched():
    roster = {"stamp": "s", "rows": CASES["rows"], "collections": CASES["collections"]}
    query = roster_query.parse({"sort": "name", "limit": "3", "offset": "2"})
    out = roster_query.apply(roster, query, NOW_MS)
    every = roster_query.sort_rows(CASES["rows"], "name", "asc", CASES["collections"])
    assert [r["id"] for r in out["rows"]] == [r["id"] for r in every[2:5]]
    assert (out["total"], out["offset"], out["limit"], out["stamp"]) == (len(CASES["rows"]), 2, 3, "s")


@pytest.mark.parametrize("args", [{"limit": "0"}, {"limit": "x"}, {"limit": str(roster_query.MAX_LIMIT + 1)},
                                  {"offset": "-1"}, {"sort": "nope"}, {"dir": "up"}, {"unchecked": "yes"},
                                  {"stale_days": "-2"}])
def test_a_parameter_it_cannot_use_is_refused(args):
    with pytest.raises(roster_query.QueryError):
        roster_query.parse(args)


def test_old_names_still_work():
    assert roster_query.wanted({"set": "c-db"})   # alone, too
    q = roster_query.parse({"sort": "sets", "set": "c-db"})
    assert q["sort"] == "collections" and q["filter"]["collection"] == "c-db"


# ── through the route ────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(os.path.join(WEB, "default-lab-data.json"), data)
    handle = fresh_app(ATLAS_DATA=str(data), ATLAS_READONLY="0",
                       ATLAS_BEATS=str(tmp_path / "hb.json"), ATLAS_BEATS_DIR=str(tmp_path / "beats"),
                       ATLAS_MAINTENANCE=str(tmp_path / "m.json"), ATLAS_EVENTS=str(tmp_path / "e.json"),
                       ATLAS_REVISIONS=str(tmp_path / "rev"))
    return handle.app.test_client()


def test_without_parameters_the_roster_is_every_row_as_before(client):
    body = client.get("/api/v2/places/roster").get_json()
    assert "total" not in body and len(body["rows"]) > 3


def test_the_route_pages_by_the_same_rules(client):
    every = client.get("/api/v2/places/roster").get_json()
    page = client.get("/api/v2/places/roster?sort=name&dir=desc&limit=2&offset=1").get_json()
    expect = roster_query.sort_rows(every["rows"], "name", "desc", every["collections"])[1:3]
    assert [r["id"] for r in page["rows"]] == [r["id"] for r in expect]
    assert page["total"] == len(every["rows"]) and page["stamp"] == every["stamp"]


def test_the_route_refuses_a_bad_parameter(client):
    r = client.get("/api/v2/places/roster?limit=nope")
    assert r.status_code == 400 and "limit" in r.get_json()["error"]
