"""THE SOURCES and THE DEPLOYMENT — `/api/v2/admin/integrations*`, `/deployment`.

Where the live signals come from, a real test of each, and a read-only list of
every setting. Split out of `admin.py` (2026-11-09); same blueprint, same gate.
"""

import logging
import os

from flask import jsonify, request

import settings
from context import atlas
from security import actor, write_refusal


log = logging.getLogger("atlas.api.v2")
from .admin import (  # noqa: E402
    _probe_allowed, _secret_stays_home, _valid_url, admin_bp,
)


# ── THE SOURCES — integration settings (v1.37.0) ─────────────────────────────
def _hub_state():
    """What the live hub is actually running, and how each source answered
    last time — so the form shows the truth beside the settings."""
    try:
        hub = atlas().signals
        feed = hub._cache or {}
        return {"enabled": list(getattr(hub, "enabled", [])),
                "last": dict(feed.get("sources") or {})}
    except Exception:  # noqa: BLE001 — a form must never 500 over a status line
        return {"enabled": [], "last": {}}


def _probe(kind, url, key, path=None):
    """Ask one source whether it is there, the way the Atlas will ask it.
    Returns (ok, detail). Never raises — the answer is the point. `path` is
    the decoy feed's roster path as typed (None = the one in force)."""
    import requests
    base = (url or "").rstrip("/")
    if not base:
        return False, "no URL to ask"
    try:
        if kind == "prometheus":
            r = requests.get(base + "/-/ready", timeout=5)
            r.raise_for_status()
            q = requests.get(base + "/api/v1/query", params={"query": "count(up == 1)"}, timeout=5)
            q.raise_for_status()
            res = q.json().get("data", {}).get("result", [])
            n = int(float(res[0]["value"][1])) if res else 0
            return True, f"Prometheus is ready — {n} watchfire{'s' if n != 1 else ''} up"
        if kind == "loki":
            r = requests.get(base + "/ready", timeout=5)
            r.raise_for_status()
            return True, "Loki is ready"
        if kind == "kuma":
            r = requests.get(base + "/metrics", auth=("", key) if key else None, timeout=5)
            if r.status_code == 401:
                return False, "Kuma refused the key"
            r.raise_for_status()
            n = sum(1 for line in r.text.splitlines() if line.startswith("monitor_status{"))
            return True, f"Kuma answers — {n} monitor{'s' if n != 1 else ''}"
        if kind == "decoys":
            import envnames
            import integrations
            header = envnames.env("ATLAS_DECOYS_KEY_HEADER")
            # TRIPWIRES: ask where the adapter will ask (ATLAS_DECOYS_PATH)
            r = requests.get(base + (path or integrations.decoys_path()),
                             headers={header: key or ""}, timeout=5)
            if r.status_code in (401, 403, 404):
                return False, "the decoy feed did not admit that key"
            r.raise_for_status()
            stones = r.json().get("stones", {})
            n = len(stones)
            return True, f"the decoy feed answers — {n} decoy{'s' if n != 1 else ''} charted"
        return False, f"unknown source {kind!r}"
    except Exception as e:  # noqa: BLE001 — a remote that will not answer is the finding
        return False, f"did not answer: {e.__class__.__name__}: {str(e)[:120]}"


_PROBE_FIELDS = {"prometheus": ("ATLAS_PROM_URL", None),
                 "loki": ("ATLAS_LOKI_URL", None),
                 "kuma": ("ATLAS_KUMA_URL", "ATLAS_KUMA_API_KEY"),
                 "decoys": ("ATLAS_DECOYS_URL", "ATLAS_DECOYS_KEY")}


@admin_bp.route("/integrations")
def integrations_get():
    import integrations
    return jsonify({"settings": integrations.describe(),
                    "allowed": list(integrations.ALLOWED),
                    "groups": {k: list(v) for k, v in integrations.GROUPS.items()},
                    "sources": list(integrations.SOURCES),
                    "hub": _hub_state()})


# ── THE DEPLOYMENT — every knob the app knows, read-only (v1.38.0) ───────────
_SECRETISH = ("KEY", "SECRET", "PASSWORD", "TOKEN")


