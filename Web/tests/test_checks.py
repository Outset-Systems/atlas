"""Built-in checks: the `checks` live source, for a map with no monitoring.

What is held here:

* ASKED RIGHT: only a charted http(s) service URL, without its credentials,
  with no redirect followed, no certificate verified and no body read.
* JUDGED RIGHT: below 500 is healthy, 500 and above is degraded, no connection
  or no answer in time is down, and no answer inside the budget is unknown.
* KUMA STANDS: a link that names a monitor is not asked, and a place a monitor
  is mapped to gets no marker state from here.
* ASKED ONCE: two workers share one stored round and one lock.
* SEEN RIGHT: a viewer gets the results for the places they may see and none
  for a hidden one.

Every name and address is invented (RFC 5737 and private ranges). Nothing here
reaches a network: `requests.get` is replaced in every test that could ask.
"""

import ast
import json
import logging
import os
import sys
import threading
import time
import warnings
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import signals as S  # noqa: E402
from appfixture import fresh_app, login_as  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = "a-long-enough-password"
W = {"X-Atlas-Write": "1", "Origin": "http://localhost"}

WIKI = "http://192.0.2.10:8080/"
FILES = "https://192.0.2.11/files"
DATA = {"nodes": [
    {"id": "app-box", "links": [{"label": "Wiki", "url": WIKI}]},
    {"id": "file-box", "links": [{"label": "Files", "url": FILES}]},
]}


class Answer:
    """What `requests.get` hands back, as far as a check may look at it."""

    def __init__(self, status):
        self.status_code = status
        self.closed = False

    def close(self):
        self.closed = True

    @property
    def content(self):
        raise AssertionError("a check never reads the body")

    text = content

    def iter_content(self, *args, **kwargs):
        raise AssertionError("a check never reads the body")


@pytest.fixture
def web(monkeypatch):
    """A fake network behind `requests.get`. `answers[url]` is a status, an
    exception to raise, or a callable giving either; an unlisted URL is a 200."""
    import requests
    calls, answers, given = [], {}, []

    def get(url, **kw):
        calls.append((url, kw))
        what = answers.get(url, 200)
        if callable(what) and not isinstance(what, type):
            what = what()
        if isinstance(what, BaseException) or isinstance(what, type):
            raise what
        answer = Answer(what)
        given.append(answer)
        return answer

    monkeypatch.setattr(requests, "get", get)
    return SimpleNamespace(calls=calls, answers=answers, given=given,
                           urls=lambda: sorted(url for url, _ in calls))


def _adapter(tmp_path, data=DATA, **kw):
    adapter = S.ChecksAdapter(path=str(tmp_path / "checks.json"), **kw)
    adapter.use_map(data)
    return adapter


def _one_place_each(urls):
    return {"nodes": [{"id": f"box-{i}", "links": [{"label": "Page", "url": url}]}
                      for i, url in enumerate(urls)]}


def _store(tmp_path, age, services=None, nodes=None):
    body = {"at": time.time() - age,
            "services": services if services is not None else {"app-box/Wiki": {"state": "down", "ms": 5}},
            "nodes": nodes if nodes is not None else {"app-box": {"state": "down"}}}
    (tmp_path / "checks.json").write_text(json.dumps(body), encoding="utf-8")
    return body


# ── the key ─────────────────────────────────────────────────────────────────
def test_a_service_is_keyed_by_its_monitor_or_by_its_place_and_label():
    assert S.service_key("app-box", {"label": "Wiki", "kuma": "Wiki monitor"}) == "Wiki monitor"
    assert S.service_key("app-box", {"label": "Wiki"}) == "app-box/Wiki"
    assert S.service_key("app-box", {"label": "Wiki", "kuma": ""}) == "app-box/Wiki"
    assert S.service_key("app-box", {}) == "app-box/"          # the page's svcKey says the same


# ── judged right ────────────────────────────────────────────────────────────
def test_each_answer_has_its_state(web, tmp_path):
    import requests
    urls = [f"http://192.0.2.{n}/" for n in range(1, 7)]
    web.answers.update(zip(urls, (200, 302, 401, 500, requests.ConnectionError("refused"),
                                  requests.Timeout("slow"))))
    feed = _adapter(tmp_path, _one_place_each(urls)).fetch()

    states = [feed["services"][f"box-{i}/Page"]["state"] for i in range(6)]
    assert states == ["healthy", "healthy", "healthy", "degraded", "down", "down"]
    assert [feed["nodes"][f"box-{i}"]["state"] for i in range(6)] == states
    for info in feed["services"].values():
        assert set(info) == {"state", "ms"}
        assert isinstance(info["ms"], int) and info["ms"] >= 0
    assert S._coerce_feed(feed) == feed, "the shape the hub already takes"


