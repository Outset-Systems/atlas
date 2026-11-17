"""DISCORD, the first kind added after the senders' split (2026-11-16).

A Discord destination's address stops at the webhook's id; the token is the
destination's named secret, put on the end of the path only at send time. What
this holds: the addresses taken and refused, the body (cut to Discord's 2000,
mentions off, no embed), the guard's own look at the request, a send through
`alert_send.send` with the host allowed and not, and the token absent from the
alerts file, the alerts read and the delivery log.

Invented ids and tokens only. Nothing here sends anywhere: `send` is given a
fake resolver and a fake transport, and the route's sender is wrapped to use
them.
"""

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
from senders import discord  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file"}

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ID = "123456789012345678"
TOKEN = "test-token-not-real"
URL = f"https://discord.com/api/webhooks/{ID}"
HOSTS = ("discord.com:443,discordapp.com:443,canary.discord.com:443,ptb.discord.com:443,"
         "hook.example:443,discord.com:80")

SHORT = dict(title="Switch down", body="core-switch is down.", priority="high",
             link=None, tags=["down"])
LINKED = dict(SHORT, link="https://atlas.example/?place=core-switch")


@pytest.fixture
def on(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ALERTS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ALERT_HOSTS", HOSTS, raising=False)
    monkeypatch.setattr(settings, "ALERT_LOG_PATH", str(tmp_path / "deliveries.jsonl"),
                        raising=False)
    monkeypatch.setattr(settings, "HOST", "0.0.0.0")
    monkeypatch.setattr(alert_send, "_machine_addresses", frozenset)
    monkeypatch.setenv("ATLAS_ALERT_SECRET_DISCORD_LAB", TOKEN)
    monkeypatch.delenv("ATLAS_ALERT_SECRET_DISCORD_LAB_FILE", raising=False)
    return tmp_path


def dest(url=URL, secret="DISCORD_LAB", **kw):
    out = {"id": "lab-channel", "name": "Lab channel", "kind": "discord", "url": url,
           "secret": secret, "secret_origin": None}
    out.update(kw)
    return out


def bound(**kw):
    return alert_send.bind_secret(dest(**kw))


def resolver(host, port, *a, **kw):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.30", port))]


class Transport:
    def __init__(self, status=204):
        self.status, self.calls = status, []

    def __call__(self, **kw):
        self.calls.append(kw)
        return types.SimpleNamespace(status=self.status, read=lambda n: b"", close=lambda: None)


def units(text):
    return len(text.encode("utf-16-le")) // 2


def built(message):
    headers, body = alert_send.build_request("discord", message, TOKEN)
    return headers, body, json.loads(body.decode("utf-8"))


# ── the declaration ─────────────────────────────────────────────────────────

def test_discord_is_registered_after_the_three_and_declares_its_form():
    assert senders.kinds()[:4] == ("ntfy", "gotify", "webhook", "discord")
    assert senders.find("discord") is discord and senders.can_send(discord)
    plain = json.load(open(os.path.join(WEB, "themes", "plain.json"), encoding="utf-8"))["text"]
    said = next(d for d in senders.declarations() if d["kind"] == "discord")
    assert said["label"] == plain["alerts_kind_discord"] == "Discord"
    url, secret = said["fields"]
    assert (url["name"], url["type"], url["required"]) == ("url", "url", True)
    assert url["hint_text"] == plain[url["hint"]] and "discord.com:443" in url["hint_text"]
    assert (secret["name"], secret["type"], secret["required"]) == ("secret", "secret-name", True)
    assert secret["hint_text"] == plain[secret["hint"]]
    assert TOKEN not in json.dumps(said) and "secret_use" not in json.dumps(said)


def test_the_kinds_sentence_names_discord(on):
    assert alert_send._kind_words() == "ntfy, gotify, webhook or discord"
    assert "The kind must be ntfy, gotify, webhook or discord." in \
        alert_send.check_destination(dest(kind="email"))


# ── addresses ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    URL, URL + "/",
    f"https://discordapp.com/api/webhooks/{ID}",
    f"https://canary.discord.com/api/webhooks/{ID}",
    f"https://ptb.discord.com/api/webhooks/{ID}",
    f"https://Discord.com:443/api/webhooks/{ID}",
])
def test_a_discord_address_is_taken(on, url):
    assert alert_send.check_destination(dest(url=url)) == []