def _known_env_names():
    """Every environment variable settings.py (and the two secret readers)
    consult, found by reading the source — so a knob added tomorrow shows up
    without anyone remembering to register it."""
    import glob as _glob
    import re as _re
    import integrations
    import auth_config
    import settings as _settings
    names = set()
    web = os.path.dirname(os.path.abspath(_settings.__file__))
    pattern = _re.compile(r'"((?:ATLAS|PROMETHEUS)_[A-Z0-9_]+|HUB_URL)"')
    for path in _glob.glob(os.path.join(web, "*.py")) + _glob.glob(os.path.join(web, "api", "**", "*.py"), recursive=True):
        try:
            with open(path, encoding="utf-8") as fh:
                names |= set(pattern.findall(fh.read()))
        except OSError:
            pass
    names |= set(integrations.ALLOWED)   # the runtime-settable ones live outside settings.py
    names |= set(auth_config.ALLOWED)    # ldap_backend reads these, not settings.py
    names |= {"ATLAS_AUTH_MODE", "ATLAS_HUB_SECRET", "ATLAS_HUB_SECRET_FILE",
              "ATLAS_HUB_AUTH_HEADER", "ATLAS_ADMIN_GROUP", "ATLAS_THEME", "HUB_URL", "ATLAS_METRICS_TOKEN", "ATLAS_METRICS_TOKEN_FILE",
              "ATLAS_KUMA_URL", "ATLAS_KUMA_API_KEY", "ATLAS_KUMA_API_KEY_FILE",
              "ATLAS_DECOYS_URL", "ATLAS_DECOYS_KEY", "ATLAS_DECOYS_KEY_FILE",
              "ATLAS_DECOYS_KEY_HEADER", "ATLAS_DECOYS_PATH",
              "ATLAS_TRIPWIRES_WEBHOOK", "ATLAS_TRIPWIRES_SECRET", "ATLAS_TRIPWIRES_SECRET_FILE",
              "ATLAS_TRIPWIRES_STATE",
              "ATLAS_LOKI_URL", "ATLAS_INTEGRATIONS", "PROMETHEUS_MULTIPROC_DIR"}
    return sorted(names)


@admin_bp.route("/deployment")
def deployment_view():
    """What this instance is actually running with: each knob, the layer its
    value came from (settings file / environment / default), and the value —
    masked to set/unset for anything that looks like a secret. Read-only by
    construction: there is no POST twin, and there must never be one (the
    allow-lists in auth_config/integrations are the only writable knobs)."""
    import auth_config
    import integrations
    layer = {"settings": "settings", "deployment": "environment", "unset": "default"}
    stored = integrations.sources()
    dir_stored, dir_values = auth_config.sources(), auth_config.effective()
    from urllib.parse import urlsplit, urlunsplit
    from flask import current_app

    def shown(name, value, secret):
        if secret:
            return "set" if value else "unset"
        # a URL that carries credentials (ATLAS_DB_URL is a DSN; a proxy URL
        # could be one) shows its shape, never its password (review, 2026-09-03)
        try:
            u = urlsplit(value)
            if u.password or u.username:
                host = u.hostname or ""
                if u.port:
                    host += f":{u.port}"
                return urlunsplit((u.scheme, f"{u.username or ''}:***@{host}", u.path, u.query, u.fragment))
        except ValueError:
            pass
        return value

    rows = []
    for name in _known_env_names():
        secret = any(tag in name for tag in _SECRETISH) or name in integrations.SECRETS
        if name in integrations.ALLOWED:
            value, source = integrations.get(name), layer[stored[name]]
        elif name in auth_config.ALLOWED:
            value, source = dir_values[name], layer[dir_stored[name]]
        else:
            # NAMES THAT CHANGED (v1.48.0): a deployment still on an old name
            # is still configured; envnames reads either spelling
            import envnames
            value = os.environ.get(name, "") or (
                (envnames.env(name) or "") if envnames.is_set(name) else "")
            source = "environment" if value else "default"
        rows.append({"name": name, "source": source, "secret": secret,
                     "value": shown(name, value, secret)})
    # `metrics` is what /metrics will actually DO: the registry came up AND a
    # token is configured. A token with a registry that failed to start (the
    # 09-03 uid case) is "off", not "on" — the first cut reported the token alone.
    token_set = bool(os.environ.get("ATLAS_METRICS_TOKEN") or os.environ.get("ATLAS_METRICS_TOKEN_FILE"))
    return jsonify({"version": settings.APP_VERSION, "mode": settings.auth_config().get("mode", ""),
                    "metrics": bool(current_app.config.get("METRICS_ENABLED")) and token_set,
                    "metrics_registry": bool(current_app.config.get("METRICS_ENABLED")),
                    "metrics_token": token_set,
                    "knobs": rows})


