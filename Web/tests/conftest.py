import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

_DATA = tempfile.mkdtemp(prefix="atlas-test-")

os.environ.update({
    "ATLAS_AUTH_MODE": "accounts",
    "ATLAS_DATA": os.path.join(_DATA, "lab-data.json"),
    "ATLAS_ACCOUNTS_DB": os.path.join(_DATA, "accounts.db"),
    "ATLAS_FALLBACK": "bundled",
    "ATLAS_SECRET_KEY": "test-only-session-key",
    "ATLAS_INSECURE_COOKIES": "1",
    "ATLAS_PUBLIC_URL": "https://atlas.test",
})

WEB = Path(__file__).resolve().parents[1]
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

# Variables that change how the app boots; cleared so the host's shell cannot leak in.
_BOOT_VARS = ("ATLAS_AUTH_MODE", "ATLAS_HUB_SECRET", "ATLAS_HUB_SECRET_FILE",
              "ATLAS_TRUSTED_PROXIES", "ATLAS_READONLY", "ATLAS_ALLOW_INSECURE")


@pytest.fixture
def run_app(tmp_path):
    """Run `body` in a fresh interpreter that imports the app with `env` set.

    The app reads its settings at import time, so each case gets its own process.
    """

    def _run(body, **env):
        full = {k: v for k, v in os.environ.items() if k not in _BOOT_VARS}
        full.update({
            "ATLAS_FALLBACK": "bundled",
            "ATLAS_DATA": str(tmp_path / "lab-data.json"),
            "ATLAS_ACCOUNTS_DB": str(tmp_path / "accounts.db"),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        full.update({k: str(v) for k, v in env.items()})
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(body)],
            cwd=WEB, env=full, capture_output=True, text=True, timeout=120)

    return _run
