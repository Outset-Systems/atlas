"""ALERTS' sender (2026-11-13): every security item a test.

No test here sends to a real host. `send` is always given a fake resolver and
a fake transport; the default transport is called directly, never through
`send`, against a stub receiver this file runs on the loopback address.
"""

import datetime
import http.server
import json
import os
import socket
import ssl
import sys
import threading
import time

import pytest

import alert_send
import settings

HOSTS = ("ntfy.example:443,gotify.example:8080,hook.example:443,"
         "192.0.2.10:8080,[2001:db8::5]:443,rebind.example:443")
SECRET = "s3cret-value-never-seen"


@pytest.fixture
def on(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ALERTS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ALERT_HOSTS", HOSTS, raising=False)
    monkeypatch.setattr(settings, "ALERT_LOG_PATH", str(tmp_path / "deliveries.jsonl"),
                        raising=False)
    monkeypatch.setattr(settings, "HOST", "0.0.0.0")
    # the machine's own addresses are tested on their own, with a stand-in
    # resolver; here they would be whatever the test machine happens to have
    monkeypatch.setattr(alert_send, "_machine_addresses", frozenset)
    for name in ("ATLAS_ALERT_SECRET_NTFY_LAB", "ATLAS_ALERT_SECRET_NTFY_LAB_FILE",
                 "ATLAS_ALERT_SECRET_GOT", "ATLAS_ALERT_SECRET_GOT_FILE",
                 "ATLAS_ALERT_SECRET_HOOK", "ATLAS_ALERT_SECRET_HOOK_FILE"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def dest(kind="ntfy", url="https://ntfy.example/atlas", **kw):
    out = {"id": "d1", "name": "Lab phone", "kind": kind, "url": url,
           "secret": None, "secret_origin": None}
    out.update(kw)
    return out


def message(**kw):
    out = dict(title="Switch down", body="core-switch is down.", priority="default",
               link="https://atlas.example/?place=core-switch", tags=["warning"])
    out.update(kw)
    return out


class Resolver:
    def __init__(self, *addresses, fail=False):
        self.addresses, self.fail, self.calls = addresses, fail, []

    def __call__(self, host, port, *a, **kw):
        self.calls.append((host, port))
        if self.fail:
            raise socket.gaierror("no such name")
        out = []
        for a in self.addresses:
            fam = socket.AF_INET6 if ":" in a else socket.AF_INET
            out.append((fam, socket.SOCK_STREAM, 6, "", (a, port)))
        return out


class FakeResponse:
    def __init__(self, status, body=b""):
        self.status, self.body, self.reads, self.closed = status, body, [], False

    def read(self, n):
        self.reads.append(n)
        chunk, self.body = self.body[:n], self.body[n:]
        return chunk

    def close(self):
        self.closed = True


class Transport:
    def __init__(self, status=200, body=b"ok", raises=None):
        self.status, self.body, self.raises, self.calls = status, body, raises, []
        self.responses = []

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.raises is not None:
            raise self.raises
        resp = FakeResponse(self.status, self.body)
        self.responses.append(resp)
        return resp


def go(d, msg=None, address="192.0.2.20", status=200, **kw):
    resolver, transport = Resolver(address), Transport(status=status, **kw)
    result = alert_send.send(d, msg or message(), resolver=resolver, transport=transport)
    return result, resolver, transport


# ── check_destination ───────────────────────────────────────────────────────

@pytest.mark.parametrize("d", [
    dest(),
    dest("gotify", "http://gotify.example:8080"),
    dest("gotify", "http://gotify.example:8080/"),
    dest("gotify", "http://gotify.example:8080/sub/message"),
    dest("webhook", "https://hook.example/in/atlas"),
    dest("webhook", "http://192.0.2.10:8080/hook"),
    dest("webhook", "https://[2001:db8::5]/hook"),
    dest("ntfy", "https://NTFY.Example./atlas"),
    dest(secret="NTFY_LAB"),
])
def test_a_good_destination_passes(on, d):
    assert alert_send.check_destination(d) == []


@pytest.mark.parametrize("d, words", [
    ("not a dict", "an object"),
    (dest(kind="email"), "ntfy, gotify or webhook"),
    (dest(name=""), "name"),
    (dest(name="   "), "name"),
    (dest(name="x" * 61), "at most 60"),
    (dest(url=None), "address"),
    (dest(url="ftp://ntfy.example/atlas"), "http:// or https://"),
    (dest(url="https://user:pw@ntfy.example/atlas"), "user name or password"),
    (dest(url="https://token@ntfy.example/atlas"), "user name or password"),
    (dest(url="https://ntfy.example/atlas?token=abc"), "query string"),
    (dest(url="https://ntfy.example/atlas?"), "query string"),
    (dest(url="https://ntfy.example/atlas#x"), "fragment"),
    (dest(url="https://[ntfy.example/atlas"), "does not parse"),
    (dest(url="https://[abc]/x"), "does not parse"),
    (dest(url="https://ntfy.example/at las"), "spaces"),
    (dest(url="https://ntfy.example\\@other.example/atlas"), "spaces"),
    (dest(url="https://ntfy.example:99999/atlas"), "port"),
    (dest(url="https://ntfy.example:8443/atlas"), "not in ATLAS_ALERT_HOSTS"),
    (dest(url="https://elsewhere.example/atlas"), "not in ATLAS_ALERT_HOSTS"),
    (dest(url="http://ntfy.example/atlas"), "not in ATLAS_ALERT_HOSTS"),
    (dest(url="https://ntfy.example/"), "names its topic"),
    (dest("gotify", "http://gotify.example:8080/other"), "ends in /message"),
    (dest(secret="ntfy_lab"), "capitals"),
    (dest(secret="A" * 41), "capitals"),
    (dest(secret="NTFY-LAB"), "capitals"),
])
def test_each_rule_refuses(on, d, words):
    problems = alert_send.check_destination(d)
    assert problems and any(words in p for p in problems), problems


def test_a_listed_loopback_literal_is_still_refused(on, monkeypatch):
    monkeypatch.setattr(settings, "ALERT_HOSTS", "127.0.0.1:8080,169.254.169.254:80")
    for url in ("http://127.0.0.1:8080/x", "http://169.254.169.254/latest"):
        problems = alert_send.check_destination(dest("webhook", url))
        assert any("loopback, link-local" in p for p in problems)


def test_a_url_that_does_not_parse_never_raises(on):
    for url in ("https://[ntfy.example/atlas", "https://[abc]/x"):
        d = dest(url=url, secret="NTFY_LAB", secret_origin="https://ntfy.example:443")
        assert alert_send.origin(url) is None
        assert alert_send.bind_secret(d)["secret_origin"] is None
        assert alert_send.unbind_if_moved(dest(), d)[0]["secret_origin"] is None
        assert alert_send.secret_for(d) is None
        result, resolver, transport = go(d)
        assert result["outcome"] == "blocked"
        assert resolver.calls == [] and transport.calls == []
    assert alert_send.send(None, None)["outcome"] == "blocked"


def test_an_empty_list_says_so(on, monkeypatch):
    monkeypatch.setattr(settings, "ALERT_HOSTS", "")
    assert any("empty" in p for p in alert_send.check_destination(dest()))


def test_gotify_is_normalised_to_message():
    assert alert_send.normalised(dest("gotify", "http://gotify.example:8080/"))["url"] == \
        "http://gotify.example:8080/message"
    assert alert_send.normalised(dest("gotify", "https://g.example/a/message/"))["url"] == \
        "https://g.example/a/message"


# ── the allow-list ──────────────────────────────────────────────────────────

def test_allowed_hosts_parses():
    raw = " NTFY.Example.:443 , 192.0.2.10:8080,[2001:DB8::5]:443  hook.example:8443"
    assert alert_send.allowed_hosts(raw) == [
        ("ntfy.example", 443), ("192.0.2.10", 8080), ("2001:db8::5", 443),
        ("hook.example", 8443)]


def test_an_entry_without_a_port_is_left_out_and_named(on, monkeypatch):
    raw = "ntfy.example,gotify.example:8080,2001:db8::5,bad host!:80,hook.example:0"
    assert alert_send.allowed_hosts(raw) == [("gotify.example", 8080)]
    problems = " ".join(alert_send.host_problems(raw))
    assert "ntfy.example in ATLAS_ALERT_HOSTS has no port" in problems
    assert "brackets" in problems
    assert "not 1 to 65535" in problems
    monkeypatch.setattr(settings, "ALERT_HOSTS", raw)
    said = alert_send.check_destination(dest())
    assert any("without a port" in p and "ntfy.example:443" in p for p in said), said


def test_settings_fall_back_to_the_environment(monkeypatch):
    monkeypatch.delattr(settings, "ALERT_HOSTS", raising=False)
    monkeypatch.delattr(settings, "ALERTS_ENABLED", raising=False)
    monkeypatch.setenv("ATLAS_ALERT_HOSTS", "ntfy.example:443")
    monkeypatch.setenv("ATLAS_ALERTS", "1")
    assert alert_send.allowed_hosts() == [("ntfy.example", 443)]
    assert alert_send.enabled()
    monkeypatch.setenv("ATLAS_ALERTS", "0")
    assert not alert_send.enabled()


# ── refused addresses, pinning, rebinding ───────────────────────────────────

@pytest.mark.parametrize("address", [
    "127.0.0.1", "127.8.9.10", "::1", "169.254.169.254", "169.254.1.1", "fe80::1",
    "224.0.0.1", "239.255.255.250", "ff02::1", "0.0.0.0", "0.1.2.3", "::",
    "::ffff:127.0.0.1", "240.0.0.1", "255.255.255.255",
])
def test_a_refused_address_is_blocked(on, address):
    result, resolver, transport = go(dest(), address=address)
    assert result["outcome"] == "blocked"
    assert result["status"] is None
    assert address not in (result["why"] or "")
    assert transport.calls == []
    assert len(resolver.calls) == 1


def test_atlas_own_listening_address_is_blocked(on, monkeypatch):
    monkeypatch.setattr(settings, "HOST", "192.0.2.50")
    assert go(dest(), address="192.0.2.50")[0]["outcome"] == "blocked"
    assert go(dest(), address="192.0.2.51")[0]["outcome"] == "delivered"


@pytest.mark.parametrize("address", [
    "fd00:ec2::254", "100.100.100.200", "192.0.0.192", "::ffff:100.100.100.200",
])
def test_a_cloud_metadata_address_is_blocked(on, address):
    result, _, transport = go(dest(), address=address)
    assert result["outcome"] == "blocked" and transport.calls == []


@pytest.mark.parametrize("address", ["100.64.0.1", "100.100.100.201", "fd00:ec2::253",
                                     "192.0.0.193"])
def test_the_metadata_addresses_neighbours_are_allowed(on, address):
    # exact addresses, not ranges: a tailnet lives in 100.64.0.0/10
    assert go(dest(), address=address)[0]["outcome"] == "delivered"


def _machine(monkeypatch, name, answers):
    """The real `_machine_addresses`, its name and resolver stood in for."""
    calls = []

    def resolve(host, port, *a, **kw):
        calls.append(host)
        if isinstance(answers, Exception):
            raise answers
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 (a, 0)) for a in answers]

    monkeypatch.setattr(alert_send, "_machine_addresses", MACHINE_ADDRESSES)
    monkeypatch.setattr(alert_send, "_machine", {"at": None, "addresses": frozenset()})
    monkeypatch.setattr(alert_send.socket, "gethostname", lambda: name)
    monkeypatch.setattr(alert_send.socket, "getaddrinfo", resolve)
    return calls


