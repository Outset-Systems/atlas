"""ALERTS' SENDER — destinations, the allow-list, pinned resolution, three shapes, the log.

The first thing Atlas pushes outward to an address someone typed (2026-11-13).
`alerts.py` decides WHAT to say and WHEN; this module decides WHETHER a given
address may be spoken to at all, and then speaks to it in one of three fixed
shapes. It owns no Flask and no dataset.

What bounds it, each one a test in `tests/test_alerts_send.py`:

  * **Off by default.** `settings.ALERTS_ENABLED` (`ATLAS_ALERTS`) must be on,
    and the destination's host:port must be in `settings.ALERT_HOSTS`
    (`ATLAS_ALERT_HOSTS`), a list the operator writes in the environment. An
    admin can only name a host already listed, so a test send cannot be used
    to ask about any other address.
  * **Resolved once, then pinned.** The name is resolved once per send, every
    answer is vetted, and the connection goes to the vetted address with the
    original `Host` header and, for https, SNI and certificate verification
    against the original name. Nothing resolves the name a second time, so a
    resolver that answers differently the second time (a DNS rebind) never
    gets asked. The pattern is `whois.endpoint`'s, with a different verdict:
    A lab's alert receiver lives on a private address, so private is allowed;
    loopback, link-local (169.254.169.254 included), multicast, unspecified,
    reserved, the cloud metadata addresses that sit outside those ranges, and
    this machine's own addresses are not, even when listed. The name is
    resolved on a worker thread, waited for at most `RESOLVE_S` seconds.
  * **Fixed shapes.** ntfy, Gotify, a JSON webhook. Always POST, never a
    redirect, 3s to connect and 5s in all on a wall clock, a body of at most
    4 KB, at most 1 KB of the answer read and thrown away. What comes back is
    "delivered", "refused" with the status, or "unreachable" with a fixed
    reason; never a body, a header or an exception's own text.
  * **Secrets by name, bound to an origin.** A destination names its secret
    (`NTFY_LAB` → `ATLAS_ALERT_SECRET_NTFY_LAB`, or its `_FILE`). The name is
    bound to the URL's origin when the admin names it; when the URL moves to
    another origin the binding is dropped until the admin names it again
    (after `integrations.SECRET_HOMES`). A destination whose secret cannot be
    read is not sent unauthenticated: it is blocked.
  * **A delivery log** of one line per send (time, rule, destination, events,
    outcome, status, reason; never a title, a body or a secret), 0600, pruned
    after 90 days, the `token_log.py` way. The log is a record, not the rate
    limit: that is the ledger in the alert state file (`alerts._Run`), charged
    under the state's lock, so it holds across both workers (2026-11-13).
"""

import base64
import calendar
import http.client
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import threading
import time
import urllib.parse

import envnames
import schema
import settings
from filelock import exclusive, lock_for
from jsonio import iso_utc

log = logging.getLogger("atlas.live.alerts.send")   # a child of atlas.live.alerts, which calls it

KINDS = ("ntfy", "gotify", "webhook")
OUTCOMES = ("delivered", "refused", "unreachable", "blocked")
SECRET_PREFIX = "ATLAS_ALERT_SECRET_"
SECRET_NAME = re.compile(r"^[A-Z0-9_]{1,40}$")
NAME_MAX = 60
URL_MAX = 2048
DEFAULT_PORTS = {"http": 80, "https": 443}

MAX_BODY = 4096          # bytes of request body, after encoding
MAX_READ = 1024          # bytes of the answer read, then discarded
CONNECT_S = 3.0
TOTAL_S = 5.0
TITLE_MAX = 200          # characters
TAG_MAX, TAGS_MAX = 32, 8
LINK_MAX = 2000

#: How long a name may take to resolve before the send is given up (2026-11-13).
#: The tick resolves while it holds the alert state's lock.
RESOLVE_S = 3.0
#: How long the machine's own addresses are kept before they are looked up again.
MACHINE_TTL_S = 300.0

