"""
Standardized /api/status response builder.

Every app behind the Hub answers GET /api/status with the same shape so the Hub can
render uniform cards on its dashboard and external monitoring can health-check
The suite consistently.

Usage:
    from hub_auth import app_status

    @app.route("/api/status")
    def status():
        return jsonify(app_status(
            app_key="feed",
            name="The Feed",
            version="1.2.3",
            healthy=True,
            summary={
                "headline_metric":   42,
                "headline_label":    "Articles Today",
                "secondary_metrics": [
                    {"label": "High Trust", "value": 18},
                    {"label": "Flagged",    "value":  3},
                ],
                "latest_activity": "2026-05-01T12:00:00Z",
            },
            icon="broadcast-pin",
            accent="#83a598",
        ))
"""

from typing import Optional


def app_status(
    *,
    app_key: str,
    name: str,
    version: str = "0.0.0",
    healthy: bool = True,
    summary: Optional[dict] = None,
    icon: str = "bounding-box",
    accent: str = "#83a598",
    group_key: Optional[str] = None,
    path: Optional[str] = None,
) -> dict:
    """
    Build a standardized status response.

    Args:
        app_key: short identifier (e.g. "feed", "oracle"). Lowercase, no spaces.
        name: human-readable display name (e.g. "The Feed").
        version: semver string. Defaults to 0.0.0 if not set.
        healthy: True if the app is operating normally.
        summary: optional dict with dashboard metrics. Recommended keys:
            - headline_metric: a single number/string for the big stat
            - headline_label: label under the headline metric
            - secondary_metrics: list of {"label": ..., "value": ...} dicts
            - latest_activity: ISO8601 timestamp of most recent activity
        icon: Bootstrap Icons name for the dashboard card (no "bi-" prefix).
        accent: hex color for the card accent (e.g. "#83a598").
        group_key: AD/LDAP group key for access control. Defaults to app_key.
        path: Hub proxy path. Defaults to "/<app_key>/".
    """
    return {
        "app":     app_key,
        "name":    name,
        "version": version,
        "healthy": bool(healthy),
        "summary": summary or {
            "headline_metric":   None,
            "headline_label":    "",
            "secondary_metrics": [],
            "latest_activity":   None,
        },
        "card": {
            "icon":         icon,
            "accent_color": accent,
            "group_key":    group_key or app_key,
            "path":         path or f"/{app_key}/",
        },
    }
