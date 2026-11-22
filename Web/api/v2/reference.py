from flask import Response

import openapi
from redaction import private_no_cache

from . import bp


@bp.route("/openapi.json")
def openapi_document():
    resp = Response(openapi.dumps(), mimetype="application/json")
    return private_no_cache(resp)
