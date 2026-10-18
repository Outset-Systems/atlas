"""NAMES THAT CHANGED (v1.48.0): the neutral names win, and the original
deployment's old names keep working only where legacy_names.py exists."""
import importlib
import json

import pytest

import envnames

try:
    import legacy_names
except ImportError:  # the public tree ships without it
    legacy_names = None

needs_legacy = pytest.mark.skipif(legacy_names is None, reason="public build: no legacy names")

RENAMED = ["ATLAS_AUTH_MODE", "ATLAS_HUB_SECRET", "ATLAS_HUB_SECRET_FILE",
           "ATLAS_DECOYS_URL", "ATLAS_DECOYS_KEY", "ATLAS_DECOYS_KEY_FILE",
           "ATLAS_STANDALONE_USER", "ATLAS_STANDALONE_EMAIL", "ATLAS_STANDALONE_GROUPS"]


@pytest.fixture
def clean_env(monkeypatch):
    for new in RENAMED + list(envnames.DEFAULTS):
        monkeypatch.delenv(new, raising=False)
        old = envnames.old_name(new)
        if old:
            monkeypatch.delenv(old, raising=False)
    return monkeypatch


def test_new_name_is_read(clean_env):
    clean_env.setenv("ATLAS_AUTH_MODE", "accounts")
    assert envnames.env("ATLAS_AUTH_MODE") == "accounts"


def test_neutral_defaults_name_no_suite(clean_env, monkeypatch):
    monkeypatch.setattr(envnames, "_LEGACY_DEFAULTS", {})
    assert envnames.env("ATLAS_HUB_AUTH_HEADER") == "X-Hub-Auth"
    assert envnames.env("ATLAS_DECOYS_KEY_HEADER") == "X-Api-Key"
    assert envnames.env("ATLAS_ADMIN_GROUP") == "atlas-admins"


def test_unrelated_names_pass_through(clean_env):
    clean_env.setenv("ATLAS_PROM_URL", "http://prometheus.home.example:9090")
    assert envnames.env("ATLAS_PROM_URL") == "http://prometheus.home.example:9090"
    assert envnames.env("ATLAS_NOT_A_THING", "fallback") == "fallback"


def test_hub_auth_reads_the_configured_header(clean_env):
    """The signed-identity header name comes from ATLAS_HUB_AUTH_HEADER at import."""
    import hub_auth.auth as auth
    clean_env.setenv("ATLAS_HUB_AUTH_HEADER", "X-Test-Identity")
    try:
        importlib.reload(auth)
        assert auth.SIGNED_HEADER == "X-Test-Identity"
    finally:
        clean_env.setenv("ATLAS_HUB_AUTH_HEADER", "X-Hub-Auth")
        importlib.reload(auth)
