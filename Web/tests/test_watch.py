"""THE WATCH (2026-11-15): Atlas's own checks, each on its own schedule.

What is held here:

* CHARTED ONLY: a check is asked because the map charts it — a service's
  address, or a `check` on a service or a place — and never a link-local or
  metadata address. Kuma's monitor stands where it watches.
* EACH KIND JUDGED: http by its status (or the statuses it lists), tcp by a
  port answering, dns by a name resolving (to an address, if one is given),
  keyword by the text on the page, json by a value at a path. The body is
  read only by keyword and json, and only so much of it.
* SCHEDULED: only what is due is asked; a failure is believed after its
  retries, asked again 20 s apart meanwhile; past the map's rate every
  interval stretches, and the log says so once.
* A PLACE'S OWN CHECK decides its marker; without one, its services do.
* WHAT THE WIRE SHOWED: an https answer's certificate end date is kept.

Every name and address is invented (RFC 5737 and private ranges). Nothing here
reaches another host: the probes are replaced, or ask this machine's loopback.
"""

import datetime
import json
import logging
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import validation  # noqa: E402
import watch as W  # noqa: E402


def _place(pid="box", ip="192.0.2.10", links=(), **own):
    return {"id": pid, "ip": ip, "links": list(links), **own}


def _keys(ts):
    return [(t.ckey, t.type, t.url or f"{t.host}:{t.port}") for t in ts]


# ── charted only ────────────────────────────────────────────────────────────

def test_a_service_address_is_an_http_check_and_a_check_names_another_kind():
    data = {"nodes": [_place(links=[
        {"label": "Wiki", "url": "http://192.0.2.10:8080/"},
        {"label": "LDAPS", "check": "tcp", "check_port": 636},
        {"label": "Name", "check": "dns", "check_host": "wiki.example"},
        {"label": "Health", "url": "https://192.0.2.10/health", "check": "json", "check_expect": "ok=true"},
        {"label": "Quiet", "url": "http://192.0.2.10:9000/", "check": "off"},
    ])]}
    assert _keys(W.targets(data)) == [
        ("s:box/Wiki", "http", "http://192.0.2.10:8080/"),
        ("s:box/LDAPS", "tcp", "192.0.2.10:636"),
        ("s:box/Name", "dns", "wiki.example:0"),
        ("s:box/Health", "json", "https://192.0.2.10/health"),
    ]


def test_a_tcp_check_takes_its_port_from_the_address_and_needs_one():
    data = {"nodes": [_place(links=[
        {"label": "Web", "url": "https://192.0.2.10/", "check": "tcp"},
        {"label": "Odd", "url": "http://192.0.2.10:8081/x", "check": "tcp"},
        {"label": "Nothing", "check": "tcp"},
    ])]}
    assert _keys(W.targets(data)) == [("s:box/Web", "tcp", "192.0.2.10:443"),
                                      ("s:box/Odd", "tcp", "192.0.2.10:8081")]


def test_kuma_stands_where_it_watches():
    data = {"nodes": [
        _place("watched", links=[{"label": "A", "url": "http://192.0.2.11/"}], check="tcp", check_port=22),
        _place("mixed", links=[{"label": "Named", "url": "http://192.0.2.12/", "kuma": "Named monitor"},
                               {"label": "Plain", "url": "http://192.0.2.12:81/"}]),
    ], "signals": {"kuma": {"Watched monitor": "watched"}}}
    ts = W.targets(data)
    assert [t.ckey for t in ts] == ["s:watched/A", "s:mixed/Plain"]
    assert [t.rolls_up for t in ts] == [False, True], "a watched place takes no state from here"