#: Cloud metadata services on addresses no range check refuses (2026-11-13):
#: AWS's IPv6 one is a unique-local address, Alibaba's sits in the shared
#: 100.64.0.0/10 a tailnet uses, and Oracle's in 192.0.0.0/24. Exact addresses,
#: not their ranges: the ranges hold real receivers.
METADATA_ADDRESSES = frozenset(map(ipaddress.ip_address, (
    "fd00:ec2::254", "100.100.100.200", "192.0.0.192")))

LOG_FILE = "alert-deliveries.jsonl"
KEEP_DAYS = 90
MAX_ROWS = 100_000
PRUNE_EVERY_S = 3600
TAIL_BYTES = 2 * 1024 * 1024
LOCK_WAIT_S = 0.5

_HOSTNAME = re.compile(r"^[a-z0-9_]([a-z0-9_-]{0,62})(\.[a-z0-9_]([a-z0-9_-]{0,62}))*$")
#: What a URL may carry at all: printable ASCII, no space, no backslash.
_URL_CHARS = re.compile(r"^[\x21-\x7e]+$")
_PATH_CHARS = re.compile(r"^[A-Za-z0-9\-._~!$&'()*+,;=:@%/]*$")
_TAG = re.compile(r"[^A-Za-z0-9_+\-]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f\x80-\x9f  ]")
_STAMP = "%Y-%m-%dT%H:%M:%SZ"


# ── Settings, read late so a test (and the settings agent's names) can set them ─

def _setting(name, env_name):
    value = getattr(settings, name, None)
    if callable(value):
        value = value()
    if value is None:
        value = os.environ.get(env_name)
    return value


def enabled():
    """`ATLAS_ALERTS` is on. Hosts are checked per destination."""
    value = _setting("ALERTS_ENABLED", "ATLAS_ALERTS")
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _hosts_raw():
    return _setting("ALERT_HOSTS", "ATLAS_ALERT_HOSTS") or ""


def log_path():
    configured = getattr(settings, "ALERT_LOG_PATH", None)
    return configured or os.path.join(settings.DATA_DIR, LOG_FILE)


# ── The allow-list ──────────────────────────────────────────────────────────

def _ip(text):
    """`text` as an address, IPv4-mapped IPv6 unwrapped, or None."""
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip


def _norm_host(host):
    """A host as the allow-list compares it: lower case, no trailing dot, an
    address in its one canonical spelling. None when it is neither."""
    host = (host or "").strip().lower().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or "%" in host:
        return None
    ip = _ip(host)
    if ip is not None:
        return str(ip)
    if ":" in host or not _HOSTNAME.match(host) or len(host) > 253:
        return None
    return host


def _parse_hosts(raw):
    """`(entries, portless, problems)`: the (host, port) pairs, the hosts listed
    without a port, and a sentence for every entry that could not be read."""
    entries, portless, problems = [], set(), []
    for item in re.split(r"[,\s]+", raw or ""):
        item = item.strip()
        if not item:
            continue
        if item.startswith("["):
            host, _, rest = item[1:].partition("]")
            port = rest[1:] if rest.startswith(":") else None
            if rest and not rest.startswith(":"):
                host = None
        elif item.count(":") == 1:
            host, port = item.split(":")
        elif ":" in item:
            problems.append(f"{item} in ATLAS_ALERT_HOSTS: write an IPv6 address in "
                            "brackets with its port, as [2001:db8::5]:443")
            continue
        else:
            host, port = item, None
        norm = _norm_host(host)
        if norm is None:
            problems.append(f"{item} in ATLAS_ALERT_HOSTS is not a host name or an address")
            continue
        if not port:
            portless.add(norm)
            problems.append(f"{item} in ATLAS_ALERT_HOSTS has no port; list it as "
                            f"{item}:443 or with the port the receiver listens on")
            continue
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            problems.append(f"{item} in ATLAS_ALERT_HOSTS has a port that is not 1 to 65535")
            continue
        pair = (norm, int(port))
        if pair not in entries:
            entries.append(pair)
    return entries, portless, problems


def allowed_hosts(raw=None):
    """The (host, port) pairs `ATLAS_ALERT_HOSTS` allows, in the order written.
    An entry without a port, or one that cannot be read, is left out;
    `host_problems` says why."""
    return _parse_hosts(_hosts_raw() if raw is None else raw)[0]


