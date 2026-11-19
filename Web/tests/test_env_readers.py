"""How a switch and a number are read from the environment (settings.py).

One place parses each kind, and none of them can stop the boot: a value that
cannot be used means the safe reading, and a line at startup saying so.
"""

import importlib
import logging

import pytest

ATLAS_TEST_ENV = {"ATLAS_AUTH_MODE": "standalone"}


@pytest.fixture
def settings(monkeypatch):
    """`settings` as a fresh import would make it, and again afterwards."""
    import settings as module
    yield module
    monkeypatch.undo()
    importlib.reload(module)


def _reloaded(module, monkeypatch, **env):
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return importlib.reload(module)


# ── the words ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("word", ["1", "true", "TRUE", "yes", "on", " On "])
def test_a_yes_word_is_yes(word):
    import envnames
    assert envnames.yes_no(word) is True


@pytest.mark.parametrize("word", ["0", "false", "No", "off", " OFF"])
def test_a_no_word_is_no(word):
    import envnames
    assert envnames.yes_no(word) is False


@pytest.mark.parametrize("word", ["", "  ", None, "maybe", "2", "enabled"])
def test_anything_else_is_neither(word):
    import envnames
    assert envnames.yes_no(word) is None


# ── a switch ─────────────────────────────────────────────────────────────────

def test_an_unset_or_empty_switch_is_its_default(settings, monkeypatch):
    monkeypatch.delenv("ATLAS_X_SWITCH", raising=False)
    assert settings.env_flag("ATLAS_X_SWITCH") is False
    assert settings.env_flag("ATLAS_X_SWITCH", default=True) is True
    monkeypatch.setenv("ATLAS_X_SWITCH", "  ")
    assert settings.env_flag("ATLAS_X_SWITCH", default=True) is True
    assert settings.ENV_REJECTED == []


def test_a_switch_takes_any_yes_or_no_word(settings, monkeypatch):
    for word, said in (("yes", True), ("TRUE", True), ("on", True), ("no", False), ("0", False)):
        monkeypatch.setenv("ATLAS_X_SWITCH", word)
        assert settings.env_flag("ATLAS_X_SWITCH", default=not said) is said
    assert settings.ENV_REJECTED == []


def test_a_word_that_is_neither_is_the_safe_reading_and_is_noted(settings, monkeypatch):
    monkeypatch.setenv("ATLAS_X_SWITCH", "maybe")
    assert settings.env_flag("ATLAS_X_SWITCH") is False
    assert settings.env_flag("ATLAS_X_SWITCH", unknown=True) is True
    assert ("ATLAS_X_SWITCH", "maybe", "off") in settings.ENV_REJECTED
    assert ("ATLAS_X_SWITCH", "maybe", "on") in settings.ENV_REJECTED


def test_a_switch_that_removes_a_protection_takes_exactly_1(settings, monkeypatch):
    """`true` never turned one of these on, and must not start to: an install
    that wrote it has been shut ever since."""
    monkeypatch.setenv("ATLAS_X_SWITCH", "1")
    assert settings.env_flag("ATLAS_X_SWITCH", strict=True) is True
    monkeypatch.setenv("ATLAS_X_SWITCH", "0")
    assert settings.env_flag("ATLAS_X_SWITCH", strict=True) is False
    assert settings.ENV_REJECTED == []
    for word in ("true", "yes", "on", " 1", "TRUE"):
        monkeypatch.setenv("ATLAS_X_SWITCH", word)
        assert settings.env_flag("ATLAS_X_SWITCH", strict=True) is False
        assert ("ATLAS_X_SWITCH", word, "off") in settings.ENV_REJECTED


@pytest.mark.parametrize("name,attribute", [
    ("ATLAS_ALLOW_INSECURE", "ALLOW_INSECURE"),
    ("ATLAS_DEBUG", "DEBUG"),
    ("ATLAS_INGEST_ENABLED", "INGEST_ENABLED"),
])
def test_the_switches_that_open_something_stay_shut_on_true(settings, monkeypatch, name, attribute):
    module = _reloaded(settings, monkeypatch, **{name: "true"})
    assert getattr(module, attribute) is False
    assert (name, "true", "off") in module.ENV_REJECTED
    module = _reloaded(settings, monkeypatch, **{name: "1"})
    assert getattr(module, attribute) is True
    assert module.ENV_REJECTED == []