def test_nothing_planned_unmanaged_or_metadata_is_asked():
    data = {"nodes": [
        _place("later", planned=True, links=[{"label": "A", "url": "http://192.0.2.20/"}]),
        _place("idle", unmanaged=True, links=[{"label": "A", "url": "http://192.0.2.21/"}]),
        _place("box", links=[
            {"label": "Off", "url": "http://192.0.2.22/", "unmanaged": True},
            {"label": "Meta", "check": "tcp", "check_host": "169.254.169.254", "check_port": 80},
            {"label": "Cloud", "url": "http://[fd00:ec2::254]/"},
            {"label": "Zero", "check": "dns", "check_host": "0.0.0.1"},
            {"label": "Fine", "url": "http://192.0.2.23/"},
        ]),
    ]}
    assert [t.ckey for t in W.targets(data)] == ["s:box/Fine"]


def test_a_place_is_asked_only_with_a_check_of_its_own():
    data = {"nodes": [_place("plain"), _place("own", check="tcp", check_port=22),
                      _place("web", check="http", check_host="https://192.0.2.10/status"),
                      _place("network", ip="10.0.0.0/24", check="tcp", check_port=22)]}
    assert _keys(W.targets(data)) == [("p:own", "tcp", "192.0.2.10:22"),
                                      ("p:web", "http", "https://192.0.2.10/status")]


def test_settings_out_of_range_are_brought_into_range():
    spec = W.spec_of({"check": "tcp", "check_every": 5, "check_retries": 99, "check_timeout": 0.1,
                      "check_port": 70000, "check_expect": "x" * 500})
    assert (spec["every"], spec["retries"], spec["timeout"], spec["port"]) == (20, 5, 1.0, 0)
    assert len(spec["expect"]) == 200
    spec = W.spec_of({"check": "ping", "check_every": True, "check_retries": "2"})
    assert (spec["type"], spec["every"], spec["retries"]) == ("", 60, 1)


def test_the_map_editor_says_what_a_check_lacks():
    data = {"nodes": [
        {"id": "box", "ip": "192.0.2.10", "links": [
            {"label": "LDAPS", "check": "tcp", "check_port": 636},
            {"label": "Bare"},
            {"label": "KW", "url": "http://192.0.2.10/", "check": "keyword"},
            {"label": "J", "url": "http://192.0.2.10/", "check": "json", "check_expect": "healthy"},
            {"label": "Meta", "check": "tcp", "check_host": "169.254.169.254", "check_port": 80},
            {"label": "Named", "url": "http://192.0.2.10/", "kuma": "M", "check": "keyword"}]},
        {"id": "gw", "check": "tcp"},
    ]}
    problems = []
    validation._check_watch(problems, data)
    # a link that names a Kuma monitor is Kuma's: its check settings are not judged
    assert problems == [
        "node 'box': service 'Bare' needs a url, or a tcp or dns check",
        "node 'box': service 'KW': its check needs the text it expects",
        "node 'box': service 'J': its check needs what it expects as path=value",
        "node 'box': service 'Meta': its check may not ask a link-local or metadata address",
        "node 'gw': its check needs an address or a name to ask",
    ]


def test_the_tracked_map_still_validates():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "Data", "lab-data.json")
    if not os.path.exists(path):
        pytest.skip("the tracked map is not in this tree")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    problems = []
    validation._check_watch(problems, data)
    assert problems == []


# ── each kind judged ────────────────────────────────────────────────────────

def _t(**kw):
    base = dict(ckey="s:k", key="k", kind="service", place="box", type="http")
    base.update(kw)
    return W.Target(**base)


class _Raw:
    def __init__(self, body):
        self.body = body.encode()
        self.asked = None

    def read(self, n, decode_content=True):
        self.asked = n
        return self.body[:n]


class _Answer:
    def __init__(self, status, body=""):
        self.status_code = status
        self.raw = _Raw(body)
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def answer(monkeypatch):
    import requests
    box = {"answer": _Answer(200), "kw": None}

    def get(url, **kw):
        box["kw"] = kw
        what = box["answer"]
        if isinstance(what, BaseException):
            raise what
        return what
    monkeypatch.setattr(requests, "get", get)
    return box


