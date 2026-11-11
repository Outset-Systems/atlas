"""The API reference and the token's doors are one list.

A path a token may call must be documented, the document must not advertise a
path a token cannot call, and what a token is actually sent must be made of
fields the document names."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from appfixture import fresh_app, login_as  # noqa: E402

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "standalone"}

PW = "correct-horse-battery-staple-9"
W = {"X-Atlas-Write": "1", "Origin": "http://localhost"}
LAB = {"meta": {"title": "Test Lab", "surveyed": "2026-10-31"},
       "zones": [{"id": "core", "name": "Core"}],
       "nodes": [{"id": "alpha", "name": "ALPHA", "zone": "core", "ip": "192.0.2.5", "role": "router",
                  "x": 1, "y": 2, "accounts": [{"name": "root", "sudo": "password"}],
                  "links": [{"label": "Charts", "url": "http://192.0.2.5:3000"}]}],
       "routes": [],
       "rites": [{"name": "Nightly backup", "host": "alpha", "cadence": "daily", "when": "02:00"}],
       "stones": [{"id": "bait", "name": "Bait", "kind": "dns"}]}
DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "docs", "openapi.json")


@pytest.fixture
def realm(tmp_path, monkeypatch):
    data = tmp_path / "lab-data.json"
    data.write_text(json.dumps(LAB), encoding="utf-8")
    for name, value in {"ATLAS_AUTH_MODE": "accounts", "ATLAS_DATA_BACKEND": "file",
                        "ATLAS_DATA": str(data), "ATLAS_ACCOUNTS_DB": str(tmp_path / "a.db"),
                        "ATLAS_INTEGRATIONS": str(tmp_path / "integrations.json"),
                        "ATLAS_SECRET_KEY": "test-signing-key", "ATLAS_INSECURE_COOKIES": "1",
                        "ATLAS_SIGNALS_SOURCES": "", "ATLAS_AUTH_BACKENDS": "local",
                        "ATLAS_MFA_REQUIRED": "", "ATLAS_ALLOW_INSECURE": "1",
                        # agent access starts off; these suites are about what a token reads
                        "ATLAS_AGENT_API": "1"}.items():
        monkeypatch.setenv(name, value)
    app = fresh_app()
    import accounts
    accounts.create_local_user("surveyor", PW, display_name="Surveyor", is_admin=True)
    yield app
    monkeypatch.undo()
    fresh_app()


@pytest.fixture
def token(realm):
    admin = realm.app.test_client()
    login_as(admin, "surveyor", PW)
    r = admin.post("/api/v2/admin/tokens", json={"name": "reader", "days": 90}, headers=W)
    assert r.status_code == 200, r.get_json()
    return {"Authorization": f"Bearer {r.get_json()['secret']}"}


def _doc():
    import openapi
    return openapi.document()


def _resolve(doc, node):
    while "$ref" in node:
        where = doc
        for part in node["$ref"].lstrip("#/").split("/"):
            where = where[part]
        node = where
    return node


def _reply_schema(doc, path, method="get"):
    ok = doc["paths"][path][method]["responses"]["200"]
    return _resolve(doc, ok["content"]["application/json"]["schema"])


def test_every_door_a_token_has_is_documented_and_no_other():
    import api_tokens
    assert set(_doc()["paths"]) == set(api_tokens.READ_PATHS) | {api_tokens.MCP_PATH}


def test_read_paths_are_get_only_and_mcp_is_post_only():
    import api_tokens
    for path, item in _doc()["paths"].items():
        assert set(item) == ({"post"} if path == api_tokens.MCP_PATH else {"get"}), path


def test_every_reference_in_the_document_resolves():
    doc = _doc()

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                _resolve(doc, node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(doc)


def test_every_catalogue_field_type_has_a_schema():
    import openapi
    import schema
    seen = set()

    def walk(fields):
        for fld in fields:
            seen.add(fld["type"])
            walk(fld.get("of") or [])
    for sec in schema.SECTIONS.values():
        walk(sec["fields"])
    walk(schema.SIGNAL_FIELDS)
    assert seen <= set(openapi.TYPE_MAP), seen - set(openapi.TYPE_MAP)


def test_the_document_names_nothing_a_token_is_never_sent():
    dataset = _doc()["components"]["schemas"]["Dataset"]["properties"]
    assert "stones" not in dataset
    assert "accounts" not in dataset["nodes"]["items"]["properties"]


def test_the_mcp_tools_listed_are_the_tools_served():
    import api_tokens
    import mcp_tools
    listed = _doc()["paths"][api_tokens.MCP_PATH]["post"]["x-mcp-tools"]
    assert listed == [t["name"] for t in mcp_tools.TOOLS]


def test_a_token_reads_the_reference_and_a_stranger_does_not(realm, token):
    import openapi
    c = realm.app.test_client()
    r = c.get(openapi.OPENAPI_PATH, headers=token)
    assert r.status_code == 200
    assert r.get_json() == openapi.document()
    assert realm.app.test_client().get(openapi.OPENAPI_PATH).status_code in (302, 401)


def test_a_token_cannot_write_to_the_reference(realm, token):
    import openapi
    r = realm.app.test_client().post(openapi.OPENAPI_PATH, headers=token, json={})
    assert r.status_code in (403, 405)


@pytest.mark.parametrize("path", ["/api/v2/lab-data", "/api/v2/maps", "/api/v2/signals",
                                  "/api/v2/rites", "/api/v2/events"])
def test_what_a_token_is_sent_is_made_of_documented_fields(realm, token, path):
    doc = _doc()
    r = realm.app.test_client().get(path, headers=token)
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    props = _reply_schema(doc, path)["properties"]
    assert set(body) <= set(props), set(body) - set(props)
    # one level down: the rows of every list the reply carries
    for key, value in body.items():
        rows = value if isinstance(value, list) else []
        item = _resolve(doc, props[key]).get("items") or {}
        known = set(_resolve(doc, item).get("properties") or {})
        for row in rows:
            if isinstance(row, dict) and known:
                assert set(row) <= known, (key, set(row) - known)


def test_the_file_in_docs_is_this_document():
    if not os.path.exists(DOCS):
        pytest.skip("docs/ is not beside Web/ here (the image carries Web/ only)")
    import openapi
    with open(DOCS, encoding="utf-8") as fh:
        assert json.load(fh) == openapi.document(), "run: python Web/openapi.py"
