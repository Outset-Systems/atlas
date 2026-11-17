"""What the sources that ask over HTTP share: one way to make the call.

Kuma, the decoy feed and Prometheus each asked `requests.get` for themselves
with the same timeout and the same `raise_for_status`. They ask through `get`
here now (2026-11-16), each with its own headers, auth, params and `verify`,
exactly as before. Nothing is caught here: a failure goes up to
`_Adapter.fetch`, which turns it into "no signal".

`requests` is imported inside the call, never at load: a relay box imports
`signals`, and so this module, with no web stack beside it.
"""

from engines.base import _TIMEOUT


def get(url, **kwargs):
    """GET `url` with the shared timeout and give back the response; an error
    status raises, as `raise_for_status` does. Only what the caller passes
    (`headers`, `auth`, `params`, `verify`) goes on to `requests.get`."""
    import requests  # local import: optional dep, never at module load

    kwargs.setdefault("timeout", _TIMEOUT)
    resp = requests.get(url, **kwargs)
    resp.raise_for_status()
    return resp
