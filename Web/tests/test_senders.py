"""THE SENDERS (2026-11-16): each kind of destination declared once in
`Web/senders/`, the guard one path in `alert_send.py`.

What this holds: the registry is whole and in order; each kind builds byte
for byte what `alert_send.build_request` built before the kinds were split
out (the fingerprints below were taken from that code, cut message included);
a made-up fourth kind passes through the same checks, the same guard and the
same `send`, and shows up in the read Settings › Alerts draws from; a kind
whose entry is gone is refused. Nothing here sends anywhere: `send` is given
a fake resolver and a fake transport.
"""

import hashlib
import json
import os
import socket
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alert_send  # noqa: E402
import senders  # noqa: E402
import settings  # noqa: E402
from senders import common  # noqa: E402

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: The three kinds there were before the split, in the order offered.
FIRST = ("ntfy", "gotify", "webhook")
HOSTS = "ntfy.example:443,gotify.example:8080,hook.example:443,pager.example:443"

MESSAGES = {
    "plain": dict(title="Switch down", body="core-switch is down.", priority="default",
                  link="https://atlas.example/?place=core-switch", tags=["warning"]),
    "high": dict(title="Kraków ✓ down\r\nX: 1", body="café is down.", priority="high",
                 link=None, tags=["a,b", "x\r\ny", "warning"]),
    "empty": {},
    # cut to fit: a title past TITLE_MAX, a body past MAX_BODY, tags past TAGS_MAX
    "cut": dict(title="T" * 5000, body="ünïcødé ✓ " * 2000, priority="high",
                link="https://atlas.example/", tags=[f"t{i}" for i in range(50)]),
}

#: (kind, message, secret) -> (fingerprint, body length), from the
#: `build_request` committed before the split (2026-11-16): the sha256 of
#: the headers in order and the body's bytes.
BEFORE = {
    ("ntfy", "plain", None): ("decf6d70fd596079", 20),
    ("ntfy", "plain", "s3cret"): ("d3592f9e860fc524", 20),
    ("ntfy", "high", None): ("e0c773e35e015bba", 14),
    ("ntfy", "high", "s3cret"): ("52c1831ac1085230", 14),
    ("ntfy", "empty", None): ("54e8e168c92a3ae3", 0),
    ("ntfy", "empty", "s3cret"): ("ea5c619b8b3495ae", 0),
    ("ntfy", "cut", None): ("0419a26c4bfa7532", 4095),
    ("ntfy", "cut", "s3cret"): ("58ace48d275eabd9", 4095),
    ("gotify", "plain", None): ("59e5f24a002dd4da", 164),
    ("gotify", "plain", "s3cret"): ("2da28e4eeda8cabc", 164),
    ("gotify", "high", None): ("dc36d3a7551a9ffc", 73),
    ("gotify", "high", "s3cret"): ("ac5b7dc64033b341", 73),
    ("gotify", "empty", None): ("199a45925884a861", 38),
    ("gotify", "empty", "s3cret"): ("205087ea0e2766b3", 38),
    ("gotify", "cut", None): ("f7669ddb626059c0", 4096),
    ("gotify", "cut", "s3cret"): ("976e8f66a66eb442", 4096),
    ("webhook", "plain", None): ("93bf0a9bcd19cf3d", 160),
    ("webhook", "plain", "s3cret"): ("aeb8399f0203405f", 160),
    ("webhook", "high", None): ("8e756f226b76bf69", 133),
    ("webhook", "high", "s3cret"): ("d830278ddc15b0de", 133),
    ("webhook", "empty", None): ("0292d51a1cd3862d", 82),
    ("webhook", "empty", "s3cret"): ("c8254291e2e3e94e", 82),
    ("webhook", "cut", None): ("9d7fceef654885d2", 4096),
    ("webhook", "cut", "s3cret"): ("3d5513176f9bd612", 4096),
}


def fingerprint(headers, body):
    return hashlib.sha256(json.dumps([list(headers.items()), body.hex()]).encode()).hexdigest()[:16]


