#!/usr/bin/env python3

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.0.0"
USER_AGENT = f"atlas-relay/{VERSION}"

DEFAULTS = {
    "signals": {"enabled": True, "interval": 30},
    "inventory": {"enabled": False, "interval": 6 * 3600},
    "scan": {"enabled": False, "interval": 24 * 3600, "nmap_args": ["-sn"], "promote": False},
    "hyperv": {"enabled": False, "interval": 6 * 3600, "mode": "standalone", "auth": "kerberos",
               "transport": "https", "verify_tls": True, "timeout": 60},
}
BACKOFF_START = 30.0
BACKOFF_MAX = 900.0

log = logging.getLogger("atlas-relay")


class ConfigError(RuntimeError):
    pass


def load_atlas_modules(web_dir=None):
    candidates = [web_dir, os.environ.get("ATLAS_WEB_DIR"),
                  Path(__file__).resolve().parent.parent / "Web"]
    for cand in candidates:
        if cand and Path(cand).is_dir():
            path = str(Path(cand).resolve())
            if path not in sys.path:
                sys.path.insert(0, path)
            try:
                import signals as atlas_signals
                from importers.netbox_client import NetBoxClient, NetBoxError, fetch_snapshot
                from importers.scan import NmapError, parse_nmap_xml
                from importers import hyperv_client
            except ImportError as e:
                raise ConfigError(f"Atlas modules at {path} are not importable: {e}") from e
            return {
                "signals": atlas_signals,
                "NetBoxClient": NetBoxClient, "NetBoxError": NetBoxError,
                "fetch_snapshot": fetch_snapshot,
                "parse_nmap_xml": parse_nmap_xml, "NmapError": NmapError,
                "hyperv": hyperv_client,
            }
    raise ConfigError(
        "cannot find the Atlas Web/ directory — run the relay from an Atlas checkout "
        "or set ATLAS_WEB_DIR (or web_dir in [server])")


def read_config(path):
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"cannot read config {path}: {e}") from e

    if path.suffix == ".json":
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise ConfigError(f"{path}: invalid JSON: {e}") from e
    else:
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError as e:
                raise ConfigError(
                    "TOML needs Python 3.11+ or the `tomli` package — or use a .json config"
                ) from e
        try:
            data = tomllib.loads(raw)
        except Exception as e:
            raise ConfigError(f"{path}: invalid TOML: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a table at the top level")

    cfg = {section: dict(defaults) for section, defaults in DEFAULTS.items()}
    for section, values in data.items():
        if not isinstance(values, dict):
            raise ConfigError(f"{path}: [{section}] must be a table")
        cfg.setdefault(section, {}).update(values)

    server = cfg.get("server") or {}
    if not server.get("url"):
        raise ConfigError("missing server.url")
    server["url"] = str(server["url"]).rstrip("/")
    if server["url"].startswith("http://") and not server.get("allow_insecure_http"):
        raise ConfigError(
            f"server.url is plain HTTP ({server['url']}) — the token would cross the "
            "network in the clear. Use https, or set allow_insecure_http = true if this "
            "is a trusted LAN test.")
    server["token"] = _resolve_token(server)
    cfg["server"] = server
    return cfg


def _resolve_token(server):
    token_file = server.get("token_file")
    if token_file:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as e:
            raise ConfigError(f"cannot read server.token_file {token_file}: {e}") from e
        if token:
            return token
    token = (server.get("token") or "").strip() or os.environ.get("ATLAS_RELAY_TOKEN", "").strip()
    if not token:
        raise ConfigError("no token — set server.token_file, server.token, or ATLAS_RELAY_TOKEN")
    return token