def test_a_place_takes_the_worst_of_its_links_but_is_down_only_when_all_are(web, tmp_path):
    import requests
    up, bad, gone = "http://192.0.2.1/", "http://192.0.2.2/", "http://192.0.2.3/"
    web.answers.update({bad: 503, gone: requests.ConnectionError("refused")})

    def place(node_id, *urls):
        return {"id": node_id, "links": [{"label": f"s{i}", "url": url + f"p{i}"}
                                         for i, url in enumerate(urls)]}

    for url in (bad, gone):
        for i in range(2):
            web.answers[url + f"p{i}"] = web.answers[url]
    data = {"nodes": [place("all-up", up, up), place("all-down", gone, gone),
                      place("one-down", up, gone), place("one-failing", up, bad),
                      place("down-and-failing", gone, bad)]}
    nodes = _adapter(tmp_path, data).fetch()["nodes"]
    assert nodes == {"all-up": {"state": "healthy"}, "all-down": {"state": "down"},
                     "one-down": {"state": "degraded"}, "one-failing": {"state": "degraded"},
                     "down-and-failing": {"state": "degraded"}}


def test_an_address_that_cannot_be_asked_has_no_state_and_nothing_raises(web, tmp_path):
    web.answers[WIKI] = RuntimeError("not a network fault")
    feed = _adapter(tmp_path).fetch()
    assert "app-box/Wiki" not in feed["services"] and "app-box" not in feed["nodes"]
    assert feed["services"]["file-box/Files"]["state"] == "healthy"


# ── asked right ─────────────────────────────────────────────────────────────
def test_the_address_is_asked_with_its_path_and_without_credentials_or_query(web, tmp_path):
    data = _one_place_each(["https://reader:invented@192.0.2.30:8443/app/login?next=%2Fhome#top",
                            "http://reader@192.0.2.31/"])
    _adapter(tmp_path, data).fetch()
    assert web.urls() == ["http://192.0.2.31/", "https://192.0.2.30:8443/app/login"]
    assert "invented" not in json.dumps(web.urls())
    assert "invented" not in (tmp_path / "checks.json").read_text(encoding="utf-8")


def test_no_redirect_is_followed_no_certificate_verified_and_no_body_read(web, tmp_path):
    _adapter(tmp_path).fetch()
    assert len(web.calls) == 2
    for _, kw in web.calls:
        assert kw["allow_redirects"] is False
        assert kw["verify"] is False
        assert kw["stream"] is True
        assert kw["timeout"] == 3
        assert kw["headers"] == {"User-Agent": "Atlas-check"}
        assert "auth" not in kw and "cookies" not in kw
    assert len(web.given) == 2 and all(answer.closed for answer in web.given)


def test_only_a_charted_http_address_is_asked(web, tmp_path):
    data = {"nodes": [
        {"id": "app-box", "links": [
            {"label": "Wiki", "url": WIKI},
            {"label": "Watched", "url": "http://192.0.2.40/", "kuma": "Watched monitor"},
            {"label": "Not built", "url": "http://192.0.2.41/", "planned": True},
            {"label": "Relative", "url": "/wiki"},
            {"label": "Shell", "url": "ssh://192.0.2.42"},
            {"label": "No host", "url": "http://"},
            {"label": "Blank", "url": ""},
            {"label": "None"}]},
        {"id": "future-box", "planned": True,
         "links": [{"label": "Later", "url": "http://192.0.2.43/"}]},
        {"id": "watched-box", "links": [{"label": "Kept", "url": "http://192.0.2.44/",
                                         "kuma": "Kept monitor"}]},
    ]}
    feed = _adapter(tmp_path, data).fetch()
    assert web.urls() == [WIKI]
    assert set(feed["services"]) == {"app-box/Wiki"}
    assert set(feed["nodes"]) == {"app-box"}


