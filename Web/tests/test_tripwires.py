"""TRIPWIRES — the schema, the three payload shapes, the webhook (file
backend), the read model, and who may see any of it.

The db-backend half (site tokens with the `tripwires` scope) is in
`test_tripwires_db.py`. These defend the tripwires design.
"""

import hashlib
import hmac
import json
import os
import subprocess
import sys

import pytest

from appfixture import fresh_app

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(WEB)

import events  # noqa: E402
import schema  # noqa: E402
import tripwires  # noqa: E402
from validation import validate  # noqa: E402

#: Non-empty so conftest restores the Atlas environment after each test; the
#: fixtures below set everything else through monkeypatch.
ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "standalone"}

SECRET = "test-tripwires-secret-0123456789abcdef"
HOOK = "/api/v2/ingest/tripwires"
PW = "correct-horse-battery"

#: The shape every stone had before TRIPWIRES — exactly the old fields.
OLD_STONE = {"id": "nas-restore-share", "name": "Restoration-Keys", "kind": "windows-folder",
             "host": "nas", "zone": "internal", "severity": "critical",
             "placement": "a decoy folder on the file store", "mimics": "the restore keys",
             "retired": False, "note": "collection"}

#: `host` is a reference to a charted place (schema: `ref="nodes"`), so the
#: stones below are validated inside a realm that charts `nas`.
CHARTED = {
    "zones": [{"id": "vault", "name": "The Vault", "vlan": 33, "subnet": "10.77.33.0/24",
               "hue": "#C9A554", "lore": "Where the files sleep.", "label_x": 10, "label_y": 5}],
    "nodes": [{"id": "nas", "name": "NAS", "kind": "physical", "zone": "vault", "x": 10, "y": 10,
               "role": "File store", "lore": "The vault's one keeper."}],
}

STONES = [
    {"id": "canary-fs", "name": "FILESRV-OLD", "kind": "honeypot-host", "zone": "internal",
     "severity": "critical", "sensor": "opencanary-1", "host": "nas"},
    {"id": "canary-fs-smb", "name": "FILESRV-OLD share", "kind": "honeypot-smb",
     "zone": "internal", "severity": "high", "sensor": "opencanary-1:445"},
    {"id": "payroll-doc", "name": "salaries.docx", "kind": "doc-msword", "family": "token",
     "zone": "internal", "severity": "high", "sensor": "tok123abc",
     "planted": "the shared folder", "expires": "2020-01-01"},
    {"id": "cloud-key", "name": "backup.env", "kind": "cloud-key", "zone": "internal",
     "severity": "critical", "expires": "2999-01-01"},
    {"id": "wan-bug", "name": "pixel", "kind": "web-bug", "zone": "wan", "severity": "low"},
    OLD_STONE,
]


def _dataset(stones=STONES):
    return {"meta": {"title": "Test Realm"}, "zones": [],
            "nodes": [{"id": "nas", "name": "NAS", "kind": "physical", "x": 10, "y": 10}],
            "stones": list(stones)}


def _oc(logtype=5000, node="opencanary-1", port=445, **extra):
    """An OpenCanary log record, as sanitizeLog shapes it."""
    rec = {"dst_host": "192.0.2.10", "dst_port": port, "src_host": "198.51.100.7",
           "src_port": 51515, "logtype": logtype, "node_id": node,
           "local_time": "2026-10-18 12:00:00.000000", "utc_time": "2026-10-18 12:00:00.000000",
           "local_time_adjusted": "2026-10-18 07:00:00.000000",
           "logdata": {"FILENAME": "secret.xlsx", "USERNAME": "admin", "PASSWORD": "hunter2"}}
    rec.update(extra)
    return rec


def _ct(token="tok123abc", memo="a reminder", **extra):
    """A Canarytokens generic webhook body (TokenAlertDetails)."""
    body = {"channel": "HTTP", "token_type": "ms_word", "src_ip": "203.0.113.5",
            "src_data": None, "token": token, "time": "2026-10-18 12:00:00 (UTC)",
            "memo": memo, "manage_url": "https://canarytokens.example/manage?token=x&auth=y",
            "additional_data": {"useragent": "Mozilla/5.0", "geo_info": {"country": "XX"}},
            "public_domain": "canarytokens.example"}
    body.update(extra)
    return body


