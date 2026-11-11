"""The Atlas's configuration knobs, read in one place.

Most were scattered through the app as bare `os.environ` reads; collecting them
here is not tidying for its own sake: `/api/admin/settings` shows an operator
which are actually in force, and the first-run wizard needs to know whether this
deployment can be written to at all before it offers to write.

Two shapes, by how the value is used:
  * CONSTANTS resolved at import (DATA_PATH, the throttle and session knobs …) —
    a config value that changes under a running worker is a bug generator. The
    suite rebuilds via `appfixture.fresh_app`, which reloads this module, so a
    per-test value still lands.
  * FUNCTIONS that read live (`beat_token`, `auth_mode`, `mfa_required`,
    `auth_config`, `hub_url`, `accounts_db_path`) — a few values legitimately
    change per request, or must be seen the moment a test sets them; each says
    so where it is defined.

What is deliberately NOT here: secrets and subsystem-owned env, which live with
the code that understands them — the master encryption key (`crypto_at_rest`,
with its refuse-to-overwrite-a-failed-mount rule), the session signing key
(`app`, with its generate-once O_EXCL race handling), the first-run
bootstrap-admin envs (`auth_routes`), the signals adapter wiring
(`signals.build_hub_from_env`), and the LDAP directory settings (`auth_config`,
already the single seam for its domain). Moving those would fragment logic that
is inseparable from the value.
"""

import ipaddress
import logging
import os


log = logging.getLogger("atlas.settings")

APP_KEY = "atlas"
import envnames  # NAMES THAT CHANGED (v1.48.0): ATLAS_AUTH_MODE and friends
import theme as _theme   # THE THEME (v1.48.0): the realm's words live in themes/*.json

APP_NAME = _theme.T["app_name"]
# The name the door wears, before anyone has been let in. APP_NAME is the
# REALM's name and belongs to the map — a stranger at the gate should not learn
# whose lab this is, or that "the lab" exists at all, simply by loading a
# login page. The realm names itself once you are inside: the veil says it, the
# crown says it, the map is it. This matters twice over now that the Atlas has
# a public door (atlas.example.com) and again for the hosted edition, where
# one login page fronts many realms and must not leak which one you asked for.
APP_BRAND = os.environ.get("ATLAS_BRAND", "").strip() or "The Atlas"
APP_VERSION = "0.2.0-dev.6"
ACCENT_COLOR = "#C9A554"

HERE = os.path.dirname(os.path.abspath(__file__))

PORT = int(os.environ.get("ATLAS_PORT", "5006"))
# Bind address for the dev server only (`python app.py`); gunicorn takes its
# own. The local launchers set 127.0.0.1 — before 2026-09-24 this was ignored
# and they listened on every interface while saying "loopback only".
HOST = os.environ.get("ATLAS_HOST", "0.0.0.0")
LOG_LEVEL = os.environ.get("ATLAS_LOG_LEVEL", "INFO")

# Per-layer log levels — `ATLAS_LOG_LEVELS="atlas.data=DEBUG,atlas.auth=WARNING"`.
# Every module logs to `atlas.<layer>.<module>` (the tree is described in
# app.py), so a name here sets the level for that layer and everything under
# it: `atlas.io` quiets both jsonio and filelock, `atlas.api.v2` quiets the
# whole v2 blueprint, `atlas.data.labdata` quiets exactly one module. Before
# this, ATLAS_LOG_LEVEL was the only dial and it moved all 28 modules at once.
# Returns (levels, rejected) — two values rather than a sentinel key inside the
# name→level map, because a map of logger names should contain only logger
# names.
def _parse_log_levels(raw):
    levels, rejected = {}, []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, _, level = part.partition("=")
        name, level = name.strip(), level.strip().upper()
        # A bad entry must not take the app down over a logging knob, and must
        # not silently do nothing either — app.py reports what it could not use.
        # `getattr` must be an INT: `logging.getLogger` would otherwise pass a
        # bare hasattr check and reach setLevel as a function.
        if not name or not isinstance(getattr(logging, level, None), int):
            rejected.append(part)
            continue
        levels[name] = level
    return levels, rejected


LOG_LEVELS, LOG_LEVELS_REJECTED = _parse_log_levels(
    os.environ.get("ATLAS_LOG_LEVELS", ""))
DEBUG = os.environ.get("ATLAS_DEBUG") == "1"

