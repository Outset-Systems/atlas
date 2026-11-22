import json
import logging
import os
import threading

import envnames
import settings
from engines import registry

log = logging.getLogger("atlas.live.integrations")

GROUPS = {
    "sources": (
        "ATLAS_SIGNALS_SOURCES",
        "ATLAS_PROM_URL",
        "ATLAS_LOKI_URL",
        "ATLAS_KUMA_URL",
        "ATLAS_KUMA_API_KEY",
        "ATLAS_DECOYS_URL",
        "ATLAS_DECOYS_KEY",
        "ATLAS_DECOYS_PATH",
    ),
    "realm": (
        "HUB_URL",
        "ATLAS_SCROLL_ROOT",
        "ATLAS_BEAT_TOKEN",
    ),
    "glass": (
        "ATLAS_EMBED_HOSTS",
        "ATLAS_EMBED_SERVICES",
        "ATLAS_EMBED_PROBE",
        "ATLAS_WHOIS",
    ),
    "connections": (
        "ATLAS_PROXMOX_URL", "ATLAS_PROXMOX_TOKEN", "ATLAS_PROXMOX_INSECURE",
        "ATLAS_PORTAINER_URL", "ATLAS_PORTAINER_KEY", "ATLAS_PORTAINER_INSECURE",
        "ATLAS_KOMODO_URL", "ATLAS_KOMODO_KEY", "ATLAS_KOMODO_SECRET", "ATLAS_KOMODO_INSECURE",
        "ATLAS_NETBOX_URL", "ATLAS_NETBOX_API_TOKEN", "ATLAS_NETBOX_INSECURE",
        "ATLAS_UNIFI_URL", "ATLAS_UNIFI_SITE", "ATLAS_UNIFI_API_KEY", "ATLAS_UNIFI_USERNAME",
        "ATLAS_UNIFI_PASSWORD", "ATLAS_UNIFI_INSECURE", "ATLAS_KUMA_INSECURE",
    ),
}
ALLOWED = GROUPS["sources"] + GROUPS["realm"] + GROUPS["glass"] + GROUPS["connections"]
BOOLS = ("ATLAS_EMBED_SERVICES", "ATLAS_EMBED_PROBE", "ATLAS_WHOIS", "ATLAS_PROXMOX_INSECURE",
         "ATLAS_PORTAINER_INSECURE", "ATLAS_KOMODO_INSECURE", "ATLAS_NETBOX_INSECURE",
         "ATLAS_UNIFI_INSECURE", "ATLAS_KUMA_INSECURE")


def flag(name, default=True):
    raw = get(name).strip()
    if raw == "":
        return default
    return raw == "1"


SECRETS = ("ATLAS_KUMA_API_KEY", "ATLAS_DECOYS_KEY", "ATLAS_BEAT_TOKEN", "ATLAS_PROXMOX_TOKEN",
           "ATLAS_PORTAINER_KEY", "ATLAS_KOMODO_KEY", "ATLAS_KOMODO_SECRET", "ATLAS_NETBOX_API_TOKEN",
           "ATLAS_UNIFI_API_KEY", "ATLAS_UNIFI_USERNAME", "ATLAS_UNIFI_PASSWORD")
SECRET_HOMES = {"ATLAS_KUMA_URL": ("ATLAS_KUMA_API_KEY",),
                "ATLAS_DECOYS_URL": ("ATLAS_DECOYS_KEY",),
                "ATLAS_PROXMOX_URL": ("ATLAS_PROXMOX_TOKEN",),
                "ATLAS_PORTAINER_URL": ("ATLAS_PORTAINER_KEY",),
                "ATLAS_KOMODO_URL": ("ATLAS_KOMODO_KEY", "ATLAS_KOMODO_SECRET"),
                "ATLAS_NETBOX_URL": ("ATLAS_NETBOX_API_TOKEN",),
                "ATLAS_UNIFI_URL": ("ATLAS_UNIFI_API_KEY", "ATLAS_UNIFI_USERNAME", "ATLAS_UNIFI_PASSWORD")}
URLS = ("ATLAS_PROM_URL", "ATLAS_LOKI_URL", "ATLAS_KUMA_URL", "ATLAS_DECOYS_URL", "HUB_URL",
        "ATLAS_PROXMOX_URL", "ATLAS_PORTAINER_URL", "ATLAS_KOMODO_URL", "ATLAS_NETBOX_URL",
        "ATLAS_UNIFI_URL")
