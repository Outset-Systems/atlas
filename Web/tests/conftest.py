import os
import sys
import tempfile

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