MACHINE_ADDRESSES = alert_send._machine_addresses


def test_a_bind_to_every_address_still_blocks_the_machines_own(on, monkeypatch):
    # ATLAS_HOST is 0.0.0.0 here: it names no address, the machine's name does
    calls = _machine(monkeypatch, "atlas-box", ["192.0.2.60", "2001:db8::60"])
    assert go(dest(), address="192.0.2.60")[0]["outcome"] == "blocked"
    assert go(dest(), address="2001:db8::60")[0]["outcome"] == "blocked"
    assert go(dest(), address="192.0.2.61")[0]["outcome"] == "delivered"
    assert calls == ["atlas-box"]                   # looked up once, then kept


def test_the_machines_own_addresses_never_raise(on, monkeypatch):
    _machine(monkeypatch, "atlas-box", socket.gaierror("no such name"))
    assert alert_send._machine_addresses() == frozenset()
    assert go(dest(), address="192.0.2.60")[0]["outcome"] == "delivered"
    _machine(monkeypatch, "", ["192.0.2.60"])
    assert alert_send._machine_addresses() == frozenset()


def test_a_name_that_takes_too_long_to_resolve_is_given_up(on, monkeypatch):
    monkeypatch.setattr(alert_send, "RESOLVE_S", 0.2)
    release = threading.Event()

    def slow(host, port, *a, **kw):
        release.wait(5)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.20", port))]

    transport = Transport()
    started = time.monotonic()
    try:
        result = alert_send.send(dest(), message(), resolver=slow, transport=transport)
    finally:
        release.set()
    assert time.monotonic() - started < 2
    assert result == {"outcome": "unreachable", "status": None,
                      "why": "the name did not resolve in time"}
    assert transport.calls == []