def test_http_lists_the_statuses_it_takes(answer):
    t = _t(url="http://192.0.2.10/", expect="200-299, 401")
    for status, want in ((204, "healthy"), (401, "healthy"), (302, "down"), (503, "down")):
        answer["answer"] = _Answer(status)
        assert W.probe(t)[0] == want, status
    answer["answer"] = _Answer(503)
    assert W.probe(_t(url="http://192.0.2.10/"))[0] == "degraded", "no list: the old rule"


def test_keyword_and_json_read_only_so_much_of_the_body(answer):
    page = "<html>" + "x" * 70000 + "all systems go</html>"
    answer["answer"] = _Answer(200, "<p>all systems go</p>")
    assert W.probe(_t(type="keyword", url="http://192.0.2.10/", expect="systems go"))[0] == "healthy"
    answer["answer"] = _Answer(200, page)
    assert W.probe(_t(type="keyword", url="http://192.0.2.10/", expect="systems go"))[0] == "down"
    assert answer["answer"].raw.asked == W.BODY_MAX, "past 64 KB is never read"
    answer["answer"] = _Answer(500, "systems go")
    assert W.probe(_t(type="keyword", url="http://192.0.2.10/", expect="systems go"))[0] == "down"

    body = json.dumps({"status": {"healthy": True, "count": 3, "name": "ok"}, "list": [{"v": 1}]})
    for expect, want in (("status.healthy=true", "healthy"), ("status.count=3", "healthy"),
                         ("status.name=ok", "healthy"), ("list.0.v=1", "healthy"),
                         ("status.healthy=false", "down"), ("status.gone=1", "down"), ("nonsense", "down")):
        answer["answer"] = _Answer(200, body)
        assert W.probe(_t(type="json", url="http://192.0.2.10/", expect=expect))[0] == want, expect
    answer["answer"] = _Answer(200, "not json")
    assert W.probe(_t(type="json", url="http://192.0.2.10/", expect="a=1"))[0] == "down"


def test_an_http_check_still_sends_nothing_and_follows_nothing(answer):
    W.probe(_t(url="http://192.0.2.10/", timeout=4.0))
    kw = answer["kw"]
    assert (kw["allow_redirects"], kw["verify"], kw["stream"], kw["timeout"]) == (False, False, True, 4.0)
    assert kw["headers"] == {"User-Agent": "Atlas-check"} and "auth" not in kw


def test_tcp_asks_a_port_once():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert W.probe(_t(type="tcp", host="127.0.0.1", port=port, timeout=2.0))[0] == "healthy"
    finally:
        server.close()
    assert W.probe(_t(type="tcp", host="127.0.0.1", port=port, timeout=1.0))[0] == "down"


def test_dns_resolves_and_may_expect_an_address(monkeypatch):
    def fake(host, port):
        if host == "gone.example":
            raise socket.gaierror("no such name")
        return [(2, 1, 6, "", ("192.0.2.30", 0)), (2, 1, 6, "", ("192.0.2.31", 0))]
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    assert W.probe(_t(type="dns", host="wiki.example"))[0] == "healthy"
    assert W.probe(_t(type="dns", host="wiki.example", expect="192.0.2.31"))[0] == "healthy"
    assert W.probe(_t(type="dns", host="wiki.example", expect="192.0.2.99"))[0] == "down"
    assert W.probe(_t(type="dns", host="gone.example"))[0] == "down"


def test_a_certificate_says_when_it_ends_who_signed_it_and_its_names():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "wiki.example")])
    issuer = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Invented CA")])
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(issuer).public_key(key.public_key())
            .serial_number(7).not_valid_before(start).not_valid_after(start + datetime.timedelta(days=90))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("wiki.example"),
                                                        x509.DNSName("*.wiki.example")]), critical=False)
            .sign(key, hashes.SHA256()))
    der = cert.public_bytes(serialization.Encoding.DER)
    assert W.certificate(der) == {"expires": "2026-04-01", "issuer": "Invented CA",
                                  "names": ["wiki.example", "*.wiki.example"]}
    assert W.certificate(b"not a certificate") == {} and W.certificate(None) == {}


