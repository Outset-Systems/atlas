"""THE SOURCES — what the Atlas asks, and where: integration settings an
operator can edit from THE SETTINGS (v1.37.0).

Prometheus, Loki, Uptime-Kuma and the decoy feed were environment-only, so pointing
the Atlas at a moved scribe was a redeploy. This module is the same small
persisted layer over the environment that `auth_config` is for the directory:
every asker (`api/v2/charts`, `api/v2/vitals`, the signals hub) reads here
first and falls back to `os.environ`, so one seam makes them all configurable
and nothing that asks had to learn a new name.

The constraints are `auth_config`'s, plus one of its own:

  * **An allowlist, never arbitrary keys.** Only the integration settings
    below can be written — a "save these settings" route that could set
    `ATLAS_READONLY` or `ATLAS_ALLOW_INSECURE` would be a way to disable the
    gate guarding it.
  * **The file overrides the environment, and says so.** `sources()` reports
    which layer each value came from, so the form shows the value in force.
  * **Secrets are encrypted at rest and never echoed.** The Kuma API key and
    the decoy feed read key are stored as Fernet tokens under the same master key
    that guards TOTP secrets (`crypto_at_rest`); `describe()` says only whether
    one is set. A key given as '' keeps the stored one; `None` clears it.

Written with the dataset's atomic writer, so a half-written file cannot leave
an instance asking nobody. `stamp()` is the file's mtime — the signals hub
watches it and rebuilds its adapters when it moves, which is what lets a save
in one gunicorn worker reach every other worker without a restart.
"""

import json
import logging
import os
import threading

import envnames
import settings

log = logging.getLogger("atlas.live.integrations")   # a sibling of atlas.live.signals, which it feeds

#: The only keys that may be persisted, in two groups: THE SOURCES (what the
#: Atlas asks) and THE REALM (v1.38.0 — where the Hub is, the vault prefix
#: trimmed off scroll paths, and the heartbeat token the rites post with).
GROUPS = {
    "sources": (
        "ATLAS_SIGNALS_SOURCES",
        "ATLAS_PROM_URL",
        "ATLAS_LOKI_URL",
        "ATLAS_KUMA_URL",
        "ATLAS_KUMA_API_KEY",
        "ATLAS_DECOYS_URL",
        "ATLAS_DECOYS_KEY",
        # TRIPWIRES (v0.1): the decoy feed is one source among several now,
        # and not every engine serves its roster at /api/stones.
        "ATLAS_DECOYS_PATH",
    ),
    "realm": (
        "HUB_URL",
        "ATLAS_SCROLL_ROOT",
        "ATLAS_BEAT_TOKEN",
    ),
    # THE VIEWING GLASS (v1.38.2): which extra origins may be framed, whether
    # the dataset's own service origins widen that list, and whether a service
    # is probed for frameability before the glass tries. The last three
    # environment-only knobs an operator would plausibly change without a
    # redeploy. Booleans travel as "1"/"0" ('' = the deployment's value).
    "glass": (
        "ATLAS_EMBED_HOSTS",
        "ATLAS_EMBED_SERVICES",
        "ATLAS_EMBED_PROBE",
    ),
    # CONNECTIONS (connections.py): other systems the Atlas can be pointed at. The
    # NetBox key is not NETBOX_TOKEN on purpose: that one is the CLI import's, and
    # the docs promise the web app never reads it.
    "connections": (
        "ATLAS_PROXMOX_URL", "ATLAS_PROXMOX_TOKEN", "ATLAS_PROXMOX_INSECURE",
        "ATLAS_PORTAINER_URL", "ATLAS_PORTAINER_KEY", "ATLAS_PORTAINER_INSECURE",
        "ATLAS_KOMODO_URL", "ATLAS_KOMODO_KEY", "ATLAS_KOMODO_SECRET", "ATLAS_KOMODO_INSECURE",
        "ATLAS_NETBOX_URL", "ATLAS_NETBOX_API_TOKEN", "ATLAS_NETBOX_INSECURE",
    ),
}
ALLOWED = GROUPS["sources"] + GROUPS["realm"] + GROUPS["glass"] + GROUPS["connections"]
#: '', '1' or '0' only — anything else is refused by the API layer.
BOOLS = ("ATLAS_EMBED_SERVICES", "ATLAS_EMBED_PROBE", "ATLAS_PROXMOX_INSECURE",
         "ATLAS_PORTAINER_INSECURE", "ATLAS_KOMODO_INSECURE", "ATLAS_NETBOX_INSECURE")


