"""THE VIEWING GLASS's oracle: will this service render inside the map?

What matters here: the CSP is widened to the map's *own* origins and nothing
else, a header can never be injected through a dataset URL, a service that says
DENY is reported as a refusal rather than tried and blanked, an unreachable one
answers "unknown" instead of raising, and the probe endpoint refuses any URL
that is not already on the map — it is not an open fetcher.
"""

import json
import os
import shutil
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {
    "ATLAS_AUTH_MODE": "standalone",
    "ATLAS_ALLOW_INSECURE": "1",
    "ATLAS_DATA_BACKEND": "file",
    "ATLAS_INGEST_ENABLED": "0",
    "ATLAS_READONLY": "0",
}
os.environ.update(ATLAS_TEST_ENV)

import embeddable  # noqa: E402


DATA = {
    "nodes": [
        {"id": "app-host", "name": "APP HOST", "links": [
            {"label": "Hub", "url": "http://10.77.90.20:5000"},
            {"label": "Atlas", "url": "http://10.77.90.20:5006"},
        ]},
        {"id": "quiet", "name": "QUIET"},                      # no links at all
    ],
    "chronicle": [
        {"title": "HOSTS", "url": "http://10.77.30.10:3000/d/x",
         "embed": "http://10.77.30.10:3000/d-solo/x"},
    ],
    "abyss": [
        {"title": "SECURITY", "url": "report/security"},        # served by us
    ],
}


class FakeResponse:
    def __init__(self, headers=None, status_code=200):
        self.headers = headers or {}
        self.status_code = status_code

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _fresh_cache():
    embeddable.forget()
    yield
    embeddable.forget()


# ── What the map points at ───────────────────────────────────────────────────
def test_urls_are_collected_from_links_chronicle_and_abyss():
    urls = embeddable.urls_of(DATA)
    assert "http://10.77.90.20:5000" in urls
    assert "http://10.77.30.10:3000/d-solo/x" in urls   # embeds count: they are framed
    assert "report/security" in urls
    assert len(urls) == len(set(urls))                 # deduplicated


def test_origins_collapse_to_distinct_hosts():
    assert embeddable.origins(DATA) == [
        "http://10.77.30.10:3000", "http://10.77.90.20:5000", "http://10.77.90.20:5006",
    ]


def test_a_relative_url_has_no_origin_because_it_is_already_self():
    assert embeddable.origin_of("report/security") is None
    assert embeddable.origin_of("") is None
    assert embeddable.origin_of(None) is None


# ── The header ───────────────────────────────────────────────────────────────
def test_frame_src_keeps_self_first_then_configured_then_the_map():
    src = embeddable.frame_src(DATA, "http://grafana:3000")
    assert src.startswith("'self' http://grafana:3000 ")
    assert "http://10.77.90.20:5006" in src


def test_frame_src_without_a_dataset_is_the_old_behaviour():
    """`data=None` IS the switch — ATLAS_EMBED_SERVICES=0 and an unreadable
    dataset both arrive here the same way."""
    assert embeddable.frame_src(None, "http://grafana:3000") == "'self' http://grafana:3000"


def test_a_url_can_never_inject_a_csp_directive():
    """The dataset is admin-written, but a URL is still user input and this is
    still a header — a `;` in either half must not start a new directive."""
    hostile = {"nodes": [{"id": "x", "links": [
        {"label": "bad", "url": "http://evil; script-src *"},
        {"label": "worse", "url": "http://ok.example\nX-Injected: 1"},
    ]}]}
    src = embeddable.frame_src(hostile, "http://fine:1; default-src *")
    assert ";" not in src
    assert "\n" not in src
    assert src == "'self'"


# ── The verdict ──────────────────────────────────────────────────────────────
def test_deny_is_a_refusal(monkeypatch):
    monkeypatch.setattr(embeddable, "_probe", lambda u, o: (False, embeddable.R_REFUSED))
    v = embeddable.verdict("http://10.77.90.20:5000")
    assert v["embeddable"] is False


def test_a_relative_url_always_frames():
    v = embeddable.verdict("report/security")
    assert v["embeddable"] is True


def test_a_non_http_scheme_never_frames():
    v = embeddable.verdict("file:////srv/docs/x.md")
    assert v["embeddable"] is False
    assert v["reason"] == embeddable.R_NOT_HTTP


def test_protocol_relative_is_not_treated_as_our_own_page():
    """`//host/x` inherits the page's scheme and goes OFF-origin — calling it
    'served by the Atlas itself' would frame an arbitrary host unprobed.
    schema.py's link rule refuses the form; the verdict agrees with it."""
    v = embeddable.verdict("//evil.example/x")
    assert v["embeddable"] is False
    assert v["reason"] == embeddable.R_NOT_HTTP


def test_an_unreachable_service_is_unknown_not_an_error(monkeypatch):
    """Fail-silent, like signals.py: unknown means 'try it and see', which the
    glass can recover from. An exception here would break the click."""
    def boom(*_a, **_k):
        raise OSError("no route to host")
    fake = type("R", (), {"head": staticmethod(boom), "get": staticmethod(boom)})
    monkeypatch.setitem(sys.modules, "requests", fake)
    v = embeddable.verdict("http://10.77.90.20:5000")
    assert v["embeddable"] is None
    assert v["reason"] == embeddable.R_UNREACHABLE


def test_the_verdict_is_cached(monkeypatch):
    calls = []

    def probe(url, origin):
        calls.append(url)
        return True, embeddable.R_OK
    monkeypatch.setattr(embeddable, "_probe", probe)
    embeddable.verdict("http://10.77.90.20:5000")
    embeddable.verdict("http://10.77.90.20:5000")
    assert len(calls) == 1