@pytest.mark.parametrize("url, words", [
    (f"https://hook.example/api/webhooks/{ID}", "A Discord address is on discord.com"),
    (f"https://evil-discord.com/api/webhooks/{ID}", "A Discord address is on discord.com"),
    (f"https://discord.com.evil.example/api/webhooks/{ID}", "A Discord address is on discord.com"),
    (f"{URL}/{TOKEN}", "the token after it goes in a named secret"),
    (f"{URL}/{TOKEN}/github", "A Discord address is https://discord.com/api/webhooks/"),
    (f"https://discord.com/api/v10/webhooks/{ID}", "A Discord address is https://discord.com/api/webhooks/"),
    ("https://discord.com/api/webhooks/not-a-number", "in digits"),
    ("https://discord.com/api/webhooks/", "in digits"),
    ("https://discord.com/", "in digits"),
    (f"{URL}?wait=true", "query string"),
    (f"{URL}?thread_id=1234", "query string"),
    (f"http://discord.com/api/webhooks/{ID}", "starts with https://"),
    (f"https://discord.com:8443/api/webhooks/{ID}", "not in ATLAS_ALERT_HOSTS"),
    (f"https://user:pw@discord.com/api/webhooks/{ID}", "user name or password"),
])
def test_a_wrong_discord_address_is_refused_beside_the_address(on, url, words):
    problems = alert_send.check_destination(dest(url=url))
    assert any(words in p for p in problems), problems
    # each sentence says "address" (the page puts it beside that field) and
    # never quotes the address it refused: a refusal can reach the log
    for p in problems:
        if "Discord" in p:
            assert "address" in p and TOKEN not in p and ID not in p


def test_a_host_discord_serves_is_still_refused_unless_the_operator_lists_it(on, monkeypatch):
    monkeypatch.setattr(settings, "ALERT_HOSTS", "hook.example:443")
    problems = alert_send.check_destination(dest())
    assert any("discord.com:443 is not in ATLAS_ALERT_HOSTS" in p for p in problems)
    monkeypatch.setattr(settings, "ALERT_HOSTS", "")
    assert any("ATLAS_ALERT_HOSTS is empty" in p for p in alert_send.check_destination(dest()))


def test_a_discord_destination_must_name_its_token(on):
    problems = alert_send.check_destination(dest(secret=None))
    assert any("needs a secret" in p for p in problems)
    assert not any("address" in p for p in problems if "needs a secret" in p)


# ── the body ────────────────────────────────────────────────────────────────

def test_a_short_message():
    headers, body, doc = built(SHORT)
    assert headers == {"User-Agent": "Atlas-alerts", "Content-Type": "application/json"}
    assert doc == {"content": "Switch down\n\ncore-switch is down.",
                   "allowed_mentions": {"parse": []}, "flags": 4}
    assert TOKEN not in body.decode("utf-8") and TOKEN not in json.dumps(headers)
    assert "embeds" not in doc


def test_a_message_with_a_link_ends_with_it_on_its_own_line():
    _, _, doc = built(LINKED)
    assert doc["content"] == ("Switch down\n\ncore-switch is down.\n"
                              "https://atlas.example/?place=core-switch")
    _, _, doc = built(dict(LINKED, body=""))
    assert doc["content"] == "Switch down\nhttps://atlas.example/?place=core-switch"


def test_a_message_over_2000_characters_is_cut_in_the_body_and_keeps_its_link():
    _, _, doc = built(dict(LINKED, body="x" * 5000))
    content = doc["content"]
    assert units(content) == discord.CONTENT_MAX
    head, _, tail = content.partition("\n\n")
    assert head == "Switch down"
    assert tail.endswith("x…\nhttps://atlas.example/?place=core-switch")
    # a character outside the BMP is two units: still never over 2000 by either count
    _, body, doc = built(dict(SHORT, body="🙂" * 3000))
    assert units(doc["content"]) <= discord.CONTENT_MAX and doc["content"].endswith("…")
    assert len(body) <= alert_send.MAX_BODY