def host_problems(raw=None):
    """A sentence for every `ATLAS_ALERT_HOSTS` entry that was left out."""
    return _parse_hosts(_hosts_raw() if raw is None else raw)[2]


# ── A destination ───────────────────────────────────────────────────────────

def _bracket(host):
    return f"[{host}]" if ":" in host else host


def _target(url):
    """`(scheme, host, port, path)` of a URL that `check_destination` passed,
    or None. The one parser both the check and the send use."""
    if not isinstance(url, str):
        return None
    try:
        parts = urllib.parse.urlsplit(url.strip())
        port = parts.port or DEFAULT_PORTS.get(parts.scheme.lower())
    except ValueError:              # a stray bracket, a port that is not a number
        return None
    scheme = parts.scheme.lower()
    host = _norm_host(parts.hostname)
    if scheme not in DEFAULT_PORTS or host is None or port is None:
        return None
    return scheme, host, port, parts.path or "/"


def origin(url):
    """`scheme://host:port`, the port always written, so `https://h/` and
    `https://h:443/` are one origin. None for a URL that does not parse."""
    target = _target(url)
    if target is None:
        return None
    scheme, host, port, _ = target
    return f"{scheme}://{_bracket(host)}:{port}"


def _path_for(kind, path):
    if kind == "gotify":
        bare = path.rstrip("/")
        return bare if bare.endswith("/message") else "/message"
    return path


def check_destination(dest):
    """Everything wrong with `dest`, in plain sentences; an empty list when it
    may be saved and sent to."""
    if not isinstance(dest, dict):
        return ["A destination must be an object."]
    problems = []
    name = dest.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append("Give the destination a name.")
    elif len(name.strip()) > NAME_MAX:
        problems.append(f"A destination's name is at most {NAME_MAX} characters.")
    kind = dest.get("kind")
    if kind not in KINDS:
        problems.append("The kind must be ntfy, gotify or webhook.")
    secret = dest.get("secret")
    if secret is not None and (not isinstance(secret, str) or not SECRET_NAME.match(secret)):
        problems.append("A secret is named in capitals, digits and underscores, at most "
                        "40 characters, as NTFY_LAB; Atlas reads ATLAS_ALERT_SECRET_<name>.")
    problems.extend(_check_url(dest.get("url"), kind))
    return problems


def _check_url(url, kind):
    if not isinstance(url, str) or not url.strip():
        return ["Give the destination an address (a URL)."]
    url = url.strip()
    if len(url) > URL_MAX:
        return [f"The address is longer than {URL_MAX} characters."]
    if not _URL_CHARS.match(url) or "\\" in url:
        return ["The address has spaces or characters a URL cannot carry."]
    scheme = url.split(":", 1)[0].lower() if ":" in url else ""
    if scheme not in DEFAULT_PORTS:
        return ["The address must start with http:// or https://."]
    problems = []
    authority = url.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in authority or schema.carries_credentials(url):
        problems.append("The address carries a user name or password (user:pass@host). "
                        "Name a secret instead; Atlas sends it in a header.")
    if "?" in url:
        problems.append("The address may not carry a query string (?...). A key goes in "
                        "a named secret, never in the URL.")
    if "#" in url:
        problems.append("The address may not carry a fragment (#...).")
    if problems:
        return problems
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ["The address does not parse as a URL."]
    try:
        parts.port
    except ValueError:
        return ["The address's port is not a number from 1 to 65535."]
    target = _target(url)
    if target is None:
        return ["The address's host is not a host name or an address."]
    _, host, port, path = target
    if not _PATH_CHARS.match(path):
        problems.append("The address's path has characters a URL cannot carry.")
    if kind == "gotify":
        bare = path.rstrip("/")
        if bare and not bare.endswith("/message"):
            problems.append("A Gotify address is the server itself or ends in /message.")
    if kind == "ntfy" and path.strip("/") == "":
        problems.append("An ntfy address names its topic, as https://ntfy.example/atlas.")
    ip = _ip(host)
    if ip is not None and _refused_ip(ip):
        problems.append("Alerts may not be sent to a loopback, link-local, multicast, "
                        "reserved or unspecified address, or to Atlas itself.")
    entries, portless, _ = _parse_hosts(_hosts_raw())
    if (host, port) not in entries:
        if host in portless:
            problems.append(f"{host} is in ATLAS_ALERT_HOSTS without a port, so nothing "
                            f"may be sent to it; the operator lists it as {_bracket(host)}:{port}.")
        elif not entries:
            problems.append("ATLAS_ALERT_HOSTS is empty, so alerts may not be sent anywhere.")
        else:
            problems.append(f"{_bracket(host)}:{port} is not in ATLAS_ALERT_HOSTS; only "
                            "the operator can add a host there.")
    return problems