def test_probing_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(embeddable, "_probe",
                        lambda *_a: pytest.fail("must not probe when disabled"))
    v = embeddable.verdict("http://10.77.90.20:5000", enabled=False)
    assert v["embeddable"] is None


# ── Reading the headers ──────────────────────────────────────────────────────
@pytest.mark.parametrize("headers,expected", [
    ({}, True),
    ({"X-Frame-Options": "DENY"}, False),
    ({"X-Frame-Options": "SAMEORIGIN"}, False),
    ({"X-Frame-Options": "sameorigin"}, False),
    ({"Content-Security-Policy": "frame-ancestors 'none'"}, False),
    ({"Content-Security-Policy": "frame-ancestors 'self'"}, False),
    ({"Content-Security-Policy": "frame-ancestors *"}, True),
    ({"Content-Security-Policy": "default-src 'self'"}, True),      # says nothing
    # CSP wins over XFO, exactly as a browser resolves it
    ({"X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors *"}, True),
])
def test_judge_reads_the_framing_rules(headers, expected):
    assert embeddable._judge(headers, "http://atlas:5006", "http://them:1")[0] is expected


@pytest.mark.parametrize("headers", [
    {"X-Frame-Options": "SAMEORIGIN"},
    {"Content-Security-Policy": "frame-ancestors 'self'"},
])
def test_sameorigin_is_a_yes_when_it_is_our_own_page(headers):
    """The Atlas's own `/report/<name>` pages exist to be framed by the map.
    `SAMEORIGIN` from *them* means "same origin as them", which is us."""
    assert embeddable._judge(headers, "http://atlas:5006", "http://atlas:5006")[0] is True


def test_a_framing_rule_naming_us_is_a_yes():
    csp = {"Content-Security-Policy": "frame-ancestors http://atlas:5006"}
    assert embeddable._judge(csp, "http://atlas:5006", "http://them:1")[0] is True


def test_a_framing_rule_we_cannot_model_is_unknown_not_a_refusal():
    """A guess that says 'no' costs a working feature; a guess that says
    'unknown' costs one blank pane the glass already recovers from."""
    csp = {"Content-Security-Policy": "frame-ancestors https://*.example.com"}
    assert embeddable._judge(csp, "http://atlas:5006", "http://them:1")[0] is None


def test_the_report_page_lets_the_map_frame_it(arena):
    """It is served specifically to be drawn inside the Abyss and the glass —
    the app-wide DENY would block that even same-origin."""
    r = arena.app.test_client().get("/report/security")
    assert r.status_code == 200
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_head_that_is_refused_falls_through_to_get(monkeypatch):
    seen = []

    class Fake:
        @staticmethod
        def head(url, **_k):
            seen.append("head")
            return FakeResponse(status_code=405)

        @staticmethod
        def get(url, **_k):
            seen.append("get")
            return FakeResponse({"X-Frame-Options": "DENY"})
    monkeypatch.setitem(sys.modules, "requests", Fake)
    assert embeddable._probe("http://x:1", "")[0] is False
    assert seen == ["head", "get"]


# ── The endpoint ─────────────────────────────────────────────────────────────
def _fresh(tmp_path, **extra):
    """One app-under-test recipe for this file; `extra` overrides per test.
    (conftest._atlas_env restores every ATLAS_* var after each test.)"""
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    return fresh_app(ATLAS_DATA=str(data), ATLAS_READONLY="0",
                     ATLAS_EMBED_HOSTS="http://grafana:3000",
                     ATLAS_BEATS=str(tmp_path / "hb.json"),
                     ATLAS_BEATS_DIR=str(tmp_path / "beats"),
                     ATLAS_MAINTENANCE=str(tmp_path / "m.json"),
                     ATLAS_EVENTS=str(tmp_path / "e.json"),
                     ATLAS_REVISIONS=str(tmp_path / "rev"), **extra)


@pytest.fixture
def arena(tmp_path):
    return _fresh(tmp_path)


def _a_charted_url(arena):
    with open(os.path.join(WEB, "default-lab-data.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    return embeddable.urls_of(data)[0]


def test_the_probe_refuses_a_url_that_is_not_on_the_map(arena):
    """The gate that keeps this from being an open fetcher wearing the Atlas's
    network position."""
    client = arena.app.test_client()
    r = client.get("/api/v2/embeddable?url=http://169.254.169.254/latest/meta-data/")
    assert r.status_code == 400
    assert "not on this map" in r.get_json()["error"]


def test_the_probe_needs_a_url_at_all(arena):
    assert arena.app.test_client().get("/api/v2/embeddable").status_code == 400


def test_the_probe_answers_for_a_charted_url(arena, monkeypatch):
    monkeypatch.setattr(embeddable, "_probe", lambda u, o: (True, embeddable.R_OK))
    url = _a_charted_url(arena)
    r = arena.app.test_client().get("/api/v2/embeddable?url=" + url)
    assert r.status_code == 200
    body = r.get_json()
    assert body["embeddable"] is True
    assert body["url"] == url
    assert r.headers["Cache-Control"] == "no-store"


def test_the_csp_lets_the_glass_frame_the_services_the_map_links_to(arena):
    csp = arena.app.test_client().get("/").headers["Content-Security-Policy"]
    assert "frame-src 'self' http://grafana:3000 " in csp
    for origin in embeddable.origins(json.load(open(BUNDLED, encoding="utf-8"))):
        assert origin in csp


def test_the_csp_stays_narrow_when_the_widening_is_switched_off(tmp_path):
    app = _fresh(tmp_path, ATLAS_EMBED_SERVICES="0")
    csp = app.app.test_client().get("/").headers["Content-Security-Policy"]
    assert "frame-src 'self' http://grafana:3000" in csp
    assert "10.77.90.20" not in csp