# ── scheduled ───────────────────────────────────────────────────────────────

def test_a_failure_is_believed_after_its_retries():
    t = _t(retries=2)
    e = W.judge(None, t, ("healthy", 5, {}), 1000)
    assert e["state"] == "healthy" and e["fails"] == 0
    e = W.judge(e, t, ("down", 5, {}), 1010)
    e = W.judge(e, t, ("down", 5, {}), 1030)
    assert e["state"] == "healthy" and e["fails"] == 2, "still within its retries"
    assert W.due_at(e, t) == 1030 + 20, "a retry comes 20 s later"
    e = W.judge(e, t, ("down", 5, {}), 1050)
    assert e["state"] == "down" and e["since"] == 1050
    assert W.due_at(e, t) == 1050 + 60, "believed: back to its interval"
    e = W.judge(e, t, ("healthy", 4, {}), 1110)
    assert (e["state"], e["fails"], e["since"]) == ("healthy", 0, 1110)
    e = W.judge(e, t, (None, 4, {}), 1170)
    assert e["state"] == "healthy" and e["asked"] == 1170, "no answer says nothing"


def test_only_what_is_due_is_asked_and_unanswered_waits_its_interval(tmp_path, monkeypatch):
    asked = []

    def probe(t):
        asked.append(t.key)
        return (None, 1, {}) if t.key == "box/Slow" else ("healthy", 1, {})
    monkeypatch.setattr(W, "probe", probe)
    data = {"nodes": [_place(links=[{"label": "Fast", "url": "http://192.0.2.10/", "check_every": 20},
                                    {"label": "Slow", "url": "http://192.0.2.10:81/"}])]}
    path = str(tmp_path / "checks.json")
    W.tick(data, path, now=1000)
    assert sorted(asked) == ["box/Fast", "box/Slow"]
    asked.clear()
    W.tick(data, path, now=1025)
    assert asked == ["box/Fast"], "the slow one waits its 60 s, answered or not"
    asked.clear()
    W.tick(data, path, now=1061)
    assert sorted(asked) == ["box/Fast", "box/Slow"]


def test_past_the_rate_every_interval_is_stretched_and_the_log_says_so_once(monkeypatch, caplog):
    monkeypatch.setenv("ATLAS_CHECKS_PER_MINUTE", "60")
    W._stretch_logged[0] = None
    ts = [_t(ckey=f"s:{i}", key=str(i), every=20) for i in range(40)]   # 120 a minute
    with caplog.at_level(logging.WARNING, logger="atlas.live.watch"):
        assert W.stretch(ts) == 2.0
        assert W.stretch(ts) == 2.0
    said = [r for r in caplog.records if "stretched" in r.getMessage()]
    assert len(said) == 1 and "120" in said[0].getMessage()
    assert W.due_at({"asked": 1000, "fails": 0}, ts[0], 2.0) == 1040
    assert W.stretch(ts[:10]) == 1.0


def test_a_check_no_longer_charted_is_dropped_from_the_store(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "probe", lambda t: ("healthy", 1, {}))
    path = str(tmp_path / "checks.json")
    two = {"nodes": [_place(links=[{"label": "A", "url": "http://192.0.2.10/"},
                                   {"label": "B", "url": "http://192.0.2.10:81/"}])]}
    W.tick(two, path, now=1000)
    one = {"nodes": [_place(links=[{"label": "A", "url": "http://192.0.2.10/"}])]}
    W.tick(one, path, now=1001)
    assert set(W.load(path)["checks"]) == {"s:box/A"}