def test_the_guard_cuts_to_4_kb_after_discords_cut():
    # 2000 characters of three bytes each are over 4 KB: the guard's own cut
    # follows, and the title stays whole
    message = dict(title="T" * 5000, body="ü✓" * 3000, priority="high",
                   link="https://atlas.example/", tags=[f"t{i}" for i in range(50)])
    _, body, doc = built(message)
    assert len(body) <= alert_send.MAX_BODY
    assert units(doc["content"]) <= discord.CONTENT_MAX
    assert doc["content"].startswith("T" * (alert_send.TITLE_MAX - 1) + "…\n\n")
    assert doc["allowed_mentions"] == {"parse": []}


def test_a_link_with_no_room_is_left_out_rather_than_cut():
    long_link = "https://atlas.example/?place=" + "p" * 1960
    _, _, doc = built(dict(SHORT, title="T" * 100, body="b" * 50, link=long_link))
    assert units(doc["content"]) <= discord.CONTENT_MAX
    assert long_link not in doc["content"] and "https://" not in doc["content"]


def test_everyone_and_a_role_are_sent_as_text_and_ping_nobody():
    _, _, doc = built(dict(SHORT, title="@everyone core down", body="<@&123> @here look"))
    assert doc["content"] == "@everyone core down\n\n<@&123> @here look"
    assert doc["allowed_mentions"] == {"parse": []}


def test_an_empty_message_still_says_something():
    _, _, doc = built({})
    assert doc["content"] == discord.EMPTY


def test_the_request_passes_the_guards_own_look():
    for message in (SHORT, LINKED, {}, dict(SHORT, body="x" * 9000)):
        headers, body = alert_send._checked(*alert_send.build_request("discord", message, TOKEN))
        assert isinstance(body, bytes) and len(body) <= alert_send.MAX_BODY


# ── sending ─────────────────────────────────────────────────────────────────

def test_a_send_posts_to_the_id_and_the_token_with_the_host_allowed(on):
    transport = Transport()
    result = alert_send.send(bound(), LINKED, resolver=resolver, transport=transport)
    assert result == {"outcome": "delivered", "status": 204, "why": None}
    call = transport.calls[0]
    assert call["method"] == "POST" and call["scheme"] == "https" and call["port"] == 443
    assert call["host"] == "discord.com" and call["address"] == "192.0.2.30"
    assert call["path"] == f"/api/webhooks/{ID}/{TOKEN}"
    assert call["headers"]["Host"] == "discord.com"
    assert "Authorization" not in call["headers"]
    assert TOKEN not in json.dumps(call["headers"]) and TOKEN.encode() not in call["body"]
    assert json.loads(call["body"])["allowed_mentions"] == {"parse": []}


def test_a_send_with_the_host_not_allowed_is_blocked(on, monkeypatch):
    monkeypatch.setattr(settings, "ALERT_HOSTS", "hook.example:443")
    transport = Transport()
    result = alert_send.send(bound(), SHORT, resolver=resolver, transport=transport)
    assert result["outcome"] == "blocked" and "ATLAS_ALERT_HOSTS" in result["why"]
    assert transport.calls == [] and TOKEN not in json.dumps(result)


@pytest.mark.parametrize("case", ["no secret named", "unset", "not bound", "bad token"])
def test_a_send_without_a_good_token_is_blocked_never_sent_bare(on, monkeypatch, case):
    d = bound()
    if case == "no secret named":            # a hand edit: check_destination refuses it first
        d = dest(secret=None)
    elif case == "unset":
        monkeypatch.delenv("ATLAS_ALERT_SECRET_DISCORD_LAB")
    elif case == "not bound":
        d = dest()
    else:                                     # it would change the path's shape
        monkeypatch.setenv("ATLAS_ALERT_SECRET_DISCORD_LAB", "../../users/@me")
    transport = Transport()
    result = alert_send.send(d, SHORT, resolver=resolver, transport=transport)
    assert result["outcome"] == "blocked" and transport.calls == [], result
    assert "../" not in json.dumps(result)


