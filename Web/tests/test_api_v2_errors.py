"""The error arms nothing else drives — dataset-unreadable 500s and the
non-ASCII beat token.

Every surface's happy path and refusals have their own tests; these are the
`except (OSError, ValueError)` arms (a corrupt dataset) across reads, feeds,
probes and writes, plus the compare_digest hardening: a beat token carrying
non-ASCII bytes must be a 403, never a TypeError 500 (the decoy-feed failure
class, 2026-08-15).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

TOKEN = "a-test-beat-token"
WRITE = {"X-Atlas-Write": "1"}


@pytest.fixture
def broken(tmp_path):
    """An Atlas whose dataset is unreadable garbage."""
    data = tmp_path / "lab-data.json"
    data.write_text("{this is not json", encoding="utf-8")
    return fresh_app(
        ATLAS_DATA=str(data),
        ATLAS_POSITIONS=str(tmp_path / "positions.json"),
        ATLAS_RACK=str(tmp_path / "rack.json"),
        ATLAS_BEATS=str(tmp_path / "heartbeats.json"),
        ATLAS_BEATS_DIR=str(tmp_path / "beats"),
        ATLAS_READONLY="0",
        ATLAS_BEAT_TOKEN=TOKEN,
    ).app.test_client()


def test_unreadable_dataset_is_a_500_with_a_reason(broken):
    r = broken.get("/api/v2/lab-data")
    assert r.status_code == 500 and "unreadable" in r.get_json()["error"]
    r = broken.get("/api/v2/rites")
    assert r.status_code == 500 and "unreadable" in r.get_json()["error"]
    r = broken.get("/api/v2/embeddable", query_string={"url": "http://x.test/"})
    assert r.status_code == 500 and r.get_json() == {"error": "dataset unreadable"}
    r = broken.post("/api/v2/positions", headers=WRITE, json={"a": {"x": 1, "y": 1}})
    assert r.status_code == 500 and r.get_json() == {"error": "dataset unreadable"}


def test_status_still_answers_when_the_map_is_unreadable(broken):
    """A health route that dies with the thing it reports on is no health route."""
    for path in ("/api/status", "/api/v2/health"):
        r = broken.get(path)
        assert r.status_code == 200, path
        assert r.get_json()["healthy"] is False


def test_non_ascii_beat_token_is_403_not_500(broken):
    """compare_digest on str raises TypeError for non-ASCII — the route must
    refuse with the ordinary 403 instead."""
    for token in ("not-the-token-é", "bad-ÿ"):
        r = broken.post("/api/v2/rites/x/beat", headers={"X-Atlas-Beat": token}, json={})
        assert r.status_code == 403, token
        assert r.get_json() == {"error": "bad or missing beat token"}


def test_a_body_over_the_cap_is_refused_in_words(tmp_path):
    import shutil
    import mapart
    data = tmp_path / "lab-data.json"
    shutil.copy(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "default-lab-data.json"), data)
    app = fresh_app(ATLAS_DATA=str(data), ATLAS_READONLY="0").app
    assert app.config["MAX_CONTENT_LENGTH"] > mapart.MAX_BYTES, "a map image must still fit"
    app.config["MAX_CONTENT_LENGTH"] = 16
    r = app.test_client().post("/api/v2/admin/import/csv", headers={"X-Atlas-Write": "1"},
                               json={"csv": "name,ip\nsomewhere,10.9.9.9\n"})
    assert r.status_code == 413
    assert r.get_json() == {"error": "that request is too large"}