def test_a_listed_name_that_resolves_to_loopback_is_blocked(on):
    resolver = Resolver("192.0.2.20", "127.0.0.1")
    transport = Transport()
    result = alert_send.send(dest(url="https://rebind.example/t"), message(),
                             resolver=resolver, transport=transport)
    assert result["outcome"] == "blocked"
    assert transport.calls == []
    assert resolver.calls == [("rebind.example", 443)]


def test_a_listed_literal_that_resolves_elsewhere_is_blocked(on):
    result, _, transport = go(dest("webhook", "http://192.0.2.10:8080/hook"),
                              address="192.0.2.11")
    assert result["outcome"] == "blocked"
    assert transport.calls == []
    result, _, transport = go(dest("webhook", "http://192.0.2.10:8080/hook"),
                              address="192.0.2.10")
    assert result["outcome"] == "delivered"


def test_a_name_that_does_not_resolve_is_unreachable(on):
    transport = Transport()
    result = alert_send.send(dest(), message(), resolver=Resolver(fail=True),
                             transport=transport)
    assert result == {"outcome": "unreachable", "status": None,
                      "why": "the name did not resolve"}
    assert transport.calls == []


def test_the_connection_is_pinned_to_the_checked_address(on):
    result, resolver, transport = go(dest(), address="192.0.2.20")
    assert result == {"outcome": "delivered", "status": 200, "why": None}
    call = transport.calls[0]
    assert call["address"] == "192.0.2.20"
    assert call["host"] == "ntfy.example"           # SNI and the certificate's name
    assert call["scheme"] == "https" and call["port"] == 443
    assert call["method"] == "POST"
    assert call["headers"]["Host"] == "ntfy.example"
    assert call["connect_timeout"] == 3 and call["total_timeout"] == 5
    assert len(resolver.calls) == 1


