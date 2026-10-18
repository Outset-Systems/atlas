"""The ACCOUNTS scene — wiring, and the one thing it must never do.

A scene is mostly JS and pytest cannot run it, so this guards what would fail
SILENTLY: a scene listed in the band but never built, a close Escape cannot
reach, a button revealed to someone who must not have it — and, above all, the
roster reaching a viewer who is not cleared for it.

That last one is not a scene test, it is a leak test, and it is the reason this
file leans harder than `test_stones_scene.py` does. An account list says who can
get into a host and how far in; read the wrong way round it is a target list.
The scene is convenience, `redaction.py` is the control, and the control is what
is asserted here.
"""

import copy
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appfixture import fresh_app, login_as  # noqa: E402

WEB = pathlib.Path(__file__).resolve().parent.parent
TPL = WEB / "templates" / "index.html"
CSS = WEB / "static" / "atlas.css"
JS = WEB / "static" / "js" / "accounts-scene.js"
UI = WEB / "static" / "js" / "ui.js"
BOOT = WEB / "static" / "js" / "atlas.js"
BUNDLED = str(WEB / "default-lab-data.json")

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

PW = "a-long-enough-password"


def _read(p):
    return p.read_text(encoding="utf-8")


# ── The scene exists end to end ──────────────────────────────────────────────

def test_the_scene_is_wired_from_band_to_module():
    """Every hop, because a break in any one of them is invisible until a human
    clicks the button and nothing happens."""
    html, ui, boot = _read(TPL), _read(UI), _read(BOOT)
    assert 'data-scene="accounts"' in html, "no band button"
    assert 'id="accounts"' in html, "no overlay"
    assert 'id="acc-close"' in html and 'id="acc-list"' in html, "no hooks"
    assert "import './accounts-scene.js';" in boot, "never imported"
    assert "A.buildAccountsScene();" in boot, "never built"
    assert "accounts: A.openAccounts" in ui, "not in the band's opener map"
    assert "A.closeAccounts?.();" in ui, "not in closeAllScenes — Escape would not reach it"


def test_the_module_is_not_named_account_js():
    """`account.js` is the signed-in viewer's own panel and has been since the
    ui.js split. Two files a character apart about different nouns is a trap for
    every future grep — the scene file spells out which one it is."""
    assert JS.exists()
    assert (WEB / "static" / "js" / "account.js").exists(), "the other one still exists"
    assert "account.js" not in _read(BOOT).split("accounts-scene.js")[0].split("\n")[-1]


def test_the_scene_has_no_inline_script():
    """The CSP kills inline JS silently — the scene would be dead in a browser
    while this suite stayed green."""
    html = _read(TPL)
    block = html.split('<div id="accounts"')[1].split("</div>")[0]
    assert "<script" not in block.lower()


def test_the_overlay_joins_the_shared_scene_chrome():
    """Not its own copy of the shell — the one rule, so it can never drift from
    the other scenes' geometry or z-index."""
    css = _read(CSS)
    # a rule of its own would start a line; `body.drawer-open #accounts {` must not count
    own = [l for l in css.splitlines() if l.strip().startswith("#accounts {")]
    assert not own, f"declared its own overlay instead of joining the list: {own}"
    # the list may grow past it (SETTINGS joined 2026-09-04) — membership, not tail
    assert re.search(r"#reliquary, #accounts(, #\w+)* \{", css), "not in the shared overlay rule"
    assert "#accounts.open" in css, "never becomes visible"
    assert "#accounts.open .ldg-panel" in css, "the panel never settles into its seat"
    assert "body.drawer-open #accounts" in css, "would cover the Index instead of ceding room"


def test_reduced_motion_covers_it():
    """the design notes: always a full prefers-reduced-motion fallback."""
    desk = _read(WEB / "static" / "desk.css")
    blocks = desk.split("@media (prefers-reduced-motion: reduce)")[1:]
    assert any("#accounts" in b.split("}")[0] for b in blocks), (
        "no reduced-motion block names #accounts")


# ── The band button is not offered to someone who cannot use it ──────────────

def test_the_button_ships_hidden_and_is_revealed_only_for_an_admin():
    """the design notes: never show a control the caller cannot use — offer the door
    instead. A non-admin who opened this would meet an empty scene reading
    'nothing charted yet', which is a lie by omission."""
    html, ui = _read(TPL), _read(UI)
    button = [l for l in html.splitlines() if 'data-scene="accounts"' in l][0]
    assert "hidden" in button, "the button ships visible to everyone"
    assert "canAdminWrite()" in ui and "scene-accounts" in ui, "nothing ever reveals it"


# ── The control: the roster must not reach an uncleared viewer ───────────────

#: One account that is exactly the finding this scene exists to workstation.
ROSTER = [{"name": "ops", "source": "local", "sudo": "nopasswd",
           "groups": ["docker-admins"], "note": "the break-glass account"}]


def test_redaction_strips_the_roster_for_an_uncleared_viewer(monkeypatch):
    import redaction
    data = {"nodes": [{"id": "a", "name": "A", "accounts": copy.deepcopy(ROSTER)},
                      {"id": "b", "name": "B", "accounts": copy.deepcopy(ROSTER)}]}
    monkeypatch.setattr(redaction, "viewer_groups", lambda: ["HL-Viewers"])
    out, _ = redaction.redact_for_groups(data)
    for n in out["nodes"]:
        assert "accounts" not in n, "the roster rode along inside a visible node"
    # and the caller's own copy is untouched — the redactor deep-copies
    assert data["nodes"][0]["accounts"], "redaction mutated the source dataset"