@pytest.fixture
def on(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ALERTS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ALERT_HOSTS", HOSTS, raising=False)
    monkeypatch.setattr(settings, "ALERT_LOG_PATH", str(tmp_path / "deliveries.jsonl"),
                        raising=False)
    monkeypatch.setattr(settings, "HOST", "0.0.0.0")
    monkeypatch.setattr(alert_send, "_machine_addresses", frozenset)
    return tmp_path


def dest(kind="ntfy", url="https://ntfy.example/atlas", **kw):
    out = {"id": "d1", "name": "Lab phone", "kind": kind, "url": url,
           "secret": None, "secret_origin": None}
    out.update(kw)
    return out


def resolver(host, port, *a, **kw):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.20", port))]


class Transport:
    def __init__(self):
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return types.SimpleNamespace(status=200, read=lambda n: b"", close=lambda: None)


def pager_build(message, secret=None):
    m = alert_send.prepared(message)
    headers = alert_send.base_headers("text/plain; charset=utf-8")
    common.add_secret(headers, PAGER_SECRET, secret)
    return headers, alert_send.plain_body(f"{m.title}: {m.body}")


PAGER_SECRET = {"in": "header", "header": "X-Pager-Key", "prefix": ""}


def registry(monkeypatch, add=None, drop=None):
    """The registry for one test, swapped whole, so its order comes back as it was."""
    table = {k: v for k, v in senders.REGISTRY.items() if k != drop}
    if add is not None:
        table[add.kind or "pager"] = add
    monkeypatch.setattr(senders, "REGISTRY", table)


def pager(**over):
    """A made-up fourth kind, declared the way the three are."""
    entry = types.SimpleNamespace(
        kind="pager", label="A pager",
        fields=(common.url_field("https://pager.example/in"), common.SECRET_FIELD),
        secret_use=PAGER_SECRET,
        check_path=lambda path: ([] if path.startswith("/in/")
                                 else ["A pager address is the server's /in/ and a name."]),
        build=pager_build)
    for k, v in over.items():
        setattr(entry, k, v)
    return entry


# ── the registry ────────────────────────────────────────────────────────────

def test_the_registry_is_whole_and_in_the_order_the_page_offers():
    assert senders.kinds()[:3] == FIRST
    assert alert_send.KINDS == senders.kinds() == tuple(senders.REGISTRY)
    for kind in senders.kinds():
        entry = senders.find(kind)
        assert entry.kind == kind and senders.can_send(entry)
    assert senders.find("email") is None and senders.find(None) is None
    assert senders.find(["ntfy"]) is None


def test_each_kind_declares_what_the_page_asked_before_in_the_same_words():
    """The form the page drew by hand until 2026-11-16, field for field: the
    same label keys, the same plain words as plain.json, the same boxes."""
    plain = json.load(open(os.path.join(WEB, "themes", "plain.json"), encoding="utf-8"))["text"]
    placeholders = {"ntfy": "https://ntfy.example/lab-alerts", "gotify": "https://gotify.example",
                    "webhook": "https://hooks.example/atlas"}
    said = [d for d in senders.declarations() if d["kind"] in FIRST]
    assert [d["kind"] for d in said] == list(FIRST)
    for d in said:
        assert set(d) == {"kind", "label", "fields"}
        assert d["label"] == plain[f"alerts_kind_{d['kind']}"]
        assert [(f["name"], f["type"], f["required"], f["label"]) for f in d["fields"]] == [
            ("url", "url", True, "alerts_f_url"), ("secret", "secret-name", False, "alerts_f_secret")]
        url, secret = d["fields"]
        assert url["placeholder"] == placeholders[d["kind"]] and secret["placeholder"] == "NTFY_LAB"
        assert url["text"] == plain["alerts_f_url"] and secret["text"] == plain["alerts_f_secret"]
        assert secret["hint"] == "alerts_secret_hint" and secret["hint_text"] == plain["alerts_secret_hint"]
    assert "secret_use" not in json.dumps(said) and "Bearer" not in json.dumps(said)


@pytest.mark.parametrize("case", sorted(BEFORE, key=str))
def test_each_kind_builds_byte_for_byte_what_was_built_before(case):
    kind, name, secret = case
    want = BEFORE[case]
    headers, body = senders.find(kind).build(MESSAGES[name], secret)
    assert (fingerprint(headers, body), len(body)) == want
    headers, body = alert_send.build_request(kind, MESSAGES[name], secret)
    assert (fingerprint(headers, body), len(body)) == want
    assert len(body) <= alert_send.MAX_BODY


def test_a_kind_no_entry_declares_is_still_built_as_a_webhook():
    assert alert_send.build_request("email", MESSAGES["plain"]) == \
        alert_send.build_request("webhook", MESSAGES["plain"])


def test_the_path_rules_and_the_saved_address_are_the_kinds_own():
    assert alert_send._path_for("gotify", "/") == "/message"
    assert alert_send._path_for("gotify", "/a/message/") == "/a/message"
    assert alert_send._path_for("ntfy", "/") == "/" and alert_send._path_for("webhook", "/x") == "/x"
    assert senders.rewrites_url("gotify") and not senders.rewrites_url("ntfy")
    # a Gotify address already ending in /message is still written as it is sent
    assert alert_send.normalised(dest("gotify", "https://G.example:443/message"))["url"] == \
        "https://g.example/message"
    assert alert_send.normalised(dest("ntfy", "https://NTFY.example:443/atlas"))["url"] == \
        "https://NTFY.example:443/atlas"


# ── a fourth kind ───────────────────────────────────────────────────────────

def test_a_fourth_kind_passes_through_the_same_checks_guard_and_send(on, monkeypatch):
    registry(monkeypatch, add=pager())
    assert alert_send.KINDS == senders.kinds() and senders.kinds()[-1] == "pager"
    assert alert_send.check_destination(dest("pager", "https://pager.example/in/lab")) == []
    # its own path rule, and the guard's, apply to it as to the others
    assert any("/in/" in p for p in alert_send.check_destination(dest("pager", "https://pager.example/x")))
    for url, words in (("https://elsewhere.example/in/x", "not in ATLAS_ALERT_HOSTS"),
                       ("https://pager.example/in/x?k=1", "query string"),
                       ("https://u:p@pager.example/in/x", "user name or password")):
        assert any(words in p for p in alert_send.check_destination(dest("pager", url)))
    assert "gotify, webhook" in alert_send._kind_words()
    assert f"The kind must be {alert_send._kind_words()}." in alert_send.check_destination(dest("email"))
    assert alert_send._kind_words().endswith(" or pager")

    monkeypatch.setenv("ATLAS_ALERT_SECRET_PAGE", "pager-key")
    d = alert_send.bind_secret(dest("pager", "https://pager.example/in/lab", secret="PAGE"))
    transport = Transport()
    result = alert_send.send(d, MESSAGES["plain"], resolver=resolver, transport=transport)
    assert result == {"outcome": "delivered", "status": 200, "why": None}
    call = transport.calls[0]
    assert call["method"] == "POST" and call["address"] == "192.0.2.20" and call["port"] == 443
    assert call["path"] == "/in/lab" and call["host"] == "pager.example"
    assert call["headers"]["X-Pager-Key"] == "pager-key"
    assert call["headers"]["Host"] == "pager.example"
    assert call["body"] == b"Switch down: core-switch is down."
    assert call["connect_timeout"] == alert_send.CONNECT_S and call["total_timeout"] == alert_send.TOTAL_S


def test_the_guard_looks_at_what_a_kind_built_before_it_leaves(on, monkeypatch):
    big = pager(build=lambda message, secret=None: ({"User-Agent": "x"}, b"x" * (alert_send.MAX_BODY + 1)))
    evil = pager(build=lambda message, secret=None: ({"X-A": "1\r\nX-B: 2"}, b"ok"))
    text = pager(build=lambda message, secret=None: ({"User-Agent": "x"}, "not bytes"))
    path = pager(send_path=lambda p: "//elsewhere.example/x y")
    newline = pager(build=lambda message, secret=None: ({"X-A": "1\n"}, b"ok"))
    tail = pager(send_path=lambda p: "/in/x\n")
    for entry in (big, evil, text, path, newline, tail):
        registry(monkeypatch, add=entry)
        transport = Transport()
        result = alert_send.send(dest("pager", "https://pager.example/in/lab"), MESSAGES["plain"],
                                 resolver=resolver, transport=transport)
        assert result["outcome"] == "blocked" and transport.calls == [], result


def test_a_kind_that_takes_no_secret_is_never_sent_one(on, monkeypatch):
    bare = pager(fields=(common.url_field("https://pager.example/in"),), secret_use={"in": "none"})
    registry(monkeypatch, add=bare)
    assert alert_send.check_destination(dest("pager", "https://pager.example/in/lab")) == []
    problems = alert_send.check_destination(dest("pager", "https://pager.example/in/lab", secret="PAGE"))
    assert any("takes no secret" in p for p in problems)


@pytest.mark.parametrize("over", [
    {"build": None}, {"label": ""}, {"kind": ""}, {"secret_use": {"in": "url"}},
    {"fields": (common.SECRET_FIELD,)},                                  # no address
    {"fields": (common.url_field("x"), {"name": "server", "type": "text"})},  # not stored
    {"fields": (common.url_field("x"),)},                                # asks no secret, sends one
])
def test_a_kind_that_is_not_whole_is_neither_offered_nor_accepted(on, monkeypatch, over):
    entry = pager(**over)
    with pytest.raises(ValueError):
        senders.register(entry)
    registry(monkeypatch, add=entry)
    assert "pager" not in senders.kinds() and senders.find("pager") is None
    assert "pager" not in [d["kind"] for d in senders.declarations()]
    assert "pager" not in alert_send._kind_words()
    assert f"The kind must be {alert_send._kind_words()}." in         alert_send.check_destination(dest("pager", "https://pager.example/in/lab"))


def test_a_kind_whose_entry_is_removed_is_refused(on, monkeypatch):
    before = senders.kinds()
    registry(monkeypatch, drop="gotify")
    assert alert_send.KINDS == tuple(k for k in before if k != "gotify")
    assert "gotify" not in alert_send._kind_words() and "ntfy" in alert_send._kind_words()
    d = dest("gotify", "http://gotify.example:8080")
    assert f"The kind must be {alert_send._kind_words()}." in alert_send.check_destination(d)
    transport = Transport()
    result = alert_send.send(d, MESSAGES["plain"], resolver=resolver, transport=transport)
    assert result["outcome"] == "blocked" and "kind" in result["why"] and transport.calls == []
    assert [k["kind"] for k in senders.declarations()] == list(alert_send.KINDS)


# ── the read Settings › Alerts draws from ───────────────────────────────────

def test_the_alerts_read_carries_the_kinds_and_a_fourth_shows_up(tmp_path, monkeypatch):
    import alertkit
    import viewers
    handle = alertkit.build(tmp_path, monkeypatch, viewers.dataset(),
                            hosts="ntfy.example:443,pager.example:443")
    alertkit.capture(monkeypatch)
    admin = viewers.signed_in(handle, "ops")
    body = admin.get("/api/v2/admin/alerts").get_json()
    assert body["kinds"] == senders.declarations()
    assert [k["kind"] for k in body["kinds"]][:3] == list(FIRST)

    before = [k["kind"] for k in body["kinds"]]
    registry(monkeypatch, add=pager())
    body = admin.get("/api/v2/admin/alerts").get_json()
    assert [k["kind"] for k in body["kinds"]] == before + ["pager"]
    assert body["kinds"][-1]["label"] == "A pager"
    doc = {**body["doc"], "destinations": [{"id": "pg", "name": "Pager", "kind": "pager",
                                            "url": "https://pager.example/in/lab", "secret": None}]}
    r = admin.post("/api/v2/admin/alerts", json={"doc": doc, "expect": body["stamp"]},
                   headers=viewers.W)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["doc"]["destinations"][0]["kind"] == "pager"

    registry(monkeypatch, drop="pager")
    body = admin.get("/api/v2/admin/alerts").get_json()
    assert "pager" not in [k["kind"] for k in body["kinds"]]
    r = admin.post("/api/v2/admin/alerts", json={"doc": body["doc"], "expect": body["stamp"]},
                   headers=viewers.W)
    assert r.status_code == 422 and any(f"The kind must be {alert_send._kind_words()}." in p
                                        for p in r.get_json()["problems"])
