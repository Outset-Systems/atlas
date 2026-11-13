"""Pages: the atlas itself, and the staged markdown reports the Abyss iframes."""

import html
import logging
import os

from flask import Blueprint, jsonify, make_response, render_template

import mapart
import reports
import settings
from context import atlas
from security import is_admin

log = logging.getLogger("atlas.web.views")

bp = Blueprint("views", __name__)


@bp.route("/")
def index():
    """The map. `editable` decides whether the editing chrome is even rendered.

    Server-side rather than a client check: a viewer who can't write should
    never be shown a pencil that 403s when they press it.
    """
    title = _realm_title()
    seeded = atlas().reader.seeded()
    style = _default_style()
    return render_template(
        "index.html",
        editable=settings.writes_enabled() and is_admin(),
        seeded=seeded,
        # an unseeded instance on ATLAS_FALLBACK=bundled is showing the demo,
        # not an empty realm: the first-survey invite says so (first run, W8)
        demo=not seeded and settings.FALLBACK == "bundled",
        client_config=_client_config(style),
        map_image=_map_image(style),
        realm_title=title,
        veil_title=_veil_title(title),
    )


def _realm_title():
    """The realm's own name, for the tab and the veil — `meta.title` of the
    dataset being served, never a constant. Both used to be hard-coded
    "the lab", which the hosted the demo realm instance then wore too
    (2026-09-27). Signed-in only (this view is behind the gate), so naming
    the realm here is what settings.APP_BRAND's rule allows."""
    try:
        data, _, _ = atlas().dataset()
        title = str((data.get("meta") or {}).get("title") or "").strip()
    except (OSError, ValueError):
        title = ""
    return title or settings.APP_BRAND


def _veil_title(title):
    """The veil's short form: "The Archipelago Atlas" -> "THE ARCHIPELAGO", the way it
    has always read; a realm not named "... Atlas" is shown whole."""
    short = title[:-len(" Atlas")] if title.endswith(" Atlas") else title
    return (short or title).upper()


def _default_style():
    """`ATLAS_DEFAULT_STYLE` as this viewer's maps list has it, or None when
    it is unset or its art is gone. table.js wears it until the viewer picks."""
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
    """Which base render this map is drawn on.

    Resolved server-side so the browser makes one request for the right
    picture — a client-side swap would paint the default first and then
    replace it, which on a 4 MB render is a visible flash of somebody else's
    map. Falls back to the bundled default whenever the dataset is unreadable
    or names art that isn't there: an unconfigured backdrop is recoverable, a
    broken <img> on the only screen is not.
    """
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
    """Serve an uploaded base render.

    Gated exactly like the map it backs: `/` is already behind the Hub in the
    deployment that matters, and a floor plan of the building is not less
    sensitive than the markers drawn on it. `Content-Type` is set from the
    bytes rather than the extension, and `nosniff` stops the browser
    second-guessing that.
    """
    blob, kind = mapart.read_upload(name)
    if blob is None:
        return jsonify({"error": "no such render"}), 404
    if not kind:
        # stored before a validator existed, or tampered with on the volume
        log.warning("refusing to serve map art %s: not a raster image",
                    mapart.safe_name(name))
        return jsonify({"error": "that render is not a usable image"}), 415

    resp = make_response(blob)
    resp.headers["Content-Type"] = mapart.MIMETYPES[kind]
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Disposition"] = "inline"
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


@bp.route("/report/<name>")
def report(name):
    """Serve a staged markdown report as a dark page the Abyss can iframe.

    Raw markdown in a styled <pre> — readable, zero dependencies, and the vault's
    original stays the artifact of record. `security` is the bound scroll —
    both reports combined behind one head (see reports._security_scroll);
    `crowdsec` still serves the insight alone for anyone linking straight to it.
    """
    status = 200
    if name == "security":
        body = reports._security_scroll()
    elif name in reports.REPORTS:
        body, _ = reports._read_report(name)
        if body is None:
            body = "_The scribes have not yet delivered this report._"
    else:
        # A page answers as a page. This was the one route that spoke HTML on
        # success and JSON on failure; the Abyss frames
        # it, and a frame that lands on a JSON document shows the viewer a
        # bare string.
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
    # The app-wide default is `DENY`, which is right for the map and wrong for
    # the one page that exists to be drawn inside it: DENY blocks *same-origin*
    # framing too, so the Abyss and THE VIEWING GLASS could never show this.
    # Set here rather than relaxed globally — this is the only frameable page.
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    return resp
