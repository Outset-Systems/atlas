"""Layout writes — `/api/v2/positions`, `/api/v2/rack`.

The write gate (`write_refusal`) in front of the smallest write shape in the
app: a permitted write lands in the overlay files with honest counts, a
malformed body is one sentence, and every refusal — no header, cross-site,
read-only — is a 403 with a reason.
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

WRITE = {"X-Atlas-Write": "1"}


def _app(tmp_path, **extra):
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    return fresh_app(
        ATLAS_DATA=str(data),
        ATLAS_POSITIONS=str(tmp_path / "positions.json"),
        ATLAS_RACK=str(tmp_path / "rack.json"),
        **{**{"ATLAS_READONLY": "0"}, **extra},
    )


@pytest.fixture
def client(tmp_path):
    return _app(tmp_path).app.test_client()


def test_positions_write_lands_and_is_idempotent(client):
    body = {"hypervisor": {"x": 51.0, "y": 50.0}}
    r = client.post("/api/v2/positions", headers=WRITE, json=body)
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "saved": 1, "total": 1}
    # merging the same body twice reports the same counts
    assert client.post("/api/v2/positions", headers=WRITE, json=body).get_json() == \
        {"ok": True, "saved": 1, "total": 1}


def test_rack_write_lands(client):
    r = client.post("/api/v2/rack", headers=WRITE, json={"hypervisor": {"u": 9}})
    assert r.status_code == 200
    body = r.get_json()
    # hypervisor is a charted place but not a rack slot, so the overlay
    # keeps nothing — an honest 0, never an error
    assert body["ok"] is True and body["saved"] == 0 and body["total"] == 0


def test_bad_body_is_one_sentence(client):
    for body in ([1, 2], "nope", None):
        r = client.post("/api/v2/positions", headers=WRITE, json=body)
        assert r.status_code == 400, body
        assert r.get_json() == {"error": "expected an object of key -> value"}


def test_missing_write_header_refuses(client):
    r = client.post("/api/v2/positions", json={"hypervisor": {"x": 51.0, "y": 50.0}})
    assert r.status_code == 403
    assert "write header" in r.get_json()["error"]


def test_cross_site_refuses(client):
    r = client.post("/api/v2/rack", headers={**WRITE, "Sec-Fetch-Site": "cross-site"},
                    json={"hypervisor": {"u": 9}})
    assert r.status_code == 403
    assert "cross-site" in r.get_json()["error"]


def test_read_only_refuses(tmp_path):
    client = _app(tmp_path, ATLAS_READONLY="1").app.test_client()
    r = client.post("/api/v2/rack", headers=WRITE, json={"hypervisor": {"u": 9}})
    assert r.status_code == 403
    assert "read-only" in r.get_json()["error"]
