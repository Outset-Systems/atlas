import html
import logging
import os

from flask import Blueprint, jsonify, make_response, render_template

import demoreports
import mapart
import reports
import settings
from context import atlas
from security import is_admin

log = logging.getLogger("atlas.web.views")

bp = Blueprint("views", __name__)


@bp.route("/")
def index():
    title = _realm_title()
    seeded = atlas().reader.seeded()
    style = _default_style()
    return render_template(
        "index.html",
        editable=settings.writes_enabled() and is_admin(),
        seeded=seeded,
        demo=not seeded and settings.FALLBACK == "bundled",
        client_config=_client_config(style),
        map_image=_map_image(style),
        realm_title=title,
        veil_title=_veil_title(title),
    )


def _realm_title():
    try:
        data, _, _ = atlas().dataset()
        title = str((data.get("meta") or {}).get("title") or "").strip()
    except (OSError, ValueError):
        title = ""
    return title or settings.APP_BRAND


def _veil_title(title):
    short = title[:-len(" Atlas")] if title.endswith(" Atlas") else title
    return (short or title).upper()


def _default_style():
    if not settings.DEFAULT_STYLE:
        return None
    from api.v2.reads import maps_for_viewer
    return next((m for m in maps_for_viewer() if m["name"] == settings.DEFAULT_STYLE), None)


def _client_config(style):
    config = settings.client_config()
    if style:
        config["defaultStyle"] = style
    return config


def _map_image(style=None):
    if style:
        return style["url"]
    try:
        data, _, _ = atlas().dataset()
        name = (data.get("meta") or {}).get("map_image") or mapart.DEFAULT
    except (OSError, ValueError):
        name = mapart.DEFAULT
    path, bundled = mapart.resolve(name)
    if path:
        return mapart.url_of(os.path.basename(path), bundled)
    return mapart.url_of(mapart.DEFAULT, True)


@bp.route("/map-art/<name>")
def map_art(name):
    blob, kind = mapart.read_upload(name)
    if blob is None:
        return jsonify({"error": "no such render"}), 404
    if not kind:
        log.warning("refusing to serve map art %s: not a raster image",
                    mapart.safe_name(name))
        return jsonify({"error": "that render is not a usable image"}), 415

    resp = make_response(blob)
    resp.headers["Content-Type"] = mapart.MIMETYPES[kind]
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Disposition"] = "inline"
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


def _demo_report(name):
    if name != "uptime":
        return demoreports.security()
    from api.v2.feeds import _redact_feed, build_feed
    from redaction import redact_for_groups, sees_everything, viewer_groups
    ctx = atlas()
    try:
        raw, _, _ = ctx.dataset()
    except (OSError, ValueError):
        return "_The board could not read the map._"
    groups = viewer_groups()
    feed = build_feed(ctx)
    if not (sees_everything(groups) and is_admin()):
        feed = _redact_feed(ctx, feed, groups, data=raw)
    return demoreports.uptime(redact_for_groups(raw)[0], feed)


@bp.route("/report/<name>")
def report(name):
    status = 200
    if demoreports.enabled() and name in demoreports.NAMES:
        body = _demo_report(name)
    elif name in reports.REPORTS and not is_admin():
        body, status = "_This scroll is kept for an admin._", 403
    elif name == "security":
        body = reports._security_scroll()
    elif name in reports.REPORTS:
        body, _ = reports._read_report(name)
        if body is None:
            body = "_The scribes have not yet delivered this report._"
    else:
        body, status = "_No such scroll._", 404
    page = (
        "<!doctype html><meta charset='utf-8'>"
        f"<title>{html.escape(name)} report</title>"
        "<style>body{background:#1d2021;color:#ebdbb2;margin:0;padding:1.2rem 1.6rem;}"
        "pre{font:12.5px/1.55 'Cascadia Code',Consolas,monospace;white-space:pre-wrap;"
        "word-break:break-word;margin:0;}</style>"
        f"<pre>{html.escape(body)}</pre>"
    )
    resp = make_response(page, status)
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    return resp
