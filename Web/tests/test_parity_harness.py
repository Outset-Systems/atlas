"""The parity harness, tested as a thing in its own right.

Two halves. The structural comparer is exercised on literals, because the
rules it must get right (null vs absent, bool vs int, key order, list
positions, accepted-and-stale bookkeeping) are easier to read as literals than
as HTTP. Then the harness is pointed at a real Atlas and made to FAIL on
endpoints that genuinely differ — a parity harness that cannot fail is worse
than none, so its failure is the thing this file proves most carefully.
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app  # noqa: E402
from parity import (ABSENT, Accepted, Call, assert_parity, compare,  # noqa: E402
                    diff_json, parse_path, render_path)

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(WEB, "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}


def _where(diffs):
    return sorted(d.where for d in diffs)


# ── The comparer ─────────────────────────────────────────────────────────────

def test_key_order_is_not_a_difference():
    assert diff_json({"a": 1, "b": {"c": 2, "d": 3}}, {"b": {"d": 3, "c": 2}, "a": 1}) == []


def test_null_and_absent_are_different():
    diffs = diff_json({"a": None}, {})
    assert len(diffs) == 1
    d = diffs[0]
    assert d.where == "$.a" and d.v1 is None and d.v2 is ABSENT and d.note == "absent in v2"

    diffs = diff_json({}, {"a": None})
    assert _where(diffs) == ["$.a"] and diffs[0].note == "absent in v1"

    # and null on both sides is equal
    assert diff_json({"a": None}, {"a": None}) == []


def test_types_are_compared_before_values():
    assert _where(diff_json({"n": 1}, {"n": True})) == ["$.n"]       # Python says 1 == True
    assert _where(diff_json({"n": 1}, {"n": 1.0})) == ["$.n"]        # JSON 1 vs 1.0
    assert _where(diff_json({"n": 1}, {"n": "1"})) == ["$.n"]
    assert diff_json({"n": 1}, {"n": 1}) == []
    d = diff_json({"n": {}}, {"n": []})[0]
    assert d.note == "type: object vs array"


def test_lists_compare_by_position_and_report_extras():
    diffs = diff_json({"xs": [1, 2, 3]}, {"xs": [1, 9]})
    assert _where(diffs) == ["$.xs[1]", "$.xs[2]"]
    by = {d.where: d for d in diffs}
    assert by["$.xs[1]"].note == "value"
    assert by["$.xs[2]"].v2 is ABSENT and by["$.xs[2]"].note == "absent in v2"


def test_nested_paths_render_and_parse_round_trip():
    diffs = diff_json({"a": [{"b c": {"d": 1}}]}, {"a": [{"b c": {"d": 2}}]})
    assert diffs[0].where == '$.a[0]["b c"].d'
    assert parse_path(diffs[0].where) == diffs[0].path
    assert render_path(parse_path("$.summary.secondary_metrics[*].value")) == \
        "$.summary.secondary_metrics[*].value"
    assert parse_path("status") == ("status",)
    assert parse_path("header:Cache-Control") == ("header", "Cache-Control")
    with pytest.raises(ValueError):
        parse_path("summary.x")


def test_accepted_needs_a_reason():
    with pytest.raises(ValueError):
        Accepted("$.x", "")


class _Resp:
    """Just enough of a Flask response for compare()."""

    def __init__(self, status, body, mimetype="application/json", headers=None):
        import json as _json
        self.status_code = status
        self.mimetype = mimetype
        self._data = (_json.dumps(body) if mimetype == "application/json" else body)
        self.headers = {"Content-Type": mimetype, **(headers or {})}

    def get_data(self, as_text=False):
        data = self._data
        if isinstance(data, str):
            return data if as_text else data.encode()
        return data.decode() if as_text else data


class _Client:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def open(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return self.routes[path]


def test_accepted_difference_is_recorded_not_dropped():
    client = _Client({"/v1": _Resp(200, {"a": 1, "b": "/atlas/"}),
                      "/v2": _Resp(200, {"a": 1, "b": "/atlas/v2/"})})
    acc = Accepted("$.b", "v2 reports its own mount path", v1="/atlas/", v2="/atlas/v2/")
    result = compare(client, "/v1", "/v2", accepted=[acc])
    assert result.ok
    assert [(d.where, a) for d, a in result.accepted_hits] == [("$.b", acc)]
    assert "accepted (declared)" in result.report()
    assert "v2 reports its own mount path" in result.report()


def test_accepted_with_other_values_does_not_match():
    client = _Client({"/v1": _Resp(200, {"b": "/atlas/"}),
                      "/v2": _Resp(200, {"b": "/elsewhere/"})})
    acc = Accepted("$.b", "only this exact divergence", v1="/atlas/", v2="/atlas/v2/")
    result = compare(client, "/v1", "/v2", accepted=[acc])
    assert not result.ok
    assert _where(result.differences) == ["$.b"]
    assert result.stale == [acc]


def test_stale_acceptance_fails_unless_optional():
    client = _Client({"/v1": _Resp(200, {"a": 1}), "/v2": _Resp(200, {"a": 1})})
    stale = Accepted("$.gone", "this divergence was fixed in v2 last week")
    result = compare(client, "/v1", "/v2", accepted=[stale])
    assert not result.ok and result.stale == [stale] and result.differences == []
    with pytest.raises(AssertionError) as err:
        assert_parity(client, "/v1", "/v2", accepted=[stale])
    assert "stale acceptances" in str(err.value) and "$.gone" in str(err.value)

    conditional = Accepted("$.gone", "db mode only", optional=True)
    assert assert_parity(client, "/v1", "/v2", accepted=[conditional]).ok


def test_wildcards_match_one_segment():
    client = _Client({"/v1": _Resp(200, {"rows": [{"at": 1}, {"at": 2}], "n": 2}),
                      "/v2": _Resp(200, {"rows": [{"at": 9}, {"at": 9}], "n": 3})})
    result = compare(client, "/v1", "/v2",
                     accepted=[Accepted("$.rows[*].at", "timestamps are per-call")])
    assert _where(result.differences) == ["$.n"]
    assert [d.where for d, _ in result.accepted_hits] == ["$.rows[0].at", "$.rows[1].at"]


def test_status_headers_and_non_json_bodies():
    client = _Client({
        "/v1": _Resp(200, {"a": 1}, headers={"Cache-Control": "no-store"}),
        "/v2": _Resp(404, b"<h1>Not Found</h1>", mimetype="text/html"),
    })
    result = compare(client, "/v1", "/v2", headers=("Content-Type", "Cache-Control"))
    assert _where(result.differences) == ["body", "header:Cache-Control",
                                          "header:Content-Type", "status"]
    by = {d.where: d for d in result.differences}
    assert by["status"].v1 == 200 and by["status"].v2 == 404
    assert by["header:Cache-Control"].v2 is ABSENT
    assert by["body"].note == "v1 is JSON, v2 is not"
    assert Accepted("status", "404 is expected until the route is ported").matches(by["status"])

    same = _Client({"/a": _Resp(200, b"bytes", mimetype="image/png"),
                    "/b": _Resp(200, b"bytes", mimetype="image/png")})
    assert compare(same, "/a", "/b").ok
    other = _Client({"/a": _Resp(200, b"bytes", mimetype="image/png"),
                     "/b": _Resp(200, b"other", mimetype="image/png")})
    assert _where(compare(other, "/a", "/b").differences) == ["body"]


def test_call_is_sent_identically_to_both_paths():
    client = _Client({"/v1": _Resp(200, {"ok": True}), "/v2": _Resp(200, {"ok": True})})
    call = Call("POST", headers={"X-Atlas-Write": "1"}, json={"k": "v"},
                query_string={"q": "1"})
    assert compare(client, "/v1", "/v2", call).ok
    assert [p for p, _ in client.calls] == ["/v1", "/v2"]
    kw1, kw2 = (kw for _, kw in client.calls)
    assert kw1 == kw2 == {"method": "POST", "headers": {"X-Atlas-Write": "1"},
                          "json": {"k": "v"}, "query_string": {"q": "1"}}
    assert call.describe("/v1") == "POST /v1?q=1"


# ── Against a real Atlas: it must FAIL on endpoints that differ ─────────────

@pytest.fixture
def client(tmp_path):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    handle = fresh_app(ATLAS_AUTH_MODE="standalone", ATLAS_DATA_BACKEND="file",
                       ATLAS_DATA=str(data))
    return handle.app.test_client()


def test_harness_fails_on_two_genuinely_different_endpoints(client):
    """/api/status and /api/v2/maps are both 200 JSON and share no keys."""
    with pytest.raises(AssertionError) as err:
        assert_parity(client, "/api/status", "/api/v2/maps")
    text = str(err.value)
    assert "PARITY FAILURE: GET /api/status  vs  GET /api/v2/maps" in text
    assert "$.app" in text and "absent in v2" in text
    assert "$.maps" in text and "absent in v1" in text
    assert "--- v1 GET /api/status" in text and "+++ v2 GET /api/v2/maps" in text


def test_harness_fails_on_a_status_mismatch(client):
    """A ported route that is not there yet is the first failure every group
    will see: 200 JSON on one side, the framework's 404 page on the other."""
    result = compare(client, "/api/status", "/api/v2/not-ported-yet")
    assert not result.ok
    by = {d.where: d for d in result.differences}
    assert by["status"].v1 == 200 and by["status"].v2 == 404
    assert by["header:Content-Type"].v1 == "application/json"
    assert by["body"].note == "v1 is JSON, v2 is not"
    with pytest.raises(AssertionError):
        assert_parity(client, "/api/status", "/api/v2/not-ported-yet")


def test_stale_acceptance_fails_against_a_real_endpoint(client):
    """An endpoint compared with itself has no differences — so the only way
    this can fail is the declared acceptance going unused, which it must."""
    assert assert_parity(client, "/api/v2/events", "/api/v2/events",
                         Call(query_string={"limit": "1"})).ok
    with pytest.raises(AssertionError) as err:
        assert_parity(client, "/api/v2/events", "/api/v2/events",
                      Call(query_string={"limit": "1"}),
                      accepted=[Accepted("$.events[*]", "never fires — proves stale detection")])
    assert "stale acceptances" in str(err.value) and "$.events[*]" in str(err.value)


def test_report_reads_well(client):
    result = compare(client, "/api/status", "/api/v2/maps")
    lines = result.report().splitlines()
    assert lines[0].startswith("PARITY FAILURE: ")
    assert "unaccepted difference(s)" in lines[1]
    assert lines[2].startswith("  status: v1=200 v2=200")
    # one aligned row per difference, then the unified diff
    rows = [ln for ln in lines if ln.startswith("  $.")]
    assert rows and all("  v1=" in r and "  v2=" in r and r.endswith(")") for r in rows)
    assert any(ln.startswith("  @@") for ln in lines)
