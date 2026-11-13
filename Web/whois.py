"""THE NAMING DEEP's engine — one conversation on port 43, with every hop vetted.

The route that asks it is `api/v2/probes.py` (`GET /api/v2/whois`); this
module is the socket, the hop cap, and the public-internet check every
referral must pass. It owns no Flask and no dataset — its import graph is the
standard library — so "what can this route reach" is answered by reading one
file. Moved here whole at the v1 removal (v1.41.0): it lived inside the v1
route module and was imported by v2 through it.

The outbound-fetch worry `/api/v2/embeddable` answers with "the URL must be in
the dataset" is answered differently here, because the whole point is names
that are NOT on the map. What bounds it instead:

  * It speaks exactly one protocol to exactly one port — the whois text
    protocol on 43. There is no URL, no scheme, no redirect to follow into
    an internal service; the query string is the only thing a caller
    controls, and the route validates it down to hostname/IP characters.
  * The conversation starts at IANA and only ever moves to servers the
    registries' own answers name (`refer:` / registrar whois), hop-capped
    and size-capped.
  * 🔴 **Every hop must land on the public internet** — see `endpoint`.
    Validating the SHAPE of a referral's hostname says nothing about where it
    POINTS, and the value comes out of an upstream registry's reply: a hostile
    or compromised registry could refer the Atlas at `10.0.20.5` (or a name
    that resolves there) and get port 43 opened on the admin VLAN with the
    banner handed back to the caller. This is the one place in the app that
    fetches an address it was told about rather than one the dataset charted,
    so it carries the check the dataset is elsewhere.
"""

import ipaddress
import logging
import re
import socket

log = logging.getLogger("atlas.live.whois")

ROOT = "whois.iana.org"
PORT = 43
MAX_HOPS = 3            # IANA → registry → registrar is the whole story
MAX_BYTES = 64 * 1024   # whois is prose; nobody needs more than this
TIMEOUT_S = 6


def public_ip(ip):
    """Is this an address on the public internet, and nothing of ours?

    `is_global` alone is the answer on a current interpreter, but the IPv4-
    mapped form (`::ffff:10.0.20.5`) has been read as global by some releases
    of `ipaddress`, and that is precisely the spelling an attacker reaches for.
    The mapping is unwrapped by hand so the verdict does not depend on which
    patch release the image happens to carry, and the rest is stated rather
    than implied — a reader should not have to know what `is_global` folds in.
    """
    if ip.version == 6:
        mapped = ip.ipv4_mapped
        if mapped is not None:
            ip = mapped
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified) and ip.is_global


def endpoint(server):
    """Resolve a whois server and return the vetted addresses to speak to.

    Returns a list of `(family, sockaddr)` in the resolver's own order — every
    one of them public — or None if the name does not resolve or resolves
    anywhere that is not the public internet. The whole list is kept because
    `create_connection`, which this replaces, tried each address in turn; a
    registry with four A records should not become unreachable because the
    first one is having a bad afternoon.

    Two things are load-bearing:

    * **Any private answer disqualifies the whole name.** A name that resolves
      to one public address and one internal one is not a whois server having a
      bad day, it is the shape of the attack; `create_connection` would have
      been free to pick either.
    * **The vetted address is what gets connected to**, not the name. Checking
      the name and then handing the name to the socket leaves a second lookup
      in between — the resolver may answer differently, which is a DNS
      rebind, and the check would have been decoration.
    """
    try:
        infos = socket.getaddrinfo(server, PORT, proto=socket.IPPROTO_TCP)
    except OSError:
        return None
    vetted = []
    for family, _type, _proto, _canon, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return None
        if not public_ip(ip):
            log.warning("whois: refusing %s — it resolves to %s, which is not "
                        "on the public internet", server, ip)
            return None
        vetted.append((family, sockaddr))
    return vetted or None


def ask(targets, query):
    """One conversation on port 43: send the name, read until EOF or the cap.

    `targets` is the vetted list from `endpoint` — addresses, never a name, so
    there is no second resolution to disagree with the one that was checked.
    They are tried in order and the last failure is raised, which is what
    `create_connection` did with the names it resolved itself.
    """
    last = None
    for family, sockaddr in targets:
        chunks, total = [], 0
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            with sock:
                sock.settimeout(TIMEOUT_S)
                sock.connect(sockaddr)
                sock.sendall((query + "\r\n").encode("ascii", "ignore"))
                while total < MAX_BYTES:
                    data = sock.recv(4096)
                    if not data:
                        break
                    chunks.append(data)
                    total += len(data)
        except OSError as e:
            last = e
            continue
        return b"".join(chunks)[:MAX_BYTES].decode("utf-8", "replace")
    raise last if last is not None else OSError("no address to speak to")


def referral(text):
    """The next server this answer points at, or None.

    Three spellings cover the registries that use them: IANA says `refer:`,
    the RIRs say `whois:`, and the gTLD registries say `Registrar WHOIS
    Server:`. The value is validated with the same rule as the query itself —
    a referral is still just a hostname, wherever it came from.
    """
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() not in ("refer", "whois", "registrar whois server"):
            continue
        value = value.strip().lower()
        for prefix in ("rwhois://", "whois://"):
            if value.startswith(prefix):
                value = value[len(prefix):]
        value = value.split("/")[0].split(":")[0].rstrip(".")
        if value and "." in value and re.match(r"^[a-z0-9._-]{1,253}$", value):
            return value
    return None


def follow(query):
    """Ask the root, then each server the last answer points at, hop-capped.

    Returns `(servers, texts, dead_server, error)`. `servers` are the ones that
    answered, in order; `texts` is what to show for each hop, closed by a note
    when the chain stopped at a server that could not be asked. `dead_server`
    is None unless the FIRST server could not be asked, so nothing was learned:
    then it names that server, and `error` is the OSError its conversation
    raised, or None for a name `endpoint` would not vouch for.
    """
    servers, texts = [], []
    server, seen = ROOT, set()
    for _ in range(MAX_HOPS):
        if not server or server in seen:
            break
        seen.add(server)
        # Vetted per hop, the root included: one path, so a mistake here cannot
        # be a mistake that only some hops make.
        targets = endpoint(server)
        if targets is None:
            # Deliberately the SAME sentence for "does not resolve" and
            # "resolves somewhere private". The referral is written by whoever
            # answered the last hop, so telling them apart would answer
            # "does this internal name exist?" for a caller who is not
            # supposed to be able to ask. `endpoint`'s log line says which.
            if not texts:
                return servers, texts, server, None
            texts.append(f"% {server} is not a public whois server — "
                         "the chain ends here.")
            break
        try:
            answer = ask(targets, query)
        except OSError as e:
            if not texts:
                return servers, texts, server, e
            texts.append(f"% {server} would not answer — the chain ends here.")
            break
        servers.append(server)
        texts.append(f"% ── {server} ──\n{answer.strip()}")
        server = referral(answer)
    return servers, texts, None, None
