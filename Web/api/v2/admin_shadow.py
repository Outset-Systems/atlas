"""SHADOW for an admin (2026-11-15): how often Atlas's own checks agreed
with Kuma's monitors, thing by thing (shadow.py). Admin only, like every route
on `admin_bp`: it names monitors and places across the whole map."""

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