@admin_bp.route("/integrations/test", methods=["POST"])
def integrations_test():
    """Probe ONE source with the values as typed (unsaved) — a blank key means
    'the one in force', so a stored secret can be tested without retyping it, at
    the address it was saved with and nowhere else."""
    refusal = write_refusal()
    if refusal:
        return refusal
    if not _probe_allowed(actor()):
        return jsonify({"ok": False, "error": "Too many tests in a minute — wait a moment."}), 429
    import integrations
    body = request.get_json(silent=True) or {}
    kind = str(body.get("kind") or "").strip().lower()
    if kind not in _PROBE_FIELDS:
        return jsonify({"ok": False, "error": f"not a source that can be tested: {kind!r}"}), 400
    proposed = body.get("settings") or {}
    unknown = [k for k in proposed if k not in integrations.ALLOWED]
    if unknown:
        return jsonify({"ok": False, "error": f"not an integration setting: {unknown[0]}"}), 400
    url_key, secret_key = _PROBE_FIELDS[kind]
    url = str(proposed.get(url_key) or "").strip() or integrations.get(url_key)
    if not url:
        return jsonify({"ok": False, "error": f"No URL is set for {kind} — nothing to ask."}), 400
    if not _valid_url(url):
        return jsonify({"ok": False, "error": "That is not an http(s) URL with a host."}), 400
    if integrations.moves_secret(url_key, proposed):
        return jsonify({"ok": False, "error": _secret_stays_home()}), 400
    key = (str(proposed.get(secret_key) or "").strip() or integrations.get(secret_key)) if secret_key else None
    path = None
    if kind == "decoys":
        path = str(proposed.get("ATLAS_DECOYS_PATH") or "").strip() or None
        if path and not integrations.valid_decoys_path(path):
            return jsonify({"ok": False, "error": "ATLAS_DECOYS_PATH must be an absolute "
                                                  "path like /api/stones."}), 400
    # the path only when one was typed: `_probe(kind, url, key)` stays the call shape
    ok, detail = _probe(kind, url, key, path=path) if path else _probe(kind, url, key)
    log.info("v2: source test %s by %s: ok=%s", kind, actor(), ok)
    return jsonify({"ok": ok, "detail": detail if ok else "", "error": "" if ok else detail})


@admin_bp.route("/integrations", methods=["POST"])
def integrations_save():
    refusal = write_refusal()
    if refusal:
        return refusal
    import integrations
    proposed = (request.get_json(silent=True) or {}).get("settings") or {}
    unknown = [k for k in proposed if k not in integrations.ALLOWED]
    if unknown:
        return jsonify({"error": f"not an integration setting: {unknown[0]}"}), 400

    def in_force(key):
        given = proposed.get(key)
        if key in integrations.SECRETS:
            if given is None and key in proposed:
                return ""                              # being cleared
            return str(given or "").strip() or integrations.get(key)
        if key in proposed:
            return str(given or "").strip() or integrations._env(key)
        return integrations.get(key)

    for key in integrations.URLS:
        value = in_force(key)
        if value and not _valid_url(value):
            return jsonify({"error": f"{key} must be an http(s) URL with a host."}), 422
        # saving is how a blank secret would otherwise follow a URL to a new host
        if integrations.moves_secret(key, proposed, saving=True):
            return jsonify({"error": _secret_stays_home()}), 422
    # THE GLASS (v1.38.2): the hosts list goes into a CSP header, where a `;`
    # or a newline voids the whole value (embeddable.frame_src refuses it, but
    # the form should say so before the save, not the log after); the two
    # switches are '1', '0' or blank.
    hosts = str(proposed.get("ATLAS_EMBED_HOSTS", "") or "")
    if ";" in hosts or "\n" in hosts or "\r" in hosts:
        return jsonify({"error": "ATLAS_EMBED_HOSTS is a space-separated list of origins — no ';' or newlines."}), 422
    decoys_path = str(proposed.get("ATLAS_DECOYS_PATH", "") or "").strip()
    if decoys_path and not integrations.valid_decoys_path(decoys_path):
        return jsonify({"error": "ATLAS_DECOYS_PATH must be an absolute path on the decoy "
                                 "feed, like /api/stones — no scheme, host, query or spaces."}), 422
    site = str(proposed.get("ATLAS_UNIFI_SITE", "") or "").strip()
    if site and not integrations.valid_unifi_site(site):
        return jsonify({"error": "ATLAS_UNIFI_SITE is the site's short name from the controller's "
                                 "address, like default: letters, digits, - and _ only."}), 422
    for key in integrations.BOOLS:
        if key in proposed and str(proposed.get(key) or "").strip() not in ("", "0", "1"):
            return jsonify({"error": f"{key} must be 1, 0, or blank (the deployment's value)."}), 422
    wanted = [s.strip().lower() for s in in_force("ATLAS_SIGNALS_SOURCES").split(",") if s.strip()]
    bad = [s for s in wanted if s not in integrations.SOURCES]
    if bad:
        return jsonify({"error": f"unknown signals source: {bad[0]} — one of "
                                 f"{', '.join(integrations.SOURCES)}"}), 422
    for src, need in integrations.SOURCE_NEEDS.items():
        if src in wanted and not in_force(need):
            return jsonify({"error": f"the {src} source needs {need} before it can be enabled."}), 422
    try:
        described = integrations.save(proposed)
    except Exception as e:  # noqa: BLE001 — ValueError, OSError, or a master key that will not open
        log.warning("v2: integration settings save failed: %s", e)
        return jsonify({"error": f"could not save: {e}"}), 500
    log.info("v2: integration settings changed by %s", actor())
    # the hub rebuilds on its next poll (it watches the file's mtime); make it now
    try:
        atlas().signals._refresh_adapters()
    except Exception:  # noqa: BLE001 — the next poll will
        pass
    return jsonify({"ok": True, "settings": described, "hub": _hub_state()})