SOURCES = registry.listed_names()
SOURCE_NEEDS = registry.needs()

DECOYS_PATH_DEFAULT = "/api/tripwires"

_lock = threading.Lock()
_cache = {"mtime": None, "data": {}}


def valid_decoys_path(value):
    v = str(value or "")
    return (0 < len(v) <= 200 and v.startswith("/") and not v.startswith("//")
            and not any(c.isspace() or c in "?#\\" for c in v))


def valid_unifi_site(value):
    from importers.unifi import SITE_OK
    return bool(SITE_OK.match(str(value or "")))


def decoys_path():
    raw = get("ATLAS_DECOYS_PATH").strip()
    if not raw:
        return DECOYS_PATH_DEFAULT
    if not valid_decoys_path(raw):
        log.warning("ATLAS_DECOYS_PATH %r is not an absolute path; using %s",
                    raw, DECOYS_PATH_DEFAULT)
        return DECOYS_PATH_DEFAULT
    return raw


def path():
    return os.environ.get("ATLAS_INTEGRATIONS") or os.path.join(
        settings.DATA_DIR, "integrations.json")


def stamp():
    try:
        return os.path.getmtime(path())
    except OSError:
        return None


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
            renamed = {}
            for k, v in loaded.items():
                new = envnames.new_name(k)
                if new in ALLOWED and (new == k or new not in loaded):
                    renamed[new] = v
            _cache["data"] = renamed
            _cache["mtime"] = mtime
        except (OSError, ValueError):
            log.warning("integrations file unreadable, falling back to the environment",
                        exc_info=True)
            return {}
    return _cache["data"]


def _env(name):
    if name in SECRETS:
        return envnames.secret(name)
    return (envnames.env(name) or "").strip()


def _stored(name):
    raw = _load().get(name)
    if not raw:
        return ""
    if name in SECRETS:
        try:
            import crypto_at_rest
            return crypto_at_rest.decrypt_text(str(raw)) or ""
        except Exception:
            log.warning("integrations: stored %s does not open with the master key", name)
            return ""
    return str(raw)


def get(name, default=""):
    if name not in ALLOWED:
        return default
    return _stored(name) or _env(name) or default


def moves_secret(url_key, proposed, saving=False):
    url = str(proposed.get(url_key) or "").strip().rstrip("/")
    if not url or url in (get(url_key).rstrip("/"), _env(url_key).rstrip("/")):
        return False
    for name in SECRET_HOMES.get(url_key, ()):
        typed = str(proposed.get(name) or "").strip()
        cleared = saving and name in proposed and proposed[name] is None and not _env(name)
        if not typed and not cleared and get(name):
            return True
    return False


def sources():
    out = {}
    for key in ALLOWED:
        if _stored(key):
            out[key] = "settings"
        elif _env(key):
            out[key] = "deployment"
        else:
            out[key] = "unset"
    return out


def describe():
    src = sources()
    out = {}
    for key in ALLOWED:
        value = get(key)
        out[key] = {
            "value": "" if key in SECRETS else value,
            "set": bool(value),
            "source": src[key],
            "secret": key in SECRETS,
        }
    return out


def enabled_sources():
    raw = get("ATLAS_SIGNALS_SOURCES")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def save(values):
    for key in (values or {}):
        if key not in ALLOWED:
            raise ValueError(f"{key} is not an integration setting")
    from filelock import exclusive, lock_for
    from jsonio import write_json_atomic
    with _lock, exclusive(lock_for(path())):
        _cache["mtime"] = None
        clean = _merge(values)
        os.makedirs(os.path.dirname(path()), exist_ok=True)
        write_json_atomic(path(), clean)
        _cache["mtime"] = None
    log.info("integration settings saved (%d keys)", len(clean))
    return describe()


def _merge(values):
    clean = {k: v for k, v in _load().items() if v}
    for key, raw in (values or {}).items():
        if key in SECRETS:
            if raw is None:
                clean.pop(key, None)
                continue
            text = str(raw).strip()
            if text == "":
                continue
            import crypto_at_rest
            clean[key] = crypto_at_rest.encrypt_text(text)
        else:
            text = str(raw or "").strip()
            if text:
                clean[key] = text
            else:
                clean.pop(key, None)
    return clean