def normalised(dest):
    """A copy of `dest` with its URL written the way it is sent: a Gotify
    address ends in /message. For the save, after `check_destination`."""
    out = dict(dest)
    target = _target(dest.get("url"))
    if target is not None and dest.get("kind") == "gotify":
        scheme, host, port, path = target
        default = DEFAULT_PORTS[scheme] == port
        hostport = _bracket(host) if default else f"{_bracket(host)}:{port}"
        out["url"] = f"{scheme}://{hostport}{_path_for('gotify', path)}"
    return out


# ── Secrets, bound to an origin ─────────────────────────────────────────────

def bind_secret(dest):
    """A copy of `dest` with its secret bound to the URL's current origin.
    Called when an admin names a secret, and only then."""
    out = dict(dest)
    out["secret_origin"] = origin(dest.get("url")) if dest.get("secret") else None
    return out


def unbind_if_moved(old, new):
    """`(new_copy, note)`. The binding survives only when the secret is the same
    one and the origin has not changed; otherwise it is dropped, and `note`
    says so when there was one to drop. Anything the caller copied into
    `new["secret_origin"]` is ignored: a binding is carried, never supplied."""
    out = dict(new)
    old = old or {}
    bound = old.get("secret_origin")
    keep = (bool(bound) and bool(new.get("secret"))
            and new.get("secret") == old.get("secret")
            and bound == origin(old.get("url"))
            and bound == origin(new.get("url")))
    out["secret_origin"] = bound if keep else None
    note = None
    if bound and new.get("secret") and not keep:
        note = (f"The address moved to another host, so the secret {new.get('secret')} "
                "is no longer sent with it. Name the secret again to send it there.")
    return out, note


def _secret_state(dest):
    """`(value, why)`: the secret, or None and the reason it is not sent."""
    name = dest.get("secret")
    if not name:
        return None, None
    if not isinstance(name, str) or not SECRET_NAME.match(name):
        return None, "the secret's name is not valid"
    current = origin(dest.get("url"))
    if not current or dest.get("secret_origin") != current:
        return None, "its secret is not bound to this address; name the secret again"
    value = envnames.secret(SECRET_PREFIX + name) or None
    if value is None:
        return None, f"{SECRET_PREFIX}{name} is not set"
    if _CONTROL.search(value) or not value.isascii():
        return None, f"{SECRET_PREFIX}{name} holds characters a header cannot carry"
    return value, None


def secret_for(dest):
    """The destination's secret, only while it is bound to the URL's current
    origin; else None. Never logged, never returned by a route."""
    return _secret_state(dest)[0]


# ── Addresses ───────────────────────────────────────────────────────────────

