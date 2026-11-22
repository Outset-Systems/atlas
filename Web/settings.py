import ipaddress
import logging
import os

import envnames
import theme as _theme


log = logging.getLogger("atlas.settings")

APP_KEY = "atlas"

APP_NAME = _theme.T["app_name"]
APP_BRAND = os.environ.get("ATLAS_BRAND", "").strip() or "The Atlas"
APP_VERSION = "0.2.0-dev.50"
ACCENT_COLOR = "#C9A554"

HERE = os.path.dirname(os.path.abspath(__file__))

ENV_REJECTED = []


def _rejected(name, raw, used):
    entry = (name, str(raw)[:40], str(used))
    if entry not in ENV_REJECTED:
        ENV_REJECTED.append(entry)


def env_flag(name, default=False, strict=False, unknown=None):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    if strict:
        if raw in ("1", "0"):
            return raw == "1"
        _rejected(name, raw, "off")
        return False
    said = envnames.yes_no(raw)
    if said is None:
        said = default if unknown is None else unknown
        _rejected(name, raw, "on" if said else "off")
    return said

HOST = os.environ.get("ATLAS_HOST", "0.0.0.0")
def _log_level(raw):
    level = (raw or "").strip().upper() or "INFO"
    if isinstance(getattr(logging, level, None), int):
        return level
    _rejected("ATLAS_LOG_LEVEL", raw, "INFO")
    return "INFO"


LOG_LEVEL = _log_level(os.environ.get("ATLAS_LOG_LEVEL", "INFO"))

def _parse_log_levels(raw):
    levels, rejected = {}, []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, _, level = part.partition("=")
        name, level = name.strip(), level.strip().upper()
        if not name or not isinstance(getattr(logging, level, None), int):
            rejected.append(part)
            continue
        levels[name] = level
    return levels, rejected


LOG_LEVELS, LOG_LEVELS_REJECTED = _parse_log_levels(
    os.environ.get("ATLAS_LOG_LEVELS", ""))
DEBUG = env_flag("ATLAS_DEBUG", strict=True)

def data_dir():
    return os.path.dirname(os.environ.get("ATLAS_DATA", "/data/lab-data.json")) or "."


DATA_PATH = os.environ.get("ATLAS_DATA", "/data/lab-data.json")
DEFAULT_DATA_PATH = os.path.join(HERE, "default-lab-data.json")
DATA_DIR = data_dir()

DATA_BACKEND = os.environ.get("ATLAS_DATA_BACKEND", "file")
SITE_SLUG = os.environ.get("ATLAS_SITE", "default")

FALLBACK = os.environ.get("ATLAS_FALLBACK", "empty").lower().strip()

POSITIONS_PATH = os.environ.get("ATLAS_POSITIONS", os.path.join(DATA_DIR, "positions.json"))
RACK_PATH = os.environ.get("ATLAS_RACK", os.path.join(DATA_DIR, "rack.json"))
TOPOLOGY_LAYOUT_PATH = os.environ.get("ATLAS_TOPOLOGY_LAYOUT",
                                      os.path.join(DATA_DIR, "topology-layout.json"))
REVISIONS_DIR = os.environ.get("ATLAS_REVISIONS", os.path.join(DATA_DIR, "revisions"))
OBSERVED_PATH = os.environ.get("ATLAS_OBSERVED", os.path.join(DATA_DIR, "observed.json"))
EVENTS_PATH = os.environ.get("ATLAS_EVENTS", os.path.join(DATA_DIR, "events.json"))
REPORTS_DIR = os.environ.get("ATLAS_REPORTS", os.path.join(DATA_DIR, "reports"))
MAINTENANCE_PATH = os.environ.get("ATLAS_MAINTENANCE", os.path.join(DATA_DIR, "maintenance.json"))
BEATS_PATH = os.environ.get("ATLAS_BEATS", os.path.join(DATA_DIR, "heartbeats.json"))

BEATS_DIR = os.environ.get("ATLAS_BEATS_DIR", os.path.join(DATA_DIR, "beats"))

MAPS_DIR = os.environ.get("ATLAS_MAPS", os.path.join(DATA_DIR, "maps"))

ALERTS_ENABLED = env_flag("ATLAS_ALERTS")
ALERT_HOSTS = os.environ.get("ATLAS_ALERT_HOSTS", "").strip()
PUBLIC_URL = os.environ.get("ATLAS_PUBLIC_URL", "").strip()
ALERTS_PATH = os.environ.get("ATLAS_ALERTS_FILE", os.path.join(DATA_DIR, "alerts.json"))
ALERTS_STATE_PATH = os.environ.get("ATLAS_ALERTS_STATE", os.path.join(DATA_DIR, "alerts-state.json"))
ALERT_LOG_PATH = os.environ.get("ATLAS_ALERT_LOG", os.path.join(DATA_DIR, "alert-deliveries.jsonl"))


def alerts_on():
    return bool(ALERTS_ENABLED and ALERT_HOSTS)

ALLOW_INSECURE = env_flag("ATLAS_ALLOW_INSECURE", strict=True)

INSECURE_COOKIES = os.environ.get("ATLAS_INSECURE_COOKIES", "").strip() in ("1", "true", "yes")


def auth_mode():
    return (envnames.env("ATLAS_AUTH_MODE") or "standalone").lower().strip()