# ── The dataset ──────────────────────────────────────────────────────────────
def data_dir():
    """The directory beside the dataset, where every sibling store lives
    (`accounts.db`, `secrets/`, `integrations.json`, the drop-dirs). LIVE,
    reading the environment each call: a test re-points `ATLAS_DATA` without
    rebuilding the app, and the callers that must follow it
    (`accounts_db_path`, `crypto_at_rest`) use this rather than the boot-time
    `DATA_DIR` below, which the import-time paths are built from."""
    return os.path.dirname(os.environ.get("ATLAS_DATA", "/data/lab-data.json")) or "."


DATA_PATH = os.environ.get("ATLAS_DATA", "/data/lab-data.json")
DEFAULT_DATA_PATH = os.path.join(HERE, "default-lab-data.json")
DATA_DIR = data_dir()

# Atlas for Teams Phase 1: "file" = the classic hand-edited
# JSON (default, byte-for-byte unchanged); "db" = the SQLAlchemy store serving
# the same dataset shape. With the flag unset, no new code runs.
DATA_BACKEND = os.environ.get("ATLAS_DATA_BACKEND", "file")
SITE_SLUG = os.environ.get("ATLAS_SITE", "default")

# What an *unseeded* instance renders — no dataset at the path, or a db site
# that has never been imported into.
#
#   "empty"   (default) an empty map and an invitation to survey it.
#   "bundled"           the dataset baked into the image.
#
# This used to be "bundled" with no way to change it, which had two bad
# consequences. A new install opened onto somebody else's home lab and, worse,
# the first save *forked* it — 17 places you never charted, now yours. And on
# the real deployment, a broken /data mount silently served a months-old copy
# of the map that looked completely live. An empty map that says it is empty
# is the better failure in both cases. Set "bundled" to get the old behaviour.
FALLBACK = os.environ.get("ATLAS_FALLBACK", "empty").lower().strip()

# ── Files the app writes ─────────────────────────────────────────────────────
# Deliberately never shipped, so a deploy can't clobber a hand-placed layout.
POSITIONS_PATH = os.environ.get("ATLAS_POSITIONS", os.path.join(DATA_DIR, "positions.json"))
RACK_PATH = os.environ.get("ATLAS_RACK", os.path.join(DATA_DIR, "rack.json"))
REVISIONS_DIR = os.environ.get("ATLAS_REVISIONS", os.path.join(DATA_DIR, "revisions"))
OBSERVED_PATH = os.environ.get("ATLAS_OBSERVED", os.path.join(DATA_DIR, "observed.json"))
EVENTS_PATH = os.environ.get("ATLAS_EVENTS", os.path.join(DATA_DIR, "events.json"))
REPORTS_DIR = os.environ.get("ATLAS_REPORTS", os.path.join(DATA_DIR, "reports"))
MAINTENANCE_PATH = os.environ.get("ATLAS_MAINTENANCE", os.path.join(DATA_DIR, "maintenance.json"))
BEATS_PATH = os.environ.get("ATLAS_BEATS", os.path.join(DATA_DIR, "heartbeats.json"))

# Where a job that cannot reach the app drops a file to report a turning.
# `touch /data/beats/<rite-key>` is the whole client protocol; the app adopts
# the file and deletes it. Kept separate from BEATS_PATH so the drop point can
# be a shared mount while the store stays local.
BEATS_DIR = os.environ.get("ATLAS_BEATS_DIR", os.path.join(DATA_DIR, "beats"))

# Uploaded base renders — the picture the map is drawn on. Bundled art in
# `static/map/` always wins over anything here (mapart.resolve).
MAPS_DIR = os.environ.get("ATLAS_MAPS", os.path.join(DATA_DIR, "maps"))

# ── Posture ──────────────────────────────────────────────────────────────────
# Acknowledge that standalone mode serves the whole map with no auth.
ALLOW_INSECURE = os.environ.get("ATLAS_ALLOW_INSECURE") == "1"

# Plain-http LAN testing: opt out of Secure cookies (app._configure_sessions),
# or a browser silently drops the session cookie. Read once here; the cookie
# posture is decided at startup and never per request.
INSECURE_COOKIES = os.environ.get("ATLAS_INSECURE_COOKIES", "").strip() in ("1", "true", "yes")


