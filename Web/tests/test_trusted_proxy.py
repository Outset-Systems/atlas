"""X-Forwarded-* is believed only from the proxies named in ATLAS_TRUSTED_PROXIES."""

import ipaddress

import pytest
from flask import Flask, jsonify, request

from trusted_proxy import TrustedProxyFix, is_trusted


def _nets(*items):
    return tuple(ipaddress.ip_network(i, strict=False) for i in items)


def _app(trusted):
    app = Flask(__name__)

    @app.route("/where")
    def where():
        return jsonify(scheme=request.scheme, host_url=request.host_url,
                       remote=request.remote_addr,
                       xff=request.headers.get("X-Forwarded-For"),
                       xfh=request.headers.get("X-Forwarded-Host"))

    app.wsgi_app = TrustedProxyFix(app.wsgi_app, trusted)
    return app.test_client()


def _get(client, peer, **headers):
    return client.get("/where", headers=headers,
                      environ_base={"REMOTE_ADDR": peer}).get_json()


def test_a_named_proxy_sets_the_scheme():
    c = _app(_nets("172.18.0.0/16"))
    got = _get(c, "172.18.0.2", **{"X-Forwarded-Proto": "https"})
    assert got["scheme"] == "https"
    assert got["host_url"].startswith("https://")


def test_any_other_peer_cannot_claim_https():
    c = _app(_nets("172.18.0.2"))
    got = _get(c, "10.0.0.9", **{"X-Forwarded-Proto": "https"})
    assert got["scheme"] == "http"


def test_with_no_trusted_proxies_nobody_is_believed():
    c = _app(())
    got = _get(c, "127.0.0.1", **{"X-Forwarded-Proto": "https"})
    assert got["scheme"] == "http"


def test_untrusted_forwarded_headers_are_dropped():
    c = _app(_nets("172.18.0.2"))
    got = _get(c, "10.0.0.9", **{"X-Forwarded-For": "1.2.3.4",
                                 "X-Forwarded-Host": "evil.example"})
    assert got["xff"] is None
    assert got["xfh"] is None
    assert got["remote"] == "10.0.0.9"


def test_a_trusted_proxy_does_not_rewrite_the_client_or_host():
    c = _app(_nets("172.18.0.2"))
    got = _get(c, "172.18.0.2", **{"X-Forwarded-For": "1.2.3.4",
                                   "X-Forwarded-Host": "evil.example"})
    # client_ip() reads X-Forwarded-For itself; ProxyFix must not.
    assert got["remote"] == "172.18.0.2"
    assert got["xff"] == "1.2.3.4"
    assert "evil.example" not in got["host_url"]


def test_untrusted_proto_is_logged_once(caplog):
    c = _app(())
    with caplog.at_level("WARNING", logger="atlas.proxy"):
        _get(c, "10.0.0.9", **{"X-Forwarded-Proto": "https"})
        _get(c, "10.0.0.9", **{"X-Forwarded-Proto": "https"})
    assert sum("ATLAS_TRUSTED_PROXIES" in r.message for r in caplog.records) == 1


@pytest.mark.parametrize("host,expected", [
    ("172.18.0.2", True),
    ("172.19.0.2", False),
    ("::ffff:172.18.0.2", True),
    ("fd00::1", True),
    ("not-an-ip", False),
    ("", False),
    (None, False),
])
def test_is_trusted(host, expected):
    assert is_trusted(host, _nets("172.18.0.0/16", "fd00::/8")) is expected


def test_the_app_uses_the_setting(run_app):
    r = run_app("""
        from flask import request
        from app import app
        seen = []
        app.before_request(lambda: seen.append(request.scheme))
        c = app.test_client()
        for peer in ("172.18.0.2", "10.9.9.9"):
            c.get("/api/v2/health", headers={"X-Forwarded-Proto": "https"},
                  environ_base={"REMOTE_ADDR": peer})
        print(seen)
    """, ATLAS_AUTH_MODE="standalone", ATLAS_READONLY="1",
        ATLAS_TRUSTED_PROXIES="172.18.0.0/16")
    assert r.returncode == 0, r.stderr
    assert "['https', 'http']" in r.stdout