def test_a_place_kuma_is_mapped_to_gets_no_marker_state(web, tmp_path):
    data = {"nodes": [
        {"id": "app-box", "links": [{"label": "Wiki", "url": WIKI}]},
        {"id": "file-box", "monitors": ["File box"], "links": [{"label": "Files", "url": FILES}]},
        {"id": "mail-box", "links": [{"label": "Mail", "url": "http://192.0.2.12/"}]},
    ], "signals": {"kuma": {"Mail box": "mail-box"}}}
    feed = _adapter(tmp_path, data).fetch()
    assert set(feed["nodes"]) == {"app-box"}
    # the links themselves name no monitor, so they are still asked
    assert set(feed["services"]) == {"app-box/Wiki", "file-box/Files", "mail-box/Mail"}


def test_at_most_200_addresses_are_asked_and_the_log_says_so_once(web, tmp_path):
    data = _one_place_each([f"http://10.20.{i // 250}.{i % 250 + 1}/" for i in range(205)])
    seen = []
    handler = logging.Handler(level=logging.WARNING)
    handler.emit = seen.append
    S.log.addHandler(handler)
    try:
        adapter = _adapter(tmp_path, data, fresh=0)      # every fetch is a new round
        feed = adapter.fetch()
        adapter.fetch()
    finally:
        S.log.removeHandler(handler)
    first = {f"box-{i}/Page" for i in range(200)}
    assert set(feed["services"]) == first
    assert len(web.calls) == 400 and len(set(web.urls())) == 200
    capped = [r for r in seen if "asking the first 200" in r.getMessage()]
    assert len(capped) == 1 and "205" in capped[0].getMessage()
    assert capped[0].name == "atlas.live.signals"


def test_a_target_that_does_not_answer_inside_the_budget_has_no_state(web, tmp_path):
    gate = threading.Event()
    slow = "http://192.0.2.50/"
    web.answers[slow] = lambda: (gate.wait(10), 200)[1]
    data = {"nodes": [
        {"id": "app-box", "links": [{"label": "Wiki", "url": WIKI}]},
        {"id": "slow-box", "links": [{"label": "Slow", "url": slow}]},
        {"id": "mixed-box", "links": [{"label": "Quick", "url": FILES},
                                      {"label": "Slow", "url": slow + "again"}]},
    ]}
    web.answers[slow + "again"] = web.answers[slow]
    try:
        started = time.monotonic()
        feed = _adapter(tmp_path, data, budget=0.4).fetch()
        took = time.monotonic() - started
    finally:
        gate.set()
    assert took < 5, "the round waited for the slow address"
    assert set(feed["services"]) == {"app-box/Wiki", "mixed-box/Quick"}
    # unknown, never down: the slow place has no entry, the mixed one is judged
    # by the link that answered
    assert feed["nodes"] == {"app-box": {"state": "healthy"}, "mixed-box": {"state": "healthy"}}


def test_the_certificate_warning_is_silenced_for_these_calls_only(web, tmp_path):
    from urllib3.exceptions import InsecureRequestWarning

    def warn_then_answer():
        warnings.warn("unverified request", InsecureRequestWarning)
        return 200

    web.answers[WIKI] = web.answers[FILES] = warn_then_answer
    with warnings.catch_warnings(record=True) as heard:
        warnings.simplefilter("always")
        filters = list(warnings.filters)
        feed = _adapter(tmp_path).fetch()
        assert len(feed["services"]) == 2
        assert [w for w in heard if issubclass(w.category, InsecureRequestWarning)] == []
        assert list(warnings.filters) == filters, "the filter outlived the round"
        warnings.warn("another caller's request", InsecureRequestWarning)
        assert len([w for w in heard if issubclass(w.category, InsecureRequestWarning)]) == 1


# ── asked once ──────────────────────────────────────────────────────────────
def test_a_round_is_stored_and_a_second_fetch_inside_a_minute_asks_nothing(web, tmp_path):
    first = _adapter(tmp_path).fetch()
    assert len(web.calls) == 2
    stored = json.loads((tmp_path / "checks.json").read_text(encoding="utf-8"))
    assert set(stored) == {"at", "services", "nodes"}
    assert abs(stored["at"] - time.time()) < 30
    assert stored["services"] == first["services"] and stored["nodes"] == first["nodes"]
    assert not list(tmp_path.glob("checks.json.bak*")), "a round keeps no backup"

    # another worker: its own adapter, the same file
    assert _adapter(tmp_path).fetch() == first
    assert len(web.calls) == 2


