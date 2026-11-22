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
import senders
import settings
from filelock import exclusive, lock_for
from jsonio import iso_utc
from senders.shape import (
    MAX_BODY, TITLE_MAX, TAG_MAX, TAGS_MAX, LINK_MAX, _URL_CHARS, _TAG, _CONTROL,
    _text, _one_line, _header, _link, _tags, _cut_bytes, _fit_json, Prepared, prepared,
    base_headers, header_text, plain_body, json_body)

log = logging.getLogger("atlas.live.alerts.send")


def __getattr__(name):
    if name == "KINDS":
        return senders.kinds()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


OUTCOMES = ("delivered", "refused", "unreachable", "blocked")
SECRET_PREFIX = "ATLAS_ALERT_SECRET_"
SECRET_NAME = re.compile(r"^[A-Z0-9_]{1,40}$")
NAME_MAX = 60
URL_MAX = 2048
DEFAULT_PORTS = {"http": 80, "https": 443}

MAX_READ = 1024
CONNECT_S = 3.0
TOTAL_S = 5.0

RESOLVE_S = 3.0
MACHINE_TTL_S = 300.0

METADATA_ADDRESSES = frozenset(map(ipaddress.ip_address, (
    "fd00:ec2::254", "100.100.100.200", "192.0.0.192")))

LOG_FILE = "alert-deliveries.jsonl"
KEEP_DAYS = 90
MAX_ROWS = 100_000
PRUNE_EVERY_S = 3600
TAIL_BYTES = 2 * 1024 * 1024
LOCK_WAIT_S = 0.5

_HOSTNAME = re.compile(r"^[a-z0-9_]([a-z0-9_-]{0,62})(\.[a-z0-9_]([a-z0-9_-]{0,62}))*$")
_PATH_CHARS = re.compile(r"^[A-Za-z0-9\-._~!$&'()*+,;=:@%/]*$")
_STAMP = "%Y-%m-%dT%H:%M:%SZ"



def _setting(name, env_name):
    value = getattr(settings, name, None)
    if callable(value):
        value = value()
    if value is None:
        value = os.environ.get(env_name)
    return value


def enabled():
    value = _setting("ALERTS_ENABLED", "ATLAS_ALERTS")
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _hosts_raw():
    return _setting("ALERT_HOSTS", "ATLAS_ALERT_HOSTS") or ""


def log_path():
    configured = getattr(settings, "ALERT_LOG_PATH", None)
    return configured or os.path.join(settings.DATA_DIR, LOG_FILE)



def _ip(text):
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip


def _norm_host(host):
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
    return _parse_hosts(_hosts_raw() if raw is None else raw)[0]


def host_problems(raw=None):
    return _parse_hosts(_hosts_raw() if raw is None else raw)[2]



def _bracket(host):
    return f"[{host}]" if ":" in host else host


def _target(url):
    if not isinstance(url, str):
        return None
    try:
        parts = urllib.parse.urlsplit(url.strip())
        port = parts.port or DEFAULT_PORTS.get(parts.scheme.lower())
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = _norm_host(parts.hostname)
    if scheme not in DEFAULT_PORTS or host is None or port is None:
        return None
    return scheme, host, port, parts.path or "/"


def origin(url):
    target = _target(url)
    if target is None:
        return None
    scheme, host, port, _ = target
    return f"{scheme}://{_bracket(host)}:{port}"


def _path_for(kind, path):
    return senders.send_path(kind, path)


def _kind_words():
    names = list(senders.kinds())
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} or {names[-1]}"


def check_destination(dest):
    if not isinstance(dest, dict):
        return ["A destination must be an object."]
    problems = []
    name = dest.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append("Give the destination a name.")
    elif len(name.strip()) > NAME_MAX:
        problems.append(f"A destination's name is at most {NAME_MAX} characters.")
    kind = dest.get("kind")
    entry = senders.find(kind)
    if entry is None:
        problems.append(f"The kind must be {_kind_words()}." if senders.kinds()
                        else "No kind of destination can send.")
    secret = dest.get("secret")
    if secret is not None and (not isinstance(secret, str) or not SECRET_NAME.match(secret)):
        problems.append("A secret is named in capitals, digits and underscores, at most "
                        "40 characters, as NTFY_LAB; Atlas reads ATLAS_ALERT_SECRET_<name>.")
    elif secret and entry is not None and entry.secret_use.get("in") == "none":
        problems.append("This kind of destination takes no secret.")
    elif not secret and entry is not None and senders.secret_in_path(kind):
        problems.append("This kind of destination needs a secret: name it, and the "
                        "server reads ATLAS_ALERT_SECRET_<name>.")
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
    scheme, host, port, path = target
    if not _PATH_CHARS.match(path):
        problems.append("The address's path has characters a URL cannot carry.")
    problems.extend(senders.check_path(kind, path))
    problems.extend(senders.check_address(kind, scheme, host, port, path))
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
    out = dict(dest)
    target = _target(dest.get("url"))
    kind = dest.get("kind")
    if target is not None and senders.rewrites_url(kind):
        scheme, host, port, path = target
        default = DEFAULT_PORTS[scheme] == port
        hostport = _bracket(host) if default else f"{_bracket(host)}:{port}"
        out["url"] = f"{scheme}://{hostport}{_path_for(kind, path)}"
    return out



def bind_secret(dest):
    out = dict(dest)
    out["secret_origin"] = origin(dest.get("url")) if dest.get("secret") else None
    return out