def test_the_secret_path_rule_and_the_guards_path_rule():
    assert senders.secret_path("discord", f"/api/webhooks/{ID}", TOKEN) == f"/api/webhooks/{ID}/{TOKEN}"
    assert senders.secret_path("discord", f"/api/webhooks/{ID}/", TOKEN) == f"/api/webhooks/{ID}/{TOKEN}"
    for path, secret in ((f"/api/webhooks/{ID}", None), (f"/api/webhooks/{ID}", "a.b"),
                         (f"/api/webhooks/{ID}", "a/b"), (f"/api/webhooks/{ID}", "a?b=1"),
                         ("/elsewhere", TOKEN), (f"/api/webhooks/{ID}/{TOKEN}", TOKEN)):
        assert senders.secret_path("discord", path, secret) is None
    # a kind whose secret goes in a header keeps its path as it is
    assert senders.secret_path("ntfy", "/atlas", "s3cret") == "/atlas"
    # a kind that says its secret goes in the path but has no rule for it is not whole
    half = types.SimpleNamespace(**{k: getattr(discord, k) for k in senders.NEEDS})
    assert not senders.can_send(half)


# ── what a reader sees ──────────────────────────────────────────────────────

def test_the_token_is_never_in_the_alerts_read_the_file_or_the_delivery_log(tmp_path, monkeypatch):
    import alertkit
    import viewers
    monkeypatch.setenv("ATLAS_ALERT_SECRET_DISCORD_LAB", TOKEN)
    handle = alertkit.build(tmp_path, monkeypatch, viewers.dataset(), hosts="discord.com:443")
    monkeypatch.setattr(alert_send, "_machine_addresses", frozenset)
    transport = Transport()
    real = alert_send.send
    monkeypatch.setattr(alert_send, "send", lambda d, m, **kw: real(d, m, resolver=resolver,
                                                                    transport=transport))
    admin = viewers.signed_in(handle, "ops")
    body = admin.get("/api/v2/admin/alerts").get_json()
    lab = {"id": "lab-channel", "name": "Lab channel", "kind": "discord", "url": URL,
           "secret": "DISCORD_LAB"}

    # the address with its token in it is refused, and so never stored
    doc = {**body["doc"], "destinations": [{**lab, "url": f"{URL}/{TOKEN}"}]}
    r = admin.post("/api/v2/admin/alerts", json={"doc": doc, "expect": body["stamp"]},
                   headers=viewers.W)
    assert r.status_code == 422 and TOKEN not in r.get_data(as_text=True)

    doc = {**body["doc"], "destinations": [lab]}
    r = admin.post("/api/v2/admin/alerts", json={"doc": doc, "expect": body["stamp"]},
                   headers=viewers.W)
    assert r.status_code == 200, r.get_json()
    r = admin.post("/api/v2/admin/alerts/destinations/lab-channel/test", json={},
                   headers=viewers.W)
    assert r.get_json() == {"outcome": "delivered", "status": 204, "why": None}
    assert transport.calls[0]["path"] == f"/api/webhooks/{ID}/{TOKEN}"

    read = admin.get("/api/v2/admin/alerts")
    shown = read.get_json()["doc"]["destinations"][0]
    assert shown == {**lab, "secret_bound": True}
    rows = admin.get("/api/v2/admin/alerts/deliveries")
    assert rows.get_json()["deliveries"][0]["outcome"] == "delivered"
    for text in (read.get_data(as_text=True), rows.get_data(as_text=True),
                 (tmp_path / "alerts.json").read_text(encoding="utf-8"),
                 (tmp_path / "alert-deliveries.jsonl").read_text(encoding="utf-8")):
        assert TOKEN not in text
    # the delivery log names the destination, never its address
    assert URL not in (tmp_path / "alert-deliveries.jsonl").read_text(encoding="utf-8")
