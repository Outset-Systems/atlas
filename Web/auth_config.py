"""Directory (AD/LDAPS) settings an operator can edit from THE SETTINGS.

Until now every one of these was environment-only, which meant changing which
AD group may sign in was a redeploy. This module adds a small persisted layer
*over* the environment: `ldap_backend._cfg` asks here first and falls back to
`os.environ`, so one seam makes the whole backend configurable and no call site
changed.

Three deliberate constraints, because this file decides who may sign in and who
is an admin:

  * **An allowlist, never arbitrary keys.** Only the directory settings below
    can be written. Without that, "save these settings" would be a route that
    can set `ATLAS_ALLOW_INSECURE` or `ATLAS_READONLY` and turn the editor's
    own config screen into a way to disable the gate guarding it.
  * **The file overrides the environment, and says so.** An operator editing a
    field and seeing the old value win would be worse than not offering the
    field; `sources()` reports which layer each value came from so the UI can
    show it.
  * **No secret lives here.** `ldap_backend.authenticate` binds AS THE USER —
    there is no service account and no stored bind password, so this file holds
    nothing that needs encrypting. If a service bind is ever added, its password
    belongs in `crypto_at_rest`, not in this JSON.

Written with the same atomic writer the dataset uses, so a half-written config
cannot leave an instance unable to authenticate anyone.
"""

import json
import logging
import os
import threading

import settings

log = logging.getLogger("atlas.auth.config")

#: The only keys that may be persisted. Anything else is refused — see above.
ALLOWED = (
    "ATLAS_AUTH_BACKENDS",
    "ATLAS_LDAP_URL",
    "ATLAS_LDAP_BASE_DN",
    "ATLAS_LDAP_UPN_DOMAIN",
    "ATLAS_LDAP_CA_FILE",
    "ATLAS_LDAP_ACCESS_GROUPS",
    "ATLAS_LDAP_ADMIN_GROUPS",
    "ATLAS_LDAP_TIMEOUT",
)

_lock = threading.Lock()
_cache = {"mtime": None, "data": {}}


def path():
    return os.environ.get("ATLAS_AUTH_CONFIG") or os.path.join(
        settings.DATA_DIR, "auth-config.json")


def _load():
    """The persisted overrides, re-read when the file changes on disk."""
    p = path()
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        _cache["mtime"], _cache["data"] = None, {}
        return {}
    if _cache["mtime"] != mtime:
        try:
            with open(p, encoding="utf-8") as fh:
                loaded = json.load(fh)
            _cache["data"] = {k: v for k, v in loaded.items() if k in ALLOWED}
            _cache["mtime"] = mtime
        except (OSError, ValueError):
            # A broken file must not lock everyone out: fall through to the
            # environment, which is what the instance booted with.
            log.warning("auth-config unreadable, falling back to the environment",
                        exc_info=True)
            return {}
    return _cache["data"]


def get(name, default=""):
    """The persisted value for `name`, or '' so callers fall back to env."""
    if name not in ALLOWED:
        return default
    value = _load().get(name)
    return default if value is None else str(value)


def sources():
    """{key: 'settings' | 'deployment' | 'unset'} — where each value comes from,
    so the form can say which layer an operator is actually looking at."""
    stored = _load()
    out = {}
    for key in ALLOWED:
        if stored.get(key):
            out[key] = "settings"
        elif os.environ.get(key):
            out[key] = "deployment"
        else:
            out[key] = "unset"
    return out


def effective():
    """Every directory setting as the backend will actually read it."""
    stored = _load()
    return {k: (stored.get(k) or os.environ.get(k) or "") for k in ALLOWED}


def save(values):
    """Persist `values` (allowlisted keys only). Returns the effective config.

    Validation lives in the API layer, which knows the caller and can refuse a
    config that would lock the instance out; this function is the writer.
    """
    clean = {}
    for key, raw in (values or {}).items():
        if key not in ALLOWED:
            raise ValueError(f"{key} is not a directory setting")
        clean[key] = str(raw or "").strip()
    from jsonio import write_json_atomic
    with _lock:
        os.makedirs(os.path.dirname(path()), exist_ok=True)
        write_json_atomic(path(), clean)
        _cache["mtime"] = None      # force a re-read on the next get()
    log.info("directory settings saved (%d keys)", len(clean))
    return effective()
