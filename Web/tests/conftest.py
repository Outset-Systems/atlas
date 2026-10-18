"""Shared test setup.

Two things, both about isolation.

**A writable temp root.** `tmp_path` defaults under the system temp directory,
which is not always writable in a sandbox, and several suites want a scratch
dataset. `pytest.ini` points `--basetemp` at a directory beside the tests.

**Environment that no suite should inherit.** Each test module sets its own
db/ingest configuration at import time, because `app.py` used to read config
at import. That is why the suite passes file by file and fails as a whole:
whichever module imports `app` first decides the backend for the entire run.

`create_app()` now exists, so a module *can* build its own app — but the
existing suites predate it and still import the module-level `app`. Rather
than rewrite ten files, this fixture records the environment before each
module and restores it after, which stops one suite's settings leaking into
the next module's import.
"""

import os
import sys

import pytest

#: THE THEME (v1.48.0). The suite runs as the internal image does (its
#: Dockerfile stage sets ATLAS_THEME=lab): several suites key on the real
#: lab's wording. test_theme.py covers the plain theme on its own. Set before
#: anything imports settings, which reads the theme at import.
os.environ.setdefault("ATLAS_THEME", "lab")
#: NAMES THAT CHANGED (v1.48.0). The suite speaks the neutral names even where
#: legacy_names.py would hand the old deployment its old header and group
#: defaults, so the same suite passes with or without that private file.
#: test_envnames.py covers the old names on their own.
os.environ.setdefault("ATLAS_HUB_AUTH_HEADER", "X-Hub-Auth")
os.environ.setdefault("ATLAS_DECOYS_KEY_HEADER", "X-Api-Key")
os.environ.setdefault("ATLAS_ADMIN_GROUP", "atlas-admins")

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WEB not in sys.path:
    sys.path.insert(0, WEB)

#: Variables a test module may set for itself and must not leave behind.
ATLAS_ENV = [
    "ATLAS_DATA", "ATLAS_DATA_BACKEND", "ATLAS_DB_URL", "ATLAS_SITE",
    "ATLAS_POSITIONS", "ATLAS_RACK", "ATLAS_REVISIONS", "ATLAS_OBSERVED",
    "ATLAS_REPORTS", "ATLAS_MAINTENANCE", "ATLAS_INGEST_ENABLED",
    "ATLAS_BEATS", "ATLAS_BEATS_DIR", "ATLAS_BEAT_TOKEN", "ATLAS_BEAT_TOKEN_FILE",
    "ATLAS_SIGNALS_SOURCES", "ATLAS_SIGNALS_FILE", "ATLAS_READONLY",
    "ATLAS_FALLBACK", "ATLAS_ALLOW_INSECURE",
    "ATLAS_EMBED_HOSTS", "ATLAS_EMBED_SERVICES", "ATLAS_EMBED_PROBE",
    "ATLAS_SCROLL_ROOT", "ATLAS_AUTH_MODE", "ATLAS_PROM_URL", "ATLAS_LOKI_URL",
    # THE SOURCES (integrations.py) — the file and the env it layers over
    "ATLAS_INTEGRATIONS", "ATLAS_KUMA_URL", "ATLAS_KUMA_API_KEY", "ATLAS_KUMA_API_KEY_FILE",
    "ATLAS_DECOYS_URL", "ATLAS_DECOYS_KEY", "ATLAS_DECOYS_KEY_FILE",
    # accounts mode (atlas_auth.py / accounts.py / ldap_backend.py)
    "ATLAS_ACCOUNTS_DB", "ATLAS_SECRET_KEY", "ATLAS_SECRET_KEY_FILE",
    "ATLAS_ENCRYPTION_KEY", "ATLAS_ENCRYPTION_KEY_FILE",
    "ATLAS_AUTH_BACKENDS", "ATLAS_MFA_REQUIRED", "ATLAS_TRUSTED_PROXIES",
    "ATLAS_INSECURE_COOKIES", "ATLAS_SESSION_IDLE_MIN", "ATLAS_SESSION_ABS_HOURS",
    "ATLAS_BOOTSTRAP_ADMIN_USER", "ATLAS_BOOTSTRAP_ADMIN_PASSWORD",
    "ATLAS_BOOTSTRAP_ADMIN_PASSWORD_FILE",
    "ATLAS_LDAP_URL", "ATLAS_LDAP_BASE_DN", "ATLAS_LDAP_UPN_DOMAIN",
    "ATLAS_LDAP_CA_FILE", "ATLAS_LDAP_ACCESS_GROUPS", "ATLAS_LDAP_ADMIN_GROUPS",
    "ATLAS_LDAP_TIMEOUT",
]


@pytest.fixture(autouse=True)
def _atlas_env(request):
    """Give each test the environment its own module declared.

    pytest imports every test module before running any test, so the module
    that happened to import last owned `os.environ` for the whole run — and
    `store.session_scope()` reads `ATLAS_DB_URL` live, which is why suites
    passed alone and 401'd together. Each module now declares `ATLAS_TEST_ENV`
    and it is re-applied here, per test.
    """
    declared = getattr(request.module, "ATLAS_TEST_ENV", None)
    if not declared:
        yield
        return
    before = {name: os.environ.get(name) for name in ATLAS_ENV}
    os.environ.update({k: str(v) for k, v in declared.items()})
    yield
    for name, value in before.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture
def dataset_dir(tmp_path):
    """An empty directory to point ATLAS_DATA at."""
    out = tmp_path / "data"
    out.mkdir()
    return out


# ── Private-only tests ───────────────────────────────────────────────────────
#: True in the original deployment's own repo, False in the public tree (which
#: never carries legacy_names.py). A test marked `private_only` checks a file
#: or a dataset that exists only there, such as the proxy trust map or the
#: real map's own rites, and is skipped everywhere else.
PRIVATE_TREE = os.path.exists(os.path.join(WEB, "legacy_names.py"))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "private_only: needs the original deployment's private files or dataset")


def pytest_collection_modifyitems(config, items):
    if PRIVATE_TREE:
        return
    skip = pytest.mark.skip(reason="private tree only (not part of the public build)")
    for item in items:
        if "private_only" in item.keywords:
            item.add_marker(skip)
