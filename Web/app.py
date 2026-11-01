"""Atlas — the cinematic sand-table map of the lab.

The suite-contract Flask app (dual-mode auth, `/api/status`, `/data`
persistence). This module used to be the whole backend; it is now the factory
that assembles it, because a 600-line module whose configuration was read at
import time could not be tested twice in one process — which is exactly why
The suite only passed one file at a time.

What lives where now:

    settings.py    every environment variable, read once
    schema.py      the field catalogue: what the dataset *is*
    validation.py  the catalogue applied to a dataset (warnings)
    labdata.py     the cached, hot-reloading read path
    dataset.py     the ops-based write path, strict, journalled
    overlays.py    positions.json / rack.json merged over the truth
    security.py    who may write, and proof the request came from us
    views.py       the page, the map art and the staged reports
    auth_routes.py the sign-in page and the first-run bootstrap
    api/status.py  /api/status — the fleet card contract, kept
    api/v2/        every other HTTP workstation: reads, feeds, probes, the beat,
                   the editor (admin), sites (db), ingest (db + opt-in),
                   accounts (accounts/hybrid), vitals, charts — one blueprint
    ingest.py      the relay ingest GATE (token, size cap, limiter)
    whois.py       THE NAMING DEEP's vetted socket engine

`/api/v2/` is the API; the unversioned routes it replaced were removed in
v1.41.0.

Prod entrypoint: `gunicorn app:app` (see Dockerfile). `python app.py` = dev.
"""

import logging
import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api_tokens  # noqa: E402
import atlas_auth  # noqa: E402
from api import status as api_status  # noqa: E402
from api import v2 as api_v2  # noqa: E402
import dataset  # noqa: E402
import embeddable  # noqa: E402
import envnames  # noqa: E402
import ingest  # noqa: E402
import labdata  # noqa: E402
import overlays as overlays_mod  # noqa: E402
import settings  # noqa: E402
import theme  # noqa: E402
import views  # noqa: E402
from context import AtlasContext  # noqa: E402
from hub_auth.auth import AUTH_MODE  # noqa: E402
from signals import build_hub_from_env  # noqa: E402

# ── The logger tree ──────────────────────────────────────────────────────────
# Every module logs to `atlas.<layer>.<module>`, so a level can be set for one
# layer instead of for the whole app:
#
#   atlas.web    the pages and what serves them      app, views, embeddable
#   atlas.api    the HTTP surfaces                   v2 (one logger), status
#   atlas.auth   who may pass, and what proves it    gate, routes, config,
#                                                    accounts, crypto, security
#   atlas.data   the dataset and what shapes it      dataset, labdata, overlays,
#                                                    mapart, worldsurvey
#   atlas.io     how bytes reach disk intact         jsonio, filelock
#   atlas.live   what the lab is doing right now     signals, ingest, events,
#                                                    heartbeats, discovery,
#                                                    maintenance, dependencies
#   atlas.settings   cross-cutting; deliberately in no layer
#
# It used to be 18 modules on a flat "atlas" and 9 on ad-hoc dotted children
# (`atlas.auth_config` a SIBLING of `atlas.auth`, not a child), which meant
# there was no way to ask for "the dataset layer, louder". `%(name)s` replaces
# the hard-coded literal `atlas` in the format — the tree is worthless in a log
# line that refuses to print which logger spoke. `tests/test_logging_tree.py`
# holds the convention.
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("atlas.web.app")

for _name, _level in settings.LOG_LEVELS.items():
    logging.getLogger(_name).setLevel(_level)
if settings.LOG_LEVELS_REJECTED:
    # Loud, not fatal: a typo in a logging knob should never stop the Atlas
    # booting, but it must not look like it worked either.
    log.warning("ATLAS_LOG_LEVELS: ignored unparseable entr%s %s",
                "y" if len(settings.LOG_LEVELS_REJECTED) == 1 else "ies",
                ", ".join(repr(b) for b in settings.LOG_LEVELS_REJECTED))

# ── A name the tests still import (`tests/test_store.py` reads `app._validate`).
# Three redaction aliases sat beside it under a comment claiming other modules
# imported them; nothing did (2026-08-21 survey, repo-wide grep).
from validation import validate as _validate  # noqa: E402,F401

# The one settings alias the tests still read (`atlas_app.DATA_BACKEND` in
# test_store / test_api_v2_sites_scoping). Eight siblings — APP_KEY, APP_NAME,
# APP_VERSION, ACCENT_COLOR, PORT, DATA_PATH, DEFAULT_DATA_PATH, SITE_SLUG —
# had no reader anywhere (2026-11-01 repo-wide grep) and are gone; read
# `settings.<NAME>` directly.
DATA_BACKEND = settings.DATA_BACKEND
# (EMBED_HOSTS alias removed 2026-09-03: the glass knobs are live via
#  settings.embed_hosts(); a boot-time copy here would be the one that disagrees)


