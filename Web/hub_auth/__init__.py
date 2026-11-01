"""
hub_auth — dual-mode authentication and Hub integration helpers
================================================================

1. Operate in two modes (standalone or behind a Hub) via ATLAS_AUTH_MODE
2. Respond to a Hub's discovery probe at GET /api/status
"""

from .auth import (
    require_hub_or_standalone,
    get_remote_user,
    get_remote_groups,
    AUTH_MODE,
)
from .status import app_status

__version__ = "1.0.0"

from .auth import mint_token, verify_token  # noqa: E402

__all__ = [
    "mint_token",
    "verify_token",
    "require_hub_or_standalone",
    "get_remote_user",
    "get_remote_groups",
    "AUTH_MODE",
    "app_status",
]
