"""The API reference — `GET /api/v2/openapi.json`.

Gated like the map: a signed-in viewer or an API token reads it. The same
document is `docs/openapi.json` in the repository, so nothing here is worth an
anonymous door. The document itself is built in `openapi.py`.
"""

from flask import Response

import openapi
from redaction import private_no_cache

from . import bp


@bp.route("/openapi.json")
def openapi_document():
    resp = Response(openapi.dumps(), mimetype="application/json")
    # Revalidated every time, like the map's own reads: a browser that kept a copy
    # would hand it to a later request with no sign-in at all (seen 2026-11-09).
    return private_no_cache(resp)