def env_int(name, default, floor, zero_off=False):
    raw = os.environ.get(name, str(default)).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        _rejected(name, raw, default)
        return default
    if zero_off and value == 0:
        return 0
    if value < floor:
        _rejected(name, raw, default)
        return default
    return value


def beat_token():
    try:
        import integrations
        value = integrations.get("ATLAS_BEAT_TOKEN")
        if value:
            return value
    except Exception:
        pass
    return envnames.secret("ATLAS_BEAT_TOKEN") or None


def accounts_db_path():
    explicit = os.environ.get("ATLAS_ACCOUNTS_DB")
    if explicit:
        return explicit
    return os.path.join(data_dir(), "accounts.db")


def _read_only():
    explicit = os.environ.get("ATLAS_READONLY")
    if explicit is not None and explicit.strip():
        return env_flag("ATLAS_READONLY", unknown=True)
    return auth_mode() not in ("hub", "accounts", "hybrid") and not ALLOW_INSECURE


READ_ONLY = _read_only()

DEFAULT_STYLE = os.environ.get("ATLAS_DEFAULT_STYLE", "").strip()
DEMO_TRUST = os.environ.get("ATLAS_DEMO_TRUST", "").strip()
_DEMO_LINK = os.environ.get("ATLAS_DEMO_LINK", "").strip()
DEMO_LINK = _DEMO_LINK if _DEMO_LINK.startswith("https://") and " " not in _DEMO_LINK else ""


LOGIN_MAX_USER = env_int("ATLAS_LOGIN_MAX_USER", 5, 1)
LOGIN_MAX_IP = env_int("ATLAS_LOGIN_MAX_IP", 20, 1)
LOGIN_WINDOW_S = env_int("ATLAS_LOGIN_WINDOW_MIN", 15, 1) * 60

SESSION_IDLE_S = env_int("ATLAS_SESSION_IDLE_MIN", 60, 1) * 60
SESSION_ABS_S = env_int("ATLAS_SESSION_ABS_HOURS", 12, 1) * 3600
PORT = env_int("ATLAS_PORT", 5006, 1)


def _parse_trusted(raw):
    raw = (raw or "").strip()
    if not raw:
        return ()
    if raw.isdigit():
        log.warning("ATLAS_TRUSTED_PROXIES=%r is a hop count; that form is refused — name "
                    "the proxy addresses/CIDRs instead. Trusting no proxy "
                    "until it is fixed.", raw)
        return ()
    nets = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            log.warning("ATLAS_TRUSTED_PROXIES entry %r is not an IP or CIDR; ignoring it.",
                        token)
    return tuple(nets)

TRUSTED_PROXIES = _parse_trusted(os.environ.get("ATLAS_TRUSTED_PROXIES"))
MAX_IP_KEY = 64

INGEST_ENABLED = env_flag("ATLAS_INGEST_ENABLED", strict=True)


def mfa_required():
    return (os.environ.get("ATLAS_MFA_REQUIRED", "") or "").strip().lower()

def embed_hosts():
    import integrations
    return integrations.get("ATLAS_EMBED_HOSTS")


def embed_services():
    import integrations
    return integrations.flag("ATLAS_EMBED_SERVICES", default=True)


def embed_probe():
    import integrations
    return integrations.flag("ATLAS_EMBED_PROBE", default=True)


def whois_enabled():
    import integrations
    return integrations.flag("ATLAS_WHOIS", default=True)


def diagnose_outside():
    return (os.environ.get("ATLAS_DIAGNOSE_OUTSIDE") or "").strip()



def auth_config():
    mode = auth_mode()
    out = {"mode": mode, "user": "", "admin": False, "mfa": False,
           "session": "", "source": "", "emblem": "", "canSignOut": False}
    if mode == "standalone":
        return out
    try:
        import atlas_auth
        import security
        out["user"] = security.actor()
        out["admin"] = bool(security.is_admin())
        out["session"] = atlas_auth.session_source()
        if atlas_auth.sessions_enabled():
            acc = atlas_auth.current_account()
            out["mfa"] = bool(acc and acc.get("mfa_enabled"))
            out["source"] = (acc or {}).get("source", "")
            out["emblem"] = (acc or {}).get("emblem", "")
            out["canSignOut"] = out["session"] == "atlas"
    except Exception:
        log.warning("auth_config: could not resolve the viewer", exc_info=True)
    return out


def hub_url():
    from flask import request
    given = request.headers.get("X-Hub-URL")
    if given:
        return given
    import integrations
    return integrations.get("HUB_URL")


def _scroll_root():
    import integrations
    return integrations.get("ATLAS_SCROLL_ROOT")


def client_config():
    auth = auth_config()
    try:
        from notebook import notes_home
    except ImportError:
        notes_home = None
    out = {
        "hubUrl": hub_url(),
        "scrollRoot": _scroll_root(),
        "version": APP_VERSION,
        "auth": auth,
        "notesHome": notes_home(bool(auth.get("admin"))) if notes_home else "",
        "theme": _theme.client(),
        "whois": whois_enabled(),
        "demoTrust": bool(DEMO_TRUST),
        "demoLink": DEMO_LINK,
    }
    return out


def writes_enabled():
    return not READ_ONLY