def test_a_store_from_before_schedules_reads_as_empty(tmp_path):
    (tmp_path / "checks.json").write_text(json.dumps({"at": 5, "services": {}, "nodes": {}}), encoding="utf-8")
    assert W.load(str(tmp_path / "checks.json")) == {"v": 2, "at": None, "checks": {}}


def test_the_thread_is_off_at_zero(monkeypatch):
    monkeypatch.setenv("ATLAS_CHECKS_POLL", "0")
    assert W.poll_every() == 0 and W.start(object()) is None
    monkeypatch.setenv("ATLAS_CHECKS_POLL", "1")
    assert W.poll_every() == W.POLL
    monkeypatch.setenv("ATLAS_CHECKS_POLL", "junk")
    assert W.poll_every() == W.POLL


# ── a place's own check, and what the wire showed ───────────────────────────

def test_a_place_with_its_own_check_is_decided_by_it_alone():
    data = {"nodes": [_place("own", check="tcp", check_port=22,
                             links=[{"label": "Web", "url": "http://192.0.2.10/"}]),
                      _place("rolled", ip="192.0.2.11", links=[{"label": "Web", "url": "http://192.0.2.11/"}])]}
    ts = W.targets(data)
    store = {"checks": {
        "p:own": {"state": "healthy", "asked": 1000, "heard": 1000},
        "s:own/Web": {"state": "down", "asked": 1000, "heard": 1000, "ms": 9},
        "s:rolled/Web": {"state": "down", "asked": 1000, "heard": 1000, "ms": 9},
    }}
    feed = W.as_feed(store, ts, now=1010, factor=1.0)
    assert feed["nodes"] == {"own": {"state": "healthy"}, "rolled": {"state": "down"}}
    assert feed["services"]["own/Web"] == {"state": "down", "ms": 9}
    assert W.as_feed(store, ts, now=1000 + 301, factor=1.0) == {"services": {}, "nodes": {}}, "too old to serve"


def test_an_https_check_reads_its_certificate_at_most_every_six_hours(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "probe", lambda t: ("healthy", 3, {}))
    read = []

    def peer(t):
        read.append(t.key)
        return {"expires": "2026-12-17", "issuer": "Invented CA", "names": ["wiki.example"]}
    monkeypatch.setattr(W, "peer_certificate", peer)
    data = {"nodes": [_place(links=[{"label": "Wiki", "url": "https://192.0.2.10/"},
                                    {"label": "Plain", "url": "http://192.0.2.10:81/"}])]}
    path = str(tmp_path / "checks.json")
    W.tick(data, path, now=1000)
    assert read == ["box/Wiki"], "plain http has no certificate"
    entry = W.load(path)["checks"]["s:box/Wiki"]
    assert entry["tls"]["expires"] == "2026-12-17" and entry["tls_at"] == 1000
    assert entry["state"] == "healthy"
    W.tick(data, path, now=1100)
    assert read == ["box/Wiki"], "not again within six hours"
    W.tick(data, path, now=1000 + W.TLS_EVERY + 60)
    assert read == ["box/Wiki", "box/Wiki"]
    feed = W.as_feed(W.load(path), W.targets(data), now=1000 + W.TLS_EVERY + 61)
    assert feed["services"]["box/Wiki"]["tls"]["issuer"] == "Invented CA"


def test_a_certificate_is_read_by_a_handshake_that_sends_nothing(monkeypatch):
    import ssl
    seen = {}

    class Raw:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Tls(Raw):
        def getpeercert(self, binary_form=False):
            seen["binary"] = binary_form
            return b"der"

    def connect(where, timeout):
        seen["where"], seen["timeout"] = where, timeout
        return Raw()

    def wrap(self, raw, server_hostname=None):
        seen["sni"], seen["verify"] = server_hostname, self.verify_mode
        return Tls()
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    monkeypatch.setattr(W, "certificate", lambda der: {"expires": "2026-12-17"} if der == b"der" else {})
    assert W.peer_certificate(_t(url="https://wiki.example:8443/x", timeout=2.0)) == {"expires": "2026-12-17"}
    assert seen == {"where": ("wiki.example", 8443), "timeout": 2.0, "sni": "wiki.example",
                    "verify": ssl.CERT_NONE, "binary": True}
    W.peer_certificate(_t(url="https://192.0.2.10/"))
    assert seen["sni"] is None and seen["where"] == ("192.0.2.10", 443), "no name to send for an address"
    assert W.peer_certificate(_t(url="http://192.0.2.10/")) == {}



