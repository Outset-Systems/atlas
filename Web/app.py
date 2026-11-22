import logging
import os
import sys
import threading

from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api_tokens
import atlas_auth
from api import status as api_status
from api import v2 as api_v2
import dataset
import embeddable
import envnames
import ingest
import labdata
import mapart
import metrics
import overlays as overlays_mod
import settings
import theme
import views
from context import AtlasContext
import redaction
from signals import build_hub_from_env

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("atlas.web.app")

for _name, _level in settings.LOG_LEVELS.items():
    logging.getLogger(_name).setLevel(_level)
if settings.LOG_LEVELS_REJECTED:
    log.warning("ATLAS_LOG_LEVELS: ignored unparseable entr%s %s",
                "y" if len(settings.LOG_LEVELS_REJECTED) == 1 else "ies",
                ", ".join(repr(b) for b in settings.LOG_LEVELS_REJECTED))
for _name, _given, _used in settings.ENV_REJECTED:
    log.warning("%s=%r is not a value this setting takes: using %s", _name, _given, _used)

from validation import validate as _validate



def _warn_about_posture(writable):
    if settings.auth_mode() != "standalone" or settings.ALLOW_INSECURE:
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
    import secrets as _secrets
    import time as _time

    deadline = _time.monotonic() + 2.5
    while _time.monotonic() < deadline:
        try:
            with open(key_file, encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                return key
            _time.sleep(0.05)
            continue
        except FileNotFoundError:
            pass
        except OSError:
            _time.sleep(0.05)
            continue
        candidate = _secrets.token_hex(32)
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        try:
            fd = os.open(key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(candidate)
        finally:
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass
        return candidate
    log.error("could not establish a stable session key at %s — sessions will "
              "not survive a restart", key_file)
    return _secrets.token_hex(32)


def _configure_sessions(app):
    key = envnames.secret("ATLAS_SECRET_KEY")
    if not key:
        key = _generated_session_key(
            os.path.join(settings.DATA_DIR, "secrets", "session.key"))
    app.secret_key = key
    app.config["SESSION_COOKIE_NAME"] = "atlas_session"
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = not settings.INSECURE_COOKIES


def _install_proxy_and_limits(app):
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1)
    app.config["MAX_CONTENT_LENGTH"] = mapart.MAX_BYTES + 1024 * 1024

    @app.errorhandler(413)
    def _too_large(_error):
        return jsonify({"error": "that request is too large"}), 413

    app.config["APP_VERSION"] = settings.APP_VERSION


def _build_context():
    reader = labdata.build(settings.DATA_BACKEND,
                           data_path=settings.DATA_PATH,
                           default_path=settings.DEFAULT_DATA_PATH,
                           site=settings.SITE_SLUG)
    store = dataset.build_store(settings.DATA_BACKEND,
                                data_path=settings.DATA_PATH,
                                default_path=settings.DEFAULT_DATA_PATH,
                                site=settings.SITE_SLUG,
                                revisions_dir=settings.REVISIONS_DIR)
    return AtlasContext(
        reader=reader,
        store=store,
        overlays=overlays_mod.build(settings.POSITIONS_PATH, settings.RACK_PATH),
        signals=build_hub_from_env(),
        config=settings,
        backend=settings.DATA_BACKEND,
        site=settings.SITE_SLUG,
    )


def _install_gate(app):
    if atlas_auth.sessions_enabled():
        _configure_sessions(app)
    app.config["METRICS_ENABLED"] = metrics.init_app(app)
    session_gate = atlas_auth.require_atlas_auth(
        exempt_paths=list(api_v2.EXEMPT_PATHS) + [metrics.METRICS_PATH],
        exempt_prefixes=["/static/", api_v2.INGEST_URL_PREFIX + "/"])

    def _gate():
        refusal = api_tokens.gate()
        if refusal is not None:
            return refusal
        return None if api_tokens.current() else session_gate()

    app.before_request(_gate)
    app.after_request(api_tokens.log_read)


def _register_blueprints(app):
    if atlas_auth.sessions_enabled():
        import auth_routes
        app.register_blueprint(auth_routes.bp)
        auth_routes.ensure_bootstrap_admin()

    app.register_blueprint(views.bp)
    app.register_blueprint(api_status.bp)
    app.config["INGEST_ENABLED"] = ingest.enabled()
    if app.config["INGEST_ENABLED"]:
        ingest.announce(api_v2.INGEST_URL_PREFIX)
    app.config["API_V2_ENABLED"] = api_v2.init_app(app)


def _install_template_context(app):
    @app.context_processor
    def _inject():
        return {
            "app_brand": settings.APP_BRAND,
            "theme": theme.T,
            "v": settings.APP_VERSION,
        }


def _install_security_headers(app):
    _csp_cache = {"stamp": None, "hosts": None, "by_clearance": {}}
    _csp_lock = threading.Lock()

    def _csp_floor():
        return embeddable.frame_list(None, settings.embed_hosts())

    def _frame_src():
        return _frame_list()[0]

    def _frame_list():
        hosts = settings.embed_hosts()
        if not settings.embed_services():
            return _csp_floor()
        try:
            data, stamp, _ = app.extensions["atlas"].dataset()
        except Exception:
            return _csp_floor()
        groups, token = redaction.viewer_groups(), bool(api_tokens.current())
        clearance = redaction.clearance_key(groups, token)
        with _csp_lock:
            if _csp_cache["stamp"] != stamp or _csp_cache["hosts"] != hosts:
                _csp_cache.update(stamp=stamp, hosts=hosts, by_clearance={})
            hit = _csp_cache["by_clearance"].get(clearance)
        if hit is not None:
            return hit
        seen, _ = redaction.redact(data, groups, token)
        made = embeddable.frame_list(seen, hosts)
        with _csp_lock:
            if _csp_cache["stamp"] == stamp and _csp_cache["hosts"] == hosts:
                _csp_cache["by_clearance"].setdefault(clearance, made)
        return made

    app.extensions["atlas_frame_list"] = _frame_list

    @app.after_request
    def _headers(resp):
        if resp.mimetype == "text/html":
            resp.headers.setdefault("Cache-Control", "no-cache")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        try:
            authed = atlas_auth.has_viewer()
        except Exception:
            authed = False
        if not authed:
            frames = "'self'"
        elif resp.mimetype == "text/html":
            frames = _frame_src()
        else:
            frames = _csp_floor()[0]
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "base-uri 'none'; form-action 'self'; object-src 'none'; "
            "frame-src " + frames,
        )
        return resp


def create_app():
    app = Flask(__name__)
    _install_proxy_and_limits(app)
    context = app.extensions["atlas"] = _build_context()
    _install_gate(app)
    _register_blueprints(app)
    _install_template_context(app)
    _install_security_headers(app)
    _warn_about_posture(settings.writes_enabled() and context.store.writable())
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=settings.HOST, port=settings.PORT, debug=settings.DEBUG)