def _in_time(call, timeout):
    """`call()` on a worker thread, waited for at most `timeout` seconds. Raises
    TimeoutError when it takes longer (the thread is left to finish on its own;
    a resolver cannot be cancelled), and whatever `call` raised."""
    box = {}

    def work():
        try:
            box["value"] = call()
        except BaseException as e:  # noqa: BLE001 — handed back to the caller
            box["error"] = e

    worker = threading.Thread(target=work, name="atlas-alert-resolve", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError("took too long")
    if "error" in box:
        raise box["error"]
    return box.get("value")


_machine = {"at": None, "addresses": frozenset()}


def _machine_addresses():
    """This machine's own addresses, as far as its own name says (2026-11-13),
    kept for `MACHINE_TTL_S`. Best effort: never raises, and an answer that does
    not come in time is no addresses until the next look."""
    now = time.monotonic()
    if _machine["at"] is not None and now - _machine["at"] < MACHINE_TTL_S:
        return _machine["addresses"]
    found = set()
    try:
        name = socket.gethostname()
        infos = _in_time(lambda: socket.getaddrinfo(name, None), RESOLVE_S) if name else ()
        for info in infos or ():
            ip = _ip(str(info[4][0]).split("%", 1)[0])
            if ip is not None and not ip.is_unspecified:
                found.add(ip)
    except Exception:  # noqa: BLE001 — best effort: a guard, never a fault
        pass
    _machine.update(at=now, addresses=frozenset(found))
    return _machine["addresses"]


def _own_addresses():
    """The addresses that reach this machine: the one Atlas listens on, when it
    is told one (`ATLAS_HOST`), and the machine's own (`_machine_addresses`).
    A bind to every address (0.0.0.0, ::) names none of them, which is why the
    machine's own are looked up as well (2026-11-13)."""
    out = set(_machine_addresses())
    ip = _ip(str(getattr(settings, "HOST", "") or ""))
    if ip is not None and not ip.is_unspecified:
        out.add(ip)
    return out


def _refused_ip(ip):
    if ip.version == 4 and ip in ipaddress.ip_network("0.0.0.0/8"):
        return True          # "this network": a connect to it reaches this host
    return (ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_unspecified or ip.is_reserved or ip in METADATA_ADDRESSES
            or ip in _own_addresses())


def _vet(host, port, resolver):
    """`(address, why)`: the one address to connect to, or None and a reason.
    Any refused answer disqualifies the whole name, as in `whois.endpoint`."""
    try:
        infos = _in_time(lambda: resolver(host, port, proto=socket.IPPROTO_TCP), RESOLVE_S)
    except TimeoutError:
        log.warning("alerts: %s did not resolve within %ss", host, RESOLVE_S)
        return None, ("unreachable", "the name did not resolve in time")
    except (OSError, UnicodeError):
        return None, ("unreachable", "the name did not resolve")
    addresses = []
    for info in infos or ():
        try:
            raw = str(info[4][0])
        except (IndexError, TypeError):
            return None, ("blocked", "the name resolved to something that is not an address")
        ip = _ip(raw.split("%", 1)[0])
        if ip is None:
            return None, ("blocked", "the name resolved to something that is not an address")
        if _refused_ip(ip):
            log.warning("alerts: refusing %s, which resolves to %s", host, ip)
            return None, ("blocked", "the name resolves to an address alerts may not reach")
        addresses.append(ip)
    if not addresses:
        return None, ("unreachable", "the name did not resolve")
    literal = _ip(host)
    if literal is not None and any(a != literal for a in addresses):
        log.warning("alerts: %s resolved to %s", host, addresses)
        return None, ("blocked", "the address resolved to a different address")
    return addresses[0], None


# ── The three shapes ────────────────────────────────────────────────────────

def _text(value):
    """Text that encodes as UTF-8 (a lone surrogate becomes '?')."""
    if value is None:
        return ""
    return str(value).encode("utf-8", "replace").decode("utf-8")


def _one_line(value, limit):
    text = re.sub(r"\s+", " ", _CONTROL.sub(" ", _text(value))).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _header(value):
    """A header value: one line, and ASCII, as RFC 2047 when it is not
    (ntfy decodes `=?UTF-8?B?…?=`)."""
    if value.isascii():
        return value
    return "=?UTF-8?B?" + base64.b64encode(value.encode("utf-8")).decode("ascii") + "?="


def _link(value):
    if not isinstance(value, str):
        return None
    link = value.strip()
    if (not link or len(link) > LINK_MAX or not _URL_CHARS.match(link)
            or not link.lower().startswith(("http://", "https://"))
            or schema.carries_credentials(link)):
        return None
    return link


def _tags(value):
    out = []
    for tag in value if isinstance(value, (list, tuple)) else ():
        tag = _TAG.sub("", _text(tag))[:TAG_MAX]
        if tag and tag not in out:
            out.append(tag)
        if len(out) >= TAGS_MAX:
            break
    return out


def _cut_bytes(text, limit):
    """`text` in at most `limit` UTF-8 bytes, ending in '…' when cut, never
    splitting a character."""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:max(0, limit - 3)].decode("utf-8", "ignore") + "…"


