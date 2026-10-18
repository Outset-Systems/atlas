"""THE NAMING DEEP's one dangerous edge: where a referral is allowed to point.

`/api/whois` is the only route in the Atlas that opens a socket to an address it
was *told* about rather than one the dataset charted. The chain starts at IANA
and then follows whatever `refer:` / `whois:` line comes back — a value written
by whoever answered the previous hop. Validating that value's SHAPE (which is
all the route did until now) says nothing about where it POINTS, so a hostile or
compromised registry could refer the Atlas at `10.77.33.30` and have it open port
43 on the admin VLAN, with the banner returned to the caller.

So the assertions that matter here are all refusals, and one of them is about
*how* the connection is made rather than whether: the vetted ADDRESS has to be
what gets dialled, because checking a name and then handing the name to the
socket leaves a second lookup in between — a rebind, and the check was
decoration.
"""

import ipaddress
import os
import shutil
import socket
import sys

import pytest

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)

BUNDLED = os.path.join(WEB, "default-lab-data.json")

# Declared for conftest so this module owns its environment (see conftest.py).
ATLAS_TEST_ENV = {
    "ATLAS_DATA_BACKEND": "file",
    "ATLAS_ALLOW_INSECURE": "1",
    "ATLAS_AUTH_MODE": "standalone",
}
os.environ.update(ATLAS_TEST_ENV)

import whois  # noqa: E402


def _ai(*addrs):
    """A getaddrinfo() reply for these literal addresses, in this order."""
    out = []
    for a in addrs:
        ip = ipaddress.ip_address(a)
        if ip.version == 4:
            out.append((socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP,
                        "", (a, 43)))
        else:
            out.append((socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP,
                        "", (a, 43, 0, 0)))
    return out


# ── Which addresses count as the public internet ─────────────────────────────

@pytest.mark.parametrize("addr", [
    "199.7.83.42",        # a real root-server address
    "192.0.66.1",
    "2001:500:88:200::8",
])
def test_public_addresses_are_public(addr):
    assert whois.public_ip(ipaddress.ip_address(addr)) is True


@pytest.mark.parametrize("addr", [
    "10.77.33.30",         # The internal host — the whole point
    "10.77.90.10",         # the DMZ edge
    "192.168.1.1",
    "172.16.4.4",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",    # the cloud metadata address, by name and by habit
    "224.0.0.1",
    "240.0.0.1",          # reserved
    "::1",
    "fe80::1",
    "fd00::1",            # unique-local
])
def test_private_addresses_are_refused(addr):
    assert whois.public_ip(ipaddress.ip_address(addr)) is False


def test_an_ipv4_mapped_address_is_judged_as_the_ipv4_it_carries():
    """`::ffff:10.77.33.30` is the spelling that gets tried, and some releases
    of `ipaddress` have called it global. The mapping is unwrapped by hand so
    the verdict does not depend on the image's patch release."""
    assert whois.public_ip(ipaddress.ip_address("::ffff:10.77.33.30")) is False
    assert whois.public_ip(ipaddress.ip_address("::ffff:199.7.83.42")) is True


# ── Resolving a hop ──────────────────────────────────────────────────────────

def test_a_public_name_resolves_to_dialable_addresses(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: _ai("199.7.83.42", "2001:500:88:200::8"))
    assert whois.endpoint("whois.iana.org") == [
        (socket.AF_INET, ("199.7.83.42", 43)),
        (socket.AF_INET6, ("2001:500:88:200::8", 43, 0, 0)),
    ]


def test_a_name_that_resolves_inside_the_realm_is_refused(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _ai("10.77.33.30"))
    assert whois.endpoint("whois.evil.example") is None


def test_one_private_answer_disqualifies_the_whole_name(monkeypatch):
    """A name answering with one public address and one internal one is not a
    whois server having a bad day — it is the shape of the attack, and
    `create_connection` would have been free to pick either."""
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: _ai("199.7.83.42", "10.77.33.30"))
    assert whois.endpoint("whois.evil.example") is None


def test_a_bare_private_ip_as_a_referral_is_refused(monkeypatch):
    """The referral regex allows an IPv4 literal, so the address check is what
    stops `refer: 10.77.33.30` — there is no name to resolve."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _ai("10.77.33.30"))
    assert whois.endpoint("10.77.33.30") is None


def test_a_name_that_does_not_resolve_is_refused_not_raised(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("no such name")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert whois.endpoint("nope.invalid") is None


# ── The chain, end to end ────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    from appfixture import fresh_app
    data = tmp_path / "lab-data.json"
    shutil.copy(BUNDLED, data)
    atlas_app = fresh_app(
        ATLAS_DATA=str(data),
        ATLAS_POSITIONS=str(tmp_path / "positions.json"),
        ATLAS_RACK=str(tmp_path / "rack.json"),
        ATLAS_REVISIONS=str(tmp_path / "revisions"),
        ATLAS_OBSERVED=str(tmp_path / "observed.json"),
    )
    return atlas_app.app.test_client()


IANA_POINTING_INWARD = "domain: example\nrefer: 10.77.33.30\n"
IANA_POINTING_OUT = "domain: example\nrefer: whois.verisign-grs.com\n"


def test_a_registry_cannot_steer_the_atlas_at_the_admin_vlan(client, monkeypatch):
    """The finding, as a test. IANA's answer names an internal address; the
    caller must still get IANA's text, and the second hop must never happen."""
    asked = []

    def endpoint(server):
        # only public names resolve in this world
        return None if server == "10.77.33.30" else [(socket.AF_INET, ("199.7.83.42", 43))]

    def ask(target, query):
        asked.append(target)
        return IANA_POINTING_INWARD

    monkeypatch.setattr(whois, "endpoint", endpoint)
    monkeypatch.setattr(whois, "ask", ask)

    body = client.get("/api/v2/whois?q=example.com").get_json()

    assert len(asked) == 1, "a refused referral was dialled anyway"
    assert body["servers"] == ["whois.iana.org"]
    assert "refer: 10.77.33.30" in body["text"]          # what IANA said is kept
    assert "the chain ends here" in body["text"]        # and the stop is stated


