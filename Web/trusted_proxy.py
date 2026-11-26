"""Forwarded headers, believed only from the reverse proxies an operator names.

`ATLAS_TRUSTED_PROXIES` lists the addresses or CIDRs of those proxies. A request
whose socket peer is on the list gets werkzeug's ProxyFix (X-Forwarded-Proto
only); from any other peer the forwarded headers are dropped before the app
sees them, so a client cannot claim https or another address.
"""

import ipaddress
import logging

from werkzeug.middleware.proxy_fix import ProxyFix

log = logging.getLogger("atlas.proxy")

# Headers ProxyFix could act on. Peers that are not trusted lose all of them.
FORWARDED_KEYS = (
    "HTTP_FORWARDED",
    "HTTP_X_FORWARDED_FOR",
    "HTTP_X_FORWARDED_PROTO",
    "HTTP_X_FORWARDED_HOST",
    "HTTP_X_FORWARDED_PORT",
    "HTTP_X_FORWARDED_PREFIX",
)


def is_trusted(host, trusted):
    if not trusted or not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr in net for net in trusted)


class TrustedProxyFix:
    """ProxyFix(x_proto=1) for named proxies; forwarded headers stripped for everyone else."""

    def __init__(self, app, trusted):
        self.app = app
        self.trusted = tuple(trusted or ())
        self.fixed = ProxyFix(app, x_for=0, x_proto=1, x_host=0, x_port=0, x_prefix=0)
        self._warned = False

    def __call__(self, wsgi_env, start_response):
        if is_trusted(wsgi_env.get("REMOTE_ADDR"), self.trusted):
            return self.fixed(wsgi_env, start_response)
        if wsgi_env.get("HTTP_X_FORWARDED_PROTO") and not self._warned:
            self._warned = True
            log.warning(
                "ignoring X-Forwarded-Proto from %s: it is not in ATLAS_TRUSTED_PROXIES. "
                "Behind a reverse proxy, name the address the proxy connects from "
                "(docs/install.md, Trusted proxy setting).",
                wsgi_env.get("REMOTE_ADDR") or "?")
        for key in FORWARDED_KEYS:
            wsgi_env.pop(key, None)
        return self.app(wsgi_env, start_response)
