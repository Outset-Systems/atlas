"""Map images — `/api/v2/admin/map-art*`: the renders a map can be drawn on.

List, upload, survey, a style's saved layout, remove. `GET /map-art/<name>`
(the binary serve) is a page-adjacent read and stays on `views`.

Split out of `admin.py` (2026-11-12); same blueprint, same gate.
"""

import logging

from flask import jsonify, request

import mapart
from security import actor

from . import _body
from .admin import admin_bp
from .auth import write_required

log = logging.getLogger("atlas.api.v2")


# ── The base render ──────────────────────────────────────────────────────────
@admin_bp.route("/map-art")
def map_art_list():
    return jsonify({"images": mapart.available(),
                    "default": mapart.DEFAULT,
                    "max_bytes": mapart.MAX_BYTES})


@admin_bp.route("/map-art", methods=["POST"])
@write_required
def map_art_upload():
    upload = request.files.get("image")
    if not upload:
        return jsonify({"error": "send a file as `image`"}), 400
    name = (request.form.get("name") or upload.filename or "").strip()
    try:
        stored = mapart.save(name, upload.read())
    except ValueError as e:
        return jsonify({"error": str(e), "problems": [str(e)]}), 422
    except OSError as e:
        log.error("v2: could not store map art: %s", e)
        return jsonify({"error": f"could not store that render: {e}"}), 500
    log.info("v2: map art %s uploaded by %s", stored, actor())
    return jsonify({"ok": True, "name": stored, "images": mapart.available()})


@admin_bp.route("/map-art/survey", methods=["POST"])
@write_required
def map_art_survey():
    q = _body().get("query") or ""
    import worldsurvey
    try:
        name, display = worldsurvey.survey(q)
    except worldsurvey.SurveyError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:                       # noqa: BLE001 — one sentence out
        log.error("v2: survey failed for %r: %s", q, e, exc_info=True)
        return jsonify({"error": "the survey failed — see the server log"}), 502
    log.info("v2: survey render %s stored by %s", name, actor())
    return jsonify({"ok": True, "name": name, "surveyed": display,
                    "images": mapart.available()})


@admin_bp.route("/map-art/<name>/layout", methods=["POST"])
@write_required
def map_art_layout(name):
    """Settings → Move places, on a map style: the dragged spots go into that
    style's sidecar, so every viewer of the style sees them there."""
    try:
        saved = mapart.save_layout(name, request.get_json(silent=True))
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except OSError as e:
        log.error("v2: could not save the layout of %s: %s", name, e)
        return jsonify({"error": f"could not save that layout: {e}"}), 500
    log.info("v2: layout of map style %s saved by %s (%d spots)", name, actor(), saved)
    from .reads import maps_for_viewer
    return jsonify({"ok": True, "saved": saved, "maps": maps_for_viewer()})


@admin_bp.route("/map-art/<name>", methods=["DELETE"])
@write_required
def map_art_delete(name):
    try:
        mapart.remove(name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except OSError as e:
        return jsonify({"error": f"could not remove that render: {e}"}), 500
    log.info("v2: map art %s removed by %s", name, actor())
    return jsonify({"ok": True, "images": mapart.available()})