@pytest.fixture
def realm(tmp_path, monkeypatch):
    """A standalone, file-backend Atlas with the webhook on."""
    data = tmp_path / "lab-data.json"
    data.write_text(json.dumps(_dataset()), encoding="utf-8")
    env = {
        "ATLAS_AUTH_MODE": "standalone", "ATLAS_ALLOW_INSECURE": "1",
        "ATLAS_DATA_BACKEND": "file", "ATLAS_DATA": str(data),
        "ATLAS_EVENTS": str(tmp_path / "events.json"),
        "ATLAS_TRIPWIRES_STATE": str(tmp_path / "tripwires.json"),
        "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
        "ATLAS_SIGNALS_SOURCES": "", "ATLAS_FALLBACK": "empty",
        "ATLAS_TRIPWIRES_WEBHOOK": "1", "ATLAS_TRIPWIRES_SECRET": SECRET,
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for k in ("ATLAS_TRIPWIRES_SECRET_FILE", "ATLAS_DECOYS_URL", "ATLAS_DECOYS_KEY",
              "ATLAS_DECOYS_PATH", "ATLAS_READONLY"):
        monkeypatch.delenv(k, raising=False)
    handle = fresh_app()
    tripwires.limiter.reset()
    handle.client = handle.app.test_client()
    return handle


def _key():
    return tripwires.webhook_key(SECRET)


def _post(client, body, *, how="bearer", raw=None, headers=None):
    data = raw if raw is not None else json.dumps(body).encode()
    h = {"Content-Type": "application/json", **(headers or {})}
    url = HOOK
    if how == "bearer":
        h["Authorization"] = f"Bearer {_key()}"
    elif how == "query":
        url = f"{HOOK}?key={_key()}"
    elif how == "sign":
        h["X-Atlas-Signature"] = "sha256=" + hmac.new(SECRET.encode(), data, hashlib.sha256).hexdigest()
    return client.post(url, data=data, headers=h)


def _trip_events():
    return [e for e in events.listing(limit=events.KEEP) if e.get("kind") == "tripwire"]


# ── the schema: extended, never forked ──────────────────────────────────────

def test_an_old_shape_stone_still_validates():
    assert validate({**CHARTED, "stones": [OLD_STONE]}) == []
    # ...and a host that is not charted is a dangling reference, as any other
    assert validate({"stones": [OLD_STONE]}) == ["stone 'nas-restore-share': unknown host 'nas'"]
    assert schema.stone_family(OLD_STONE) == "token"


def test_every_old_kind_is_still_a_kind():
    for kind in ("windows-folder", "network-folder", "web-bug", "dns", "doc-msword",
                 "doc-excel", "doc-pdf", "aws-keys", "ad-account", "sensitive-command",
                 "kubeconfig", "other"):
        assert kind in schema.STONE_KINDS


def test_the_new_fields_validate():
    assert validate({**CHARTED, "stones": STONES}) == []
    fields = {f["name"] for f in schema.fields_of("stones")}
    assert {"family", "sensor", "planted", "expires"} <= fields
    json.dumps(schema.catalogue())


def test_family_is_derived_from_kind_when_absent():
    assert schema.stone_family({"kind": "honeypot-ssh"}) == "honeypot"
    assert schema.stone_family({"kind": "dns"}) == "token"
    assert schema.stone_family({"kind": "dns", "family": "honeypot"}) == "honeypot"
    assert schema.stone_family({"kind": "honeypot-ssh", "family": "junk"}) == "honeypot"


@pytest.mark.parametrize("bad", [{"family": "trap"}, {"expires": "next tuesday"},
                                 {"expires": "2026-13-40"}, {"planted": 5}])
def test_bad_new_values_are_problems(bad):
    assert validate({"stones": [{**OLD_STONE, **bad}]}) != []


def test_a_blank_expiry_is_none():
    assert validate({**CHARTED, "stones": [{**OLD_STONE, "expires": ""}]}) == []
    assert validate({**CHARTED, "stones": [{**OLD_STONE, "expires": "—"}]}) == []


def test_two_stones_answering_to_one_sensor_is_a_problem():
    a = {**OLD_STONE, "id": "a", "sensor": "opencanary-1"}
    b = {**OLD_STONE, "id": "b", "sensor": "OpenCanary-1"}
    problems = validate({"stones": [a, b]})
    assert problems and any("already answers" in p for p in problems)


def test_the_demo_lab_charts_a_honeypot_and_two_tokens():
    path = os.path.join(REPO, "demo-lab", "seed", "lab-data.demo.json")
    if not os.path.exists(path):
        pytest.skip("no demo-lab seed in this tree")
    data = json.load(open(path, encoding="utf-8"))
    families = [schema.stone_family(s) for s in data["stones"]]
    assert families.count("honeypot") == 1 and families.count("token") == 2
    assert not [p for p in validate(data) if "stone" in p]
    feed = json.load(open(os.path.join(REPO, "demo-lab", "seed", "signals.demo.json"),
                          encoding="utf-8"))
    assert any(v.get("state") == "speaking" for v in feed["stones"].values())


# ── reading the three shapes ─────────────────────────────────────────────────

def test_opencanary_wrapped_message_is_read():
    r = tripwires.interpret({"message": json.dumps(_oc())})
    assert r["source"] == "opencanary" and not r["contact_only"]
    assert r["signal"] == "SMB file open" and r["src"] == "198.51.100.7" and r["port"] == 445
    assert r["sent_at"] == "2026-10-18T12:00:00Z"


def test_opencanary_form_body_is_read():
    from urllib.parse import urlencode
    payload = tripwires.parse_body(urlencode({"message": json.dumps(_oc())}).encode())
    assert tripwires.interpret(payload)["source"] == "opencanary"


@pytest.mark.parametrize("logtype", [1000, 1001, 1004, 1006])
def test_opencanary_housekeeping_is_contact_not_a_trip(logtype):
    assert tripwires.interpret(_oc(logtype=logtype))["contact_only"] is True


def test_canarytokens_body_is_read_and_its_save_test_is_contact():
    r = tripwires.interpret(_ct())
    assert r["source"] == "canarytokens" and not r["contact_only"]
    assert r["signal"] == "HTTP ms_word" and r["src"] == "203.0.113.5"
    assert r["sent_at"] == "2026-10-18T12:00:00Z"
    assert tripwires.interpret(_ct(token="a+test+token"))["contact_only"] is True


def test_generic_body_is_read():
    r = tripwires.interpret({"tripwire_id": "cloud-key", "at": "2026-10-18T12:00:00Z",
                             "kind": "used"})
    assert r["source"] == "generic" and r["signal"] == "used"


def test_anything_else_is_not_a_reading():
    assert tripwires.interpret({"hello": "world"}) is None
    assert tripwires.interpret({"message": "not json"}) is None
    assert tripwires.parse_body(b"[1, 2]") is None
    assert tripwires.parse_body(b"\xff\xfe") is None


def test_matching_rules():
    m = lambda payload: (tripwires.match(tripwires.interpret(payload), STONES) or {}).get("id")
    assert m(_oc(port=445)) == "canary-fs-smb"           # node_id:port beats node_id
    assert m(_oc(port=22)) == "canary-fs"
    assert m(_oc(node="nobody", dst_host="opencanary-1", port=22)) == "canary-fs"
    assert m(_oc(node="canary-fs", port=22)) == "canary-fs"   # id = node_id fallback
    assert m(_ct()) == "payroll-doc"                      # sensor = token id
    assert m(_ct(token="zzz", memo="cloud-key")) == "cloud-key"   # id = memo
    assert m({"tripwire_id": "WAN-BUG"}) == "wan-bug"     # case-insensitive
    assert m({"tripwire_id": "tok123abc"}) == "payroll-doc"
    assert m({"tripwire_id": "nope"}) is None


def test_clean_strips_markup_and_caps():
    assert tripwires.clean("<script>alert(1)</script>") == "scriptalert(1)/script"
    assert len(tripwires.clean("x" * 10_000)) == tripwires.CAP
    assert tripwires.clean({"nested": "blob"}) is None
    assert tripwires.clean(["a"]) is None
    assert tripwires.clean("a\x00b\nc\u202ed") == "ab cd"
    assert tripwires.clean_ip("<b>1.2.3.4</b>") is None
    assert tripwires.clean_ip("2001:db8::1") == "2001:db8::1"


# ── the webhook: off, auth, limits ──────────────────────────────────────────

def test_disabled_is_404(realm, monkeypatch):
    monkeypatch.delenv("ATLAS_TRIPWIRES_WEBHOOK")
    assert _post(realm.client, {"tripwire_id": "cloud-key"}).status_code == 404


def test_on_without_a_secret_on_the_file_backend_is_404(realm, monkeypatch):
    monkeypatch.delenv("ATLAS_TRIPWIRES_SECRET")
    assert _post(realm.client, {"tripwire_id": "cloud-key"}).status_code == 404
    monkeypatch.setenv("ATLAS_TRIPWIRES_SECRET", "short")       # too short to trust
    assert _post(realm.client, {"tripwire_id": "cloud-key"}).status_code == 404


def test_the_secret_can_come_from_a_file(realm, monkeypatch, tmp_path):
    monkeypatch.delenv("ATLAS_TRIPWIRES_SECRET")
    p = tmp_path / "secret"
    p.write_text(SECRET + "\n", encoding="utf-8")
    monkeypatch.setenv("ATLAS_TRIPWIRES_SECRET_FILE", str(p))
    assert _post(realm.client, {"tripwire_id": "cloud-key"}).status_code == 200


def test_missing_and_unknown_credentials_are_401(realm):
    r = realm.client.post(HOOK, json={"tripwire_id": "cloud-key"})
    assert r.status_code == 401 and "missing credential" in r.get_json()["error"]
    r = realm.client.post(HOOK, json={"tripwire_id": "cloud-key"},
                          headers={"Authorization": "Bearer atlas_tw_wrong"})
    assert r.status_code == 401 and r.get_json() == {"error": "unknown credential"}
    r = realm.client.post(HOOK + "?key=wrong", json={"tripwire_id": "cloud-key"})
    assert r.status_code == 401
    r = realm.client.post(HOOK, json={"tripwire_id": "cloud-key"},
                          headers={"Authorization": f"Bearer {SECRET}"})
    assert r.status_code == 401, "the signing secret itself is not a bearer credential"
    assert _trip_events() == []


def test_a_bad_signature_is_401_and_never_falls_back(realm):
    body = json.dumps({"tripwire_id": "cloud-key"}).encode()
    r = realm.client.post(HOOK, data=body, headers={
        "Content-Type": "application/json", "X-Atlas-Signature": "sha256=" + "0" * 64,
        "Authorization": f"Bearer {_key()}"})
    assert r.status_code == 401 and r.get_json() == {"error": "bad signature"}
    # signed over a different body
    sig = hmac.new(SECRET.encode(), b"{}", hashlib.sha256).hexdigest()
    r = realm.client.post(HOOK, data=body, headers={"X-Atlas-Signature": f"sha256={sig}"})
    assert r.status_code == 401
    assert _trip_events() == []


@pytest.mark.parametrize("how", ["bearer", "query", "sign"])
def test_each_credential_form_is_accepted(realm, how):
    r = _post(realm.client, {"tripwire_id": "cloud-key", "kind": "used"}, how=how)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["tripwire"] == "cloud-key"


def test_oversize_is_413(realm):
    big = json.dumps({"tripwire_id": "cloud-key", "pad": "x" * (tripwires.MAX_BYTES + 10)})
    assert _post(realm.client, None, raw=big.encode()).status_code == 413
    assert _trip_events() == []


def test_malformed_and_unrecognised_are_422(realm):
    assert _post(realm.client, None, raw=b"{not json").status_code == 422
    assert _post(realm.client, None, raw=b"[1,2,3]").status_code == 422
    assert _post(realm.client, None, raw=b"[" * 5000).status_code == 422
    r = _post(realm.client, {"hello": "world"})
    assert r.status_code == 422 and "not an OpenCanary" in r.get_json()["error"]


def test_rate_limit_is_429(realm, monkeypatch):
    monkeypatch.setattr(tripwires, "limiter", tripwires._RateLimiter(limit=2, window=60))
    codes = [_post(realm.client, {"tripwire_id": "cloud-key"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# ── trips become events ─────────────────────────────────────────────────────

def test_an_opencanary_trip_lands_in_the_annals(realm):
    r = _post(realm.client, {"message": json.dumps(_oc())})
    assert r.status_code == 200
    body = r.get_json()
    assert body["trip"] is True and body["matched"] is True and body["tripwire"] == "canary-fs-smb"
    [ev] = _trip_events()
    assert ev["target"] == "canary-fs-smb" and ev["gravity"] == "grave" and ev["ack"] is None
    assert ev["trip"]["source"] == "opencanary" and ev["trip"]["port"] == 445


def test_a_form_encoded_opencanary_trip_is_accepted(realm):
    from urllib.parse import urlencode
    raw = urlencode({"message": json.dumps(_oc(port=22))}).encode()
    r = _post(realm.client, None, raw=raw,
              headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and r.get_json()["tripwire"] == "canary-fs"


def test_a_canarytokens_trip_lands_in_the_annals(realm):
    r = _post(realm.client, _ct(), how="query")
    assert r.status_code == 200 and r.get_json()["tripwire"] == "payroll-doc"
    [ev] = _trip_events()
    assert ev["trip"]["source"] == "canarytokens" and ev["trip"]["src"] == "203.0.113.5"


def test_a_generic_trip_lands_in_the_annals(realm):
    r = _post(realm.client, {"tripwire_id": "wan-bug", "at": "2026-10-18T01:02:03Z",
                             "kind": "fetched"}, how="sign")
    assert r.status_code == 200
    [ev] = _trip_events()
    assert ev["target"] == "wan-bug" and ev["gravity"] == "quiet"     # wan + low
    assert ev["trip"]["sent_at"] == "2026-10-18T01:02:03Z"


def test_contact_only_messages_write_no_event(realm):
    assert _post(realm.client, {"message": json.dumps(_oc(logtype=1000))}).get_json()["trip"] is False
    assert _post(realm.client, _ct(token="a+test+token"), how="query").get_json()["trip"] is False
    assert _trip_events() == []
    by = realm.client.get("/api/v2/tripwires").get_json()["sources"]["webhook"]["by"]
    assert by["opencanary"]["last_heard"] and by["opencanary"]["last_trip"] is None
    assert by["canarytokens"]["heard"] == 1


def test_an_unknown_tripwire_is_an_unmatched_trip_never_dropped(realm):
    r = _post(realm.client, {"tripwire_id": "never-charted"})
    assert r.status_code == 200
    assert r.get_json()["matched"] is False and r.get_json()["tripwire"] is None
    [ev] = _trip_events()
    assert ev["target"] == "unmatched" and ev["gravity"] == "grave"
    assert events.counts()["unacked"] == 1
    view = realm.client.get("/api/v2/tripwires").get_json()
    assert [t["sensor"] for t in view["unmatched"]] == ["never-charted"]
    assert view["counts"]["unmatched"] == 1


def test_a_storm_is_one_event_with_a_count(realm):
    for _ in range(3):
        _post(realm.client, {"message": json.dumps(_oc(port=22))})
    [ev] = _trip_events()
    assert ev["trip"]["count"] == 3
    assert realm.client.get("/api/v2/tripwires").get_json()["tripwires"][0]["trips"][0]["count"] == 3


def test_only_allow_listed_capped_fields_are_stored(realm, tmp_path):
    evil = "<img src=x onerror=alert(1)>" + "A" * 5000
    rec = _oc(node=evil, dst_host=evil, src_host=evil, port=evil,
              logdata={"PASSWORD": "hunter2", "USERNAME": evil, "deep": {"x": [1] * 50}})
    rec["extra_field"] = "should-vanish"
    r = _post(realm.client, {"message": json.dumps(rec), "also": evil})
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert "<" not in text and "hunter2" not in text and "AAAA" not in text
    [ev] = _trip_events()
    stored = json.dumps(ev)
    assert "<" not in stored and ">" not in stored
    for gone in ("hunter2", "should-vanish", "logdata", "USERNAME", "manage_url"):
        assert gone not in stored
    assert set(ev["trip"]) == {"source", "sensor", "signal", "src", "port",
                               "sent_at", "count", "last_at"}
    assert ev["trip"]["src"] is None and ev["trip"]["port"] is None   # not an IP / port
    assert all(len(v) <= tripwires.CAP for v in ev["trip"].values() if isinstance(v, str))
    # and the file on disk says the same
    disk = open(os.environ["ATLAS_EVENTS"], encoding="utf-8").read()
    assert "hunter2" not in disk and "<img" not in disk and "should-vanish" not in disk


def test_canarytokens_secrets_are_never_stored(realm):
    _post(realm.client, _ct(), how="query")
    stored = json.dumps(_trip_events())
    for gone in ("manage", "auth=y", "Mozilla", "a reminder", "geo_info"):
        assert gone not in stored


# ── the read model ──────────────────────────────────────────────────────────

def test_the_read_endpoint_shape_and_lit_state(realm):
    r = _post(realm.client, {"tripwire_id": "cloud-key"})
    event_id = r.get_json()["event"]
    resp = realm.client.get("/api/v2/tripwires")
    assert resp.status_code == 200
    assert "no-store" in resp.headers["Cache-Control"]
    view = resp.get_json()
    assert view["lit_window_hours"] == tripwires.LIT_HOURS
    rows = {t["id"]: t for t in view["tripwires"]}
    assert set(rows) == {s["id"] for s in STONES}
    key = rows["cloud-key"]
    assert key["state"] == "lit" and key["lit"] is True and key["unacked"] == 1
    assert key["family"] == "token" and key["trips"][0]["event"] == event_id
    assert key["expired"] is False and key["expires_in_days"] > 0
    assert rows["payroll-doc"]["expired"] is True
    assert rows["canary-fs"]["family"] == "honeypot" and rows["canary-fs"]["state"] == "quiet"
    assert rows["nas-restore-share"]["family"] == "token"            # the old shape
    assert view["counts"]["lit"] == 1 and view["counts"]["charted"] == len(STONES)

    events.acknowledge(event_id, "tester", "it was me")
    key = {t["id"]: t for t in realm.client.get("/api/v2/tripwires").get_json()["tripwires"]}["cloud-key"]
    assert key["state"] == "stirred" and key["lit"] is False
    assert key["trips"][0]["ack"]["by"] == "tester"


def test_an_old_trip_is_not_lit(realm, monkeypatch):
    _post(realm.client, {"tripwire_id": "cloud-key"})
    later = __import__("time").time() + (tripwires.LIT_HOURS + 1) * 3600
    data = json.load(open(os.environ["ATLAS_DATA"], encoding="utf-8"))
    view = tripwires.overview(data, {}, now=later)
    key = {t["id"]: t for t in view["tripwires"]}["cloud-key"]
    assert key["state"] == "quiet" and key["unacked"] == 1


def test_contact_per_source(realm, monkeypatch):
    """The decoy feed: ok / lost / off from the feed's own `sources`. The
    webhook: off when it cannot be used, waiting until something reaches it."""
    view = realm.client.get("/api/v2/tripwires").get_json()["sources"]
    assert view["decoys"]["contact"] == "off" and view["decoys"]["path"] == "/api/stones"
    assert view["webhook"]["contact"] == "waiting"
    assert view["webhook"]["auth"] == {"signature": True, "key": True, "token": False}

    import requests
    monkeypatch.setenv("ATLAS_SIGNALS_SOURCES", "deception")
    monkeypatch.setenv("ATLAS_DECOYS_URL", "http://decoys.home.example:5013")
    monkeypatch.setenv("ATLAS_DECOYS_KEY", "read-key")

    def down(url, **kw):
        raise requests.ConnectionError("unreachable")
    monkeypatch.setattr(requests, "get", down)
    handle = fresh_app()
    view = handle.app.test_client().get("/api/v2/tripwires").get_json()
    assert view["sources"]["decoys"]["contact"] == "lost"
    assert view["sources"]["decoys"]["configured"] is True

    class Answer:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"stones": {"canary-fs": {"state": "speaking",
                                             "last_spoke": "2026-10-18T03:00:00Z"}},
                    "unattributed_trips": 2}
    monkeypatch.setattr(requests, "get", lambda url, **kw: Answer())
    handle = fresh_app()
    view = handle.app.test_client().get("/api/v2/tripwires").get_json()
    assert view["sources"]["decoys"]["contact"] == "ok"
    assert view["sources"]["decoys"]["last_trip"] == "2026-10-18T03:00:00Z"
    assert view["sources"]["decoys"]["unattributed"] == 2
    fs = {t["id"]: t for t in view["tripwires"]}["canary-fs"]
    assert fs["lit"] is True and fs["decoy"]["state"] == "speaking"
    assert fs["trips"][0]["source"] == "decoys" and fs["trips"][0]["event"] is None

    monkeypatch.delenv("ATLAS_TRIPWIRES_WEBHOOK")
    view = handle.app.test_client().get("/api/v2/tripwires").get_json()
    assert view["sources"]["webhook"]["contact"] == "off"


def test_the_setup_helper_never_carries_a_secret(realm):
    resp = realm.client.get("/api/v2/tripwires/setup")
    assert resp.status_code == 200
    body = resp.get_json()
    text = resp.get_data(as_text=True)
    assert SECRET not in text and _key() not in text
    assert body["url"].endswith("/api/v2/ingest/tripwires") and body["enabled"] is True
    handler = body["opencanary"]["handler"]
    assert handler["class"] == "opencanary.logger.WebhookHandler"
    assert handler["data"] == {"message": "%(message)s"} and handler["status_code"] == 200
    assert handler["headers"]["Content-Type"] == "application/json"
    assert json.loads(body["opencanary"]["config"])["logger"]["kwargs"]["handlers"]["Webhook"] == handler
    assert body["canarytokens"]["webhook_url"] == body["url"] + "?key=" + tripwires.KEY_PLACEHOLDER
    assert body["key_command"] == "python cli.py tripwires-key"
    assert body["key_command"] and body["compose_exec"].endswith("exec atlas")
    placeholder = next(line for line in body["enable"] if "SECRET=" in line).split("=", 1)[1]
    assert len(placeholder) < tripwires.SECRET_MIN, "a pasted placeholder must not work"
    assert body["token_command"] is None                         # file backend
    assert {a["scheme"] for a in body["auth"]} == {"bearer", "query", "signature"}
    assert body["decoys"]["path"] == "/api/stones"


# ── ATLAS_DECOYS_PATH ───────────────────────────────────────────────────────

def test_decoys_path_is_honoured_by_the_adapter(realm, monkeypatch):
    import requests
    import signals
    seen = {}

    def fake(url, **kw):
        seen["url"] = url
        raise requests.ConnectionError("stop")
    monkeypatch.setattr(requests, "get", fake)
    signals.DeceptionAdapter("http://decoys.home.example:5013", "k").fetch()
    assert seen["url"] == "http://decoys.home.example:5013/api/stones"
    monkeypatch.setenv("ATLAS_DECOYS_PATH", "/v2/tripwires/state")
    signals.DeceptionAdapter("http://decoys.home.example:5013/", "k").fetch()
    assert seen["url"] == "http://decoys.home.example:5013/v2/tripwires/state"
    from api.v2 import admin
    admin._probe("decoys", "http://decoys.home.example:5013", "k")
    assert seen["url"] == "http://decoys.home.example:5013/v2/tripwires/state"


@pytest.mark.parametrize("bad", ["api/stones", "//evil.example/x", "/a b", "/x?y=1",
                                 "http://evil.example/", "/" + "a" * 300])
def test_a_bad_decoys_path_falls_back(monkeypatch, bad):
    import integrations
    monkeypatch.setenv("ATLAS_DECOYS_PATH", bad)
    assert integrations.valid_decoys_path(bad) is False
    assert integrations.decoys_path() == "/api/stones"


# ── who may see it ──────────────────────────────────────────────────────────

@pytest.fixture
def guarded(tmp_path, monkeypatch):
    """Accounts mode: an admin and a viewer cleared for nothing, a static feed
    carrying a speaking stone, and one trip already in the annals."""
    data = tmp_path / "lab-data.json"
    data.write_text(json.dumps(_dataset()), encoding="utf-8")
    feed = tmp_path / "signals.json"
    feed.write_text(json.dumps({"nodes": {"nas": {"state": "healthy"}},
                                "stones": {"canary-fs": {"state": "speaking"}},
                                "metrics": {"unattributed_trips": 3, "up": 1}}), encoding="utf-8")
    env = {
        "ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file", "ATLAS_DATA": str(data),
        "ATLAS_ACCOUNTS_DB": str(tmp_path / "accounts.db"),
        "ATLAS_SECRET_KEY": "test-signing-key", "ATLAS_INSECURE_COOKIES": "1",
        "ATLAS_AUTH_BACKENDS": "local", "ATLAS_MFA_REQUIRED": "",
        "ATLAS_EVENTS": str(tmp_path / "events.json"),
        "ATLAS_TRIPWIRES_STATE": str(tmp_path / "tripwires.json"),
        "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
        "ATLAS_SIGNALS_SOURCES": "static", "ATLAS_SIGNALS_FILE": str(feed),
        "ATLAS_TRIPWIRES_WEBHOOK": "1", "ATLAS_TRIPWIRES_SECRET": SECRET,
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    handle = fresh_app()
    import accounts
    accounts.create_local_user("viewer", PW, is_admin=False)
    accounts.create_local_user("keeper", PW, is_admin=True)
    tripwires.limiter.reset()
    return handle


def _login(handle, username):
    c = handle.app.test_client()
    r = c.post("/api/v2/auth/login", json={"username": username, "password": PW},
               headers={"X-Atlas-Write": "1"})
    assert r.get_json()["ok"] is True
    return c


def test_the_webhook_is_gate_exempt_and_nothing_else_is(guarded):
    anon = guarded.app.test_client()
    r = _post(anon, {"tripwire_id": "cloud-key"})
    assert r.status_code == 200, "the ingest prefix exemption covers the webhook"
    assert anon.get("/api/v2/tripwires").status_code in (401, 403)
    assert anon.get("/api/v2/tripwires/setup").status_code in (401, 403)


def test_a_viewer_sees_no_tripwire_anywhere(guarded):
    _post(guarded.app.test_client(), {"tripwire_id": "cloud-key"})
    viewer = _login(guarded, "viewer")

    data = viewer.get("/api/v2/lab-data").get_json()
    assert "stones" not in data
    feed = viewer.get("/api/v2/signals").get_json()
    assert "stones" not in feed and "unattributed_trips" not in feed.get("metrics", {})
    assert "deception" not in feed.get("sources", {})
    annals = viewer.get("/api/v2/events").get_json()
    assert annals["events"] == [] and annals["counts"]["unacked"] == 0
    assert annals["counts"]["total"] == 0
    assert viewer.get("/api/v2/tripwires").status_code == 403
    assert viewer.get("/api/v2/tripwires/setup").status_code == 403
    for body in (data, feed, annals):
        text = json.dumps(body)
        assert "canary-fs" not in text and "cloud-key" not in text


def test_an_admin_sees_them_all(guarded):
    _post(guarded.app.test_client(), {"tripwire_id": "cloud-key"})
    keeper = _login(guarded, "keeper")
    assert len(keeper.get("/api/v2/lab-data").get_json()["stones"]) == len(STONES)
    assert keeper.get("/api/v2/signals").get_json()["stones"]["canary-fs"]["state"] == "speaking"
    annals = keeper.get("/api/v2/events").get_json()
    assert [e["target"] for e in annals["events"]] == ["cloud-key"]
    assert annals["counts"]["unacked"] == 1
    view = keeper.get("/api/v2/tripwires").get_json()
    rows = {t["id"]: t for t in view["tripwires"]}
    assert rows["canary-fs"]["lit"] and rows["cloud-key"]["lit"]
    assert keeper.get("/api/v2/tripwires/setup").status_code == 200


# ── the documentation keeps up ──────────────────────────────────────────────

def test_env_coverage_passes():
    script = os.path.join(REPO, "docs", "env-coverage.py")
    if not os.path.exists(script):
        pytest.skip("docs not in this tree")
    r = subprocess.run([sys.executable, script], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    doc = open(os.path.join(REPO, "docs", "configuration.md"), encoding="utf-8").read()
    for name in ("ATLAS_TRIPWIRES_WEBHOOK", "ATLAS_TRIPWIRES_SECRET",
                 "ATLAS_TRIPWIRES_SECRET_FILE", "ATLAS_TRIPWIRES_STATE", "ATLAS_DECOYS_PATH"):
        assert f"`{name}`" in doc


@pytest.mark.parametrize("url, loopback", [
    ("http://localhost:5006/", True), ("http://127.0.0.1:5006/", True),
    ("http://[::1]:5006/", True), ("https://atlas.home.example/", False),
    ("http://10.0.0.5:5006/", False),
])
def test_setup_warns_when_its_address_only_works_here(realm, url, loopback):
    assert tripwires.setup(url)["loopback"] is loopback


def test_a_limiter_forgets_clients_it_has_stopped_hearing(monkeypatch):
    import ingest
    monkeypatch.setattr(ingest, "MAX_TRACKED", 3)
    limiter = ingest._RateLimiter(limit=5, window=-1.0)   # every client already stale
    for client in "abcdef":
        limiter.hit(client)
    assert len(limiter._hits) <= 3