def test_an_admin_still_sees_the_roster(monkeypatch):
    import redaction
    data = {"nodes": [{"id": "a", "name": "A", "accounts": copy.deepcopy(ROSTER)}]}
    monkeypatch.setattr(redaction, "viewer_groups", lambda: ["atlas-admins"])
    out, _ = redaction.redact_for_groups(data)
    assert out["nodes"][0]["accounts"] == ROSTER


def test_it_fails_closed_on_an_unresolvable_identity(monkeypatch):
    """Hub mode resolves no groups to NO clearance rather than full clearance —
    that is `viewer_groups`' whole point. An empty list is not None."""
    import redaction
    data = {"nodes": [{"id": "a", "name": "A", "accounts": copy.deepcopy(ROSTER)}]}
    monkeypatch.setattr(redaction, "viewer_groups", lambda: [])
    out, _ = redaction.redact_for_groups(data)
    assert "accounts" not in out["nodes"][0]


def _dataset_with_roster():
    """Two places; the roster lives on the one everybody can see, because that
    is the leak that matters — a roster on a HIDDEN node is already gone with
    the node, and would prove nothing."""
    return {
        "meta": {"title": "Test Realm"},
        "zones": [],
        "nodes": [
            {"id": "public-place", "name": "Public", "kind": "physical",
             "x": 10, "y": 10, "links": [],
             "accounts": copy.deepcopy(ROSTER)},
        ],
        "routes": [], "rack": [], "vms": [], "rites": [], "certs": [],
    }


def test_the_roster_never_reaches_the_wire_for_a_plain_viewer(tmp_path):
    """End to end through the real read endpoint, not the redactor in isolation
    — the leak that matters is the one a browser could actually fetch."""
    import json
    path = tmp_path / "lab-data.json"
    path.write_text(json.dumps(_dataset_with_roster()), encoding="utf-8")
    handle = fresh_app(
        ATLAS_AUTH_MODE="accounts",
        ATLAS_DATA=str(path),
        ATLAS_ACCOUNTS_DB=str(tmp_path / "accounts.db"),
        ATLAS_SECRET_KEY="test-signing-key",
        ATLAS_INSECURE_COOKIES="1",
        ATLAS_DATA_BACKEND="file",
        ATLAS_AUTH_BACKENDS="local",
        ATLAS_MFA_REQUIRED="",
    )
    import accounts as store
    store.create_local_user("ops", PW, is_admin=True)
    store.create_local_user("alice", PW)

    admin = handle.app.test_client()
    login_as(admin, "ops", PW)
    seen = json.dumps(admin.get("/api/v2/lab-data").get_json())
    assert "nopasswd" in seen, (
        "premise failed: the admin could not see the roster either, so the "
        "assertion below would pass for the wrong reason")

    plain = handle.app.test_client()
    login_as(plain, "alice", PW)
    body = json.dumps(plain.get("/api/v2/lab-data").get_json())
    assert "nopasswd" not in body and "docker-admins" not in body, (
        "a plain viewer's lab-data carried account posture")
    assert "public-place" in body, "the node itself should still be visible"


def test_no_credential_field_exists_in_the_catalogue():
    """The doctrine, pinned: chart the posture, never a credential. A future
    `password`/`key`/`hash` field would make this scene a place to steal from."""
    import schema
    keys = {f["name"] for f in schema.ACCOUNT_FIELDS}
    forbidden = {"password", "pass", "secret", "key", "keys", "hash",
                 "credential", "credentials", "token", "private_key"}
    assert not (keys & forbidden), f"credential-shaped field in ACCOUNT_FIELDS: {keys & forbidden}"


def test_the_field_is_attached_to_nodes_as_objects():
    import schema
    node_fields = {f["name"]: f for f in schema.SECTIONS["nodes"]["fields"]}
    assert "accounts" in node_fields, "not on nodes"
    fld = node_fields["accounts"]
    assert fld["type"] == "objects", "must be an objects list so the Desk renders a sub-form"
    assert fld["of"] is schema.ACCOUNT_FIELDS
    assert {f["name"] for f in fld["of"]} >= {"name", "sudo", "source"}


def test_sudo_is_three_state_not_a_bool():
    """Flattening it loses the distinction the scene exists to draw: the account
    that must type a password, and the one that never does."""
    import schema
    sudo = [f for f in schema.ACCOUNT_FIELDS if f["name"] == "sudo"][0]
    assert sudo["type"] == "select"
    assert sudo["options"] == ["none", "password", "nopasswd"]


def test_a_roster_validates_clean(tmp_path):
    """A charted roster must not raise a dataset problem — otherwise the Desk
    refuses the write (dataset.py validates strict=True before landing)."""
    import json
    import schema
    import validation
    data = json.loads(pathlib.Path(BUNDLED).read_text(encoding="utf-8"))
    data["nodes"][0]["accounts"] = copy.deepcopy(ROSTER)
    problems = validation.validate(data)
    assert not problems, problems


def test_a_nameless_account_is_refused(tmp_path):
    """`name` is required — an unnamed row in an access roster is worse than no
    row, because it still occupies a line that reads as surveyed."""
    import json
    import validation
    data = json.loads(pathlib.Path(BUNDLED).read_text(encoding="utf-8"))
    data["nodes"][0]["accounts"] = [{"sudo": "nopasswd"}]
    problems = validation.validate(data)
    assert any("accounts" in str(p) for p in problems), problems