class HttpTransport:

    def __init__(self, base_url, token, timeout=20, verify_tls=True):
        self.base_url, self.token, self.timeout = base_url, token, timeout
        self.verify_tls = verify_tls
        if not verify_tls:
            log.warning("TLS verification is DISABLED — do not run this way in production")

    def post(self, path, payload):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.token}",
                     "User-Agent": USER_AGENT},
        )
        ctx = None
        if not self.verify_tls:
            import ssl
            ctx = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                return resp.status, _read_json(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, _read_json(e.read())


def _read_json(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def collect_signals(atlas, cfg):
    sig, section = atlas["signals"], cfg.get("signals", {})
    adapters = []
    for name in section.get("sources", []):
        name = str(name).strip().lower()
        if name == "kuma":
            url = section.get("kuma_url")
            if not url:
                log.warning("signals: kuma requested but kuma_url unset — skipping")
                continue
            key = _secret(section, "kuma_api_key")
            adapters.append(sig.KumaAdapter(url, key, monitor_map=section.get("kuma_map") or {}))
        elif name == "prometheus":
            url = section.get("prom_url")
            if not url:
                log.warning("signals: prometheus requested but prom_url unset — skipping")
                continue
            adapters.append(sig.PrometheusAdapter(url))
        elif name == "static":
            adapters.append(sig.StaticFileAdapter(section.get("file", "signals.json")))
        else:
            log.warning("signals: unknown source %r — ignoring", name)
    if not adapters:
        return None
    feed = sig.SignalsHub(adapters, ttl=0).feed()
    payload = {k: feed.get(k, {}) for k in ("nodes", "services", "metrics")}
    if not any(payload.values()):
        log.warning("signals: every source was silent — nothing to push")
        return None
    return payload


def _secret(section, key):
    path = section.get(key + "_file")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError as e:
            log.warning("cannot read %s (%s): %s", key + "_file", path, e)
    return section.get(key)


def collect_inventory(atlas, cfg):
    section = cfg.get("inventory", {})
    url = section.get("netbox_url")
    if not url:
        log.warning("inventory: netbox_url unset — skipping")
        return None
    token = _secret(section, "netbox_token")
    if not token:
        log.warning("inventory: no netbox token — skipping")
        return None
    client = atlas["NetBoxClient"](url, token, timeout=section.get("timeout", 20),
                                  verify=section.get("verify_tls", True))
    try:
        snapshot = atlas["fetch_snapshot"](client, netbox_site=section.get("netbox_site") or None)
    except atlas["NetBoxError"] as e:
        log.warning("inventory: netbox unreachable (%s) — skipping this pass", e)
        return None
    if not any(snapshot.values()):
        log.warning("inventory: netbox returned nothing — skipping")
        return None
    if section.get("role_map"):
        snapshot["role_map"] = section["role_map"]
    return snapshot


def collect_scan(atlas, cfg, runner=None):
    section = cfg.get("scan", {})
    targets = [str(t) for t in section.get("targets", []) if str(t).strip()]
    if not targets:
        log.warning("scan: no targets configured — skipping")
        return None
    args = [str(a) for a in section.get("nmap_args", DEFAULTS["scan"]["nmap_args"])]
    cmd = [section.get("nmap_binary", "nmap"), *args, "-oX", "-", *targets]
    run = runner or _run_nmap
    try:
        xml = run(cmd, timeout=section.get("timeout", 600))
    except FileNotFoundError:
        log.warning("scan: nmap is not installed (%s) — skipping", cmd[0])
        return None
    except subprocess.TimeoutExpired:
        log.warning("scan: nmap timed out — skipping this pass")
        return None
    except subprocess.SubprocessError as e:
        log.warning("scan: nmap failed (%s) — skipping this pass", e)
        return None
    try:
        hosts = atlas["parse_nmap_xml"](xml)
    except atlas["NmapError"] as e:
        log.warning("scan: unreadable nmap output (%s) — skipping", e)
        return None
    if not hosts:
        log.info("scan: no hosts up")
        return None
    payload = {"hosts": hosts, "source": "relay"}
    if section.get("promote"):
        payload["promote"] = True
    return payload


def _run_nmap(cmd, timeout):
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise subprocess.SubprocessError(
            (proc.stderr or "").strip()[:200] or f"exit {proc.returncode}")
    return proc.stdout


HYPERV_AUTH = ("kerberos", "ntlm", "negotiate")


def hyperv_plan(section):
    """The [hyperv] settings, checked. Refuses any way of signing in that would put
    the Windows password on the wire or trust a host nobody verified."""
    mode = str(section.get("mode", "standalone")).strip().lower()
    if mode != "standalone":
        raise ConfigError(f"hyperv: mode {mode!r} is not built yet — only \"standalone\" is")
    hosts = [str(h).strip() for h in section.get("hosts", []) if str(h).strip()]
    if not hosts:
        raise ConfigError("hyperv: no hosts — list each Hyper-V host under hosts = [...]")
    auth = str(section.get("auth", "kerberos")).strip().lower()
    if auth in ("basic", "credssp"):
        raise ConfigError(f"hyperv: auth = {auth!r} is refused — it hands the password to the "
                          "host. Use kerberos, or ntlm over https")
    if auth not in HYPERV_AUTH:
        raise ConfigError(f"hyperv: auth must be one of {', '.join(HYPERV_AUTH)}")
    transport = str(section.get("transport", "https")).strip().lower()
    if transport not in ("https", "http"):
        raise ConfigError("hyperv: transport must be https or http")
    https = transport == "https"
    ca_file = section.get("ca_file")
    verify = bool(section.get("verify_tls", True))
    lab = bool(section.get("allow_unverified_ntlm"))
    # Kerberos proves which host answered. NTLM does not, so it needs a certificate
    # the relay checks — unless the operator says this is a lab.
    proven = auth == "kerberos" or (https and verify)
    if not proven and not lab:
        raise ConfigError(
            f"hyperv: auth = {auth!r} over {transport}"
            + ("" if https else " (5985)") + (" with verify_tls = false" if https else "")
            + " cannot tell the real host from an impostor. Use https with a certificate the "
            "relay trusts (ca_file), or kerberos. For a lab only, set allow_unverified_ntlm = true")
    if not proven:
        log.warning("hyperv: allow_unverified_ntlm is set — the relay cannot tell a real host "
                    "from an impostor. Lab use only")
    username = str(section.get("username") or "").strip() or None
    password = _secret(section, "password")
    if auth != "kerberos" and not (username and password):
        raise ConfigError("hyperv: ntlm needs username and password_file")
    if ca_file and not Path(str(ca_file)).is_file():
        raise ConfigError(f"hyperv: cannot read ca_file {ca_file}")
    cert = (str(ca_file) if ca_file else True) if verify else False
    return {"hosts": hosts, "auth": auth, "https": https, "cert": cert,
            "port": int(section.get("port") or (5986 if https else 5985)),
            "username": username, "password": password,
            "timeout": int(section.get("timeout", 60)),
            "configuration_name": str(section.get("configuration_name") or "Microsoft.PowerShell")}


def _winrm_runner(atlas, plan):
    """run(host) -> the script's output, over WinRM. pypsrp is imported here and
    nowhere else, so a relay without [hyperv] never needs it."""
    Unanswered = atlas["hyperv"].Unanswered
    script = atlas["hyperv"].SCRIPT
    try:
        import requests
        from pypsrp.exceptions import AuthenticationError, WinRMError, WinRMTransportError
        from pypsrp.powershell import PowerShell, RunspacePool
        from pypsrp.wsman import WSMan
    except ImportError as e:
        raise ConfigError("hyperv: the relay needs the pypsrp package for WinRM "
                          f"(pip install pypsrp; add pypsrp[kerberos] for kerberos): {e}") from e

    def run(host):
        wsman = WSMan(host, port=plan["port"], ssl=plan["https"], auth=plan["auth"],
                      username=plan["username"], password=plan["password"],
                      cert_validation=plan["cert"],
                      # over http the messages themselves must be encrypted, or nothing is sent
                      encryption="auto" if plan["https"] else "always",
                      connection_timeout=plan["timeout"], read_timeout=plan["timeout"],
                      operation_timeout=max(5, plan["timeout"] - 10), no_proxy=True)
        try:
            with wsman, RunspacePool(wsman, configuration_name=plan["configuration_name"]) as pool:
                ps = PowerShell(pool)
                ps.add_script(script)
                out = ps.invoke()
                if ps.had_errors and not out:
                    first = ps.streams.error[0] if ps.streams.error else ""
                    raise Unanswered("Hyper-V refused the read: "
                                     + " ".join(str(first).split())[:160])
                return "".join(str(o) for o in out)
        except Unanswered:
            raise
        except AuthenticationError:
            raise Unanswered("it refused the account (check the user name, the password and "
                             "the Remote Management Users group)") from None
        except requests.exceptions.SSLError:
            raise Unanswered("its certificate was not trusted (set ca_file to the "
                             "certificate that signed it)") from None
        except requests.exceptions.Timeout:
            raise Unanswered(f"it did not answer on port {plan['port']} in time") from None
        except requests.exceptions.ConnectionError:
            raise Unanswered(f"nothing answered on port {plan['port']} (is WinRM on, and the "
                             "firewall open?)") from None
        except WinRMTransportError as e:
            raise Unanswered(f"WinRM answered HTTP {getattr(e, 'code', '?')}") from None
        except WinRMError as e:
            raise Unanswered(f"WinRM refused the session ({type(e).__name__})") from None

    return run


def _address_of(host):
    import socket
    try:
        found = socket.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return ""
    return found[0][4][0] if found else ""


def collect_hyperv(atlas, cfg, runner=None, resolve=_address_of):
    plan = hyperv_plan(cfg.get("hyperv", {}))
    run = runner or _winrm_runner(atlas, plan)
    hosts = [(h, resolve(h)) for h in plan["hosts"]]
    snapshot = atlas["hyperv"].fetch_snapshot(run, hosts)
    for quiet in snapshot["silent"]:
        log.warning("hyperv: %s: %s", quiet["host"], quiet["why"])
    for host in snapshot["hosts"]:
        mine = [v for v in snapshot["vms"] if v["host"] == host["name"]]
        log.info("hyperv: %s: %d vm(s), %d with an address", host["name"], len(mine),
                 sum(1 for v in mine if any(n["ips"] for n in v["nics"])))
        for vm in mine:
            log.debug("hyperv:   %s (%s) %s", vm["name"], vm["state"],
                      ", ".join(ip for n in vm["nics"] for ip in n["ips"]) or "no address")
    if not snapshot["hosts"]:
        # silence beats an empty snapshot that would blank the review
        raise RuntimeError("no Hyper-V host answered")
    return snapshot


class Task:

    def __init__(self, name, path, collector, interval):
        self.name, self.path, self.collect = name, path, collector
        self.interval = max(5.0, float(interval))
        self.next_run = 0.0
        self.backoff = 0.0
        self.failures = 0

    def due(self, now):
        return now >= self.next_run

    def schedule(self, now, failed):
        if failed:
            self.failures += 1
            self.backoff = min(BACKOFF_MAX,
                               self.backoff * 2 if self.backoff else BACKOFF_START)
            self.next_run = now + self.backoff
        else:
            self.failures, self.backoff = 0, 0.0
            self.next_run = now + self.interval


def build_tasks(atlas, cfg):
    tasks = []
    spec = (("signals", "/api/v2/ingest/signals", collect_signals),
            ("inventory", "/api/v2/ingest/inventory", collect_inventory),
            ("scan", "/api/v2/ingest/observed", collect_scan),
            ("hyperv", "/api/v2/ingest/hyperv", collect_hyperv))
    for name, path, collector in spec:
        section = cfg.get(name, {})
        if not section.get("enabled"):
            continue
        interval = section.get("interval", DEFAULTS[name]["interval"])
        tasks.append(Task(name, path, (lambda c=collector: c(atlas, cfg)), interval))
    return tasks


def _dump(directory, name, payload):
    path = Path(directory) / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    return path


def run_task(task, transport, dry_run=False, dump=None):
    try:
        payload = task.collect()
    except Exception as e:
        log.warning("%s: collector failed (%s: %s)", task.name, type(e).__name__, e)
        return False
    if payload is None:
        return True

    if dry_run:
        log.info("%s: DRY RUN, would push %s", task.name, _summarize(payload))
        if dump:
            log.info("%s: wrote what it would push to %s", task.name, _dump(dump, task.name, payload))
        return True

    try:
        status, body = transport.post(task.path, payload)
    except (OSError, urllib.error.URLError) as e:
        log.warning("%s: push failed (%s) — will retry", task.name, e)
        return False

    if status == 200:
        log.info("%s: pushed %s%s", task.name, _summarize(payload), _result(body))
        return True
    if status in (401, 403):
        log.error("%s: server rejected the token (HTTP %s: %s) — check `atlasctl token-list`",
                  task.name, status, (body or {}).get("error", ""))
        return False
    if status == 429:
        log.warning("%s: rate limited — backing off", task.name)
        return False
    log.warning("%s: server said HTTP %s (%s)", task.name, status, (body or {}).get("error", ""))
    return False


def _summarize(payload):
    if "vms" in payload and "mode" in payload:
        return (f"{len(payload.get('hosts', []))} hyper-v host(s), "
                f"{len(payload.get('vms', []))} vm(s), {len(payload.get('silent', []))} silent")
    if "hosts" in payload:
        return f"{len(payload['hosts'])} host(s)"
    if "devices" in payload:
        return (f"{len(payload.get('devices', []))} device(s), "
                f"{len(payload.get('vms', []))} vm(s), {len(payload.get('vlans', []))} vlan(s)")
    return (f"{len(payload.get('nodes', {}))} node(s), "
            f"{len(payload.get('services', {}))} service(s), "
            f"{len(payload.get('metrics', {}))} metric(s)")


def _result(body):
    stats = (body or {}).get("stats") or {}
    interesting = {k: v for k, v in stats.items() if v}
    if stats.get("undocumented"):
        return f" -> {interesting} ** UNDOCUMENTED DEVICES **"
    return f" -> {interesting}" if interesting else ""


class _Stopper:
    def __init__(self):
        self.stop = False
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._handle)
            except (ValueError, OSError):
                pass

    def _handle(self, *_):
        log.info("shutting down")
        self.stop = True


def run(tasks, transport, once=False, dry_run=False, sleeper=time.sleep, now=time.monotonic,
        dump=None):
    stopper = _Stopper()
    failures = 0
    if once:
        for task in tasks:
            if not run_task(task, transport, dry_run, dump):
                failures += 1
        return failures

    while not stopper.stop:
        t = now()
        for task in tasks:
            if stopper.stop:
                break
            if task.due(t):
                ok = run_task(task, transport, dry_run, dump)
                task.schedule(now(), failed=not ok)
        if stopper.stop:
            break
        nap = min((task.next_run - now() for task in tasks), default=1.0)
        sleeper(max(0.5, min(nap, 60.0)))
    return failures


def main(argv=None):
    ap = argparse.ArgumentParser(prog="atlas-relay", description="atlas-relay: pushes a site's live data to a hosted Atlas")
    ap.add_argument("--config", required=True, help="relay.toml (or .json)")
    ap.add_argument("--once", action="store_true", help="one pass, then exit (cron/timer)")
    ap.add_argument("--dry-run", action="store_true", help="collect and log, push nothing")
    ap.add_argument("--dump", metavar="DIR",
                    help="with --dry-run: also write each task's payload to DIR/<task>.json")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s atlas-relay %(message)s",
    )
    # --verbose is for the relay's own lines. The WinRM libraries log every packet
    # at DEBUG, sign-in exchange included, and that does not belong in a log.
    for noisy in ("pypsrp", "spnego", "urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        cfg = read_config(args.config)
        atlas = load_atlas_modules((cfg.get("server") or {}).get("web_dir"))
    except ConfigError as e:
        log.error("%s", e)
        return 2

    server = cfg["server"]
    transport = HttpTransport(server["url"], server["token"],
                              timeout=server.get("timeout", 20),
                              verify_tls=server.get("verify_tls", True))
    tasks = build_tasks(atlas, cfg)
    if not tasks:
        log.error("no tasks enabled — set enabled = true under [signals], [inventory], [scan] or [hyperv]")
        return 2

    log.info("atlas-relay %s -> %s (site token %s...): %s", VERSION, server["url"],
             server["token"][:10], ", ".join(f"{t.name} every {t.interval:g}s" for t in tasks))
    if args.dump and not args.dry_run:
        log.error("--dump only works with --dry-run")
        return 2
    failures = run(tasks, transport, once=args.once, dry_run=args.dry_run, dump=args.dump)
    return 1 if (args.once and failures) else 0


if __name__ == "__main__":
    sys.exit(main())