def test_a_private_address_is_allowed(on):
    assert go(dest(), address="10.0.0.5")[0]["outcome"] == "delivered"
    _, _, transport = go(dest("gotify", "http://gotify.example:8080"), address="2001:db8::7")
    assert transport.calls[0]["address"] == "2001:db8::7"
    assert transport.calls[0]["headers"]["Host"] == "gotify.example:8080"


# ── outcomes ────────────────────────────────────────────────────────────────

def test_no_redirects(on):
    result, _, transport = go(dest(), status=302)
    assert result["outcome"] == "refused" and result["status"] == 302
    assert "redirects are not followed" in result["why"]
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status", [400, 401, 404, 500, 503, 199])
def test_any_other_status_is_refused(on, status):
    result = go(dest(), status=status)[0]
    assert result == {"outcome": "refused", "status": status, "why": f"HTTP {status}"}


@pytest.mark.parametrize("exc, why", [
    (socket.timeout("timed out"), "timed out"),
    (TimeoutError(), "timed out"),
    (ConnectionRefusedError(), "the connection was refused"),
    (ssl.SSLCertVerificationError("certificate verify failed: " + SECRET), "the certificate did not verify"),
    (OSError("Network unreachable " + SECRET), "could not connect"),
    (ValueError("Invalid header value b'Bearer " + SECRET + "'"), "the request could not be made"),
])
def test_failures_map_to_unreachable_with_a_fixed_reason(on, exc, why):
    result = go(dest(), raises=exc)[0]
    assert result == {"outcome": "unreachable", "status": None, "why": why}
    assert SECRET not in json.dumps(result)