def flag(name, default=True):
    """A boolean knob in force: the stored/env value, "1" = on, "0" = off,
    unset = `default`."""
    raw = get(name).strip()
    if raw == "":
        return default
    return raw == "1"


#: Stored encrypted, never returned by `describe()`.
SECRETS = ("ATLAS_KUMA_API_KEY", "ATLAS_DECOYS_KEY", "ATLAS_BEAT_TOKEN", "ATLAS_PROXMOX_TOKEN",
           "ATLAS_PORTAINER_KEY", "ATLAS_KOMODO_KEY", "ATLAS_KOMODO_SECRET", "ATLAS_NETBOX_API_TOKEN")
#: Which secrets are sent to which URL. A stored secret goes only to the address it
#: was saved with: see `moves_secret`.
SECRET_HOMES = {"ATLAS_KUMA_URL": ("ATLAS_KUMA_API_KEY",),
                "ATLAS_DECOYS_URL": ("ATLAS_DECOYS_KEY",),
                "ATLAS_PROXMOX_URL": ("ATLAS_PROXMOX_TOKEN",),
                "ATLAS_PORTAINER_URL": ("ATLAS_PORTAINER_KEY",),
                "ATLAS_KOMODO_URL": ("ATLAS_KOMODO_KEY", "ATLAS_KOMODO_SECRET"),
                "ATLAS_NETBOX_URL": ("ATLAS_NETBOX_API_TOKEN",)}
#: Must parse as http(s) URLs with a host when set.
URLS = ("ATLAS_PROM_URL", "ATLAS_LOKI_URL", "ATLAS_KUMA_URL", "ATLAS_DECOYS_URL", "HUB_URL",
        "ATLAS_PROXMOX_URL", "ATLAS_PORTAINER_URL", "ATLAS_KOMODO_URL", "ATLAS_NETBOX_URL")
#: The signals sources the hub knows how to build (signals.build_hub_from_env).
SOURCES = ("kuma", "prometheus", "deception", "relay", "static")
#: Which source needs which URL in force before it can be enabled.
SOURCE_NEEDS = {"kuma": "ATLAS_KUMA_URL", "prometheus": "ATLAS_PROM_URL",
                "deception": "ATLAS_DECOYS_URL"}

#: Where the decoy feed serves its roster when nothing says otherwise.
DECOYS_PATH_DEFAULT = "/api/stones"

_lock = threading.Lock()
_cache = {"mtime": None, "data": {}}


def valid_decoys_path(value):
    """An absolute path on the decoy feed's own origin: starts with one `/`,
    no scheme, no `//` (that would leave the origin), no whitespace or `?#`
    (a query is a second place to smuggle a host), at most 200 characters."""
    v = str(value or "")
    return (0 < len(v) <= 200 and v.startswith("/") and not v.startswith("//")
            and not any(c.isspace() or c in "?#\\" for c in v))


def decoys_path():
    """The decoy feed's roster path in force (ATLAS_DECOYS_PATH, settings file
    first). A value that is not a clean absolute path falls back to the
    default, loudly — a typo must not aim the read key somewhere else."""
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
    """The file's mtime, or None — the hub's cue to rebuild its adapters."""
    try:
        return os.path.getmtime(path())
    except OSError:
        return None


def _load():
    """The persisted overrides (secrets still encrypted), re-read on change."""
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
            # NAMES THAT CHANGED (v1.48.0): a file written before the renames
            # keeps working; a key stored under both names keeps the new one.
            renamed = {}
            for k, v in loaded.items():
                new = envnames.new_name(k)
                if new in ALLOWED and (new == k or new not in loaded):
                    renamed[new] = v
            _cache["data"] = renamed
            _cache["mtime"] = mtime
        except (OSError, ValueError):
            # A broken file must not silence the map: fall through to the
            # environment, which is what the instance booted with.
            log.warning("integrations file unreadable, falling back to the environment",
                        exc_info=True)
            return {}
    return _cache["data"]


