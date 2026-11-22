import ipaddress
import logging
import re
import socket
import time

log = logging.getLogger("atlas.live.whois")

ROOT = "whois.iana.org"
PORT = 43
MAX_HOPS = 3
MAX_BYTES = 64 * 1024
TIMEOUT_S = 6


def public_ip(ip):
    if ip.version == 6:
        mapped = ip.ipv4_mapped
        if mapped is not None:
            ip = mapped
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified) and ip.is_global


def endpoint(server):
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
    last = None
    for family, sockaddr in targets:
        chunks, total = [], 0
        sock = socket.socket(family, socket.SOCK_STREAM)
        deadline = time.monotonic() + TIMEOUT_S
        try:
            with sock:
                sock.settimeout(TIMEOUT_S)
                sock.connect(sockaddr)
                sock.sendall((query + "\r\n").encode("ascii", "ignore"))
                while total < MAX_BYTES:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise socket.timeout("the whois server took too long")
                    sock.settimeout(left)
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
    servers, texts = [], []
    server, seen = ROOT, set()
    for _ in range(MAX_HOPS):
        if not server or server in seen:
            break
        seen.add(server)
        targets = endpoint(server)
        if targets is None:
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