def auth_mode():
    """The suite auth mode ("standalone" | "hub" | "accounts" | "hybrid"),
    read LIVE from the environment on every call. The ONE spelling shared by
    `_read_only()` below, `atlas_auth.mode()`, and `auth_config()`.

    Deliberately the environment, never `hub_auth.auth.AUTH_MODE`: that
    module binds the mode at ITS import, so reading it here would answer
    whichever module imported first — the staleness `appfixture.fresh_app`
    reloads around. Live, not a constant, because the suite builds apps for
    several modes in one process and a test may set the mode after the app.
    """
    return (envnames.env("ATLAS_AUTH_MODE") or "standalone").lower().strip()


def beat_token():
    """The shared secret a rite presents to report over HTTP, or None.

    Read on every call rather than resolved at import, unlike everything else
    here: rotating this must not need a container restart, and it is compared
    with `hmac.compare_digest` at one call site, so the cost is a file read on
    a request that happens twenty times a day.

    None disables the HTTP path entirely — the file drop still works, and an
    unauthenticated write endpoint is not something to leave on by default.
    """
    try:
        import integrations   # THE REALM (v1.38.0): settings first, then the env (+ _FILE)
        value = integrations.get("ATLAS_BEAT_TOKEN")
        if value:
            return value
    except Exception:  # noqa: BLE001 — the env path below is the deployment's own
        pass
    return envnames.secret("ATLAS_BEAT_TOKEN") or None


def accounts_db_path():
    """Where the local accounts store lives (accounts.py): ATLAS_ACCOUNTS_DB if
    set, else `accounts.db` beside the dataset. LIVE, reading os.environ each
    call: a test points it at a fresh temp file per case (test_accounts_store)
    without rebuilding the app, so it must not be captured at import."""
    explicit = os.environ.get("ATLAS_ACCOUNTS_DB")
    if explicit:
        return explicit
    return os.path.join(data_dir(), "accounts.db")


def _read_only():
    """Whether this instance refuses every write.

    Explicit `ATLAS_READONLY=1` always wins. Beyond that, **standalone mode
    defaults to read-only**, because standalone has no authentication at all:
    `redaction.viewer_groups()` returns None there and `sees_everything(None)`
    is True, so every admin check in the editing surface passes for anybody who
    can reach the port. That was survivable when the Atlas only served a map.
    It is not survivable now that the same check guards a full dataset rewrite,
    the discovery inbox and the change log (the 2026-07-27 security review, finding 1).

    `ATLAS_ALLOW_INSECURE=1` opts back in. That variable already means "yes, I
    know this is unauthenticated, I meant it" — the same acknowledgement the
    startup warning asks for — so writing is enabled by the flag you already
    set deliberately, and never by forgetting one.
    """
    explicit = os.environ.get("ATLAS_READONLY")
    if explicit is not None:
        return explicit == "1"
    # `accounts` and `hybrid` both have a real gate (session sign-in, and for
    # hybrid the Hub's signed identity as well — atlas_auth.py), so they write
    # like hub mode does; the admin check still applies per request. `auth_mode`
    # reads the environment (not hub_auth.AUTH_MODE) — see its docstring.
    return auth_mode() not in ("hub", "accounts", "hybrid") and not ALLOW_INSECURE


READ_ONLY = _read_only()

# Two settings for a hosted demo. Unset, neither changes anything.
#: A map style a browser wears until its viewer picks another.
DEFAULT_STYLE = os.environ.get("ATLAS_DEFAULT_STYLE", "").strip()
#: An INVENTED trust map to show every visitor. /api/v2/trust is admin-only
#: because a real one says where to aim a forged header; never point this at one.
DEMO_TRUST = os.environ.get("ATLAS_DEMO_TRUST", "").strip()
#: ATLAS_DEMO_FIGURES=1 draws the bundled demo's invented charts and card vitals
#: instead of asking Prometheus, and only while the bundled dataset is shown:
#: demofigures.enabled() reads it, with the rest of its conditions.
#: Where a look-only demo's "get Atlas" link goes. https:// only.
_DEMO_LINK = os.environ.get("ATLAS_DEMO_LINK", "").strip()
DEMO_LINK = _DEMO_LINK if _DEMO_LINK.startswith("https://") and " " not in _DEMO_LINK else ""

# ── Accounts, sessions, ingest — knobs read once at startup ──────────────────
# Collected here so /api/admin/settings has one honest source; each was a bare
# os.environ read in its own module before. Consumers reference `settings.X`, so
# a `fresh_app` reload of this module re-resolves them (the test contract). The
# two that a test flips AFTER the app is built stay LIVE functions instead —
# `auth_mode()` above and `mfa_required()` below.

