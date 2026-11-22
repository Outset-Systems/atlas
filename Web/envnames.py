import logging
import os

log = logging.getLogger("atlas.settings")

try:
    from legacy_names import DEFAULTS as _LEGACY_DEFAULTS
    from legacy_names import OLD_NAMES as _OLD_NAMES
except ImportError:
    _OLD_NAMES, _LEGACY_DEFAULTS = {}, {}

DEFAULTS = {
    "ATLAS_HUB_AUTH_HEADER": "X-Hub-Auth",
    "ATLAS_DECOYS_KEY_HEADER": "X-Api-Key",
    "ATLAS_ADMIN_GROUP": "atlas-admins",
    "ATLAS_LLM_CONTAINERS": ".+",
    "ATLAS_LLM_LOG_TAG": "llm",
}


YES = ("1", "true", "yes", "on")
NO = ("0", "false", "no", "off")


def yes_no(raw):
    word = str(raw if raw is not None else "").strip().lower()
    if word in YES:
        return True
    if word in NO:
        return False
    return None


def old_name(name):
    return _OLD_NAMES.get(name)


def new_name(name):
    for new, old in _OLD_NAMES.items():
        if old == name:
            return new
    return name


def default(name, fallback=None):
    if name in _LEGACY_DEFAULTS:
        return _LEGACY_DEFAULTS[name]
    return DEFAULTS.get(name, fallback)


def env(name, fallback=None):
    old = _OLD_NAMES.get(name)
    if name in os.environ:
        if os.environ[name] == "" and old and os.environ.get(old):
            return os.environ[old]
        return os.environ[name]
    if old and old in os.environ:
        return os.environ[old]
    return default(name, fallback)


def is_set(name):
    old = _OLD_NAMES.get(name)
    return name in os.environ or bool(old and old in os.environ)


def secret(name, default=""):
    value = (env(name) or "").strip()
    if value:
        return value
    path = (env(name + "_FILE") or "").strip()
    if not path:
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            value = fh.read().strip()
    except OSError as e:
        log.warning("could not read %s_FILE (%s): %s", name, path, e)
        return default
    log.debug("%s read from %s", name, path)
    return value or default