def _env(name):
    """The deployment's value: the variable, or `<NAME>_FILE` for a secret
    (the docker-secret convention the signals layer has always honoured)."""
    if name in SECRETS:
        return envnames.secret(name)
    return (envnames.env(name) or "").strip()


def _stored(name):
    """The persisted value, decrypted for a secret; '' when absent or when the
    master key no longer opens it (logged — a silent '' would read as unset)."""
    raw = _load().get(name)
    if not raw:
        return ""
    if name in SECRETS:
        try:
            import crypto_at_rest
            return crypto_at_rest.decrypt_text(str(raw)) or ""
        except Exception:  # noqa: BLE001 — a key problem is a warning, not a crash
            log.warning("integrations: stored %s does not open with the master key", name)
            return ""
    return str(raw)


def get(name, default=""):
    """The value in force for `name`: persisted first, then the environment."""
    if name not in ALLOWED:
        return default
    return _stored(name) or _env(name) or default


def moves_secret(url_key, proposed, saving=False):
    """True if `proposed` would send a stored secret to a new address.

    A blank secret means "keep the stored one", so without this an admin could type
    their own host as the URL, leave the secret blank, and receive it. That would
    make the write-only secret box readable to anyone who can reach this form.
    The address it already goes to, in the settings file or the deployment's, is
    fine, and so is a secret typed afresh.

    "Typed" is read exactly as the routes read a value, or `0` or `[]` would pass
    here and still mean the stored one there. `None` is only a clearing when
    `saving`: a test reads it as blank. Even then it clears the settings file and
    not the deployment's value, which would go on to the new address.
    """
    url = str(proposed.get(url_key) or "").strip().rstrip("/")
    if not url or url in (get(url_key).rstrip("/"), _env(url_key).rstrip("/")):
        return False
    for name in SECRET_HOMES.get(url_key, ()):
        typed = str(proposed.get(name) or "").strip()
        cleared = saving and name in proposed and proposed[name] is None and not _env(name)
        if not typed and not cleared and get(name):
            return True
    return False


def effective():
    return {k: get(k) for k in ALLOWED}


def sources():
    """{key: 'settings' | 'deployment' | 'unset'}."""
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
    """What the form may see: values for plain keys, only `set` for secrets."""
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
    """The signals sources in force, as a clean list."""
    raw = get("ATLAS_SIGNALS_SOURCES")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def save(values):
    """Persist `values` (allowlisted keys only). Returns `describe()`.

    Plain keys are stored as given ('' = fall back to the deployment). A
    secret given as '' keeps whatever is stored; `None` clears it; anything
    else is encrypted before it touches the disk. Validation of URLs and
    source names lives in the API layer, which knows the caller.
    """
    # A save is a MERGE over what is stored (review, 2026-09-03): THE SOURCES,
    # THE REALM and THE GLASS are three forms posting three disjoint subsets
    # of one file, and the first cut rebuilt the file from the posted keys
    # alone — saving THE REALM silently forgot every source URL. Now a key
    # that is not mentioned keeps its stored value; a key posted as '' falls
    # back to the deployment; a secret posted as '' keeps the stored one and
    # `None` clears it.
    clean = {k: v for k, v in _load().items() if v}
    for key, raw in (values or {}).items():
        if key not in ALLOWED:
            raise ValueError(f"{key} is not an integration setting")
        if key in SECRETS:
            if raw is None:
                clean.pop(key, None)          # cleared
                continue
            text = str(raw).strip()
            if text == "":
                continue                      # kept as stored (still encrypted)
            import crypto_at_rest
            clean[key] = crypto_at_rest.encrypt_text(text)
        else:
            text = str(raw or "").strip()
            if text:
                clean[key] = text
            else:
                clean.pop(key, None)          # '' = the deployment's value
    from jsonio import write_json_atomic
    with _lock:
        os.makedirs(os.path.dirname(path()), exist_ok=True)
        write_json_atomic(path(), clean)
        _cache["mtime"] = None
    log.info("integration settings saved (%d keys)", len(clean))
    return describe()