# Sign-in throttle (accounts.py): both caps always, per the note there.
LOGIN_MAX_USER = int(os.environ.get("ATLAS_LOGIN_MAX_USER", "5"))
LOGIN_MAX_IP = int(os.environ.get("ATLAS_LOGIN_MAX_IP", "20"))
LOGIN_WINDOW_S = int(os.environ.get("ATLAS_LOGIN_WINDOW_MIN", "15")) * 60

# Session lifetimes (atlas_auth.py), in seconds.
SESSION_IDLE_S = int(os.environ.get("ATLAS_SESSION_IDLE_MIN", "60")) * 60
SESSION_ABS_S = int(os.environ.get("ATLAS_SESSION_ABS_HOURS", "12")) * 3600

# 1 in every deployment we run: tls-proxy is the only thing that APPENDS
# X-Forwarded-For, on both roads in (its own vhost, and the Hub — which
# forwards the header untouched rather than adding a hop). It stayed unset,
# and therefore 0, until 2026-09-09; the audit trail looked right only because
# ProxyFix was quietly rewriting remote_addr with its own x_for default. See
# app.py. 0 remains correct for a deployment with nothing in front.
# X-Forwarded-For hops to trust (atlas_auth.client_ip) — a HOP COUNT, not a
# boolean; 0 trusts only the socket peer. See client_ip for why it counts from
# the right.
# The reverse proxies whose X-Forwarded-For this app believes, BY ADDRESS —
# tls-proxy and the Hub, whose container IPs are PINNED in the internal host's
# compose (172.19.255.7 / .9) so they can be named here at all.
#
# This was a hop COUNT until 2026-09-09. A count believes the header from ANY
# peer that can open a socket to :5006 — all 14 containers on the `suite`
# network, not just those two. Measured, not theorised: an arbitrary peer
# sending `X-Forwarded-For: 1.2.3.4` resolved to 1.2.3.4, so a compromised
# sibling could rotate the header and walk past the login throttle. Naming the
# proxies closes that; a peer that is not one of them has its header ignored.
# Blank = trust nobody and key on the socket peer.

def _parse_trusted(raw):
    """ATLAS_TRUSTED_PROXIES -> tuple of ip_network. Never raises: a bad
    value must not stop the app booting, and must never widen trust."""
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
#: A header value is client text and becomes a throttle key; keep it bounded.
MAX_IP_KEY = 64

# Relay ingest surface (ingest.init_app): live only when this is set AND the db
# backend is on.
INGEST_ENABLED = os.environ.get("ATLAS_INGEST_ENABLED") == "1"


def mfa_required():
    """Who MUST enroll TOTP: "" (nobody), "all" (or 1/yes/on), "admins" (every
    surveyor — the lab policy since 2026-09-03; others may enroll), or a
    source name ("local"/"ldap"). The raw lowercased policy; `auth_routes`
    applies it per account. LIVE, not a constant: a test flips
    ATLAS_MFA_REQUIRED after the app is built (test_auth_gate_routes) and the
    very next request must see it."""
    return (os.environ.get("ATLAS_MFA_REQUIRED", "") or "").strip().lower()

# ── Deployment-specific addresses ────────────────────────────────────────────
# THE VIEWING GLASS knobs, LIVE (v1.38.2). The Grafana base used to be
# hard-coded in `static/js/config.js` and the vault root in `static/js/ui.js`,
# which meant every copy of the app shipped with one particular lab's internal
# address and one particular person's drive letter in its served JavaScript.
# They are configuration: these read THE SETTINGS first (integrations.py,
# group "glass") and the environment second, so an operator can widen
# frame-src or turn the probe off without a redeploy. Unset, they default to
# nothing and the glass degrades quietly rather than pointing at a host that
# isn't there.
#
# ATLAS_EMBED_HOSTS     Hosts the Chronicle may embed in an iframe
#                       (space-separated origins).
# ATLAS_EMBED_SERVICES  Widen `frame-src` to the origins the dataset already
#                       links to, so THE VIEWING GLASS can show a service in a
#                       pane over the map instead of a new tab. Only ever the
#                       origins the map itself points at — this is not a
#                       wildcard, and it grants those pages nothing: a framed
#                       cross-origin document still cannot read or touch the
#                       Atlas. 0 keeps the CSP to ATLAS_EMBED_HOSTS alone, in
#                       which case every outward button falls back to opening
#                       a tab.
# ATLAS_EMBED_PROBE     Ask a service whether it allows framing before
#                       offering to frame it. Off, the glass simply tries and
#                       falls back — which costs one blank pane per refusing
#                       service instead of one HEAD request per service per
#                       quarter-hour.
def embed_hosts():
    import integrations
    return integrations.get("ATLAS_EMBED_HOSTS")