def test_a_rejected_value_is_noted_once(settings, monkeypatch):
    monkeypatch.setenv("ATLAS_X_SWITCH", "maybe")
    for _ in range(3):
        settings.env_flag("ATLAS_X_SWITCH")
    assert settings.ENV_REJECTED.count(("ATLAS_X_SWITCH", "maybe", "off")) == 1


# ── a number ─────────────────────────────────────────────────────────────────

def test_a_number_that_cannot_be_used_is_the_default_and_is_noted(settings, monkeypatch):
    monkeypatch.setenv("ATLAS_X_NUMBER", "ten")
    assert settings.env_int("ATLAS_X_NUMBER", 5, 1) == 5
    monkeypatch.setenv("ATLAS_X_NUMBER", "0")
    assert settings.env_int("ATLAS_X_NUMBER", 5, 1) == 5
    assert settings.env_int("ATLAS_X_NUMBER", 5, 1, zero_off=True) == 0
    assert ("ATLAS_X_NUMBER", "ten", "5") in settings.ENV_REJECTED
    assert ("ATLAS_X_NUMBER", "0", "5") in settings.ENV_REJECTED


def test_an_empty_number_is_the_default_and_nothing_is_noted(settings, monkeypatch):
    monkeypatch.setenv("ATLAS_X_NUMBER", "")
    assert settings.env_int("ATLAS_X_NUMBER", 5, 1) == 5
    assert settings.ENV_REJECTED == []


# ── said at startup ──────────────────────────────────────────────────────────

def test_the_app_says_what_it_could_not_use(monkeypatch, caplog):
    """`settings` is imported before logging is configured, so it only keeps
    the list; `app.py` is what says it."""
    import settings as module
    monkeypatch.setenv("ATLAS_DEBUG", "true")
    importlib.reload(module)
    try:
        import app
        with caplog.at_level(logging.WARNING, logger="atlas.web.app"):
            importlib.reload(app)
        assert any("ATLAS_DEBUG='true'" in record.getMessage() and "using off" in record.getMessage()
                   for record in caplog.records)
    finally:
        monkeypatch.undo()
        importlib.reload(module)
        importlib.reload(app)


# ── ATLAS_READONLY (audit 2026-11-12, Foundations 1) ─────────────────────────

@pytest.mark.parametrize("word", ["1", "true", "yes", "on", "TRUE"])
def test_any_yes_word_makes_the_instance_read_only(settings, monkeypatch, word):
    module = _reloaded(settings, monkeypatch, ATLAS_AUTH_MODE="accounts", ATLAS_READONLY=word)
    assert module.READ_ONLY is True
    assert module.ENV_REJECTED == []


@pytest.mark.parametrize("word", ["0", "false", "no", "off"])
def test_any_no_word_makes_it_writable_even_standalone(settings, monkeypatch, word):
    module = _reloaded(settings, monkeypatch, ATLAS_AUTH_MODE="standalone",
                       ATLAS_ALLOW_INSECURE=None, ATLAS_READONLY=word)
    assert module.READ_ONLY is False


def test_a_word_that_is_neither_is_read_only_and_is_noted(settings, monkeypatch):
    module = _reloaded(settings, monkeypatch, ATLAS_AUTH_MODE="accounts", ATLAS_READONLY="maybe")
    assert module.READ_ONLY is True
    assert ("ATLAS_READONLY", "maybe", "on") in module.ENV_REJECTED


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_read_only_is_no_value_at_all(settings, monkeypatch, empty):
    """A compose file's `${ATLAS_READONLY:-}` hands the app an empty string.
    That is the posture's own answer, not "said, and not 1"."""
    module = _reloaded(settings, monkeypatch, ATLAS_AUTH_MODE="standalone",
                       ATLAS_ALLOW_INSECURE=None, ATLAS_READONLY=empty)
    assert module.READ_ONLY is True          # standalone with nothing said is look-only
    module = _reloaded(settings, monkeypatch, ATLAS_AUTH_MODE="standalone",
                       ATLAS_ALLOW_INSECURE="1", ATLAS_READONLY=empty)
    assert module.READ_ONLY is False
    module = _reloaded(settings, monkeypatch, ATLAS_AUTH_MODE="accounts",
                       ATLAS_ALLOW_INSECURE=None, ATLAS_READONLY=empty)
    assert module.READ_ONLY is False


# ── ATLAS_MFA_REQUIRED (audit 2026-11-12, Auth 4) ────────────────────────────