# ── what the first review of A1–A3 found (2026-11-15) ────────────────────────

def test_a_check_that_stops_answering_is_unknown_not_its_last_word(tmp_path, monkeypatch):
    answers = iter([("healthy", 1, {})] + [(None, 1, {})] * 50)
    monkeypatch.setattr(W, "probe", lambda t: next(answers))
    data = {"nodes": [_place(links=[{"label": "Web", "url": "http://192.0.2.10/"}])]}
    path = str(tmp_path / "checks.json")
    for minute in range(10):
        W.tick(data, path, now=1000 + 60 * minute)
    feed = W.as_feed(W.load(path), W.targets(data), now=1000 + 60 * 9, factor=1.0)
    assert feed == {"services": {}, "nodes": {}}, "nine minutes without a word is unknown"


def test_a_run_of_slow_checks_cannot_starve_the_rest(tmp_path, monkeypatch):
    import threading
    gate = threading.Event()
    asked = []

    def probe(t):
        asked.append(t.key)
        if int(t.key.split("/S")[1]) < 8:
            gate.wait(5)
        return ("healthy", 1, {})
    monkeypatch.setattr(W, "probe", probe)
    data = {"nodes": [_place(links=[{"label": f"S{i:02d}", "url": f"http://192.0.2.10:{8000 + i}/"}
                                    for i in range(20)])]}
    path = str(tmp_path / "checks.json")
    try:
        for r in range(4):
            W.tick(data, path, now=1000 + r, budget=0.3)
    finally:
        gate.set()
    assert len(set(asked)) == 20, sorted(set(asked))


def test_without_a_writable_directory_the_schedule_still_holds(tmp_path, monkeypatch):
    import filelock

    def refuse(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(filelock, "exclusive", refuse)
    asked = []
    monkeypatch.setattr(W, "probe", lambda t: asked.append(t.key) or ("down", 1, {}))
    data = {"nodes": [_place(links=[{"label": "Web", "url": "http://192.0.2.10/", "check_every": 3600}])]}
    path = str(tmp_path / "ro" / "checks.json")
    for now in (1000, 1005, 1010, 1021, 1030):
        store = W.tick(data, path, now=now)
    assert len(asked) == 2, "asked, then once more after its retry, and not again inside the hour"
    assert store["checks"]["s:box/Web"]["state"] == "down", "the retry was counted: it is believed"


def test_a_bare_number_or_a_name_that_resolves_to_a_metadata_address_is_never_asked(monkeypatch):
    for host in ("2852039166", "0xa9.0xfe.0xa9.0xfe", "0251.0376.0251.0376", "169.254.43518", "[fe80::1]"):
        assert W.refused_host(host), host
    for host in ("192.0.2.10", "wiki.example", "cafe.example", "10.0.0.1"):
        assert not W.refused_host(host), host
    real = socket.getaddrinfo

    def resolve(host, port, *a, **k):
        if host == "sneaky.example":
            return [(2, 1, 6, "", ("169.254.169.254", port or 0))]
        return real(host, port, *a, **k)
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("a refused address was asked"))
    assert W.probe(_t(url="http://sneaky.example/"))[0] is None
    assert W.probe(_t(type="tcp", host="sneaky.example", port=80))[0] is None
    assert W.peer_certificate(_t(url="https://sneaky.example/")) == {}
    data = {"nodes": [_place(links=[{"label": "N", "check": "tcp", "check_host": "2852039166", "check_port": 80}])]}
    assert W.targets(data) == []


