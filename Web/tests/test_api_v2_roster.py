"""THE PLACES TABLE — `GET /api/v2/places/roster` (2026-11-13).

One row per place the reader may see, built on the server from the redacted
map and the redacted live feed. What matters: a hidden place has no row and is
named nowhere, for a viewer with no groups and for a token; a cloud token is
refused; who reviewed a place is for an admin; "confirmed by" names the source
whose answer won the merge; and the certificate, repair and set columns say
what the map holds.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import viewers

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts"}

URL = "/api/v2/places/roster"
NOW = datetime.now(timezone.utc)
SOON = (NOW + timedelta(days=30)).strftime("%Y-%m-%d")
LATER = (NOW + timedelta(days=3)).replace(microsecond=0)

REVIEWED = {"charted_at": "2026-11-01T00:00:00Z", "source": "hand", "charted_by": "ops",
            "changed_at": "2026-11-01T00:00:00Z", "changed_by": "ops",
            "reviewed": True, "reviewed_at": "2026-11-02T00:00:00Z", "reviewed_by": "ops"}
IMPORTED = {"charted_at": "2026-11-03T00:00:00Z", "source": "unifi", "charted_by": "ops",
            "changed_at": "2026-11-03T00:00:00Z", "reviewed": False}


def _data():
    data = viewers.dataset(
        certs=[
            {"name": "alpha.example", "kind": "tls", "issuer": "step-ca", "expires": SOON,
             "place": "alpha"},
            {"name": "alpha-old.example", "kind": "tls", "issuer": "step-ca",
             "expires": "2099-01-01", "place": "alpha"},
            {"name": "vault.example", "kind": "tls", "issuer": "step-ca", "expires": SOON,
             "place": "secret-place"},
        ],
        sets=[{"id": "core-set", "name": "Core boxes", "places": ["alpha", "secret-place"]}],
    )
    alpha, beta, _secret = data["nodes"]
    alpha.update(mac="00:11:32:aa:bb:cc", provenance=REVIEWED,
                 depends_on=["beta", "secret-place"],
                 links=[{"label": "One", "url": "http://192.0.2.5/"},
                        {"label": "Two", "url": "http://192.0.2.5:8080/"}])
    beta.update(provenance=IMPORTED, ip="—")
    data["nodes"].append(viewers.place("gamma", "Gamma"))
    return data


WINDOWS = [
    {"id": "now", "reason": "patching", "nodes": ["gamma"],
     "starts": "2020-01-01T00:00:00Z", "ends": "2099-01-01T00:00:00Z", "repeat": "none"},
    {"id": "later", "reason": "disks", "nodes": ["alpha"],
     "starts": LATER.strftime("%Y-%m-%dT%H:%M:%SZ"),
     "ends": (LATER + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), "repeat": "none"},
]


@pytest.fixture
def realm(tmp_path, monkeypatch):
    import signals as S

    class First(S._Adapter):
        name = "first"

        def _fetch(self):
            return {"nodes": {"alpha": {"state": "healthy"}, "beta": {"state": "down"},
                              "gamma": {"state": "healthy"},
                              "secret-place": {"state": "down"}}}

    class Second(S._Adapter):
        name = "second"

        def _fetch(self):
            # wins alpha's state; adds to beta without a state, so beta stays First's
            return {"nodes": {"alpha": {"state": "degraded"}, "beta": {"uptime_30d": 99.1},
                              "secret-place": {"state": "healthy"}}}

    handle = viewers.build(tmp_path, monkeypatch, _data(), windows=WINDOWS)
    handle.app.extensions["atlas"].signals = S.SignalsHub([First(), Second()], ttl=0)
    yield handle
    monkeypatch.undo()


def _rows(body):
    return {r["id"]: r for r in body["rows"]}


def _as(realm, who):
    if who == "token":
        return realm.app.test_client().get(URL, headers=viewers.issue(realm))
    return viewers.signed_in(realm, who).get(URL)


# ── who sees what ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["alice", "token"])
def test_a_hidden_place_has_no_row_and_is_named_nowhere(realm, who):
    r = _as(realm, who)
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert set(_rows(body)) == {"alpha", "beta", "gamma"}
    text = json.dumps(body)
    for word in ("secret-place", "Secret", "192.0.2.99", "vault.example"):
        assert word not in text, word


def test_an_admin_sees_every_place(realm):
    body = _as(realm, "ops").get_json()
    assert set(_rows(body)) == {"alpha", "beta", "gamma", "secret-place"}


def test_a_cloud_token_is_refused(realm):
    r = realm.app.test_client().get(URL, headers=viewers.issue(realm, "cloud"))
    assert r.status_code == 403 and "MCP endpoint only" in r.get_json()["reason"]


def test_a_stranger_is_not_answered(realm):
    assert realm.app.test_client().get(URL).status_code in (302, 401)


def test_who_reviewed_a_place_is_for_an_admin(realm):
    assert _rows(_as(realm, "ops").get_json())["alpha"]["reviewed_by"] == "ops"
    for who in ("alice", "token"):
        row = _rows(_as(realm, who).get_json())["alpha"]
        assert "reviewed_by" not in row, who
        assert "ops" not in json.dumps(row), who
        assert row["reviewed"] is True and row["reviewed_at"] == "2026-11-02T00:00:00Z"


def test_the_answer_is_never_stored(realm):
    r = _as(realm, "alice")
    assert r.headers["Cache-Control"] == "no-store"
    assert "Cookie" in r.headers["Vary"]


# ── the columns ──────────────────────────────────────────────────────────────

def test_confirmed_by_names_the_source_that_won_the_merge(realm):
    rows = _rows(_as(realm, "alice").get_json())
    assert (rows["alpha"]["state"], rows["alpha"]["confirmed_by"]) == ("degraded", "second")
    # Second added to beta without a state: the state, and the credit, stay First's
    assert (rows["beta"]["state"], rows["beta"]["confirmed_by"]) == ("down", "first")
    # under repair: the state is the window's, and no source is named
    assert (rows["gamma"]["state"], rows["gamma"]["confirmed_by"]) == ("maintenance", None)


def test_the_feed_says_who_confirmed_and_hides_a_hidden_place(realm):
    feed = viewers.signed_in(realm, "alice").get("/api/v2/signals").get_json()
    assert feed["confirmed_by"] == {"alpha": "second", "beta": "first"}
    admin = viewers.signed_in(realm, "ops").get("/api/v2/signals").get_json()
    assert admin["confirmed_by"] == {"alpha": "second", "beta": "first", "secret-place": "second"}


def test_the_nearest_certificate_and_its_days(realm):
    import certs
    row = _rows(_as(realm, "alice").get_json())["alpha"]
    assert row["cert"]["name"] == "alpha.example" and row["cert"]["expires"] == SOON
    want = certs.days_left({"expires": SOON}, datetime.now(timezone.utc))
    assert row["cert"]["days"] == want and 29 <= want <= 31
    assert _rows(_as(realm, "alice").get_json())["beta"]["cert"] is None


def test_maintenance_now_and_next(realm):
    rows = _rows(_as(realm, "alice").get_json())
    assert rows["gamma"]["maintenance"] == {"now": True, "next": None}
    assert rows["alpha"]["maintenance"] == {"now": False,
                                            "next": LATER.strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert rows["beta"]["maintenance"] == {"now": False, "next": None}


def test_sets_are_listed_and_a_hidden_member_dropped(realm):
    body = _as(realm, "alice").get_json()
    assert body["sets"] == [{"id": "core-set", "name": "Core boxes", "note": None,
                             "places": ["alpha"]}]
    rows = _rows(body)
    assert rows["alpha"]["sets"] == ["core-set"] and rows["beta"]["sets"] == []
    admin = _as(realm, "ops").get_json()
    assert admin["sets"][0]["places"] == ["alpha", "secret-place"]
    assert _rows(admin)["secret-place"]["sets"] == ["core-set"]


def test_the_rest_of_a_row(realm):
    body = _as(realm, "alice").get_json()
    rows = _rows(body)
    alpha, beta, gamma = rows["alpha"], rows["beta"], rows["gamma"]
    assert alpha["addresses"] == ["192.0.2.5", "00:11:32:aa:bb:cc"]
    assert beta["addresses"] == []                       # "—" is no address
    assert alpha["services"] == 2 and beta["services"] == 0
    assert alpha["depends_on"] == ["beta"]               # the hidden one is scrubbed
    assert (alpha["zone"], alpha["zone_name"], alpha["kind"], alpha["role"]) == \
        ("core", "Core", "physical", "a box")
    # provenance: reviewed and settled / imported and unchecked / charted before stamps
    assert (alpha["charted_source"], alpha["unchecked"], alpha["changed_since_review"]) == \
        ("hand", False, False)
    assert (beta["charted_source"], beta["reviewed"], beta["unchecked"]) == ("unifi", False, True)
    assert (gamma["charted_source"], gamma["reviewed"], gamma["reviewed_at"], gamma["unchecked"]) == \
        (None, None, None, False)
    assert body["zones"] == [{"id": "core", "name": "Core"}]
    assert body["generated_at"].endswith("Z")
    expected = {"id", "name", "state", "cause", "zone", "zone_name", "kind", "role", "addresses",
                "services", "confirmed_by", "charted_source", "reviewed", "reviewed_at",
                "changed_since_review", "unchecked", "maintenance", "cert", "sets", "depends_on"}
    assert set(alpha) == expected
    assert set(_rows(_as(realm, "ops").get_json())["alpha"]) == expected | {"reviewed_by"}


def test_a_hidden_cause_is_not_named(realm):
    """A visible place can be dark because a hidden one is: the state is the
    viewer's, the explanation is not."""
    realm.app.extensions["atlas"].signals.feed = lambda: {
        "nodes": {"alpha": {"state": "down", "cause": "secret-place", "via": "secret-place"},
                  "beta": {"state": "healthy"}},
        "services": {}, "sources": {}, "generated": 0, "cached": True,
        "confirmed_by": {"alpha": "first", "beta": "first"}}
    rows = _rows(_as(realm, "alice").get_json())
    assert rows["alpha"]["state"] == "down" and rows["alpha"]["cause"] is None
    assert _rows(_as(realm, "ops").get_json())["alpha"]["cause"] == "secret-place"


def test_the_stamp_is_the_one_the_desk_writes_with(realm):
    admin = viewers.signed_in(realm, "ops")
    stamp = admin.get(URL).get_json()["stamp"]
    assert stamp == admin.get("/api/v2/admin/context").get_json()["stamp"]
    r = admin.post("/api/v2/admin/ops", headers=viewers.W, json={
        "expect": stamp, "ops": [{"op": "review", "section": "nodes", "id": "beta"}]})
    assert r.status_code == 200, r.get_json()
    assert _rows(admin.get(URL).get_json())["beta"]["reviewed"] is True
