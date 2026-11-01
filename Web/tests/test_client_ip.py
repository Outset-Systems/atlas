"""The client IP the login throttle and the audit trail key on.

Two mechanisms could set it and, until 2026-09-09, both were live without
anyone meaning the second one to be:

  * `atlas_auth.client_ip` + ATLAS_TRUSTED_PROXIES — the documented one.
  * `ProxyFix` in app.py, which rewrites `request.remote_addr` from the same
    header. It was constructed as `ProxyFix(app.wsgi_app, x_proto=1)` beside a
    comment saying x_for was "deliberately left at 0" — but werkzeug's default
    for x_for is 1, so it was forwarding the address anyway.

The documented one was ALSO a hop count, and a count believes the header from
any peer that can open a socket to :5006 — all 14 containers on the `suite`
network, not just tls-proxy and the Hub. Both proxies now have pinned
addresses so they can be named instead of counted.

⚠ These tests must never `importlib.reload` atlas_auth or settings. Reloading
rebinds a module's functions to NEW objects, and other modules that imported
them (or patched them) are left holding the old ones — `test_mfa_policy` once
asserted an identity that a reload here broke from the other side of the
suite. `client_ip` reads `settings.TRUSTED_PROXIES` at call time, so setting
the attribute is enough.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ATLAS_TEST_ENV = {}

NGINX = "172.19.255.7"      # tls-proxy, pinned in the internal host's compose
HUB = "172.19.255.9"        # the Hub, likewise
CLIENT = "203.0.113.7"


@pytest.fixture
def resolve(monkeypatch):
    """client_ip() for a request with the given trusted set, header and peer."""
    import atlas_auth
    import settings
    from flask import Flask

    app = Flask(__name__)

    def _go(trusted, xff=None, peer=NGINX):
        monkeypatch.setattr(settings, "TRUSTED_PROXIES",
                            settings._parse_trusted(trusted))
        headers = {"X-Forwarded-For": xff} if xff is not None else {}
        with app.test_request_context("/", headers=headers,
                                      environ_base={"REMOTE_ADDR": peer}):
            return atlas_auth.client_ip()
    return _go


def test_nothing_trusted_keys_on_the_socket_peer(resolve):
    assert resolve("", CLIENT) == NGINX


def test_a_named_proxy_is_believed(resolve):
    # both roads in: the nginx vhost, and the Hub's /atlas/ path
    assert resolve(f"{NGINX}, {HUB}", CLIENT) == CLIENT
    assert resolve(f"{NGINX}, {HUB}", CLIENT, peer=HUB) == CLIENT


def test_an_unnamed_peer_cannot_assert_anything(resolve):
    # The regression this rewrite exists for: any of the 14 containers on the
    # suite network can open a socket to :5006, and under the old hop count
    # this returned 1.2.3.4.
    assert resolve(f"{NGINX}, {HUB}", "1.2.3.4", peer="172.19.0.99") == "172.19.0.99"
    assert resolve(f"{NGINX}, {HUB}", CLIENT, peer="172.19.0.99") == "172.19.0.99"


def test_prepended_entries_are_ignored(resolve):
    assert resolve(NGINX, f"fiction, {CLIENT}") == CLIENT
    assert resolve(NGINX, f"a, b, c, {CLIENT}") == CLIENT


def test_rotating_the_header_shares_one_key(resolve):
    seen = {resolve(NGINX, f"{i}.{i}.{i}.{i}, {CLIENT}") for i in range(1, 6)}
    assert seen == {CLIENT}


def test_trusted_hops_are_skipped(resolve):
    # nginx forwarded to the Hub, which forwarded here: both are ours, so the
    # client is the first entry that is not.
    assert resolve(f"{NGINX}, {HUB}", f"{CLIENT}, {HUB}", peer=NGINX) == CLIENT


def test_no_header_or_all_ours_falls_back_to_the_peer(resolve):
    assert resolve(NGINX, None) == NGINX
    assert resolve(f"{NGINX}, {HUB}", f"{NGINX}, {HUB}") == NGINX


def test_a_header_value_cannot_grow_without_bound(resolve):
    import settings
    assert len(resolve(NGINX, "A" * 500)) == settings.MAX_IP_KEY


def test_a_hop_count_is_refused_not_reinterpreted(resolve):
    # The old spelling. "1" must not be read as an address, and must not
    # quietly keep the previous behaviour.
    assert resolve("1", CLIENT) == NGINX


def test_garbage_entries_are_dropped_not_fatal():
    import settings
    nets = settings._parse_trusted("172.19.255.7, not-an-address, 10.77.0.0/16")
    assert [str(n) for n in nets] == ["172.19.255.7/32", "10.77.0.0/16"]
    assert settings._parse_trusted(None) == () and settings._parse_trusted(" ") == ()


def _app_source():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "app.py"), encoding="utf-8") as fh:
        return fh.read()


def test_proxyfix_does_not_also_forward_the_address():
    """app.py must pin x_for=0. werkzeug defaults it to 1, so omitting it
    turns on a second, undocumented forwarded-IP path. Read from disk rather
    than imported: importing the app for one assertion is a lot of side
    effect."""
    assert "ProxyFix(app.wsgi_app, x_for=0, x_proto=1)" in _app_source(), (
        "ProxyFix must set x_for=0 EXPLICITLY: werkzeug's default is 1, so "
        "dropping it silently re-enables forwarded-IP trust."
    )


def test_werkzeug_still_defaults_x_for_to_one():
    """The reason the line above must stay explicit. If a future werkzeug
    changes this default to 0, this test fails and the comment in app.py can
    be relaxed — deliberately, rather than by accident."""
    import inspect

    from werkzeug.middleware.proxy_fix import ProxyFix
    assert inspect.signature(ProxyFix.__init__).parameters["x_for"].default == 1