def test_the_response_is_read_at_most_1kb_then_dropped(on):
    result, _, transport = go(dest(), body=b"x" * 100_000)
    resp = transport.responses[0]
    assert sum(resp.reads) <= 1024 and resp.closed
    assert set(result) == {"outcome", "status", "why"}
    assert "x" not in (result["why"] or "")


def test_disabled_blocks_with_no_resolver_or_transport(on, monkeypatch):
    monkeypatch.setattr(settings, "ALERTS_ENABLED", False)
    result, resolver, transport = go(dest())
    assert result["outcome"] == "blocked"
    assert resolver.calls == [] and transport.calls == []


def test_a_bad_destination_is_blocked_before_resolving(on):
    result, resolver, transport = go(dest(url="https://elsewhere.example/x"))
    assert result["outcome"] == "blocked" and "ATLAS_ALERT_HOSTS" in result["why"]
    assert resolver.calls == [] and transport.calls == []


# ── the three shapes ────────────────────────────────────────────────────────

def test_ntfy_request(on, monkeypatch):
    monkeypatch.setenv("ATLAS_ALERT_SECRET_NTFY_LAB", SECRET)
    d = alert_send.bind_secret(dest(secret="NTFY_LAB"))
    _, _, transport = go(d, message(priority="high", tags=["warning", "rotating_light"]))
    call = transport.calls[0]
    assert call["path"] == "/atlas"
    assert call["method"] == "POST"
    h = call["headers"]
    assert h["Title"] == "Switch down"
    assert h["Priority"] == "5"
    assert h["Tags"] == "warning,rotating_light"
    assert h["Click"] == "https://atlas.example/?place=core-switch"
    assert h["Authorization"] == f"Bearer {SECRET}"
    assert h["Content-Type"].startswith("text/plain")
    assert call["body"] == "core-switch is down.".encode()
    _, _, transport = go(dest(), message(priority="default"))
    assert transport.calls[0]["headers"]["Priority"] == "3"
    assert "Authorization" not in transport.calls[0]["headers"]


def test_gotify_request_and_its_key_in_the_header(on, monkeypatch):
    monkeypatch.setenv("ATLAS_ALERT_SECRET_GOT", SECRET)
    d = alert_send.bind_secret(dest("gotify", "http://gotify.example:8080", secret="GOT"))
    _, _, transport = go(d, message(priority="high"))
    call = transport.calls[0]
    assert call["path"] == "/message"
    assert call["method"] == "POST"
    assert call["headers"]["X-Gotify-Key"] == SECRET
    assert "Authorization" not in call["headers"]
    assert SECRET not in call["path"] and "token" not in call["path"]
    doc = json.loads(call["body"])
    assert doc == {"title": "Switch down", "message": "core-switch is down.", "priority": 8,
                   "extras": {"client::notification": {"click": {
                       "url": "https://atlas.example/?place=core-switch"}}}}
    _, _, transport = go(d, message(link=None))
    doc = json.loads(transport.calls[0]["body"])
    assert doc["priority"] == 5 and "extras" not in doc