def test_the_check_address_is_asked_before_the_service_address(answer):
    data = {"nodes": [_place(links=[{"label": "Health", "url": "http://192.0.2.10/", "check": "json",
                                     "check_host": "http://192.0.2.10:9000/health", "check_expect": "ok=true"}])]}
    assert W.targets(data)[0].url == "http://192.0.2.10:9000/health"
    problems = []
    validation._check_watch(problems, {"nodes": [_place(links=[
        {"label": "M", "url": "http://192.0.2.10/", "check": "http", "check_host": "http://169.254.169.254/"}])]})
    assert problems == ["node 'box': service 'M': its check may not ask a link-local or metadata address"]


def test_a_certificate_belongs_to_the_address_it_was_read_from(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "probe", lambda t: ("healthy", 1, {}))
    monkeypatch.setattr(W, "peer_certificate",
                        lambda t: {"expires": "2026-12-17", "issuer": "Old CA", "names": ["old.example"]}
                        if "old" in t.url else {})
    path = str(tmp_path / "checks.json")
    old = {"nodes": [_place(links=[{"label": "Web", "url": "https://old.example/"}])]}
    W.tick(old, path, now=1000)
    assert W.as_feed(W.load(path), W.targets(old), now=1001, factor=1.0)["services"]["box/Web"]["tls"]["issuer"] == "Old CA"
    plain = {"nodes": [_place(links=[{"label": "Web", "url": "http://new.example/"}])]}
    feed = W.as_feed(W.load(path), W.targets(plain), now=1001, factor=1.0)
    assert "tls" not in feed["services"]["box/Web"], "the old address's certificate is not this one's"
    moved = {"nodes": [_place(links=[{"label": "Web", "url": "https://new.example/"}])]}
    W.tick(moved, path, now=1000 + 61)
    entry = W.load(path)["checks"]["s:box/Web"]
    assert "tls" not in entry, "a new address with no certificate read drops the old one"


def test_a_blank_url_is_a_left_out_one_for_a_tcp_service():
    data = {"meta": {"title": "x"}, "zones": [], "routes": [], "nodes": [
        {"id": "box", "name": "BOX", "kind": "physical", "ip": "192.0.2.10", "x": 10, "y": 10,
         "links": [{"label": "LDAPS", "url": "", "check": "tcp", "check_port": 636}]}]}
    assert not [p for p in validation.validate(data, strict=True) if "LDAPS" in p or "url" in p]


def test_a_stretched_interval_is_served_as_long_as_it_waits(monkeypatch):
    t = _t(every=60)
    store = {"checks": {"s:k": {"state": "healthy", "heard": 1000, "asked": 1000}}}
    assert W.as_feed(store, [t], now=1000 + 500, factor=6.0)["services"] == {"k": {"state": "healthy"}}
    assert W.as_feed(store, [t], now=1000 + 500, factor=1.0)["services"] == {}


def test_a_viewer_who_sees_less_gets_a_certificate_without_its_names():
    from api.v2 import feeds
    data = {"nodes": [{"id": "open", "links": [{"label": "Web", "url": "https://192.0.2.10/"}]}]}
    feed = {"nodes": {}, "services": {"open/Web": {"state": "healthy", "tls": {
        "expires": "2026-12-17", "issuer": "Invented CA", "names": ["open.example", "secret.example"]}}}}
    seen = feeds._redact_feed(None, feed, [], data=data)["services"]["open/Web"]["tls"]
    assert seen == {"expires": "2026-12-17", "issuer": "Invented CA"}
    everything = feeds._redact_feed(None, feed, None, data=data)["services"]["open/Web"]["tls"]
    assert everything["names"] == ["open.example", "secret.example"]
