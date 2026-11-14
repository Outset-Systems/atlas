"""CERTIFICATES on the server (2026-11-13).

Two things. The days-left rule in `certs.py` is a port of the SEALS scene's
(`static/js/seals.js`), and the first test runs the browser's own function
under node on the same cases, so the two cannot disagree. And a certificate
tied to a place this viewer may not see, by its `place` or in its words, does
not reach that viewer or a token (the 11-12 audit found it reaching both).
"""

import json
import os
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone

import pytest

import viewers

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "accounts"}

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEALS = os.path.join(WEB, "static", "js", "seals.js")

#: What a hand-edited `expires` can hold, and the browser's corners: a year
#: alone, a year and month, a day past the month's end, a signed year, a year
#: Python's `date` cannot hold, the edge of a JavaScript date, a value that is
#: not text, and things that are not dates at all.
EXPIRES = [
    "2026-11-13", "2026-11-14", "2026-11-12", "2026-12-01", "2027-11-13", "2025-01-01",
    "2026", "2026-09", "2026-02-30", "2026-02-29", "2024-02-29", "2026-09-31",
    "2026-13-01", "2026-00-10", "2026-09-00", "2026-9-2", " 2026-09-02", "2026-09-02 ",
    "2026-09-02T10:00", "2026/09/02", "Sep 2 2026", "garbage", "", "20260902",
    "+002026-09-02", "-000001-01-01", "0000-01-01", "9999-12-31", "+275760-09-13",
    "+275760-09-14", "-000000-01-01", "+2026-09-02",
    None, 0, 2026, 2026.0, 2026.5, -2026, True, False, [2026], ["2026-09-02"], [], {},
]

#: Instants to measure from: midnight, exactly noon (a half day rounds up),
#: a millisecond either side of noon, and late in the day.
CLOCKS = [
    datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc),
    datetime(2026, 11, 13, 11, 59, 59, 999000, tzinfo=timezone.utc),
    datetime(2026, 11, 13, 12, 0, 0, 1000, tzinfo=timezone.utc),
    datetime(2026, 11, 13, 23, 30, tzinfo=timezone.utc),
]


def _ms(when):
    return int((when - datetime(1970, 1, 1, tzinfo=timezone.utc)) / timedelta(milliseconds=1))


def _browser_rule():
    """`DAY` and `daysUntil` as seals.js has them, cut from the file itself:
    a copy typed here would prove nothing."""
    with open(SEALS, encoding="utf-8") as fh:
        source = fh.read()
    day = re.search(r"^const DAY = [^;]+;", source, re.M)
    fn = re.search(r"^function daysUntil\(iso\) \{.*?^\}", source, re.M | re.S)
    assert day and fn, "seals.js no longer has `const DAY` and `function daysUntil`"
    return day.group(0) + "\n" + fn.group(0)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_days_left_agrees_with_the_seals_scene():
    import certs
    script = _browser_rule() + """
const input = JSON.parse(process.argv[1]);
const out = [];
for (const now of input.clocks) {
  Date.now = () => now;
  out.push(input.expires.map((x) => daysUntil(x)));
}
process.stdout.write(JSON.stringify(out));
"""
    payload = json.dumps({"clocks": [_ms(c) for c in CLOCKS], "expires": EXPIRES})
    run = subprocess.run(["node", "-e", script, payload], capture_output=True, text=True,
                         timeout=60, check=True)
    browser = json.loads(run.stdout)
    for clock, row in zip(CLOCKS, browser):
        for expires, want in zip(EXPIRES, row):
            got = certs.days_left({"expires": expires}, clock)
            assert got == want, f"expires={expires!r} at {clock.isoformat()}: browser {want}, server {got}"


def test_the_fixtures_reach_every_branch():
    """Guard the guard: the cases above must include lapsed, today, ahead, a
    rolled-over day and no date at all, at a clock where a half day rounds."""
    import certs
    noon = CLOCKS[1]
    got = {e if isinstance(e, str) else repr(e): certs.days_left({"expires": e}, noon) for e in EXPIRES}
    assert got["2026-11-12"] == -1 and got["2025-01-01"] < 0
    assert got["2026-11-14"] == 1          # 1.5 days from noon, after midnight: rounds up
    assert got["2026-11-13"] == 0          # half a day ago rounds to zero, not -1
    assert got["2026-02-30"] == certs.days_left({"expires": "2026-03-02"}, noon)
    assert got["garbage"] is None and got["None"] is None and got["2026"] < 0
    assert got["9999-12-31"] > 0 and got["-000001-01-01"] < 0


def test_days_left_takes_a_date_or_now():
    import certs
    assert certs.days_left({"expires": "2026-12-13"}, date(2026, 11, 13)) == 30
    assert certs.days_left({"expires": "2026-12-13"}, datetime(2026, 11, 13)) == 30   # naive = UTC
    assert certs.days_left({"expires": "nonsense"}) is None
    assert certs.days_left("not a cert") is None


