"""OVERVIEW — `GET /api/v2/overview` (2026-11-13).

The realm's own facts, built on the server from the redacted map and the
redacted live feed. What matters: a hidden place is in no tile, for a viewer
with no groups and for a token (not in what is down, not downstream of it, not
in a repair window or its reason, not on a certificate, not in the review list,
not in the unacknowledged events); who changed what, which source is silent and
the drift are for an admin; a cloud token is refused; and the MCP tool
`atlas_overview`, which now reads through the same module, answers in the shape
it always had.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

import viewers

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts"}

URL = "/api/v2/overview"
NOW = datetime.now(timezone.utc)
MODERN = "2026-07-28"


def _at(days=0, hours=0):
    return (NOW + timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(days):
    return (NOW + timedelta(days=days)).strftime("%Y-%m-%d")


def _mark(reviewed_days_ago=None, changed_days_ago=30, imported=False):
    """A provenance stamp: reviewed that many days ago, or an unchecked import."""
    changed = _at(-changed_days_ago)
    if imported:
        return {"charted_at": changed, "source": "unifi", "charted_by": "ops",
                "changed_at": changed, "reviewed": False}
    reviewed = _at(-reviewed_days_ago)
    return {"charted_at": _at(-400), "source": "hand", "charted_by": "ops",
            "changed_at": min(changed, reviewed), "changed_by": "ops",
            "reviewed": True, "reviewed_at": reviewed, "reviewed_by": "ops"}


#: The words of the hidden place. None of them may reach a viewer or a token.
HIDDEN = ("secret-place", "Secret", "192.0.2.99", "vault.example", "Bait")


def _data():
    data = viewers.dataset(
        certs=[
            {"name": "alpha.example", "kind": "tls", "issuer": "step-ca", "expires": _day(10),
             "place": "alpha"},
            {"name": "gone.example", "kind": "tls", "issuer": "step-ca", "expires": _day(-3)},
            {"name": "far.example", "kind": "tls", "issuer": "step-ca", "expires": _day(40),
             "place": "alpha"},
            {"name": "vault.example", "kind": "tls", "issuer": "step-ca", "expires": _day(5),
             "place": "secret-place"},
        ])
    alpha, beta, secret = data["nodes"]
    # alpha is the root; beta needs alpha and gamma, gamma needs beta (a loop
    # downstream of the root); the hidden place needs alpha, and delta needs the
    # hidden place. epsilon is degraded and nothing names it.
    alpha.update(provenance=_mark(1, changed_days_ago=2))   # changed this week, reviewed since
    beta.update(depends_on=["alpha", "gamma"], provenance=_mark(200))
    secret.update(depends_on=["alpha"], provenance=_mark(imported=True, changed_days_ago=1),
                  links=[{"label": "Vault UI", "url": "http://192.0.2.99/", "kuma": "Secret Mon"}])
    data["nodes"] += [
        viewers.place("gamma", "Gamma", depends_on=["beta"], provenance=_mark(imported=True)),
        viewers.place("delta", "Delta", depends_on=["secret-place"]),
        viewers.place("epsilon", "Epsilon", provenance=_mark(100)),
    ]
    return data


WINDOWS = [
    {"id": "now", "reason": "patching", "nodes": ["gamma"],
     "starts": "2020-01-01T00:00:00Z", "ends": "2099-01-01T00:00:00Z", "repeat": "none"},
    {"id": "soon", "reason": "disks", "nodes": ["alpha"],
     "starts": _at(3), "ends": _at(3, 2), "repeat": "none"},
    {"id": "far", "reason": "far off", "nodes": ["alpha"],
     "starts": _at(20), "ends": _at(20, 2), "repeat": "none"},
    {"id": "hidden-only", "reason": "vault work", "nodes": ["secret-place"],
     "starts": _at(2), "ends": _at(2, 2), "repeat": "none"},
    {"id": "mixed", "reason": "network", "nodes": ["beta", "secret-place"],
     "starts": _at(1), "ends": _at(1, 2), "repeat": "none"},
    {"id": "named", "reason": "after Secret is moved", "nodes": ["beta"],
     "starts": _at(1, 1), "ends": _at(1, 3), "repeat": "none"},
]


def _event(eid, kind, target, name, to, gravity="grave", ack=None, hours_ago=0):
    return {"id": eid, "at": _at(hours=-hours_ago), "kind": kind, "target": target, "name": name,
            "from": "healthy", "to": to, "gravity": gravity, "ack": ack}


EVENTS = [
    _event(1, "node", "beta", "Beta", "down", ack={"at": _at(), "by": "ops", "note": "seen"},
           hours_ago=9),
    _event(2, "node", "secret-place", "Secret", "down", hours_ago=8),
    _event(3, "service", "Secret Mon", "Secret Mon", "down", hours_ago=7),
    _event(4, "tripwire", "bait", "Bait tripped", "down", hours_ago=6),
    _event(5, "node", "epsilon", "Epsilon", "degraded", gravity="warn", hours_ago=5),
    _event(6, "node", "alpha", "Alpha", "down", hours_ago=4),
]


@pytest.fixture
def realm(tmp_path, monkeypatch):
    import signals as S

    class First(S._Adapter):
        name = "first"

        def _fetch(self):
            return {"nodes": {"alpha": {"state": "down"}, "beta": {"state": "down"},
                              "delta": {"state": "down"}, "epsilon": {"state": "degraded"},
                              "secret-place": {"state": "down"}},
                    "services": {"Uncharted Mon": {"state": "healthy"},
                                 "Secret Mon": {"state": "down"}}}

    class Quiet(S._Adapter):
        name = "quiet"

        def _fetch(self):
            return {}

    class Decoy(S._Adapter):
        name = "deception"

        def _fetch(self):
            return {"metrics": {"unattributed_trips": 1}}

    (tmp_path / "events.json").write_text(
        json.dumps({"seq": len(EVENTS), "state": {}, "events": EVENTS}), encoding="utf-8")
    handle = viewers.build(tmp_path, monkeypatch, _data(), windows=WINDOWS)
    handle.app.extensions["atlas"].signals = S.SignalsHub([First(), Quiet(), Decoy()], ttl=0)
    yield handle
    monkeypatch.undo()


def _as(realm, who):
    if who == "token":
        return realm.app.test_client().get(URL, headers=viewers.issue(realm))
    return viewers.signed_in(realm, who).get(URL)


def _body(realm, who):
    r = _as(realm, who)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


KEYS = {"generated_at", "admin", "states", "down", "unacked", "maintenance", "certs", "review",
        "changes", "sources"}


# ── who reads it ─────────────────────────────────────────────────────────────

def test_a_cloud_token_is_refused(realm):
    r = realm.app.test_client().get(URL, headers=viewers.issue(realm, "cloud"))
    assert r.status_code == 403 and "MCP endpoint only" in r.get_json()["reason"]


def test_a_stranger_is_not_answered(realm):
    assert realm.app.test_client().get(URL).status_code in (302, 401)


def test_the_answer_is_never_stored(realm):
    r = _as(realm, "alice")
    assert r.headers["Cache-Control"] == "no-store"
    assert "Cookie" in r.headers["Vary"]


def test_the_keys_each_reader_gets(realm):
    admin = _body(realm, "ops")
    assert set(admin) == KEYS | {"drift"} and admin["admin"] is True
    for who in ("alice", "token"):
        body = _body(realm, who)
        assert set(body) == KEYS, who            # drift is absent, not empty
        assert body["admin"] is False, who


@pytest.mark.parametrize("who", ["alice", "token"])
def test_a_hidden_place_is_in_no_tile(realm, who):
    text = json.dumps(_body(realm, who))
    for word in HIDDEN:
        assert word not in text, word


# ── the tiles ────────────────────────────────────────────────────────────────

def test_places_by_state(realm):
    # gamma is under repair; beta is down behind alpha; nobody reported on the rest
    assert _body(realm, "alice")["states"] == {
        "healthy": 0, "degraded": 1, "down": 3, "slumbering": 0, "maintenance": 1, "unknown": 0,
        "total": 5}
    assert _body(realm, "ops")["states"]["down"] == 4
    assert _body(realm, "ops")["states"]["total"] == 6


def test_what_is_down_and_what_depends_on_it(realm):
    down = _body(realm, "alice")["down"]
    # beta is alpha's fallout; delta's cause is the hidden place, so it stands alone
    assert [(d["id"], d["state"]) for d in down] == [("alpha", "down"), ("delta", "down"),
                                                    ("epsilon", "degraded")]
    alpha, delta, epsilon = down
    # transitive, and the beta <-> gamma loop ends
    assert alpha["downstream"] == [{"id": "beta", "name": "Beta"}, {"id": "gamma", "name": "Gamma"}]
    assert alpha["declared"] is True and alpha["cause"] is None
    assert (delta["downstream"], delta["declared"]) == ([], False)
    assert (epsilon["downstream"], epsilon["declared"]) == ([], False)


def test_an_admin_sees_the_hidden_place_downstream(realm):
    down = _body(realm, "ops")["down"]
    # delta is the hidden place's fallout, and the hidden place is alpha's
    assert [d["id"] for d in down] == ["alpha", "epsilon"]
    assert [d["id"] for d in down[0]["downstream"]] == ["beta", "secret-place", "gamma", "delta"]


def test_unacknowledged_events(realm):
    seen = _body(realm, "alice")["unacked"]
    assert seen["count"] == 2
    assert [e["id"] for e in seen["items"]] == [6, 5]
    assert set(seen["items"][0]) == {"id", "at", "kind", "target", "name", "from", "to"}
    # the admin reads the ANNALS whole: the hidden place, its monitor and the trip
    admin = _body(realm, "ops")["unacked"]
    assert admin["count"] == 5 and [e["id"] for e in admin["items"]] == [6, 5, 4, 3, 2]


def test_maintenance_in_the_next_week(realm):
    seen = _body(realm, "alice")["maintenance"]
    # far is three weeks off; hidden-only names only the hidden place; named's reason names it
    assert [w["window"] for w in seen] == ["now", "mixed", "soon"]
    now, mixed, soon = seen
    assert now["now"] is True and now["places"] == [{"id": "gamma", "name": "Gamma"}]
    assert mixed["places"] == [{"id": "beta", "name": "Beta"}] and mixed["now"] is False
    assert (soon["reason"], soon["starts"], soon["ends"]) == ("disks", _at(3), _at(3, 2))
    admin = _body(realm, "ops")["maintenance"]
    assert [w["window"] for w in admin] == ["now", "mixed", "named", "hidden-only", "soon"]
    assert len(admin[1]["places"]) == 2


def test_certificates_lapsing_within_30_days(realm):
    import certs
    seen = _body(realm, "alice")["certs"]
    assert [c["name"] for c in seen] == ["gone.example", "alpha.example"]
    gone, alpha = seen
    assert gone["days"] < 0 and gone["place"] is None
    assert alpha["place"] == {"id": "alpha", "name": "Alpha"}
    assert alpha["days"] == certs.days_left({"expires": _day(10)}, datetime.now(timezone.utc))
    admin = _body(realm, "ops")["certs"]
    assert [c["name"] for c in admin] == ["gone.example", "vault.example", "alpha.example"]


def test_review_never_says_who(realm):
    review = _body(realm, "alice")["review"]
    assert review["unchecked"] == 1                        # gamma, an unchecked import
    # stale: never reviewed (delta, charted before stamps; gamma), then the oldest review
    assert review["stale"] == 4
    assert [r["id"] for r in review["items"]] == ["delta", "gamma", "beta", "epsilon"]
    assert review["items"][0]["reviewed_at"] is None
    assert review["items"][2]["reviewed_at"] == _at(-200)
    assert "ops" not in json.dumps(review)
    admin = _body(realm, "ops")["review"]
    assert (admin["unchecked"], admin["stale"]) == (2, 5)


def test_changes_name_nobody_but_to_an_admin(realm):
    for who in ("alice", "token"):
        changes = _body(realm, who)["changes"]
        # alpha changed two days ago; the hidden place yesterday, and is not counted
        assert changes == {"count_7d": 1}, who
    ctx = realm.app.extensions["atlas"]
    import os
    os.makedirs(ctx.store.revisions_dir, exist_ok=True)
    with open(ctx.store._journal_path(), "a", encoding="utf-8") as fh:
        for i in range(1, 11):
            fh.write(json.dumps({"id": i, "at": _at(hours=i - 20), "actor": "ops",
                                 "summary": [f"changed place {i}", "moved it"], "note": "",
                                 "ops": []}) + "\n")
    items = _body(realm, "ops")["changes"]["items"]
    assert len(items) == 8
    assert items[0] == {"at": _at(hours=-10), "by": "ops", "summary": "changed place 10; moved it"}
    assert _body(realm, "alice")["changes"] == {"count_7d": 1}


def test_sources_say_which_only_to_an_admin(realm):
    for who in ("alice", "token"):
        sources = _body(realm, who)["sources"]
        # the decoy feed is not counted, nor named
        assert sources == {"all_ok": False, "silent": 1, "items": []}, who
    admin = _body(realm, "ops")["sources"]
    assert (admin["all_ok"], admin["silent"]) == (False, 1)
    by_name = {s["name"]: s for s in admin["items"]}
    assert set(by_name) == {"first", "quiet", "deception"}
    assert by_name["first"]["ok"] is True and by_name["first"]["last_ok"].endswith("Z")
    assert by_name["quiet"] == {"name": "quiet", "ok": False, "last_ok": None}


def test_drift_is_for_an_admin(realm):
    assert _body(realm, "ops")["drift"] == {"count": 1, "items": ["Uncharted Mon"]}
    for who in ("alice", "token"):
        assert "drift" not in _body(realm, who)


# ── a source's last good answer ──────────────────────────────────────────────

def test_a_source_s_last_good_answer_is_kept(realm):
    hub = realm.app.extensions["atlas"].signals
    feed = hub.feed()
    assert set(feed["sources_at"]) == {"first", "quiet", "deception"}
    assert feed["sources_at"]["quiet"] is None
    first = feed["sources_at"]["first"]
    assert first and first == hub.last_ok()["first"]
    assert "quiet" not in hub.last_ok()
    # the shape of `sources` itself is unchanged
    assert feed["sources"] == {"first": "ok", "quiet": "silent", "deception": "ok"}


def test_a_last_good_answer_outlives_a_silent_one():
    import signals as S

    class Flaky(S._Adapter):
        name = "flaky"
        answers = [{"nodes": {"a": {"state": "healthy"}}}, {}]

        def _fetch(self):
            return self.answers.pop(0)

    hub = S.SignalsHub([Flaky()], ttl=0)
    first = hub.feed()
    assert first["sources"] == {"flaky": "ok"} and first["sources_at"]["flaky"]
    second = hub.feed()
    assert second["sources"] == {"flaky": "silent"}
    assert second["sources_at"]["flaky"] == first["sources_at"]["flaky"]


def test_the_signals_feed_does_not_name_the_decoy_s_time(realm):
    seen = viewers.signed_in(realm, "alice").get("/api/v2/signals").get_json()
    assert set(seen["sources_at"]) == {"first", "quiet"}
    admin = viewers.signed_in(realm, "ops").get("/api/v2/signals").get_json()
    assert set(admin["sources_at"]) == {"first", "quiet", "deception"}


# ── the MCP tool reads through the same module ───────────────────────────────

def _tool(realm, auth, name):
    head = {**auth, "MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call", "Mcp-Name": name}
    params = {"name": name, "arguments": {},
              "_meta": {"io.modelcontextprotocol/protocolVersion": MODERN,
                        "io.modelcontextprotocol/clientCapabilities": {}}}
    r = realm.app.test_client().post("/api/v2/mcp", headers=head, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    assert r.status_code == 200, r.get_data(as_text=True)
    result = r.get_json()["result"]
    assert result["isError"] is False, result
    return result["structuredContent"]


MCP_KEYS = {"title", "surveyed", "zones", "places", "services", "roads", "health", "sources",
            "provenance"}


def test_atlas_overview_keeps_its_shape(realm):
    told = _tool(realm, viewers.issue(realm), "atlas_overview")
    assert set(told) == MCP_KEYS
    assert told["title"] == "Test Realm" and told["zones"] == ["Core"]
    assert (told["places"], told["services"], told["roads"]) == (5, 0, 0)
    assert set(told["health"]) == {"places", "services"}
    assert told["health"]["places"] == {"down": 3, "degraded": 1, "maintenance": 1}
    # still {name: "ok" | "silent"}, and the decoy is not named to a token
    assert told["sources"] == {"first": "ok", "quiet": "silent"}
    assert set(told["provenance"]) == {"reviewed", "unreviewed", "unknown", "oldest_unreviewed",
                                       "newest_change"}
    for word in HIDDEN:
        assert word not in json.dumps(told), word


def test_atlas_overview_for_a_cloud_token_still_says_what_is_withheld(realm):
    told = _tool(realm, viewers.issue(realm, "cloud"), "atlas_overview")
    assert set(told) == MCP_KEYS | {"withheld"}



def test_a_certificate_whose_place_is_not_one_id_is_listed_with_no_place():
    # a list there was saved before validation refused it, and `place in
    # by_id` raised on it: a 500 for every reader (2026-11-13)
    import overview
    data = viewers.dataset(certs=[
        {"name": "listed.example", "expires": _day(5), "place": ["alpha"]},
        {"name": "boxed.example", "expires": _day(6), "place": {"id": "alpha"}},
        {"name": "alpha.example", "expires": _day(7), "place": "alpha"}])
    out = overview.lapsing_certs(data, datetime.now(timezone.utc))
    assert [(c["name"], c["place"]) for c in out] == [
        ("listed.example", None), ("boxed.example", None),
        ("alpha.example", {"id": "alpha", "name": "Alpha"})]
