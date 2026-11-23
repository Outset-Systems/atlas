import logging

from flask import jsonify, make_response

import names
from context import atlas
from jsonio import iso_utc
from redaction import no_store, redact_for_groups

from . import bp

log = logging.getLogger("atlas.api.v2")

NAMES_PATH = "/names"


@bp.route(NAMES_PATH)
def names_list():
    try:
        raw, _, _ = atlas().dataset()
    except (OSError, ValueError) as e:
        log.error("v2 names: lab data unreadable: %s", e)
        return jsonify({"error": f"lab data unreadable: {e}"}), 500
    rows, counts = names.listing(redact_for_groups(raw)[0])
    return no_store(make_response(jsonify(
        {"generated_at": iso_utc(), "names": rows, "counts": counts})))