def test_the_nearest_certificate_for_a_place():
    import certs
    today = date(2026, 11, 13)
    pile = [
        {"name": "far", "place": "alpha", "expires": "2027-11-13"},
        {"name": "near", "place": "alpha", "expires": "2026-12-13"},
        {"name": "undated", "place": "alpha", "expires": "soon"},
        {"name": "other", "place": "beta", "expires": "2026-11-14"},
        {"name": "words only", "host": "alpha", "expires": "2026-11-14"},
        "not a cert",
    ]
    assert certs.nearest_for_place(pile, "alpha", today) == {
        "name": "near", "days": 30, "expires": "2026-12-13"}
    lapsed = pile + [{"name": "lapsed", "place": "alpha", "expires": "2026-11-01"}]
    assert certs.nearest_for_place(lapsed, "alpha", today)["name"] == "lapsed"
    assert certs.nearest_for_place([pile[2]], "alpha", today) == {
        "name": "undated", "days": None, "expires": "soon"}
    # a certificate that names a place only in words is not guessed at
    assert certs.nearest_for_place(pile, "gamma", today) is None
    assert certs.nearest_for_place(pile, "", today) is None


# ── the catalogue ────────────────────────────────────────────────────────────

def test_a_certificate_can_name_its_place():
    import schema
    fld = schema.field("certs", "place")
    assert fld["type"] == "ref" and fld["ref"] == "nodes" and not fld["required"]
    assert fld["label"] == "Place" and fld["help"] == "The place this certificate is for"


# ── who sees what ────────────────────────────────────────────────────────────

CERTS = [
    {"name": "alpha.example", "kind": "tls", "issuer": "step-ca", "expires": "2027-01-01",
     "place": "alpha", "host": "Alpha"},
    {"name": "vault.example", "kind": "tls", "issuer": "step-ca", "expires": "2027-01-01",
     "place": "secret-place"},
    {"name": "edge.example", "kind": "tls", "issuer": "step-ca", "expires": "2027-01-01",
     "host": "Secret"},
    {"name": "secret-place.example", "kind": "tls", "issuer": "step-ca", "expires": "2027-01-01"},
    {"name": "wild.example", "kind": "tls", "issuer": "step-ca", "expires": "2027-01-01",
     "note": "also served at 192.0.2.99"},
]


@pytest.fixture
def realm(tmp_path, monkeypatch):
    handle = viewers.build(tmp_path, monkeypatch, viewers.dataset(certs=CERTS))
    yield handle
    monkeypatch.undo()


def _names(body):
    return [c["name"] for c in body.get("certs") or []]


def test_a_certificate_for_a_hidden_place_never_reaches_a_restricted_viewer(realm):
    body = viewers.signed_in(realm, "alice").get("/api/v2/lab-data").get_json()
    assert _names(body) == ["alpha.example"]
    text = json.dumps(body)
    assert "secret-place" not in text and "192.0.2.99" not in text and "vault.example" not in text


def test_nor_a_token(realm):
    body = realm.app.test_client().get("/api/v2/lab-data", headers=viewers.issue(realm)).get_json()
    assert _names(body) == ["alpha.example"]


def test_an_admin_sees_every_certificate(realm):
    body = viewers.signed_in(realm, "ops").get("/api/v2/lab-data").get_json()
    assert _names(body) == [c["name"] for c in CERTS]


def test_a_certificate_with_a_hidden_place_goes_whole_not_blanked():
    """The reference scrub would only blank an optional field inside a place;
    outside `nodes` the place is the certificate's reason to exist."""
    import redaction
    out, _ = redaction.redact(viewers.dataset(certs=CERTS[1:2]), set())
    assert out["certs"] == []



# ── one place, as text (2026-11-13) ──────────────────────────────────────────
#
# `place` had no type check, so a list was saved, and then the overview 500ed
# for everyone and the dataset for every restricted reader and token.

def test_a_list_for_a_certificates_place_is_refused_at_write(realm):
    import dataset
    with realm.app.app_context():
        from context import atlas
        with pytest.raises(dataset.RejectedError) as caught:
            atlas().store.apply([{"op": "insert", "section": "certs", "body": {
                "name": "listed.example", "kind": "tls", "issuer": "step-ca",
                "expires": "2027-01-01", "place": ["alpha"]}}], actor="test")
    assert any("place must be one id, as text" in p for p in caught.value.problems)


def test_a_list_saved_before_the_check_breaks_no_reader(tmp_path, monkeypatch):
    soon = (date.today() + timedelta(days=10)).isoformat()
    old = [{"name": "listed.example", "kind": "tls", "issuer": "step-ca", "expires": soon,
            "place": ["alpha"]},
           {"name": "boxed.example", "kind": "tls", "issuer": "step-ca", "expires": soon,
            "place": {"id": "alpha"}},
           {"name": "inner.example", "kind": "tls", "issuer": "step-ca", "expires": soon,
            "place": ["secret-place"]}]
    handle = viewers.build(tmp_path, monkeypatch, viewers.dataset(certs=old))
    readers = {"alice": (viewers.signed_in(handle, "alice"), {}),
               "ops": (viewers.signed_in(handle, "ops"), {}),
               "token": (handle.app.test_client(), viewers.issue(handle))}
    for who, (client, headers) in readers.items():
        for url in ("/api/v2/lab-data", "/api/v2/overview"):
            r = client.get(url, headers=headers)
            assert r.status_code == 200, (who, url, r.get_data(as_text=True)[:300])
    alice, headers = readers["alice"]
    body = alice.get("/api/v2/lab-data").get_json()
    assert _names(body) == ["listed.example", "boxed.example"]
    assert all("place" not in c for c in body["certs"])
    assert "secret-place" not in json.dumps(body)
    lapsing = alice.get("/api/v2/overview").get_json()["certs"]
    assert [(c["name"], c["place"]) for c in lapsing] == [
        ("boxed.example", None), ("listed.example", None)]
    monkeypatch.undo()
