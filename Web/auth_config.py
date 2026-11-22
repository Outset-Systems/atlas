import json
import logging
import os
import threading

import settings

log = logging.getLogger("atlas.auth.config")

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
            if not isinstance(loaded, dict):
                raise ValueError("not a JSON object")
            _cache["data"] = {k: v for k, v in loaded.items() if k in ALLOWED}
            _cache["mtime"] = mtime
        except (OSError, ValueError):
            log.warning("auth-config unreadable, falling back to the environment",
                        exc_info=True)
            return {}
    return _cache["data"]


def get(name, default=""):
    if name not in ALLOWED:
        return default
    value = _load().get(name)
    return default if value is None else str(value)


def sources():
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
    stored = _load()
    return {k: (stored.get(k) or os.environ.get(k) or "") for k in ALLOWED}


def save(values):
    clean = {}
    for key, raw in (values or {}).items():
        if key not in ALLOWED:
            raise ValueError(f"{key} is not a directory setting")
        clean[key] = str(raw or "").strip()
    from jsonio import write_json_atomic
    with _lock:
        os.makedirs(os.path.dirname(path()), exist_ok=True)
        write_json_atomic(path(), clean)
        _cache["mtime"] = None
    log.info("directory settings saved (%d keys)", len(clean))
    return effective()
