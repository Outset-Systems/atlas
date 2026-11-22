from flask import jsonify

import shadow
from context import atlas

from .admin import admin_bp


@admin_bp.route("/shadow")
def shadow_read():
    try:
        data, _, _ = atlas().dataset()
    except (OSError, ValueError):
        data = {}
    return jsonify(shadow.summary(data))