def test_a_round_older_than_a_minute_is_asked_again(web, tmp_path):
    _store(tmp_path, age=61)
    feed = _adapter(tmp_path).fetch()
    assert len(web.calls) == 2
    assert feed["services"]["app-box/Wiki"]["state"] == "healthy"
    assert json.loads((tmp_path / "checks.json").read_text(encoding="utf-8"))["nodes"] == feed["nodes"]


def test_a_worker_that_cannot_take_the_lock_serves_the_stored_round(web, tmp_path):
    import filelock
    stored = _store(tmp_path, age=120)
    with filelock.exclusive(filelock.lock_for(str(tmp_path / "checks.json"))):
        feed = _adapter(tmp_path).fetch()
    assert web.calls == []
    assert feed == {"services": stored["services"], "nodes": stored["nodes"]}


def test_a_round_older_than_five_minutes_is_not_served_at_all(web, tmp_path):
    import filelock
    _store(tmp_path, age=301)
    with filelock.exclusive(filelock.lock_for(str(tmp_path / "checks.json"))):
        assert _adapter(tmp_path).fetch() == {}
    assert web.calls == []
    # with no round stored at all, the worker that waits has nothing to say either
    os.remove(tmp_path / "checks.json")
    with filelock.exclusive(filelock.lock_for(str(tmp_path / "checks.json"))):
        assert _adapter(tmp_path).fetch() == {}
    assert web.calls == []


def test_a_stored_round_is_cut_to_what_the_map_charts_now(web, tmp_path):
    _store(tmp_path, age=5,
           services={"app-box/Wiki": {"state": "healthy", "ms": 3},
                     "old-box/Gone": {"state": "down", "ms": 9}},
           nodes={"app-box": {"state": "healthy"}, "old-box": {"state": "down"},
                  "file-box": {"state": "down"}})
    data = {"nodes": [{"id": "app-box", "links": [{"label": "Wiki", "url": WIKI}]},
                      {"id": "file-box", "monitors": ["File box"],
                       "links": [{"label": "Files", "url": FILES}]}]}
    feed = _adapter(tmp_path, data).fetch()
    assert web.calls == []
    assert feed == {"services": {"app-box/Wiki": {"state": "healthy", "ms": 3}},
                    "nodes": {"app-box": {"state": "healthy"}}}


def test_nothing_to_check_is_an_answer_and_no_map_is_silence(web, tmp_path):
    assert _adapter(tmp_path, {"nodes": [{"id": "app-box"}]}).fetch() == {"nodes": {}}
    assert S.ChecksAdapter(path=str(tmp_path / "checks.json")).fetch() == {}
    assert web.calls == [] and not (tmp_path / "checks.json").exists()