def test_webhook_request(on, monkeypatch):
    monkeypatch.setenv("ATLAS_ALERT_SECRET_HOOK", SECRET)
    d = alert_send.bind_secret(dest("webhook", "https://hook.example/in/atlas", secret="HOOK"))
    _, _, transport = go(d)
    call = transport.calls[0]
    assert call["path"] == "/in/atlas"
    assert call["method"] == "POST"
    assert call["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert call["headers"]["Content-Type"] == "application/json"
    assert json.loads(call["body"]) == dict(
        title="Switch down", body="core-switch is down.", priority="default",
        link="https://atlas.example/?place=core-switch", tags=["warning"],
        source="atlas")


def test_headers_carry_one_line_and_ascii(on):
    msg = message(title="Kraków ✓ down\r\nX-Evil: 1", tags=["a,b", "x\r\ny"],
                  link="https://atlas.example/\r\nX-Evil: 1")
    _, _, transport = go(dest(), msg)
    h = transport.calls[0]["headers"]
    for value in h.values():
        assert "\r" not in value and "\n" not in value
        assert value.isascii()
        value.encode("latin-1")
    assert "X-Evil" not in h and "Click" not in h      # a bad link is dropped
    assert h["Title"].startswith("=?UTF-8?B?")
    import email.header
    decoded = email.header.decode_header(h["Title"])[0][0].decode("utf-8")
    assert decoded == "Kraków ✓ down X-Evil: 1"
    assert h["Tags"] == "ab,xy"


def test_a_link_with_credentials_is_dropped(on):
    _, _, transport = go(dest("webhook", "https://hook.example/in"),
                         message(link="https://u:p@atlas.example/"))
    doc = json.loads(transport.calls[0]["body"])
    assert doc == dict(doc, link=None)


@pytest.mark.parametrize("kind, url", [
    ("ntfy", "https://ntfy.example/atlas"),
    ("gotify", "http://gotify.example:8080"),
    ("webhook", "https://hook.example/in"),
])
def test_the_body_is_capped_at_4kb_and_stays_whole(on, kind, url):
    long = "ünïcødé ✓ " * 2000
    _, _, transport = go(dest(kind, url), message(body=long, title="T" * 5000,
                                                  tags=[f"t{i}" for i in range(50)]))
    body = transport.calls[0]["body"]
    assert len(body) <= alert_send.MAX_BODY
    text = body.decode("utf-8")
    if kind == "ntfy":
        assert text.endswith("…")
        import email.header
        title = email.header.decode_header(transport.calls[0]["headers"]["Title"])[0][0]
        assert len(title.decode("utf-8")) <= alert_send.TITLE_MAX
    else:
        doc = json.loads(text)
        said = doc["message"] if kind == "gotify" else doc["body"]
        assert said.endswith("…") and long.startswith(said[:-1])
        assert len(doc["title"]) <= alert_send.TITLE_MAX
        if kind == "webhook":
            assert len(doc["tags"]) <= alert_send.TAGS_MAX


def test_a_short_body_is_not_cut(on):
    _, _, transport = go(dest("webhook", "https://hook.example/in"), message(body="x" * 3000))
    assert json.loads(transport.calls[0]["body"])["body"] == "x" * 3000


# ── secrets ─────────────────────────────────────────────────────────────────

def test_secret_from_the_environment(on, monkeypatch):
    monkeypatch.setenv("ATLAS_ALERT_SECRET_NTFY_LAB", SECRET)
    assert alert_send.secret_for(alert_send.bind_secret(dest(secret="NTFY_LAB"))) == SECRET


def test_secret_from_a_file(on, monkeypatch):
    path = on / "ntfy.secret"
    path.write_text(SECRET + "\n", encoding="utf-8")
    monkeypatch.setenv("ATLAS_ALERT_SECRET_NTFY_LAB_FILE", str(path))
    d = alert_send.bind_secret(dest(secret="NTFY_LAB"))
    assert alert_send.secret_for(d) == SECRET
    _, _, transport = go(d)
    assert transport.calls[0]["headers"]["Authorization"] == f"Bearer {SECRET}"


def test_the_secret_is_never_logged_or_returned(on, monkeypatch, caplog):
    caplog.set_level("DEBUG")
    monkeypatch.setenv("ATLAS_ALERT_SECRET_NTFY_LAB", SECRET)
    d = alert_send.bind_secret(dest(secret="NTFY_LAB"))
    results = [go(d)[0], go(d, status=401)[0],
               go(d, raises=ValueError("header b'Bearer " + SECRET + "'"))[0],
               go(d, address="127.0.0.1")[0]]
    for r in results:
        alert_send.log_delivery({"rule": "r1", "destination": d["name"], "events": [1],
                                 "secret": SECRET, "title": "Switch down",
                                 "body": "core-switch is down.", **r})
    assert SECRET not in json.dumps(results)
    assert SECRET not in caplog.text
    text = open(settings.ALERT_LOG_PATH, encoding="utf-8").read()
    assert SECRET not in text and "Switch down" not in text and "core-switch" not in text
    for row in alert_send.read_deliveries():
        assert set(row) <= {"at", "rule", "destination", "events", "outcome", "status", "why"}
    assert SECRET not in json.dumps(alert_send.bind_secret(d))


def test_a_named_secret_that_cannot_be_read_blocks_the_send(on, monkeypatch):
    d = alert_send.bind_secret(dest(secret="NTFY_LAB"))
    result, resolver, transport = go(d)
    assert result["outcome"] == "blocked" and "ATLAS_ALERT_SECRET_NTFY_LAB" in result["why"]
    assert resolver.calls == [] and transport.calls == []
    monkeypatch.setenv("ATLAS_ALERT_SECRET_NTFY_LAB", "two\nlines")
    assert go(d)[0]["outcome"] == "blocked"


def test_a_secret_is_bound_to_its_origin(on, monkeypatch):
    monkeypatch.setenv("ATLAS_ALERT_SECRET_NTFY_LAB", SECRET)
    d = alert_send.bind_secret(dest(secret="NTFY_LAB"))
    assert d["secret_origin"] == "https://ntfy.example:443"
    # `https://h/` and `https://h:443/` are the same origin
    same = dict(d, url="https://ntfy.example:443/other-topic")
    assert alert_send.secret_for(same) == SECRET
    # the URL moves host: the stored binding no longer matches
    moved = dict(d, url="https://hook.example/atlas")
    assert alert_send.secret_for(moved) is None
    result, resolver, _ = go(dict(moved, kind="webhook"))
    assert result["outcome"] == "blocked" and resolver.calls == []
    # and unbind_if_moved clears it, with a note
    out, note = alert_send.unbind_if_moved(d, moved)
    assert out["secret_origin"] is None and "NTFY_LAB" in note
    assert alert_send.secret_for(out) is None
    # a move inside the origin keeps it, with no note
    out, note = alert_send.unbind_if_moved(d, same)
    assert out["secret_origin"] == "https://ntfy.example:443" and note is None
    # a binding the caller supplies is not taken
    forged = dict(moved, secret_origin="https://hook.example:443")
    out, _ = alert_send.unbind_if_moved(d, forged)
    assert out["secret_origin"] is None
    # naming it again binds it to the new place
    assert alert_send.secret_for(alert_send.bind_secret(moved)) == SECRET


def test_bind_without_a_secret_binds_nothing(on):
    assert alert_send.bind_secret(dest())["secret_origin"] is None


# ── the delivery log ────────────────────────────────────────────────────────

def _iso(days_ago):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_log_is_0600_and_newest_first(on):
    path = str(on / "log.jsonl")
    for i in range(3):
        assert alert_send.log_delivery({"rule": f"r{i}", "destination": "Lab phone",
                                        "events": [i], "outcome": "delivered",
                                        "status": 200, "why": None}, path=path)
    rows = alert_send.read_deliveries(path=path)
    assert [r["rule"] for r in rows] == ["r2", "r1", "r0"]
    assert rows[0] == {"at": rows[0]["at"], "rule": "r2", "destination": "Lab phone",
                       "events": [2], "outcome": "delivered", "status": 200, "why": None}
    assert len(alert_send.read_deliveries(limit=2, path=path)) == 2
    if sys.platform != "win32":
        assert os.stat(path).st_mode & 0o777 == 0o600


def test_log_prunes_at_90_days(on):
    path = str(on / "log.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for days, rule in ((120, "ancient"), (91, "old"), (89, "recent")):
            fh.write(json.dumps({"at": _iso(days), "rule": rule, "destination": "d",
                                 "events": [], "outcome": "delivered", "status": 200,
                                 "why": None}) + "\n")
    alert_send.log_delivery({"rule": "now", "destination": "d", "outcome": "refused",
                             "status": 500}, path=path)
    assert [r["rule"] for r in alert_send.read_deliveries(path=path)] == ["now", "recent"]


def test_log_never_raises(on, tmp_path):
    assert alert_send.log_delivery({"outcome": "delivered"},
                                   path=str(tmp_path / "missing" / "dir" / "x.jsonl")) is True
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    assert alert_send.log_delivery({"outcome": "delivered"},
                                   path=str(blocker / "x.jsonl")) is False


def test_the_rate_limit_lives_in_the_alert_state_not_here():
    # one limit, one place (2026-11-13): the tick's ledger (tests in
    # test_alerts_rules.py); the sender's log-reading copy had no caller
    assert not hasattr(alert_send, "rate_allows")


# ── the default transport, against a stub on the loopback address ──────────
#
# Called directly, never through `send` (which refuses loopback, as it must).

class _Stub(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length") or 0)
        self.server.seen.append({"path": self.path, "headers": dict(self.headers),
                                 "body": self.rfile.read(size)})
        status = self.server.status
        self.send_response(status)
        if 300 <= status < 400:
            self.send_header("Location", "/elsewhere")
        payload = b"y" * self.server.size
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except OSError:
            pass

    def log_message(self, *a):
        pass


def _serve(status=200, size=10, context=None):
    server = http.server.HTTPServer(("127.0.0.1", 0), _Stub)
    server.seen, server.status, server.size = [], status, size
    if context is not None:
        server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _call(server, host="alerts.example", scheme="http", **kw):
    port = server.server_address[1]
    return alert_send.default_transport(
        address="127.0.0.1", port=port, scheme=scheme, host=host, path="/topic",
        headers={"Host": f"{host}:{port}", "Content-Type": "text/plain"},
        body=b"hello", **kw)


def test_default_transport_posts_with_the_original_host_and_no_redirect():
    server = _serve(status=302)
    try:
        resp = _call(server)
        assert resp.status == 302
        resp.read(1024)
        resp.close()
        assert len(server.seen) == 1                      # /elsewhere never asked
        seen = server.seen[0]
        assert seen["path"] == "/topic" and seen["body"] == b"hello"
        assert seen["headers"]["Host"] == f"alerts.example:{server.server_address[1]}"
    finally:
        server.shutdown()


def test_default_transport_reads_no_more_than_asked():
    server = _serve(size=200_000)
    try:
        resp = _call(server)
        assert len(resp.read(alert_send.MAX_READ)) == alert_send.MAX_READ
        resp.close()
    finally:
        server.shutdown()


def test_default_transport_has_a_wall_clock_deadline():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    stop = threading.Event()

    def drip():
        conn, _ = listener.accept()
        conn.recv(65536)
        try:
            while not stop.is_set():          # one byte a little faster than any timeout
                conn.sendall(b"H")
                time.sleep(0.1)
        except OSError:
            pass
        finally:
            conn.close()

    threading.Thread(target=drip, daemon=True).start()
    started = time.monotonic()
    try:
        with pytest.raises(Exception) as caught:
            alert_send.default_transport(
                address="127.0.0.1", port=listener.getsockname()[1], scheme="http",
                host="alerts.example", path="/", headers={"Host": "alerts.example"},
                body=b"x", connect_timeout=0.5, total_timeout=0.6)
        assert time.monotonic() - started < 3
        assert alert_send._why(caught.value, True) == "timed out"
    finally:
        stop.set()
        listener.close()


@pytest.fixture(scope="module")
def tls_files(tmp_path_factory):
    crypto = pytest.importorskip("cryptography")  # noqa: F841
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "alerts.example")])
    now = datetime.datetime.now(datetime.timezone.utc)
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("alerts.example")]),
                           critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True,
                                         crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False,
                                         decipher_only=False), critical=True)
            .add_extension(ski, critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ski),
                           critical=False)
            .sign(key, hashes.SHA256()))
    folder = tmp_path_factory.mktemp("tls")
    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return str(cert_path), str(key_path)