def embed_services():
    import integrations
    return integrations.flag("ATLAS_EMBED_SERVICES", default=True)


def embed_probe():
    import integrations
    return integrations.flag("ATLAS_EMBED_PROBE", default=True)


# ATLAS_WHOIS           Let a viewer ask public whois servers from the Chronicle
#                       ("1"/"0", default on). Off for an Atlas strangers can
#                       reach, because each question goes out from this host.
def whois_enabled():
    import integrations
    return integrations.flag("ATLAS_WHOIS", default=True)

# (GRAFANA_URL — `ATLAS_GRAFANA` — lived here until v1.36.0. Grafana was
# decommissioned 2026-09-03: the card vitals and the watchings both draw from
# Prometheus/Loki themselves, and nothing in this app points at it any more.)


def auth_config():
    """Who the viewer is, and what this instance can actually offer them.

    The three modes differ in kind, not degree, so the front-end must be told
    which one it is rather than guessing — and it draws nothing it cannot act
    on:

      * `hub`        — the Hub owns the session and did the signing in.
                       There is no Atlas-side session to end, and `auth_routes`
                       is not even registered (app.py), so `/api/auth/*` 404s
                       here. The viewer gets their name, and no sign-out.
      * `accounts`   — a real Atlas session. Name, admin, MFA state, and a
                       sign-out, which needs the CSRF token `/api/auth/logout`
                       enforces (the Hub's own meta-tag precedent, 2026-05-17).
      * `standalone` — no gate and no identity; there is nothing to show.

    Resolved per request (`client_config` is called from `views.index`), and
    imported lazily because settings is the base layer the auth modules sit on
    top of — by request time every one of them is loaded, so there is no cycle.
    """
    mode = (envnames.env("ATLAS_AUTH_MODE") or "standalone").lower().strip()
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
            # which backend vouched for an Atlas session ('local' | 'ldap');
            # a Hub-named viewer has no account row and keeps '' — the front
            # end says "via the Hub" from `session` instead
            out["source"] = (acc or {}).get("source", "")
            out["emblem"] = (acc or {}).get("emblem", "")
            # A sign-out is offered only for a session we can actually end. In
            # hybrid a Hub-named viewer has no Atlas session, so the button
            # would POST to a route that would clear nothing and leave them
            # signed in by the very header that named them.
            out["canSignOut"] = out["session"] == "atlas"
    except Exception:      # noqa: BLE001 — identity plumbing never stops the map drawing
        log.warning("auth_config: could not resolve the viewer", exc_info=True)
    return out


def hub_url():
    """Where the Hub lives, per request: its forwarded header, else the env.

    ONE spelling, used by both the template inject (app.py) and client_config
    — the header name and the fallback must never drift between the two.
    """
    from flask import request   # request-time only; settings imports early
    given = request.headers.get("X-Hub-URL")
    if given:
        return given
    import integrations   # THE REALM (v1.38.0): the settings file first, then HUB_URL
    return integrations.get("HUB_URL")


def _scroll_root():
    """Prefix trimmed off `scroll` paths for display (the full path is still
    copied). THE REALM (v1.38.0): the settings file first, then ATLAS_SCROLL_ROOT."""
    import integrations
    return integrations.get("ATLAS_SCROLL_ROOT")


def client_config():
    """The deployment values the front-end needs, injected into the page.

    Delivered as a JSON block rather than baked into a module, so the same
    static assets serve every deployment.
    """
    out = {
        # where the Hub lives, for the seal's "sign out at the Hub" door
        "hubUrl": hub_url(),
        "scrollRoot": _scroll_root(),
        "version": APP_VERSION,
        "auth": auth_config(),
        # THE THEME (v1.48.0): the words and emblems that name one lab
        "theme": _theme.client(),
        # whether the Chronicle offers its whois pane
        "whois": whois_enabled(),
        "demoTrust": bool(DEMO_TRUST),
        "demoLink": DEMO_LINK,
    }
    # (`grafana`, `grafanaToken`, `grafanaTokenTtl` rode here until v1.36.0 —
    # the §20c embed token went with Grafana, 2026-09-03.)
    return out


def writes_enabled():
    """False when this instance refuses every write, whoever is asking."""
    return not READ_ONLY
