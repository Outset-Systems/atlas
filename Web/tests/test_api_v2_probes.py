"""Outbound probes — `/api/v2/embeddable`, `/api/v2/whois`.

Neither test speaks to the network: the embeddable happy path patches the
verdict engine (`embeddable.verdict`), and the whois tests patch the socket
engine on `whois` (the route calls through the module so the patch lands).
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}


@pytest.fixture
def client(tmp_path):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    return fresh_app(ATLAS_DATA=str(data)).app.test_client()


# ── embeddable ───────────────────────────────────────────────────────────────

def test_embeddable_needs_a_url(client):
    r = client.get("/api/v2/embeddable")
    assert r.status_code == 400
    assert r.get_json() == {"error": "no url given"}


def test_embeddable_refuses_an_uncharted_url(client):
    """The route makes an outbound request from inside the lab; the dataset is
    what bounds it."""
    r = client.get("/api/v2/embeddable", query_string={"url": "http://evil.example/"})
    assert r.status_code == 400
    assert r.get_json() == {"error": "that address is not on this map"}


def test_embeddable_answers_for_a_charted_url_and_never_caches(client, monkeypatch):
    import json
    import embeddable
    with open(BUNDLED, encoding="utf-8") as f:
        data = json.load(f)
    url = next(l["url"] for n in data["nodes"] for l in (n.get("links") or []))
    monkeypatch.setattr(embeddable, "verdict",
                        lambda u, self_origin=None, enabled=True:
                        {"url": u, "embeddable": None,
                         "reason": "probe stubbed", "checked": 1.0})
    r = client.get("/api/v2/embeddable", query_string={"url": url})
    assert r.status_code == 200
    assert r.get_json()["url"] == url
    assert r.headers["Cache-Control"] == "no-store"


# ── whois ────────────────────────────────────────────────────────────────────

def test_whois_refuses_bad_queries(client):
    for q in ("", "-flag", "no spaces allowed", "..", "a" * 300):
        r = client.get("/api/v2/whois", query_string={"q": q})
        assert r.status_code == 400, q
        assert r.get_json() == {"error": "ask about a domain or an IP address"}


def test_whois_can_be_switched_off(tmp_path):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    client = fresh_app(ATLAS_DATA=str(data), ATLAS_WHOIS="0").app.test_client()
    r = client.get("/api/v2/whois", query_string={"q": "example.com"})
    assert r.status_code == 403
    assert r.get_json() == {"error": "whois is switched off on this Atlas"}
    assert b'"whois": false' in client.get("/").data.replace(b'"whois":false', b'"whois": false')


def test_whois_answers_a_person_and_stops_a_relay(client, monkeypatch):
    from api.v2 import probes
    probes.whois_limiter.reset()
    monkeypatch.setattr(probes.whois, "endpoint", lambda server: [("192.0.2.1", 43)])
    monkeypatch.setattr(probes.whois, "ask", lambda targets, q: "% nothing\n")
    ask = lambda: client.get("/api/v2/whois", query_string={"q": "example.com"})
    assert [ask().status_code for _ in range(probes.WHOIS_PER_MINUTE)] == (
        [200] * probes.WHOIS_PER_MINUTE)
    refused = ask()
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "60"
    probes.whois_limiter.reset()


def test_whois_502s_when_the_root_will_not_answer(client, monkeypatch):
    import whois
    monkeypatch.setattr(whois, "endpoint", lambda server: None)
    r = client.get("/api/v2/whois?q=example.com")
    assert r.status_code == 502
    assert r.get_json() == {"error": "whois.iana.org would not answer"}


def test_whois_follows_the_referral_chain(client, monkeypatch):
    import whois
    answers = {"whois.iana.org": "refer: whois.verisign-grs.com\n",
               "whois.verisign-grs.com": "Domain Name: EXAMPLE.COM\n"}
    monkeypatch.setattr(whois, "endpoint", lambda server: [("AF_INET", (server, 43))])
    monkeypatch.setattr(whois, "ask",
                        lambda targets, q: answers.get(targets[0][1][0], "no match\n"))
    r = client.get("/api/v2/whois?q=example.com")
    assert r.status_code == 200
    body = r.get_json()
    assert body["query"] == "example.com"
    assert body["servers"] == ["whois.iana.org", "whois.verisign-grs.com"]
    assert "Domain Name: EXAMPLE.COM" in body["text"]
    assert r.headers["Cache-Control"] == "no-store"
