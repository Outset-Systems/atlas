from engines.base import _TIMEOUT


def get(url, **kwargs):
    import requests

    kwargs.setdefault("timeout", _TIMEOUT)
    resp = requests.get(url, **kwargs)
    resp.raise_for_status()
    return resp
