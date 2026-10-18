"""The cutover guard — the front end, the HEALTHCHECK and the relay speak v2,
and the server has nothing else left to speak.

The 2026-08-25 cutover flipped every in-repo consumer from `api/...` to
`api/v2/...` (the API migration plan, cutover phase); v1.41.0 removed the v1 routes
themselves. This pins both: a v1 literal creeping back into a fetch would 404
now, and a v1-shaped route creeping back into the url map would be a second
surface with no test in front of it.

`/api/status` is deliberately the exception: it is the fleet-wide the suite card
contract (the Hub and Kuma probe it on every app), so it stays until that
contract changes fleet-wide.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(WEB)

ATLAS_TEST_ENV = {"ATLAS_DATA_BACKEND": "file", "ATLAS_ALLOW_INSECURE": "1",
                  "ATLAS_AUTH_MODE": "standalone"}

#: A network call aimed at a non-v2 api path. Matches the app's three calling
#: idioms (fetch / the login page's post / account.js's authPost/authApi).
V1_CALL = re.compile(r"""(?:[fF]etch|post|authPost|authApi)\([`'"]/?api/(?!v2/)""")


def _js_files():
    for root, _dirs, files in os.walk(os.path.join(WEB, "static", "js")):
        if root.endswith("vendor"):
            continue
        for name in files:
            if name.endswith(".js"):
                yield os.path.join(root, name)


def test_no_front_end_call_reaches_v1():
    offenders = []
    for path in _js_files():
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if V1_CALL.search(line):
                    offenders.append(f"{os.path.relpath(path, WEB)}:{lineno}: "
                                     f"{line.strip()[:100]}")
    assert offenders == [], (
        "front-end calls still aimed at v1 (the cutover moved everything to "
        "api/v2/):\n  " + "\n  ".join(offenders))


def test_healthcheck_probes_v2():
    # the image ships /app (= Web/) only — this guard runs on the source tree
    if not os.path.isfile(os.path.join(ROOT, "Dockerfile")):
        pytest.skip("Dockerfile not shipped inside the image")
    with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as fh:
        dockerfile = fh.read()
    assert "/api/v2/health" in dockerfile
    assert "5006/api/status" not in dockerfile


def test_the_server_serves_only_v2_and_the_card_contract():
    """Every `/api/` rule is under `/api/v2/`, or is `/api/status`. The four
    v1 route modules are gone from the tree, not merely unregistered."""
    import shutil
    from appfixture import fresh_app
    import tempfile
    tmp = tempfile.mkdtemp(prefix="atlas-cutover-")
    data = os.path.join(tmp, "lab-data.json")
    shutil.copy(os.path.join(WEB, "default-lab-data.json"), data)
    handle = fresh_app(ATLAS_AUTH_MODE="accounts", ATLAS_DATA=data,
                       ATLAS_ACCOUNTS_DB=os.path.join(tmp, "accounts.db"),
                       ATLAS_SECRET_KEY="k", ATLAS_INSECURE_COOKIES="1",
                       ATLAS_DATA_BACKEND="file")
    api_rules = sorted(r.rule for r in handle.app.url_map.iter_rules()
                       if r.rule.startswith("/api/"))
    # The two fleet-contract addresses stay unversioned on purpose: the card
    # (`/api/status`, Kuma + the Hub) and the manifest (`/api/manifest`,
    # APP_MANIFEST.md — the Hub reads `<url>/api/manifest` on every app).
    contract = {"/api/status", "/api/manifest"}
    strays = [r for r in api_rules if not r.startswith("/api/v2/") and r not in contract]
    assert strays == [], f"unversioned API routes are back: {strays}"
    assert contract <= set(api_rules)
    for name in ("api_v1.py", "api_data.py", "api_admin.py", "api_whois.py"):
        assert not os.path.exists(os.path.join(WEB, name)), f"{name} is back"


def test_relay_client_speaks_v2():
    if not os.path.isfile(os.path.join(ROOT, "relay", "atlas_relay.py")):
        pytest.skip("relay client not shipped inside the image")
    with open(os.path.join(ROOT, "relay", "atlas_relay.py"), encoding="utf-8") as fh:
        relay = fh.read()
    for path in ("/api/v2/ingest/signals", "/api/v2/ingest/inventory",
                 "/api/v2/ingest/observed"):
        assert path in relay
    assert '"/api/v1/ingest/' not in relay