def unbind_if_moved(old, new):
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
    return _secret_state(dest)[0]



def _in_time(call, timeout):
    box = {}

    def work():
        try:
            box["value"] = call()
        except BaseException as e:
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
    except Exception:
        pass
    _machine.update(at=now, addresses=frozenset(found))
    return _machine["addresses"]


def _own_addresses():
    out = set(_machine_addresses())
    ip = _ip(str(getattr(settings, "HOST", "") or ""))
    if ip is not None and not ip.is_unspecified:
        out.add(ip)
    return out


def _refused_ip(ip):
    if ip.version == 4 and ip in ipaddress.ip_network("0.0.0.0/8"):
        return True
    return (ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_unspecified or ip.is_reserved or ip in METADATA_ADDRESSES
            or ip in _own_addresses())


def _vet(host, port, resolver):
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


class ShapeError(ValueError):
    pass


_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_HEADER_VALUE = re.compile(r"^[\x20-\x7e]*$")


def _checked(headers, body):
    if not isinstance(body, bytes) or len(body) > MAX_BODY:
        raise ShapeError(f"the message is not a body of at most {MAX_BODY} bytes")
    if not isinstance(headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and _HEADER_NAME.fullmatch(k)
            and _HEADER_VALUE.fullmatch(v) for k, v in headers.items()):
        raise ShapeError("the message has a header that cannot be sent")
    return headers, body


def build_request(kind, message, secret=None):
    entry = senders.find(kind) or senders.find("webhook")
    if entry is None:
        raise ShapeError("no kind of destination can send")
    return entry.build(prepared(message), secret)



def _ca_bundle():
    for name in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return None


class _Response:

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
    if late or isinstance(exc, (socket.timeout, TimeoutError)):
        return "timed out"
    try:
        from urllib3 import exceptions as u3
        if isinstance(exc, u3.SSLError):
            return "the certificate did not verify"
        if isinstance(exc, (u3.ConnectTimeoutError, u3.ReadTimeoutError)):
            return "timed out"
        from urllib3.util.ssl_match_hostname import CertificateError
        if isinstance(exc, CertificateError):
            return "the certificate did not verify"
    except ImportError:
        pass
    if isinstance(exc, (ssl.SSLError, ssl.CertificateError)):
        return "the certificate did not verify"
    if isinstance(exc, ConnectionRefusedError):
        return "the connection was refused"
    if isinstance(exc, (OSError, http.client.HTTPException)):
        return "could not connect"
    return "the request could not be made"



def _result(outcome, status=None, why=None):
    return {"outcome": outcome, "status": status, "why": why}


def send(dest, message, *, resolver=None, transport=None):
    try:
        if not enabled():
            return _result("blocked", why="alerts are off (ATLAS_ALERTS)")
        problems = check_destination(dest)
        if problems:
            return _result("blocked", why=problems[0])
        return _send(dest, message, resolver or socket.getaddrinfo,
                     transport or default_transport)
    except Exception as e:
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
    elif senders.secret_in_path(kind):
        return _result("blocked", why="this kind of destination needs a secret")
    address, refused = _vet(host, port, resolver)
    if address is None:
        return _result(refused[0], why=refused[1])
    try:
        headers, body = _checked(*build_request(kind, message, secret))
        path = senders.secret_path(kind, _path_for(kind, path), secret)
        if not (isinstance(path, str) and path.startswith("/") and _PATH_CHARS.fullmatch(path)):
            raise ShapeError("the kind's path cannot be sent")
    except ShapeError as e:
        log.warning("alert to %s: blocked (%s)", dest.get("id"), e)
        return _result("blocked", why=str(e))
    headers["Host"] = (_bracket(host) if DEFAULT_PORTS[scheme] == port
                       else f"{_bracket(host)}:{port}")
    deadline = time.monotonic() + TOTAL_S
    try:
        resp = transport(method="POST", address=str(address), port=port, scheme=scheme, host=host,
                         path=path, headers=headers, body=body,
                         connect_timeout=CONNECT_S, total_timeout=TOTAL_S)
    except Exception as e:
        why = _why(e, time.monotonic() >= deadline)
        log.info("alert to %s: unreachable (%s)", dest.get("id"), why)
        return _result("unreachable", why=why)
    try:
        status = int(resp.status)
        try:
            resp.read(MAX_READ)
        except Exception:
            pass
    finally:
        try:
            resp.close()
        except Exception:
            pass
    if 200 <= status < 300:
        outcome, why = "delivered", None
    elif 300 <= status < 400:
        outcome, why = "refused", f"HTTP {status}: redirects are not followed"
    else:
        outcome, why = "refused", f"HTTP {status}"
    log.info("alert to %s: %s (HTTP %s)", dest.get("id"), outcome, status)
    return _result(outcome, status, why)



_prune_lock = threading.Lock()
_pruned_at = {}


def _clip(value, limit):
    return None if value is None else _one_line(value, limit)


def _row(entry):
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
        row["folded"] = folded
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
        return 0


def log_delivery(entry, path=None):
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
                except OSError:
                    pass
            _prune_if_due(target)
        return True
    except Exception as e:
        log.warning("alert delivery not logged: %s", e.__class__.__name__)
        return False


def _prune_if_due(target, force=False):
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


def _rows_newest_first(target):
    try:
        size = os.path.getsize(target)
        with open(target, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()
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
