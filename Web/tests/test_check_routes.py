"""One check (2026-11-16): `GET /api/v2/checks/<key>` and
`POST /api/v2/admin/checks/run`.

What is held here:

* READ RIGHT: every field of one check's last answer, for an http, a tcp, a
  failed and a TLS one; a certificate's names only for a viewer who sees
  everything.
* ONE 404: an unknown key, a thing with no check, and a thing this viewer may
  not see answer the same status and the same body.
* GATED LIKE THE FEED: signed out, a viewer, an admin, the look-only demo and
  an API token each get what the feed's rules give them.
* ASKED RIGHT: an admin asks one check now, only one the map charts, inside
  the worker's budget, and the answer is stored where a round stores it, so
  the GET and the feed agree; one failed ask is one failure of its retries.

Every name and address is invented (RFC 5737 and `example`). Nothing here
reaches a network: `watch.probe` and `watch.peer_certificate` are replaced.
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import watch as W  # noqa: E402
from appfixture import fresh_app, login_as  # noqa: E402

PW = "a-long-enough-password"
WRITE = {"X-Atlas-Write": "1"}
WEB = "http://192.0.2.10:8080/"
SECURE = "https://192.0.2.10/"
CERT = {"expires": "2027-01-31", "issuer": "Test CA", "names": ["app.example", "vault.example"]}

LAB = {"meta": {"title": "Test map"}, "zones": [], "routes": [],
       "signals": {"kuma": {"Gate monitor": "gate"}},
       "nodes": [
           {"id": "app", "name": "APP", "ip": "192.0.2.10", "kind": "physical", "x": 10, "y": 10,
            "check": "tcp", "check_port": 22,
            "links": [{"label": "Web", "url": WEB},
                      {"label": "Secure", "url": SECURE, "check_retries": 0},
                      {"label": "Wiki", "url": "http://192.0.2.10:81/", "kuma": "Wiki monitor"},
                      {"label": "Back office", "url": "http://192.0.2.10:9000/",
                       "require_group": "ops-team"},
                      {"label": "Spare", "url": "http://192.0.2.10:82/", "unmanaged": True}]},
           {"id": "vault", "name": "VAULT", "ip": "192.0.2.20", "kind": "physical", "x": 20, "y": 20,
            "require_group": "ops-team", "check": "tcp", "check_port": 443,
            "links": [{"label": "Ledger", "url": "https://192.0.2.20/"}]},
           {"id": "gate", "name": "GATE", "ip": "192.0.2.1", "kind": "network", "x": 30, "y": 30,
            "check": "tcp", "check_port": 22},
           {"id": "old", "name": "OLD", "ip": "192.0.2.30", "kind": "physical", "x": 40, "y": 40,
            "unmanaged": True, "check": "tcp", "check_port": 22},
           {"id": "plain", "name": "PLAIN", "ip": "192.0.2.40", "kind": "physical", "x": 50, "y": 50},
       ]}


# ── the fakes ───────────────────────────────────────────────────────────────

@pytest.fixture
def net(monkeypatch):
    """`watch.probe` and `watch.peer_certificate` replaced: `answers[ckey]` is
    what a probe of that check says; anything else is healthy in 4 ms."""
    asked, answers = [], {}

    def probe(t):
        asked.append(t.ckey)
        return answers.get(t.ckey, ("healthy", 4, {}))

    monkeypatch.setattr(W, "probe", probe)
    monkeypatch.setattr(W, "peer_certificate", lambda t: dict(CERT))
    return type("Net", (), {"asked": asked, "answers": answers})


def _env(tmp_path, **extra):
    data = tmp_path / "lab-data.json"
    data.write_text(json.dumps(LAB), encoding="utf-8")
    env = {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file", "ATLAS_READONLY": "0",
           "ATLAS_DATA": str(data), "ATLAS_ACCOUNTS_DB": str(tmp_path / "accounts.db"),
           "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
           "ATLAS_BEATS": str(tmp_path / "heartbeats.json"),
           "ATLAS_BEATS_DIR": str(tmp_path / "beats"),
           "ATLAS_EVENTS": str(tmp_path / "events.json"),
           "ATLAS_SECRET_KEY": "test-signing-key", "ATLAS_INSECURE_COOKIES": "1",
           "ATLAS_SIGNALS_SOURCES": "checks", "ATLAS_AUTH_BACKENDS": "local",
           "ATLAS_MFA_REQUIRED": "", "ATLAS_ALLOW_INSECURE": "1"}
    env.update(extra)
    return env


def _boot(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ATLAS_AGENT_API", raising=False)
    import integrations
    integrations._cache["mtime"] = None
    return fresh_app()


@pytest.fixture
def realm(net, tmp_path, monkeypatch):
    handle = _boot(monkeypatch, _env(tmp_path))
    import accounts
    accounts.create_local_user("map-admin", PW, is_admin=True)
    accounts.create_local_user("map-viewer", PW)
    yield handle
    monkeypatch.undo()
    fresh_app()


@pytest.fixture
def look_only(net, tmp_path, monkeypatch):
    handle = _boot(monkeypatch, _env(tmp_path, ATLAS_AUTH_MODE="standalone", ATLAS_READONLY="1"))
    yield handle
    monkeypatch.undo()
    fresh_app()


def _signed_in(realm, name):
    client = realm.app.test_client()
    r, _ = login_as(client, name, PW)
    assert r.status_code == 200 and r.get_json()["ok"]
    return client


def _store(tmp_path, checks, at=None):
    """A store written now (so no read asks a round of its own)."""
    at = time.time() if at is None else at
    (tmp_path / "checks.json").write_text(json.dumps({"v": 2, "at": at, "checks": checks}),
                                          encoding="utf-8")


def _stored(tmp_path):
    return json.loads((tmp_path / "checks.json").read_text(encoding="utf-8"))["checks"]


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


# ── read right ──────────────────────────────────────────────────────────────

def test_an_http_check_answers_every_field(realm, tmp_path):
    now = time.time() - 5
    _store(tmp_path, {"s:app/Web": {"state": "healthy", "said": "healthy", "fails": 0, "ms": 12,
                                    "asked": now, "heard": now, "since": now - 600}})
    r = _signed_in(realm, "map-viewer").get("/api/v2/checks/app/Web")
    assert r.status_code == 200, r.get_json()
    assert r.headers["Cache-Control"] == "no-store"
    assert r.get_json() == {
        "key": "app/Web", "thing": "service", "authority": "service", "place": "app",
        "type": "http", "asks": WEB, "url": WEB, "host": None, "port": None, "expect": None,
        "every": 60, "retries": 1, "timeout": 3.0,
        "state": "healthy", "stale": False, "said": "healthy", "fails": 0,
        "since": _iso(now - 600), "asked_at": _iso(now), "heard_at": _iso(now), "ms": 12,
        "error": None, "status": None, "tls": None, "on": True}


def test_a_tcp_check_of_a_place_answers_every_field(realm, tmp_path):
    now = time.time() - 5
    _store(tmp_path, {"p:app": {"state": "healthy", "said": "healthy", "fails": 0, "ms": 3,
                                "asked": now, "heard": now, "since": now}})
    body = _signed_in(realm, "map-viewer").get("/api/v2/checks/app").get_json()
    assert (body["key"], body["thing"], body["authority"], body["place"]) == ("app", "place", "place", "app")
    assert (body["type"], body["asks"], body["host"], body["port"], body["url"]) == \
        ("tcp", "192.0.2.10 port 22", "192.0.2.10", 22, None)
    assert (body["state"], body["ms"], body["error"], body["asked_at"]) == ("healthy", 3, None, _iso(now))


def test_a_failed_check_says_why_in_fixed_words(realm, tmp_path):
    now = time.time() - 5
    _store(tmp_path, {"s:app/Web": {"state": "down", "said": "down", "fails": 2, "ms": 40,
                                    "why": "status", "status": 503,
                                    "asked": now, "heard": now, "since": now}})
    body = _signed_in(realm, "map-viewer").get("/api/v2/checks/app/Web").get_json()
    assert (body["state"], body["said"], body["fails"]) == ("down", "down", 2)
    assert body["error"] == W.WHY["status"] and body["status"] == 503
    # an ask that got no answer, and a reason the store does not know
    _store(tmp_path, {"s:app/Web": {"state": "down", "said": "down", "fails": 2,
                                    "why": "Traceback: boom", "asked": now, "heard": now}})
    assert _signed_in(realm, "map-viewer").get("/api/v2/checks/app/Web").get_json()["error"] == W.NOT_HEALTHY
    _store(tmp_path, {"s:app/Web": {"state": "healthy", "said": "healthy", "asked": now, "heard": now - 60}})
    assert _signed_in(realm, "map-viewer").get("/api/v2/checks/app/Web").get_json()["error"] == W.NO_ANSWER


def test_a_state_too_old_to_serve_is_stale_as_in_the_feed(realm, tmp_path):
    then = time.time() - 3600
    _store(tmp_path, {"s:app/Web": {"state": "healthy", "said": "healthy", "asked": then, "heard": then}})
    body = _signed_in(realm, "map-admin").get("/api/v2/checks/app/Web").get_json()
    assert (body["state"], body["stale"], body["said"]) == (None, True, "healthy")


def test_a_certificate_names_only_for_a_viewer_who_sees_everything(realm, tmp_path):
    now = time.time() - 5
    _store(tmp_path, {"s:app/Secure": {"state": "healthy", "said": "healthy", "asked": now, "heard": now,
                                       "ms": 9, "tls": CERT, "tls_url": SECURE, "tls_at": now,
                                       "tls_from": SECURE}})
    admin = _signed_in(realm, "map-admin").get("/api/v2/checks/app/Secure").get_json()
    assert admin["tls"] == CERT
    viewer = _signed_in(realm, "map-viewer").get("/api/v2/checks/app/Secure").get_json()
    assert viewer["tls"] == {"expires": "2027-01-31", "issuer": "Test CA"}
    assert "vault.example" not in json.dumps(viewer)
    # read from another address: not this check's certificate
    _store(tmp_path, {"s:app/Secure": {"state": "healthy", "asked": now, "heard": now,
                                       "tls": CERT, "tls_url": "https://192.0.2.99/"}})
    assert _signed_in(realm, "map-admin").get("/api/v2/checks/app/Secure").get_json()["tls"] is None


# ── one 404 ─────────────────────────────────────────────────────────────────

def test_unknown_no_check_and_hidden_all_answer_the_same_404(realm, tmp_path):
    now = time.time() - 5
    _store(tmp_path, {k: {"state": "down", "said": "down", "asked": now, "heard": now}
                      for k in ("p:vault", "s:vault/Ledger", "s:app/Back office")})
    viewer = _signed_in(realm, "map-viewer")
    seen = []
    for key in ("nothing-here", "plain", "gate", "Wiki monitor", "old", "app/Spare",
                "vault", "vault/Ledger", "app/Back office", "x" * 600):
        r = viewer.get(f"/api/v2/checks/{key}")
        seen.append((key, r.status_code, r.get_data(), r.headers.get("Cache-Control")))
    first = seen[0][1:]
    assert first[0] == 404 and json.loads(first[1]) == {"error": "no such check"}
    for key, *rest in seen:
        assert tuple(rest) == first, key
    # an admin sees the hidden ones, so the 404 was the viewer's alone
    admin = _signed_in(realm, "map-admin")
    for key in ("vault", "vault/Ledger", "app/Back office"):
        r = admin.get(f"/api/v2/checks/{key}")
        assert r.status_code == 200 and r.get_json()["state"] == "down", key


def test_a_shadow_answer_is_an_admins(realm, tmp_path):
    doc = json.loads((tmp_path / "lab-data.json").read_text(encoding="utf-8"))
    doc["meta"]["shadow_kuma"] = True
    (tmp_path / "lab-data.json").write_text(json.dumps(doc), encoding="utf-8")
    now = time.time() - 5
    _store(tmp_path, {"kp:gate": {"state": "healthy", "said": "healthy", "asked": now, "heard": now},
                      "k:Wiki monitor": {"state": "down", "said": "down", "asked": now, "heard": now}})
    admin = _signed_in(realm, "map-admin")
    assert admin.get("/api/v2/checks/gate").get_json()["authority"] == "shadow-place"
    assert admin.get("/api/v2/checks/Wiki monitor").get_json()["authority"] == "shadow"
    viewer = _signed_in(realm, "map-viewer")
    for key in ("gate", "Wiki monitor"):
        r = viewer.get(f"/api/v2/checks/{key}")
        assert (r.status_code, r.get_json()) == (404, {"error": "no such check"}), key


# ── gated like the feed ─────────────────────────────────────────────────────

def test_signed_out_is_refused_as_the_feed_is(realm):
    c = realm.app.test_client()
    assert c.get("/api/v2/checks/app/Web").status_code == c.get("/api/v2/signals").status_code == 401
    assert c.post("/api/v2/admin/checks/run", json={"key": "app/Web"}, headers=WRITE).status_code == 401


def test_the_look_only_demo_reads_and_cannot_ask(look_only, tmp_path, net):
    now = time.time() - 5
    _store(tmp_path, {"s:app/Secure": {"state": "healthy", "asked": now, "heard": now,
                                       "tls": CERT, "tls_url": SECURE}})
    c = look_only.app.test_client()
    r = c.get("/api/v2/checks/app/Secure")
    assert r.status_code == 200 and r.get_json()["tls"] == CERT, "it shows the whole map, as its feed does"
    assert c.get("/api/v2/checks/vault").status_code == 200
    # no admin there: no shadow answer and no asking
    r = c.post("/api/v2/admin/checks/run", json={"key": "app/Web"}, headers=WRITE)
    assert r.status_code == 403 and net.asked == []


def test_an_api_token_is_not_let_in(realm):
    admin = _signed_in(realm, "map-admin")
    assert admin.post("/api/v2/admin/tokens/access", json={"on": True}, headers=WRITE).status_code == 200
    r = admin.post("/api/v2/admin/tokens", json={"name": "reader", "days": 30}, headers=WRITE)
    assert r.status_code == 200, r.get_json()
    bearer = {"Authorization": f"Bearer {r.get_json()['secret']}"}
    c = realm.app.test_client()
    assert c.get("/api/v2/signals", headers=bearer).status_code == 200
    # not one of a token's doors: the token is not looked at, and the request
    # meets the sign-in gate as one with no session
    r = c.get("/api/v2/checks/app/Web", headers=bearer)
    assert r.status_code == 401 and "state" not in (r.get_json() or {})


# ── asked right ─────────────────────────────────────────────────────────────

def _run(client, key="app/Web", **kw):
    return client.post("/api/v2/admin/checks/run", json={"key": key}, headers=WRITE, **kw)


def test_an_admin_asks_one_check_and_the_get_and_the_feed_agree(realm, tmp_path, net):
    _store(tmp_path, {})
    net.answers["s:app/Web"] = ("degraded", 21, {"why": "server-error", "status": 502})
    admin = _signed_in(realm, "map-admin")
    r = _run(admin)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert net.asked == ["s:app/Web"], "one check, the one asked for"
    assert body["asked"] is True and "stored" not in body
    # retries 1, never heard before: one failed ask is one failure, not a state
    assert (body["state"], body["said"], body["fails"], body["ms"]) == (None, "degraded", 1, 21)
    assert (body["error"], body["status"]) == (W.WHY["server-error"], 502)
    entry = _stored(tmp_path)["s:app/Web"]
    assert (entry["said"], entry["fails"], entry["why"], entry["status"]) == ("degraded", 1, "server-error", 502)

    got = admin.get("/api/v2/checks/app/Web").get_json()
    assert {k: v for k, v in got.items() if k != "on"} == {k: v for k, v in body.items()
                                                           if k not in ("asked", "on")}

    # a healthy answer is believed at once, and clears the reason
    entry["asked"] -= 30
    _store(tmp_path, {"s:app/Web": entry})
    net.answers["s:app/Web"] = ("healthy", 7, {})
    body = _run(admin).get_json()
    assert (body["state"], body["fails"], body["error"], body["status"]) == ("healthy", 0, None, None)
    realm._signals._cache = None                          # past the hub's 30 s cache
    feed = admin.get("/api/v2/signals").get_json()
    assert feed["services"]["app/Web"] == {"state": "healthy", "ms": 7}
    assert admin.get("/api/v2/checks/app/Web").get_json()["state"] == "healthy"


def test_one_manual_failure_does_not_flip_a_state_that_needs_two(realm, tmp_path, net):
    then = time.time() - 30
    _store(tmp_path, {"s:app/Web": {"state": "healthy", "said": "healthy", "fails": 0,
                                    "asked": then, "heard": then, "since": then - 600}})
    net.answers["s:app/Web"] = ("down", 3000, {"why": "timeout"})
    admin = _signed_in(realm, "map-admin")
    body = _run(admin).get_json()
    assert (body["state"], body["said"], body["fails"], body["error"]) == \
        ("healthy", "down", 1, W.WHY["timeout"]), "still inside its retries"
    entry = _stored(tmp_path)["s:app/Web"]
    entry["asked"] -= 30
    _store(tmp_path, {"s:app/Web": entry})
    body = _run(admin).get_json()
    assert (body["state"], body["fails"]) == ("down", 2), "the second failure is believed"


def test_a_tls_answer_asked_now_reads_the_certificate(realm, tmp_path, net):
    _store(tmp_path, {})
    body = _run(_signed_in(realm, "map-admin"), "app/Secure").get_json()
    assert body["state"] == "healthy" and body["tls"] == CERT


def test_the_budget_spent_answers_429_with_a_retry_after(realm, tmp_path, net, monkeypatch):
    now = time.time()
    monkeypatch.setattr(W, "per_minute", lambda: 3)
    _store(tmp_path, {f"s:x/{i}": {"asked": now - 50 + i, "heard": now - 50 + i} for i in range(3)})
    r = _run(_signed_in(realm, "map-admin"))
    assert r.status_code == 429 and r.get_json()["why"] == "spent"
    assert 1 <= int(r.headers["Retry-After"]) <= 11 and r.get_json()["retry_after"] == int(r.headers["Retry-After"])
    assert net.asked == []


def test_a_check_asked_a_moment_ago_waits(realm, tmp_path, net):
    now = time.time()
    _store(tmp_path, {"s:app/Web": {"state": "healthy", "said": "healthy", "asked": now - 5, "heard": now - 5}})
    r = _run(_signed_in(realm, "map-admin"))
    assert r.status_code == 429 and r.get_json()["why"] == "soon"
    assert 1 <= int(r.headers["Retry-After"]) <= W.EVERY_MIN
    assert net.asked == []


def test_another_worker_holding_the_store_gets_the_stored_answer(realm, tmp_path, net):
    import filelock
    then = time.time() - 30
    _store(tmp_path, {"s:app/Web": {"state": "down", "said": "down", "asked": then, "heard": then}})
    admin = _signed_in(realm, "map-admin")
    with filelock.exclusive(filelock.lock_for(str(tmp_path / "checks.json"))):
        r = _run(admin)
    assert r.status_code == 200
    body = r.get_json()
    assert (body["asked"], body["stored"], body["state"]) == (False, True, "down")
    assert net.asked == []


def test_what_kuma_watches_and_what_is_unmanaged_is_not_asked(realm, tmp_path, net):
    _store(tmp_path, {})
    admin = _signed_in(realm, "map-admin")
    for key, monitor in (("gate", "Gate monitor"), ("Wiki monitor", "Wiki monitor")):
        r = _run(admin, key)
        assert r.status_code == 409, key
        assert (r.get_json()["why"], r.get_json()["monitor"]) == ("kuma", monitor), key
    for key in ("old", "app/Spare"):
        r = _run(admin, key)
        assert (r.status_code, r.get_json()["why"]) == (409, "unmanaged"), key
    assert net.asked == []


def test_with_the_checks_source_off_nothing_is_asked(net, tmp_path, monkeypatch):
    handle = _boot(monkeypatch, _env(tmp_path, ATLAS_SIGNALS_SOURCES=""))
    try:
        import accounts
        accounts.create_local_user("map-admin", PW, is_admin=True)
        admin = _signed_in(handle, "map-admin")
        r = _run(admin)
        assert (r.status_code, r.get_json()["why"]) == (409, "off")
        assert admin.get("/api/v2/checks/app/Web").get_json()["on"] is False
        assert net.asked == []
    finally:
        monkeypatch.undo()
        fresh_app()


def test_a_viewer_may_not_ask(realm, net):
    r = _run(_signed_in(realm, "map-viewer"))
    assert (r.status_code, r.get_json()["error"]) == (403, "admins only")
    assert net.asked == []


def test_a_missing_write_header_is_refused_as_every_admin_post_is(realm, net):
    admin = _signed_in(realm, "map-admin")
    mine = admin.post("/api/v2/admin/checks/run", json={"key": "app/Web"})
    theirs = admin.post("/api/v2/admin/maintenance", json={"windows": []})
    assert mine.status_code == theirs.status_code == 403
    assert mine.get_json() == theirs.get_json()
    cross = admin.post("/api/v2/admin/checks/run", json={"key": "app/Web"},
                       headers={**WRITE, "Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    assert net.asked == []


def test_a_bad_body_is_400(realm, net):
    admin = _signed_in(realm, "map-admin")
    for body in (None, [], "app/Web", {}, {"key": 7}, {"key": ""}, {"key": "x" * 513},
                 {"key": "app/Web", "url": "http://192.0.2.99/"}, {"key": "app/Web", "host": "192.0.2.99"}):
        r = admin.post("/api/v2/admin/checks/run", headers=WRITE,
                       data=json.dumps(body), content_type="application/json")
        assert r.status_code == 400, body
    assert net.asked == []


def test_a_key_the_map_does_not_chart_is_never_asked(realm, tmp_path, net):
    _store(tmp_path, {})
    admin = _signed_in(realm, "map-admin")
    for key in ("192.0.2.99", "http://192.0.2.99/", "plain", "nothing/Here", "app/Nothing"):
        r = _run(admin, key)
        assert (r.status_code, r.get_json()) == (404, {"error": "no such check"}), key
    r = admin.post("/api/v2/admin/checks/run", headers=WRITE,
                   json={"key": "nothing", "url": "http://192.0.2.99/", "type": "tcp"})
    assert r.status_code == 400
    assert net.asked == []
    assert _stored(tmp_path) == {}


# ── the plain functions ─────────────────────────────────────────────────────

def test_a_reason_is_kept_only_beside_an_answer_that_was_not_healthy():
    t = W.Target(ckey="s:app/Web", key="app/Web", kind="service", place="app", type="http", url=WEB)
    e = W.judge(None, t, ("down", 5, {"why": "refused", "status": 7}), 1000)
    assert (e["why"], e["status"]) == ("refused", 7)
    e = W.judge(e, t, ("down", 5, {"why": "the raw words of an exception"}), 1030)
    assert "why" not in e and "status" not in e, "only a code from WHY is kept"
    e = W.judge(e, t, ("healthy", 5, {}), 1060)
    assert "why" not in e and "status" not in e
    assert W.find(LAB, "app").kind == "place" and W.find(LAB, "app/Web").kind == "service"
    assert W.find(LAB, "192.0.2.10") is None and W.find(LAB, "") is None
    assert W.not_asked(LAB, "gate") == {"why": "kuma", "monitor": "Gate monitor"}
    assert W.not_asked(LAB, "old") == {"why": "unmanaged"} == W.not_asked(LAB, "app/Spare")
    assert W.not_asked(LAB, "plain") is None and W.not_asked(LAB, "nothing") is None