def _tls_server(tls_files, names):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(*tls_files)
    context.sni_callback = lambda sock, name, ctx: names.append(name)
    return _serve(context=context)


def test_default_transport_tls_names_the_host_not_the_address(tls_files):
    names = []
    server = _tls_server(tls_files, names)
    try:
        resp = _call(server, scheme="https", ca_certs=tls_files[0])
        assert resp.status == 200
        resp.close()
        assert names == ["alerts.example"]                 # SNI is the name
        assert server.seen[0]["headers"]["Host"].startswith("alerts.example:")
    finally:
        server.shutdown()


def test_default_transport_tls_refuses_a_certificate_for_another_name(tls_files):
    server = _tls_server(tls_files, [])
    try:
        with pytest.raises(Exception) as caught:
            _call(server, host="other.example", scheme="https", ca_certs=tls_files[0])
        assert alert_send._why(caught.value, False) == "the certificate did not verify"
        assert server.seen == []
    finally:
        server.shutdown()


def test_default_transport_tls_refuses_an_untrusted_certificate(tls_files):
    server = _tls_server(tls_files, [])
    try:
        with pytest.raises(Exception) as caught:
            _call(server, scheme="https")                  # the stub's CA is not trusted
        assert alert_send._why(caught.value, False) == "the certificate did not verify"
    finally:
        server.shutdown()