ADMIN = {"is_admin": True, "source": "local"}
PLAIN = {"is_admin": False, "source": "ldap"}


def _fenced(monkeypatch, policy):
    import atlas_auth
    monkeypatch.setenv("ATLAS_MFA_REQUIRED", policy)
    return atlas_auth.mfa_policy_applies(ADMIN), atlas_auth.mfa_policy_applies(PLAIN)


@pytest.mark.parametrize("policy", ["true", "TRUE", "1", "yes", "on", "all"])
def test_a_yes_word_requires_a_second_factor_of_everyone(monkeypatch, policy):
    assert _fenced(monkeypatch, policy) == (True, True)


@pytest.mark.parametrize("policy", ["", "0", "false", "no", "off"])
def test_a_no_word_requires_it_of_nobody(monkeypatch, policy):
    assert _fenced(monkeypatch, policy) == (False, False)


def test_the_named_policies_still_mean_what_they_meant(monkeypatch):
    assert _fenced(monkeypatch, "admins") == (True, False)
    assert _fenced(monkeypatch, "admin") == (True, False)
    assert _fenced(monkeypatch, "local") == (True, False)
    assert _fenced(monkeypatch, "ldap") == (False, True)


def test_a_policy_that_names_nothing_fences_everyone_and_says_so(monkeypatch, caplog):
    import atlas_auth
    atlas_auth._mfa_policy_warned.clear()
    with caplog.at_level(logging.WARNING, logger="atlas.auth.gate"):
        assert _fenced(monkeypatch, "everybody") == (True, True)
        assert _fenced(monkeypatch, "everybody") == (True, True)
    said = [r for r in caplog.records if "names no policy" in r.getMessage()]
    assert len(said) == 1 and "'everybody'" in said[0].getMessage()


# ── numbers and the log level at startup (audit 2026-11-12, Foundations 8) ───

def test_a_lowercase_log_level_is_accepted(settings, monkeypatch):
    """`basicConfig(level="debug")` raises, so this used to stop the boot."""
    module = _reloaded(settings, monkeypatch, ATLAS_LOG_LEVEL="debug")
    assert module.LOG_LEVEL == "DEBUG"
    assert module.ENV_REJECTED == []
    logging.getLogger("atlas.test.level").setLevel(module.LOG_LEVEL)


def test_a_log_level_logging_does_not_know_is_info_and_is_noted(settings, monkeypatch):
    module = _reloaded(settings, monkeypatch, ATLAS_LOG_LEVEL="chatty")
    assert module.LOG_LEVEL == "INFO"
    assert ("ATLAS_LOG_LEVEL", "chatty", "INFO") in module.ENV_REJECTED
    # a name `logging` has that is not a level must not pass for one
    module = _reloaded(settings, monkeypatch, ATLAS_LOG_LEVEL="getLogger")
    assert module.LOG_LEVEL == "INFO"


@pytest.mark.parametrize("name,attribute,default", [
    ("ATLAS_PORT", "PORT", 5006),
    ("ATLAS_LOGIN_MAX_USER", "LOGIN_MAX_USER", 5),
    ("ATLAS_LOGIN_MAX_IP", "LOGIN_MAX_IP", 20),
    ("ATLAS_LOGIN_WINDOW_MIN", "LOGIN_WINDOW_S", 15 * 60),
    ("ATLAS_SESSION_IDLE_MIN", "SESSION_IDLE_S", 60 * 60),
    ("ATLAS_SESSION_ABS_HOURS", "SESSION_ABS_S", 12 * 3600),
])
def test_a_startup_number_that_cannot_be_used_is_its_default(settings, monkeypatch,
                                                              name, attribute, default):
    for bad in ("", "soon", "0", "-3", "1.5"):
        module = _reloaded(settings, monkeypatch, **{name: bad})
        assert getattr(module, attribute) == default, bad
        assert bool(module.ENV_REJECTED) is (bad != ""), bad


def test_a_startup_number_that_is_one_is_used(settings, monkeypatch):
    module = _reloaded(settings, monkeypatch, ATLAS_LOGIN_MAX_USER="9",
                       ATLAS_SESSION_IDLE_MIN="2", ATLAS_PORT="8080")
    assert (module.LOGIN_MAX_USER, module.SESSION_IDLE_S, module.PORT) == (9, 120, 8080)
    assert module.ENV_REJECTED == []
