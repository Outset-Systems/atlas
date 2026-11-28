"""What the relay needs to read Hyper-V: the script, and the shape of a snapshot.

Standard library only, so the relay can import it without the rest of Atlas.
`hyperv.py` turns a snapshot into review rows on the server.
"""
import json
import time

MODES = ("standalone",)

HOST_BUDGET = 120

MAX_HOSTS = 64
MAX_VMS = 4000
MAX_NICS = 16
MAX_IPS = 16

# Runs on the Hyper-V host itself, so there is no second hop. Read-only: every
# cmdlet it calls is in READS, and a test holds it to that. Nothing from the
# relay's configuration is ever written into this text.
READS = ("Get-VMHost", "Get-VM", "Get-VMNetworkAdapter")

SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$h = Get-VMHost
$vms = @(Get-VM | ForEach-Object {
    $vm = $_
    $nics = @(Get-VMNetworkAdapter -VM $vm | ForEach-Object {
        [ordered]@{
            mac    = [string]$_.MacAddress
            switch = [string]$_.SwitchName
            ips    = @($_.IPAddresses | ForEach-Object { [string]$_ })
        }
    })
    [ordered]@{
        id          = [string]$vm.VMId
        name        = [string]$vm.Name
        state       = [string]$vm.State
        vcpu        = [int]$vm.ProcessorCount
        memory      = [long]$vm.MemoryStartup
        clustered   = [bool]$vm.IsClustered
        replication = [string]$vm.ReplicationMode
        nics        = $nics
    }
})
[ordered]@{
    name   = [string]$h.ComputerName
    fqdn   = [string]$h.FullyQualifiedDomainName
    cores  = [int]$h.LogicalProcessorCount
    memory = [long]$h.MemoryCapacity
    vms    = $vms
} | ConvertTo-Json -Depth 6 -Compress
"""


class Unanswered(Exception):
    """A host did not give a usable answer. Its text is shown to an admin, so it
    must be a plain sentence with no credential in it."""


def _text(value, limit=255):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return str(value).strip()[:limit]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _list(value):
    # PowerShell 5.1 writes a one-item array as the bare item in some shapes.
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _nic(raw):
    if not isinstance(raw, dict):
        return None
    ips = [_text(ip, 64) for ip in _list(raw.get("ips"))][:MAX_IPS]
    return {"mac": _text(raw.get("mac"), 17), "switch": _text(raw.get("switch"), 120),
            "ips": [ip for ip in ips if ip]}


def _vm(raw, host):
    if not isinstance(raw, dict) or not _text(raw.get("id"), 64):
        return None
    nics = [n for n in (_nic(x) for x in _list(raw.get("nics"))[:MAX_NICS]) if n]
    return {"id": _text(raw.get("id"), 64).lower(), "name": _text(raw.get("name")),
            "host": host, "state": _text(raw.get("state"), 40),
            "vcpu": _number(raw.get("vcpu")), "memory": _number(raw.get("memory")),
            "clustered": raw.get("clustered") is True,
            "replication": _text(raw.get("replication"), 40), "nics": nics}


def parse_answer(text, asked, address=""):
    """One host's JSON answer, as (host, vms). `asked` is the name in the config."""
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        raise Unanswered("it answered, but not with the inventory Atlas asked for") from None
    if not isinstance(raw, dict):
        raise Unanswered("it answered, but not with the inventory Atlas asked for")
    name = _text(raw.get("fqdn")) or _text(raw.get("name")) or _text(asked)
    host = {"name": name.lower(), "label": _text(raw.get("name")) or name,
            "asked": _text(asked), "address": _text(address, 64),
            "cores": _number(raw.get("cores")), "memory": _number(raw.get("memory"))}
    vms = [v for v in (_vm(x, host["name"]) for x in _list(raw.get("vms"))) if v]
    return host, vms


def fetch_snapshot(run, hosts, *, clock=time.monotonic, budget=HOST_BUDGET):
    """Ask each host in turn. `hosts` is [(name, address)], `run(name)` returns the
    script's output as text or raises. One silent host does not stop the rest."""
    snapshot = {"mode": "standalone", "hosts": [], "vms": [], "silent": []}
    seen = set()
    deadline = clock() + budget * max(1, len(hosts))
    for asked, address in hosts:
        if clock() > deadline:
            snapshot["silent"].append({"host": _text(asked), "why": "there was no time left to ask it"})
            continue
        try:
            host, vms = parse_answer(run(asked), asked, address)
        except Unanswered as e:
            snapshot["silent"].append({"host": _text(asked), "why": _text(str(e), 200)})
            continue
        except Exception as e:
            # never the exception's own text: a library may put the credential in it
            snapshot["silent"].append({"host": _text(asked),
                                       "why": f"it did not answer ({type(e).__name__})"})
            continue
        if host["name"] in seen:
            continue
        seen.add(host["name"])
        snapshot["hosts"].append(host)
        snapshot["vms"].extend(vms)
    return snapshot


def checked(payload):
    """A snapshot as the server accepts it, or ValueError with a sentence."""
    if payload.get("mode") not in MODES:
        raise ValueError(f"'mode' must be one of: {', '.join(MODES)}")
    out = {"mode": payload["mode"], "hosts": [], "vms": [], "silent": []}
    for key, limit in (("hosts", MAX_HOSTS), ("vms", MAX_VMS), ("silent", MAX_HOSTS)):
        value = payload.get(key, [])
        if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
            raise ValueError(f"{key!r} must be a list of objects")
        if len(value) > limit:
            raise ValueError(f"{key!r} holds more than {limit} entries")
    for raw in payload.get("hosts", []):
        name = _text(raw.get("name")).lower()
        if not name:
            raise ValueError("every host needs a 'name'")
        out["hosts"].append({"name": name, "label": _text(raw.get("label")) or name,
                             "asked": _text(raw.get("asked")), "address": _text(raw.get("address"), 64),
                             "cores": _number(raw.get("cores")), "memory": _number(raw.get("memory"))})
    for raw in payload.get("vms", []):
        vm = _vm(raw, _text(raw.get("host")).lower())
        if vm is None:
            raise ValueError("every vm needs an 'id'")
        out["vms"].append(vm)
    for raw in payload.get("silent", []):
        out["silent"].append({"host": _text(raw.get("host")), "why": _text(raw.get("why"), 200)})
    if not out["hosts"]:
        raise ValueError("empty snapshot: no host answered")
    return out