# ── wiring ──────────────────────────────────────────────────────────────────
def test_signals_still_loads_with_only_settings_beside_the_standard_library():
    """A relay box imports `signals` with no web stack installed."""
    with open(os.path.join(WEB, "signals.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    top = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            top |= {alias.name for alias in stmt.names}
        elif isinstance(stmt, ast.ImportFrom):
            top.add(stmt.module)
    assert top == {"json", "logging", "os", "threading", "time", "settings"}


def _sources(monkeypatch, tmp_path, listed):
    monkeypatch.setenv("ATLAS_INTEGRATIONS", str(tmp_path / "integrations.json"))
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", listed)
    import integrations
    integrations._cache["mtime"] = None


def test_the_source_is_off_unless_it_is_listed(monkeypatch, tmp_path):
    _sources(monkeypatch, tmp_path, "")
    assert "checks" not in [a.name for a in S.make_adapters()]
    _sources(monkeypatch, tmp_path, "checks")
    adapters = S.make_adapters()
    assert [a.name for a in adapters] == ["checks"]
    assert isinstance(adapters[0], S.ChecksAdapter)


def test_checks_is_a_source_the_settings_know_and_it_needs_no_address():
    import integrations
    assert "checks" in integrations.SOURCES
    assert "checks" not in integrations.SOURCE_NEEDS
    assert not any("CHECK" in key for key in integrations.ALLOWED), "no setting of its own"


def test_the_sources_form_can_switch_it_on(web, tmp_path, monkeypatch):
    data = tmp_path / "lab-data.json"
    data.write_text(json.dumps({"meta": {"title": "Test map"}, "zones": [], "routes": [],
                                "nodes": DATA["nodes"]}), encoding="utf-8")
    for name, value in {"ATLAS_AUTH_MODE": "standalone", "ATLAS_DATA_BACKEND": "file",
                        "ATLAS_ALLOW_INSECURE": "1", "ATLAS_READONLY": "0",
                        "ATLAS_DATA": str(data), "ATLAS_SIGNALS_SOURCES": "",
                        "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
                        "ATLAS_POSITIONS": str(tmp_path / "positions.json"),
                        "ATLAS_RACK": str(tmp_path / "rack.json"),
                        "ATLAS_EVENTS": str(tmp_path / "events.json"),
                        "ATLAS_BEATS": str(tmp_path / "heartbeats.json"),
                        "ATLAS_BEATS_DIR": str(tmp_path / "beats")}.items():
        monkeypatch.setenv(name, value)
    try:
        import integrations
        integrations._cache["mtime"] = None
        client = fresh_app().app.test_client()
        r = client.post("/api/v2/admin/integrations", headers=W,
                        json={"settings": {"ATLAS_SIGNALS_SOURCES": "checks"}})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["hub"]["enabled"] == ["checks"]
        assert "checks" in client.get("/api/v2/admin/integrations").get_json()["sources"]

        feed = client.get("/api/v2/signals").get_json()
        assert feed["sources"] == {"checks": "ok"}
        assert set(feed["services"]) == {"app-box/Wiki", "file-box/Files"}
        assert feed["nodes"]["app-box"]["state"] == "healthy"
    finally:
        monkeypatch.undo()
        fresh_app()


# ── seen right ──────────────────────────────────────────────────────────────
LAB = {"meta": {"title": "Test map"}, "zones": [], "routes": [],
       "nodes": [{"id": "open-box", "name": "Open", "kind": "physical", "x": 10, "y": 10,
                  "links": [{"label": "Wiki", "url": WIKI},
                            {"label": "Back office", "url": "http://192.0.2.10:9000/",
                             "require_group": "ops-team"}]},
                 {"id": "closed-box", "name": "Closed", "kind": "physical", "x": 20, "y": 20,
                  "require_group": "ops-team",
                  "links": [{"label": "Ledger", "url": "https://192.0.2.20/"}]}]}
EVERY_KEY = {"open-box/Wiki", "open-box/Back office", "closed-box/Ledger"}


def test_the_viewer_gate_takes_a_link_with_no_monitor_by_its_key():
    import redaction
    assert redaction.visible_monitors(LAB, []) == {"open-box/Wiki"}
    assert redaction.visible_monitors(LAB, ["ops-team"]) == EVERY_KEY
    # a link that names a monitor is in the set as it always was
    named = {"nodes": [{"id": "open-box", "links": [{"label": "Wiki", "kuma": "Wiki monitor"}]}]}
    assert redaction.visible_monitors(named, []) == {"Wiki monitor"}


@pytest.fixture
def realm(web, tmp_path, monkeypatch):
    web.answers["https://192.0.2.20/"] = 503
    data = tmp_path / "lab-data.json"
    data.write_text(json.dumps(LAB), encoding="utf-8")
    for name, value in {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file",
                        "ATLAS_DATA": str(data), "ATLAS_ACCOUNTS_DB": str(tmp_path / "accounts.db"),
                        "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
                        "ATLAS_BEATS": str(tmp_path / "heartbeats.json"),
                        "ATLAS_BEATS_DIR": str(tmp_path / "beats"),
                        "ATLAS_EVENTS": str(tmp_path / "events.json"),
                        "ATLAS_SECRET_KEY": "test-signing-key", "ATLAS_INSECURE_COOKIES": "1",
                        "ATLAS_SIGNALS_SOURCES": "checks", "ATLAS_AUTH_BACKENDS": "local",
                        "ATLAS_MFA_REQUIRED": "", "ATLAS_ALLOW_INSECURE": "1"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ATLAS_AGENT_API", raising=False)
    import integrations
    integrations._cache["mtime"] = None
    handle = fresh_app()
    import accounts
    accounts.create_local_user("map-admin", PW, is_admin=True)
    accounts.create_local_user("map-viewer", PW)
    yield handle
    monkeypatch.undo()
    fresh_app()


def _signed_in(realm, name):
    client = realm.app.test_client()
    r, _ = login_as(client, name, PW)
    assert r.status_code == 200 and r.get_json()["ok"]
    return client


def test_an_admin_sees_every_check_and_none_of_them_as_drift(realm, tmp_path):
    feed = _signed_in(realm, "map-admin").get("/api/v2/signals").get_json()
    assert feed["sources"] == {"checks": "ok"}
    assert set(feed["services"]) == EVERY_KEY
    assert feed["nodes"]["open-box"]["state"] == "healthy"
    assert feed["nodes"]["closed-box"]["state"] == "degraded"
    assert feed["drift"] == {"count": 0, "uncharted": []}, (
        "a check's own result was reported as an uncharted monitor")
    assert (tmp_path / "checks.json").exists(), "the round is stored beside the dataset"


def test_a_viewer_gets_no_check_result_for_a_place_they_may_not_see(realm):
    feed = _signed_in(realm, "map-viewer").get("/api/v2/signals").get_json()
    assert set(feed["services"]) == {"open-box/Wiki"}
    assert set(feed["nodes"]) == {"open-box"}
    said = json.dumps(feed)
    for hidden in ("closed-box", "Ledger", "Back office"):
        assert hidden not in said, f"{hidden} reached a viewer without its group"
    assert feed["sources"] == {"checks": "ok"}


def test_an_api_token_gets_no_check_result_for_a_hidden_place_either(realm):
    admin = _signed_in(realm, "map-admin")
    r = admin.post("/api/v2/admin/tokens/access", json={"on": True}, headers=W)
    assert r.status_code == 200, r.get_json()
    r = admin.post("/api/v2/admin/tokens", json={"name": "reader", "days": 30}, headers=W)
    assert r.status_code == 200, r.get_json()
    secret = r.get_json()["secret"]

    r = realm.app.test_client().get("/api/v2/signals",
                                    headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 200, r.get_json()
    feed = r.get_json()
    assert set(feed["services"]) == {"open-box/Wiki"}
    assert set(feed["nodes"]) == {"open-box"}
    assert "closed-box" not in json.dumps(feed) and "Ledger" not in json.dumps(feed)


# ── what the second review found (2026-11-12) ────────────────────────────────

def test_a_charted_query_string_is_not_sent():
    """`?token=` on a charted URL is a credential, and a check sends none."""
    import signals
    assert signals._check_url("https://ops:pw@10.0.0.5:3000/d/board?orgId=1&auth_token=abc#panel") \
        == "https://10.0.0.5:3000/d/board"
    assert signals._check_url("http://10.0.0.5/status?key=abc") == "http://10.0.0.5/status"


def test_the_round_starts_somewhere_else_each_minute(monkeypatch):
    """With a fixed order, slow addresses at the head of the list would spend the
    budget every round and the rest would never be asked."""
    import signals
    targets = [(f"p/{i}", "p", f"http://10.0.0.{i}/") for i in range(1, 6)]
    asked = []
    monkeypatch.setattr(signals, "_check_one", lambda url: asked.append(url) or ("healthy", 1))
    monkeypatch.setattr(signals, "CHECKS_WORKERS", 1)
    adapter = signals.ChecksAdapter(path="unused")
    firsts = set()
    for minute in range(5):
        asked.clear()
        monkeypatch.setattr(signals.time, "time", lambda m=minute: 1_000_000_020 + 60 * m)
        adapter._probe(list(targets), set())
        assert sorted(asked) == sorted(url for _, _, url in targets)
        firsts.add(asked[0])
    assert len(firsts) == 5


def test_a_data_directory_that_cannot_be_written_still_gets_checks(tmp_path, monkeypatch):
    import filelock
    import signals

    def refuse(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(filelock, "exclusive", refuse)
    monkeypatch.setattr(signals, "_check_one", lambda url: ("healthy", 1))
    adapter = signals.ChecksAdapter(path=str(tmp_path / "checks.json"))
    adapter.use_map({"nodes": [{"id": "alpha", "links": [{"label": "Wiki", "url": "http://10.0.0.5/"}]}]})
    assert adapter.fetch()["services"] == {"alpha/Wiki": {"state": "healthy", "ms": 1}}
