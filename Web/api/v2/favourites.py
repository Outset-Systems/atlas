import logging

from flask import jsonify

import favourite_opens
import overview
import settings
from context import atlas
from errors import fail
from redaction import redact_for_groups
from security import same_origin_refusal

from . import _body, _text, bp

log = logging.getLogger("atlas.api.v2")

URL_LIMIT = 2048


@bp.route("/favourites/open", methods=["POST"])
def favourite_opened():
    if settings.READ_ONLY:
        return fail(403, "this Atlas is read-only",
                    reason="a look-only Atlas counts nothing")
    refusal = same_origin_refusal()
    if refusal:
        return refusal
    url = _text(_body(), "url", URL_LIMIT).strip()
    try:
        raw, _, _ = atlas().dataset()
    except (OSError, ValueError) as e:
        log.error("v2 favourites/open: lab data unreadable: %s", e)
        return jsonify({"error": "dataset unreadable"}), 500
    if not url or url not in overview.favourite_urls(redact_for_groups(raw)[0]):
        return jsonify({"error": "not a favourite you can see"}), 404
    opens = favourite_opens.bump(url, overview.favourite_urls(raw))
    if opens is None:
        return jsonify({"ok": False, "error": "not counted just now"}), 503
    return jsonify({"ok": True, "opens": opens})
