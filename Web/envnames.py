"""NAMES THAT CHANGED (v1.48.0) — one place that reads a renamed setting.

The Atlas grew up inside one lab's app suite, so some of its settings, headers
and groups were named after that suite. They now have neutral names:

  ATLAS_AUTH_MODE          standalone | accounts | hub | hybrid
  ATLAS_HUB_SECRET(_FILE)  the shared secret that signs the Hub's identity header
  ATLAS_HUB_AUTH_HEADER    which header carries that signed identity
  ATLAS_ADMIN_GROUP        the group that makes a viewer an Atlas admin
  ATLAS_DECOYS_URL / _KEY / _KEY_FILE / _KEY_HEADER / _PATH   the decoy feed
                           (one TRIPWIRES source; _PATH is new, default /api/stones)
  ATLAS_STANDALONE_USER / _EMAIL / _GROUPS            who "you" are in standalone

`env(name)` reads the new name first. A deployment that still carries the old
names keeps working only where `legacy_names.py` sits beside this file: it maps
each new name to its old one and supplies the old defaults (the suite's header
and group names). That file is private to the original deployment and never
ships in the public image or repository, so a fresh install knows only the
neutral names and neutral defaults below.

`secret(name)` is the one reader for a value that may arrive as a docker
secret: `NAME`, else the contents of the file `NAME_FILE` names. Every module
that takes a token or a key reads it through here (settings.beat_token,
tripwires.secret, signals._read_secret, integrations._env, metrics._token,
app's session key, the bootstrap admin password; hub_auth.auth keeps its own
because its secret is not optional). `crypto_at_rest` keeps its stricter reader on purpose — a
master key that cannot be read must stop the app, not fall back to "".
"""
import logging
import os

log = logging.getLogger("atlas.settings")

try:  # the original deployment's old names; absent from public builds
    from legacy_names import DEFAULTS as _LEGACY_DEFAULTS
    from legacy_names import OLD_NAMES as _OLD_NAMES
except ImportError:  # pragma: no cover - exercised by the public image
    _OLD_NAMES, _LEGACY_DEFAULTS = {}, {}

#: Neutral defaults for the settings that used to be hard-coded.
DEFAULTS = {
    "ATLAS_HUB_AUTH_HEADER": "X-Hub-Auth",
    "ATLAS_DECOYS_KEY_HEADER": "X-Api-Key",
    "ATLAS_ADMIN_GROUP": "atlas-admins",
    "ATLAS_LLM_CONTAINERS": ".+",
    "ATLAS_LLM_LOG_TAG": "llm",
}


def old_name(name):
    """The pre-1.48 name for `name`, or None (always None in a public build)."""
    return _OLD_NAMES.get(name)


def new_name(name):
    """The current name for a possibly-old `name` (identity when not renamed)."""
    for new, old in _OLD_NAMES.items():
        if old == name:
            return new
    return name


def default(name, fallback=None):
    """The default in force for `name` when nothing sets it."""
    if name in _LEGACY_DEFAULTS:
        return _LEGACY_DEFAULTS[name]
    return DEFAULTS.get(name, fallback)


def env(name, fallback=None):
    """The environment's value for `name`: the new name, then its old name,
    then the default (legacy first, then neutral), then `fallback`."""
    if name in os.environ:
        return os.environ[name]
    old = _OLD_NAMES.get(name)
    if old and old in os.environ:
        return os.environ[old]
    return default(name, fallback)


def is_set(name):
    """True when the deployment names `name` under either spelling."""
    old = _OLD_NAMES.get(name)
    return name in os.environ or bool(old and old in os.environ)


def secret(name, default=""):
    """A secret from the environment: `name`'s value, else the contents of the
    file `name + "_FILE"` names (the docker-secret convention), stripped.
    `default` when neither is set, or when the named file cannot be read —
    which is logged, because a secret silently reading as "" looks like
    "unset" and sends someone to the wrong place. Old names are honoured
    for both spellings, as `env()` does. The value itself is never logged."""
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
