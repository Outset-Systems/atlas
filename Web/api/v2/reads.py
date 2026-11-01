"""Map reads — `GET /api/v2/lab-data`, `GET /api/v2/maps`.

The two reads the map itself lives on. The bodies are dynamic and
redaction-shaped, so they are NOT modelled: `schema.py`'s catalogue is the
source of truth for the dataset, and a pydantic mirror of it would be a second
one. They are plain Flask views. Redaction,
`Vary`, cache-control and the `lab-data` ETag/304 come from the shared
helpers (`redaction.py`, `context.py`).
"""

import hashlib
import logging

from flask import jsonify, make_response, request

import settings
from context import atlas
from redaction import redact_for_groups, vary_on_viewer

from . import bp

log = logging.getLogger("atlas.api.v2")


@bp.route("/lab-data")
def lab_data():
    ctx = atlas()
    try:
        data, mtime, problems = ctx.dataset()
    except (OSError, ValueError) as e:
        log.error("v2 lab-data unreadable: %s", e)
        return jsonify({"error": f"lab data unreadable: {e}"}), 500

    data, overlay_tag = ctx.with_overlays(data)
    data, group_tag = redact_for_groups(data)

    resp = make_response(jsonify(data))
    stamps = "-".join(str(m) for m in ctx.overlay_mtimes())
    # sha1, not hash(): str hashing is salted per interpreter, so two gunicorn
    # workers would mint two ETags for one body and every If-None-Match missed
    tags = hashlib.sha1((group_tag + overlay_tag).encode("utf-8")).hexdigest()[:8]
    resp.set_etag(f"{settings.APP_VERSION}-{mtime}-{stamps}-{tags}")
    # `private` + `Vary` (below): a shared cache must never hand one viewer's
    # redacted dataset — or an admin's unredacted one — to the next.
    resp.headers["Cache-Control"] = "private, no-cache"
    vary_on_viewer(resp)
    if problems:
        resp.headers["X-Atlas-Data-Problems"] = str(len(problems))
    return resp.make_conditional(request)


@bp.route("/maps")
def maps_list():
    """Every base render this Atlas can be drawn on, with its theme if charted."""
    import mapart
    import theme as theme_mod
    ctx = atlas()
    try:
        data, _, _ = ctx.dataset()
    except (OSError, ValueError):
        data = {}
    meta = data.get("meta") or {}
    art = {entry.get("name"): entry
           for entry in (meta.get("map_art") or []) if isinstance(entry, dict)}
    default = meta.get("map_image") or mapart.DEFAULT
    out = []
    for image in mapart.available():
        name = image["name"]
        entry = art.get(name) or {}
        theme = entry.get("theme")
        out.append({
            "name": name,
            "label": entry.get("label") or theme_mod.map_label(name) or name.rsplit(".", 1)[0],
            # bundled art is served from static/, uploads from /map-art/ —
            # resolved here so the client never has to know the difference
            "url": (f"static/map/{name}" if image["bundled"] else f"map-art/{name}"),
            "default": name == default,
            "theme": theme if isinstance(theme, dict) else None,
        })
    resp = make_response(jsonify({"maps": out}))
    resp.headers["Cache-Control"] = "private, no-cache"
    return vary_on_viewer(resp)