def _warn_about_posture(writable):
    """Say plainly what this deployment exposes, at the moment it starts.

    Standalone mode serves the full lab map — every internal address, hostname
    and service URL — with no auth. That is fine on loopback and dangerous on
    a routable interface. Now that the same instance can also be *edited*, the
    warning has to say so.
    """
    if AUTH_MODE != "standalone" or settings.ALLOW_INSECURE:
        return
    log.warning(
        "SECURITY: running in STANDALONE mode — NO authentication. The whole map "
        "(internal addresses, host names, service URLs) is served to anyone who can "
        "reach this port%s. For real use set ATLAS_AUTH_MODE=accounts (or hub / "
        "hybrid behind a signing proxy; docs/configuration.md). Bind to loopback for "
        "local dev, set ATLAS_READONLY=1 to at least refuse writes, or set "
        "ATLAS_ALLOW_INSECURE=1 to silence this on a trusted network.",
        ", and the editing API will accept changes from them" if writable else "",
    )


def _generated_session_key(key_file):
    """Read the generated session key, creating it if this process is first.

    The create is `O_CREAT | O_EXCL`, and losing that race means re-reading the
    winner's key rather than keeping our own. Gunicorn forks its workers and
    each runs `create_app()` at import (there is no `--preload`), so on a fresh
    install every worker reached the `else` branch at the same moment, wrote a
    DIFFERENT key, and kept the one it had generated. The workers then disagreed
    about every session cookie's signature, and a signed-in user was logged out
    on roughly whichever request happened to land on the other worker.
    """
    import secrets as _secrets

    for _ in range(2):
        try:
            with open(key_file, encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                return key
        except OSError:
            pass
        candidate = _secrets.token_hex(32)
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        try:
            fd = os.open(key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue            # somebody else won; go back and read theirs
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(candidate)
        finally:
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass
        return candidate
    # Two passes and the file is still unreadable: better a working process with
    # sessions that do not survive a restart than a boot loop.
    log.error("could not establish a stable session key at %s — sessions will "
              "not survive a restart", key_file)
    return _secrets.token_hex(32)


def _configure_sessions(app):
    """Cookie sessions exist only in accounts mode (every other mode is
    cookie-less). The signing key must be STABLE across restarts and shared by
    all gunicorn workers, or each restart/worker logs everyone out:
    ATLAS_SECRET_KEY env wins, then ATLAS_SECRET_KEY_FILE (file-mounted
    secret), else one is generated once into `<data-dir>/secrets/session.key`.

    Cookie posture is decided ONCE at startup, never per request — deriving
    Secure from a client-influenced header is a documented bug class.
    Secure defaults ON (production sits behind TLS); ATLAS_INSECURE_COOKIES=1
    is the explicit opt-out for plain-http LAN testing, where a browser would
    otherwise silently drop the cookie.
    """
    key = envnames.secret("ATLAS_SECRET_KEY")
    if not key:
        key = _generated_session_key(
            os.path.join(settings.DATA_DIR, "secrets", "session.key"))
    app.secret_key = key
    # 🔴 NOT Flask's default "session". The Atlas is served from the same
    # hostname as the Hub (<hub-host>/atlas/), and both are
    # Flask — a shared cookie name means whichever signs in last silently
    # overwrites the other's session at path "/". Signing into the Atlas
    # would sign you out of the Hub. This became reachable the moment the
    # Hub started proxying the Atlas anonymously so it can show its own
    # login; before that a Hub-authenticated user never triggered one.
    app.config["SESSION_COOKIE_NAME"] = "atlas_session"
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = not settings.INSECURE_COOKIES


def create_app():
    """Build a configured Atlas. One per process in production; the tests
    build several, which is the point of it being a function."""
    app = Flask(__name__)
    # 🔴 THE ATLAS NEVER SEES ITS OWN FRONT DOOR. TLS is terminated upstream
    # (tls-proxy, and Traefik beyond it) and the Hub proxies /atlas/ over
    # plain http on the compose network, so without this Flask computes
    # `request.host_url` as "http://…" while the browser is on https. The
    # routes that read `host_url` as their OWN origin — /api/embeddable and
    # /api/whois, which compare it against a target before making an outbound
    # request — must see the real scheme, or their same-origin reasoning is
    # done against the wrong string.
    #
    # (Until v1.22 this also fixed sign-in: the old CSRF check compared the
    # browser's Origin against host_url and 403'd every direct sign-in behind
    # the TLS front. That check is gone — `security.same_origin_refusal` proves
    # same-origin with `X-Atlas-Write` + `Sec-Fetch-Site`, neither of which
    # depends on the scheme — so ProxyFix stays only for the host_url readers.)
    #
    # x_proto=1 ONLY. The scheme is the thing that is wrong and the thing the
    # front ends actually set. `x_for`/`x_host` are pinned to 0: trusting a
    # forwarded client IP is how the Feed's per-IP lockout was evaded
    # (the 2026-07-18 security review), and nothing here should inherit that bug for free.
    # One hop is correct on both roads — tls-proxy sets X-Forwarded-Proto
    # and the Hub passes it through unchanged rather than appending its own.
    #
    # 🔴 x_for=0 IS WRITTEN OUT ON PURPOSE. werkzeug's default is x_for=1, so
    # `ProxyFix(app.wsgi_app, x_proto=1)` — what stood here until 2026-09-09 —
    # silently did the exact thing the paragraph above forbids: it rewrote
    # request.remote_addr from X-Forwarded-For on every request. It was not
    # exploitable, because the port is not published and only tls-proxy and
    # the Hub can reach it, and it even produced the RIGHT answer (nginx
    # appends the real caller) — which is why nothing caught it. But the
    # client IP now comes from ONE place, `atlas_auth.client_ip` +
    # ATLAS_TRUSTED_PROXIES, which counts hops from the right and says so.
    # Leaving both mechanisms on meant the knob read 0 while the address was
    # being forwarded anyway. Pinned by test_client_ip.py.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1)
    app.config["APP_NAME"] = settings.APP_NAME
    app.config["APP_VERSION"] = settings.APP_VERSION
    app.config["ACCENT_COLOR"] = settings.ACCENT_COLOR

    reader = labdata.build(settings.DATA_BACKEND,
                           data_path=settings.DATA_PATH,
                           default_path=settings.DEFAULT_DATA_PATH,
                           site=settings.SITE_SLUG)
    store = dataset.build_store(settings.DATA_BACKEND,
                                data_path=settings.DATA_PATH,
                                default_path=settings.DEFAULT_DATA_PATH,
                                site=settings.SITE_SLUG,
                                revisions_dir=settings.REVISIONS_DIR)
    app.extensions["atlas"] = AtlasContext(
        reader=reader,
        store=store,
        overlays=overlays_mod.build(settings.POSITIONS_PATH, settings.RACK_PATH),
        signals=build_hub_from_env(),
        config=settings,
        backend=settings.DATA_BACKEND,
        site=settings.SITE_SLUG,
    )

    # Auth first. The relay ingest surface is exempt from the Hub session gate
    # (a push agent has no session, so its per-site bearer token is the whole
    # credential); the prefix is exempt whether or not ingest is enabled,
    # since without it those paths simply 404.
    #
    # atlas_auth wraps the framework gate: in hub/standalone modes it defers
    # to it untouched; `accounts` adds real sign-in (local password store
    # and/or a direct LDAPS bind), and `hybrid` accepts the Hub's signed
    # identity when it is present and falls back to that same sign-in when it
    # is not — see atlas_auth.py. Both need the session cookie and the login
    # page, so every switch here asks `sessions_enabled`, not `accounts_mode`.
    if atlas_auth.sessions_enabled():
        _configure_sessions(app)
    # /metrics (metrics.py, v1.38.0) is exempt from the SESSION gate — a
    # scraper has no session — and gates ITSELF on a bearer token, answering
    # 404 when none is configured. The hooks it installs must wrap every
    # request, gate included, so it registers before the gate does.
    import metrics
    app.config["METRICS_ENABLED"] = metrics.init_app(app)
    session_gate = atlas_auth.require_atlas_auth(
        exempt_paths=list(api_v2.EXEMPT_PATHS) + [metrics.METRICS_PATH],
        exempt_prefixes=["/static/", api_v2.INGEST_URL_PREFIX + "/"])

    # An API token answers on its own short list of routes and nowhere else
    # (api_tokens.py); every other request reaches the session gate unchanged.
    def _gate():
        refusal = api_tokens.gate()
        if refusal is not None:
            return refusal
        return None if api_tokens.current() else session_gate()

    app.before_request(_gate)

    if atlas_auth.sessions_enabled():
        import auth_routes
        app.register_blueprint(auth_routes.bp)
        auth_routes.ensure_bootstrap_admin()

    app.register_blueprint(views.bp)
    # /api/status — the fleet card contract the Hub and Kuma probe on every
    # app. The ONE unversioned API path kept at the v1 removal (v1.41.0).
    app.register_blueprint(api_status.bp)
    # The API. One blueprint, always mounted; the surfaces that exist only in
    # some postures (sites: db; ingest: db + opt-in; accounts: sessions) fence
    # themselves per request with a 404, so the url map is the same in every
    # mode and a missing route never looks like a broken deploy.
    app.config["INGEST_ENABLED"] = ingest.enabled()
    if app.config["INGEST_ENABLED"]:
        ingest.announce(api_v2.INGEST_URL_PREFIX)
    app.config["API_V2_ENABLED"] = api_v2.init_app(app)

    @app.context_processor
    def _inject():
        return {
            "app_name": app.config["APP_NAME"],
            # pre-auth pages use this instead — see settings.APP_BRAND
            "app_brand": settings.APP_BRAND,
            # THE THEME (v1.48.0): every lab-specific word in the templates
            "theme": theme.T,
            "accent_color": app.config["ACCENT_COLOR"],
            "hub_url": settings.hub_url(),
            "v": settings.APP_VERSION,   # cache-buster for static asset URLs
        }

    # The floor: 'self' + the configured embed hosts, dataset or no dataset.
    # THE GLASS knobs are live since v1.38.2 (integrations.py, group "glass"):
    # the floor and the memo both key on the hosts value in force, so a change
    # made in THE SETTINGS reaches the next response without a restart.
    _csp_cache = {"stamp": None, "hosts": None, "value": None}

    def _csp_floor():
        return embeddable.frame_src(None, settings.embed_hosts())

    def _frame_src():
        """The `frame-src` list: 'self', the configured embed hosts, and — when
        ATLAS_EMBED_SERVICES is on — the origins the dataset already links to,
        so THE VIEWING GLASS can show a service without leaving the map.

        Derived from the dataset rather than configured by hand because the two
        would drift the moment a service moved, and the failure mode of drift
        here is a silently blank pane.

        Memoized on the dataset stamp the reader already returns: this runs in
        `after_request` — every response, every static file — and re-walking
        the dataset each time measured ~175 µs a response for a string that
        changes only when the map does. A transient read error serves the last
        derived value rather than quietly narrowing the CSP to the floor,
        whose only symptom would be a blank glass pane on a few responses.
        """
        hosts = settings.embed_hosts()
        if not settings.embed_services():
            return _csp_floor()
        try:
            data, stamp, _ = app.extensions["atlas"].dataset()
        except Exception:      # noqa: BLE001 — never fail a response over this
            return _csp_cache["value"] if _csp_cache["value"] is not None else _csp_floor()
        if _csp_cache["stamp"] != stamp or _csp_cache["hosts"] != hosts:
            _csp_cache["stamp"], _csp_cache["hosts"] = stamp, hosts
            _csp_cache["value"] = embeddable.frame_src(data, hosts)
        return _csp_cache["value"]

    @app.after_request
    def _headers(resp):
        # HTML must revalidate every load — a stale index.html pins stale JS
        # for days via heuristic caching (bit us 2026-07-11). Static assets
        # carry ?v=APP_VERSION instead, so they cache hard between releases.
        if resp.mimetype == "text/html":
            resp.headers.setdefault("Cache-Control", "no-cache")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        # Self-contained app; inline styles are set on elements the JS builds.
        #
        # 🔴 `frame-src` is DERIVED FROM THE DATASET (see `_frame_src`), so it
        # enumerates the internal service origins the map links to — hosts,
        # ports, subnets. That is precisely the topology the login wall exists
        # to protect, and it must never reach a caller who has not signed in.
        #
        # Found 2026-08-19, hours after the Atlas first answered on the public
        # internet: an anonymous `GET /auth/login` returned a CSP header listing
        # **36 origins, 8 of them internal hosts with their ports**. No
        # credentials needed, and invisible to every check that reads the body —
        # the same blind spot that let this arc's three decorative-gate bugs
        # through. The login page embeds nothing, so it has no use for the list.
        #
        # Only withheld where the Atlas actually gates itself. In `hub` and
        # `standalone` mode there is no anonymous side of an Atlas gate (the Hub
        # is the gate, and the port is unpublished), so behaviour is unchanged.
        try:
            gated = atlas_auth.sessions_enabled()
            authed = (not gated) or bool(atlas_auth.current_user())
        except Exception:      # noqa: BLE001 — never fail a response over this
            authed = False     # fail CLOSED: the narrow CSP is the safe default
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            # three directives `default-src` does not govern (the 2026-11-01
            # review): no <base> rewriting, forms post only to this origin,
            # and no plugins
            "base-uri 'none'; form-action 'self'; object-src 'none'; "
            "frame-src "
            + (_frame_src() if authed else "'self'"),
        )
        return resp

    _warn_about_posture(settings.writes_enabled() and store.writable())
    return app


app = create_app()
# (five "historic module-level names the tests read directly" sat here — `_lab`,
# `_signals`, `_store`, `INGEST_ENABLED`, `API_V1_ENABLED`. The tests build
# their handle from `app.extensions["atlas"]` via tests/appfixture.py and never
# read these; removed 2026-08-21.)


if __name__ == "__main__":
    # dev only — production runs gunicorn (Dockerfile CMD)
    app.run(host=settings.HOST, port=settings.PORT, debug=settings.DEBUG)
