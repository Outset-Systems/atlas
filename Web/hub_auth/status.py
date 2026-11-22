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