def test_the_refusal_reads_the_same_whether_the_name_was_private_or_absent(client, monkeypatch):
    """Two different failures, one sentence. The referral is written by whoever
    answered the last hop, so distinguishing them would answer 'does this
    internal name exist?' for someone who cannot otherwise ask."""
    def run(second_hop_text):
        monkeypatch.setattr(whois, "endpoint",
                            lambda s: None if s != "whois.iana.org"
                            else [(socket.AF_INET, ("199.7.83.42", 43))])
        monkeypatch.setattr(whois, "ask", lambda t, q: second_hop_text)
        return client.get("/api/v2/whois?q=example.com").get_json()["text"]

    private = run("refer: 10.77.33.30\n").replace("10.77.33.30", "«name»")
    absent = run("refer: nope.invalid\n").replace("nope.invalid", "«name»")
    # the server's own name may be echoed — the caller was just shown it in the
    # answer that named it. What must not differ is the REASON.
    assert private.splitlines()[-1] == absent.splitlines()[-1]
    assert "is not a public whois server" in private.splitlines()[-1]


def test_a_good_chain_still_walks(client, monkeypatch):
    """The guard must not cost the feature: a public referral is followed."""
    seen = []

    def ask(target, query):
        seen.append(target)
        return IANA_POINTING_OUT if len(seen) == 1 else "registrar: someone\n"

    monkeypatch.setattr(whois, "endpoint",
                        lambda s: [(socket.AF_INET, ("199.7.83.42", 43))])
    monkeypatch.setattr(whois, "ask", ask)

    body = client.get("/api/v2/whois?q=example.com").get_json()
    assert body["servers"] == ["whois.iana.org", "whois.verisign-grs.com"]
    assert "registrar: someone" in body["text"]


class FakeSock:
    """A socket that records where it was dialled, and can refuse."""

    dialled = []

    def __init__(self, refuse=()):
        self._refuse = refuse
        self._sent = False

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def settimeout(self, t): pass

    def connect(self, sockaddr):
        FakeSock.dialled.append(sockaddr)
        if sockaddr[0] in self._refuse:
            raise ConnectionRefusedError(sockaddr[0])

    def sendall(self, b): pass

    def recv(self, n):
        """One banner, then EOF — a reader that never ends is a test that
        hangs until the 64KB cap saves it."""
        if self._sent:
            return b""
        self._sent = True
        return b"% an answer\n"

    def close(self): pass


def test_the_socket_is_dialled_at_the_vetted_address_not_the_name(monkeypatch):
    """The rebind guard. `_whois_ask` takes the (family, sockaddr) pairs that
    were checked; if it ever takes a hostname again, the resolver gets a second
    chance to answer differently and the check means nothing."""
    FakeSock.dialled = []
    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
    whois.ask([(socket.AF_INET, ("199.7.83.42", 43))], "example.com")
    assert FakeSock.dialled == [("199.7.83.42", 43)]


def test_a_refused_address_falls_through_to_the_next_vetted_one(monkeypatch):
    """What `create_connection` used to do for free: a registry with several A
    records stays reachable when the first one is down. Every address in the
    list has already been vetted, so the fallback cannot widen the target."""
    FakeSock.dialled = []
    monkeypatch.setattr(socket, "socket",
                        lambda *a, **k: FakeSock(refuse=("199.7.83.42",)))
    text = whois.ask([(socket.AF_INET, ("199.7.83.42", 43)),
                                (socket.AF_INET, ("192.0.32.59", 43))], "example.com")
    assert FakeSock.dialled == [("199.7.83.42", 43), ("192.0.32.59", 43)]
    assert "an answer" in text


def test_every_address_refusing_raises_so_the_route_can_say_so(monkeypatch):
    FakeSock.dialled = []
    monkeypatch.setattr(socket, "socket",
                        lambda *a, **k: FakeSock(refuse=("199.7.83.42", "192.0.32.59")))
    with pytest.raises(OSError):
        whois.ask([(socket.AF_INET, ("199.7.83.42", 43)),
                             (socket.AF_INET, ("192.0.32.59", 43))], "example.com")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