def _fit_json(build, text):
    """The JSON bytes of `build(text)` in at most MAX_BODY bytes, cutting only
    the text: the structure is always whole."""
    def encode(t):
        return json.dumps(build(t), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    whole = encode(text)
    if len(whole) <= MAX_BODY:
        return whole
    lo, hi = 0, len(text)
    while lo < hi:                       # the longest prefix that fits
        mid = (lo + hi + 1) // 2
        if len(encode(text[:mid] + "…")) <= MAX_BODY:
            lo = mid
        else:
            hi = mid - 1
    return encode(text[:lo] + "…")


def build_request(kind, message, secret=None):
    """`(headers, body_bytes)` for one of the three shapes. Public so a test can
    read exactly what would be sent."""
    message = message if isinstance(message, dict) else {}
    title = _one_line(message.get("title"), TITLE_MAX)
    body = _text(message.get("body"))
    high = message.get("priority") == "high"
    link = _link(message.get("link"))
    tags = _tags(message.get("tags"))
    headers = {"User-Agent": "Atlas-alerts"}
    if kind == "ntfy":
        headers["Content-Type"] = "text/plain; charset=utf-8"
        if title:
            headers["Title"] = _header(title)
        headers["Priority"] = "5" if high else "3"
        if tags:
            headers["Tags"] = ",".join(tags)
        if link:
            headers["Click"] = link
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        return headers, _cut_bytes(body, MAX_BODY).encode("utf-8")
    headers["Content-Type"] = "application/json"
    if kind == "gotify":
        if secret:
            headers["X-Gotify-Key"] = secret

        def build(text):
            doc = {"title": title, "message": text, "priority": 8 if high else 5}
            if link:
                doc["extras"] = {"client::notification": {"click": {"url": link}}}
            return doc
        return headers, _fit_json(build, body)
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    def build(text):
        return {"title": title, "body": text, "priority": "high" if high else "default",
                "link": link, "tags": tags, "source": "atlas"}
    return headers, _fit_json(build, body)


# ── The transport ───────────────────────────────────────────────────────────

def _ca_bundle():
    """The CAs `requests` would trust here, so a lab CA the importers already
    trust (REQUESTS_CA_BUNDLE) is trusted for alerts too."""
    for name in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    try:
        import certifi
        return certifi.where()
    except ImportError:          # pragma: no cover - requests brings it
        return None


class _Response:
    """What the default transport hands back: `.status`, `.read(n)`, `.close()`.
    The watchdog stays armed until `close`, so reading is on the clock too."""

    def __init__(self, conn, resp, timer):
        self._conn, self._resp, self._timer = conn, resp, timer
        self.status = resp.status

    def read(self, amount):
        return self._resp.read(amount, decode_content=False)

    def close(self):
        self._timer.cancel()
        try:
            self._resp.close()
        finally:
            self._conn.close()


def default_transport(*, address, port, scheme, host, path, headers, body,
                      connect_timeout=CONNECT_S, total_timeout=TOTAL_S, ca_certs=None,
                      method="POST"):
    """POST `body` (always POST: `method` is accepted only to be checked) to `address`:`port` — an address, never a name — with
    `headers` (which carry `Host`). For https the TLS handshake names `host`
    (SNI) and the certificate must be valid for `host`, not for the address.

    One connection, one request: no pool, no retry, no redirect, no proxy
    from the environment. A watchdog shuts the socket at `total_timeout` on
    the wall clock, because a socket timeout is per call and a receiver that
    drips one byte a second would otherwise hold the annalist's thread."""
    from urllib3.connection import HTTPConnection, HTTPSConnection

    if method != "POST":
        raise ValueError("alerts only POST")
    started = time.monotonic()
    if scheme == "https":
        conn = HTTPSConnection(address, port, timeout=connect_timeout,
                               server_hostname=host, assert_hostname=host,
                               cert_reqs="CERT_REQUIRED",
                               ca_certs=ca_certs or _ca_bundle())
    else:
        conn = HTTPConnection(address, port, timeout=connect_timeout)

    def kill():
        sock = getattr(conn, "sock", None)
        try:
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    timer = threading.Timer(total_timeout, kill)
    timer.daemon = True
    timer.start()
    try:
        conn.connect()
        conn.timeout = max(0.05, total_timeout - (time.monotonic() - started))
        conn.sock.settimeout(conn.timeout)
        conn.request("POST", path, body=body, headers=headers,
                     preload_content=False, decode_content=False)
        resp = conn.getresponse()
    except BaseException:
        timer.cancel()
        conn.close()
        raise
    return _Response(conn, resp, timer)


def _why(exc, late):
    """A fixed reason for a failure to connect: never the exception's own
    text, which can quote a header (the secret) or an address."""
    if late or isinstance(exc, (socket.timeout, TimeoutError)):
        return "timed out"
    try:
        from urllib3 import exceptions as u3
        if isinstance(exc, u3.SSLError):
            return "the certificate did not verify"
        if isinstance(exc, (u3.ConnectTimeoutError, u3.ReadTimeoutError)):
            return "timed out"
        from urllib3.util.ssl_match_hostname import CertificateError
        if isinstance(exc, CertificateError):       # urllib3's own name check
            return "the certificate did not verify"
    except ImportError:          # pragma: no cover
        pass
    if isinstance(exc, (ssl.SSLError, ssl.CertificateError)):
        return "the certificate did not verify"
    if isinstance(exc, ConnectionRefusedError):
        return "the connection was refused"
    if isinstance(exc, (OSError, http.client.HTTPException)):
        return "could not connect"
    return "the request could not be made"


# ── Send ────────────────────────────────────────────────────────────────────

def _result(outcome, status=None, why=None):
    return {"outcome": outcome, "status": status, "why": why}


def send(dest, message, *, resolver=None, transport=None):
    """Send `message` to `dest`. Never raises. Returns
    `{"outcome": delivered|refused|unreachable|blocked, "status", "why"}`."""
    try:
        if not enabled():
            return _result("blocked", why="alerts are off (ATLAS_ALERTS)")
        problems = check_destination(dest)
        if problems:
            return _result("blocked", why=problems[0])
        return _send(dest, message, resolver or socket.getaddrinfo,
                     transport or default_transport)
    except Exception as e:  # noqa: BLE001 — a send must never take the tick down
        log.warning("alert not sent: %s", e.__class__.__name__)
        return _result("unreachable", why="the request could not be made")


def _send(dest, message, resolver, transport):
    kind = dest["kind"]
    scheme, host, port, path = _target(dest["url"])
    secret = None
    if dest.get("secret"):
        secret, why = _secret_state(dest)
        if secret is None:
            return _result("blocked", why=why)
    address, refused = _vet(host, port, resolver)
    if address is None:
        return _result(refused[0], why=refused[1])
    headers, body = build_request(kind, message, secret)
    headers["Host"] = (_bracket(host) if DEFAULT_PORTS[scheme] == port
                       else f"{_bracket(host)}:{port}")
    deadline = time.monotonic() + TOTAL_S
    try:
        resp = transport(method="POST", address=str(address), port=port, scheme=scheme, host=host,
                         path=_path_for(kind, path), headers=headers, body=body,
                         connect_timeout=CONNECT_S, total_timeout=TOTAL_S)
    except Exception as e:  # noqa: BLE001 — mapped to a fixed reason
        why = _why(e, time.monotonic() >= deadline)
        log.info("alert to %s: unreachable (%s)", dest.get("id"), why)
        return _result("unreachable", why=why)
    try:
        status = int(resp.status)
        try:
            resp.read(MAX_READ)          # read a little, then let it go unread
        except Exception:  # noqa: BLE001 — the status is the answer
            pass
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    if 200 <= status < 300:
        outcome, why = "delivered", None
    elif 300 <= status < 400:
        outcome, why = "refused", f"HTTP {status}: redirects are not followed"
    else:
        outcome, why = "refused", f"HTTP {status}"
    log.info("alert to %s: %s (HTTP %s)", dest.get("id"), outcome, status)
    return _result(outcome, status, why)


# ── The delivery log ────────────────────────────────────────────────────────

_prune_lock = threading.Lock()
_pruned_at = {}


def _clip(value, limit):
    return None if value is None else _one_line(value, limit)


def _row(entry):
    """Only the named keys, each cut to size: a caller that passes a title, a
    body or a secret by mistake cannot get it written."""
    entry = entry if isinstance(entry, dict) else {}
    at = entry.get("at")
    if not (isinstance(at, str) and _epoch(at) is not None):
        at = iso_utc()
    events = entry.get("events")
    events = [e if isinstance(e, int) else _clip(e, 80)
              for e in (events if isinstance(events, (list, tuple)) else [])[:100]]
    status = entry.get("status")
    outcome = entry.get("outcome")
    row = {"at": at, "rule": _clip(entry.get("rule"), 80),
           "destination": _clip(entry.get("destination"), 80), "events": events,
           "outcome": outcome if outcome in OUTCOMES else "unknown",
           "status": status if isinstance(status, int) and not isinstance(status, bool) else None,
           "why": _clip(entry.get("why"), 200)}
    folded = entry.get("folded")
    if isinstance(folded, int) and not isinstance(folded, bool) and folded > 0:
        row["folded"] = folded       # the rate limit's "and N more" (security item 8)
    return row


def _epoch(at):
    try:
        return calendar.timegm(time.strptime(at, _STAMP))
    except (TypeError, ValueError):
        return None


def _stamp(line):
    try:
        return _epoch(json.loads(line).get("at")) or 0
    except (ValueError, AttributeError, TypeError):
        return 0             # a line nobody can read is not worth keeping


def log_delivery(entry, path=None):
    """Append one line for one send. Never raises; False when it could not be
    written (and a warning says so)."""
    target = path or log_path()
    try:
        line = json.dumps(_row(entry), separators=(",", ":")) + "\n"
        with exclusive(lock_for(target), timeout=LOCK_WAIT_S):
            fresh = not os.path.exists(target)
            with open(target, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
            if fresh:
                try:
                    os.chmod(target, 0o600)
                except OSError:      # a share that will not take modes
                    pass
            _prune_if_due(target)
        return True
    except Exception as e:  # noqa: BLE001 — the send happened either way
        log.warning("alert delivery not logged: %s", e.__class__.__name__)
        return False


def _prune_if_due(target, force=False):
    """Drop lines older than KEEP_DAYS, at most once an hour per file per
    process. Called with the lock held."""
    now = time.time()
    with _prune_lock:
        if not force and now - _pruned_at.get(target, 0) < PRUNE_EVERY_S:
            return
        _pruned_at[target] = now
    cutoff = now - KEEP_DAYS * 86400
    with open(target, encoding="utf-8") as fh:
        lines = fh.readlines()
    kept = [ln for ln in lines if _stamp(ln) >= cutoff][-MAX_ROWS:]
    if len(kept) == len(lines):
        return
    tmp = f"{target}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(kept)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, target)
    log.info("alert delivery log pruned: %d of %d lines kept", len(kept), len(lines))


def prune(path=None):
    """Prune now. For the CLI and the tests."""
    target = path or log_path()
    if os.path.exists(target):
        with exclusive(lock_for(target), timeout=LOCK_WAIT_S):
            _prune_if_due(target, force=True)


def _rows_newest_first(target):
    try:
        size = os.path.getsize(target)
        with open(target, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()            # the cut landed mid-line
            lines = fh.read().decode("utf-8", "replace").split("\n")
    except OSError:
        return
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            yield row


def read_deliveries(limit=100, path=None):
    """The newest lines first, at most `limit` (1 to 1000)."""
    try:
        limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        limit = 100
    out = []
    for row in _rows_newest_first(path or log_path()):
        out.append(row)
        if len(out) >= limit:
            break
    return out
