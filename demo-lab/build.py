r"""build.py — generate the demo lab: seed dataset, static health and base render.

The public Atlas ships with this lab, and the public test suite runs against
it. Everything is invented: a believable small homelab (a router, a switch, a
hypervisor and its guests, a NAS, an edge proxy, monitoring, a media box and a
GPU box). No address, host name, person or franchise from anywhere real.

  addresses  10.77.<vlan>.0/24 (private range, used by no real network here)
  domain     home.example (RFC 2606)
  place ids  role names (`hypervisor`, `nas`, `app-host` …), so the map reads
             the same in any language and the tests can name them

Deterministic; rerun after editing:

    python demo-lab/build.py        # writes demo-lab/seed/
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
DOMAIN = "home.example"
ADMIN_GROUP = "atlas-admins"


def net(vlan, host):
    return f"10.77.{vlan}.{host}"


# ── zones (VLANs) ─────────────────────────────────────────────────────────────
ZONES = [
    {"id": "sky", "name": "Servers", "vlan": 33, "subnet": "10.77.33.0/24",
     "hue": "#7FB0C4", "net_hue": "#7FB0C4", "label_x": 50.0, "label_y": 18.0,
     "lore": "The hypervisor, the NAS and the guests that run the house. Nothing here faces the internet."},
    {"id": "workstation-vlan", "name": "Clients", "vlan": 10, "subnet": "10.77.10.0/24",
     "hue": "#8FB573", "net_hue": "#8FB573", "label_x": 18.0, "label_y": 40.0, "hide_label": True,
     "lore": "Laptops, phones and the desk machines. Trusted to reach services, never to serve them."},
    {"id": "monitor-vlan", "name": "Watch", "vlan": 30, "subnet": "10.77.30.0/24",
     "hue": "#C9A554", "net_hue": "#C9A554", "label_x": 78.0, "label_y": 36.0, "hide_label": True,
     "lore": "Monitoring lives on its own network so it can still see when everything else is down."},
    {"id": "depths", "name": "Management", "vlan": 1, "subnet": "10.77.1.0/24",
     "hue": "#B8C4D6", "net_hue": "#B8C4D6", "label_x": 50.0, "label_y": 88.0, "hide_label": True,
     "lore": "Switch and router management. Reachable only from the admin workstation."},
    {"id": "lookout", "name": "IoT", "vlan": 66, "subnet": "10.77.66.0/24",
     "hue": "#C06B62", "net_hue": "#C06B62", "label_x": 86.0, "label_y": 70.0, "hide_label": True,
     "lore": "Cameras, plugs and sensors. Allowed out to their clouds, never in to anything else."},
    {"id": "dmz", "name": "DMZ", "vlan": 90, "subnet": "10.77.90.0/24",
     "hue": "#C0714E", "net_hue": "#C0714E", "label_x": 24.0, "label_y": 74.0, "hide_label": True,
     "lore": "The only machines the internet can knock on: the edge proxy and what it fronts."},
]


def link(label, url, desc, hue="#8ec07c", kuma=None, path=None, container=None,
         require_group=None, connects=None):
    out = {"label": label, "url": url, "desc": desc, "hue": hue}
    if kuma:
        out["kuma"] = kuma
    if path:
        out["path"] = path
    if container:
        out["container"] = container
    if require_group:
        out["require_group"] = require_group
    if connects:
        out["connects"] = connects
    return out


def acct(name, source="local", sudo="none", groups=(), note=""):
    return {"name": name, "source": source, "sudo": sudo, "groups": list(groups), "note": note}


GUESTS = ["dc", "monitor", "downloads", "internal-host", "media", "edge", "app-host", "standby"]

# ── places ────────────────────────────────────────────────────────────────────
NODES = [
    {"id": "gateway", "name": "GATEWAY", "kind": "network", "zone": "sky", "shape": "diamond",
     "x": 50.0, "y": 52.0, "ip": net(1, 1),
     "role": "Router + firewall",
     "lore": "Every VLAN meets here, and every rule about who may talk to whom lives here.",
     "hw": "OPNsense 26.1 · N100 · 6× 2.5GbE",
     "links": [link("OPNsense", f"https://{net(1, 1)}",
                    "Interfaces, firewall rules, DHCP and the VPN.", kuma="Gateway")],
     "reaches": ["core-switch", "hypervisor", "nas", "edge", "the-wild"],
     "accounts": [acct("admin", sudo="nopasswd", groups=["wheel"], note="Console and web UI. The only admin."),
                  acct("backup-bot", source="service", note="Pulls the config nightly. Read-only API key.")]},
    {"id": "core-switch", "name": "CORE SWITCH", "kind": "network", "zone": "depths", "shape": "triangle",
     "x": 50.0, "y": 80.0, "ip": net(1, 2),
     "role": "Managed switch · 24 ports",
     "lore": "Carries every VLAN to every room. Its management page is the most boring and most important page in the house.",
     "hw": "24× 1GbE · 4× SFP+ · PoE",
     "links": [link("Switch UI", f"https://{net(1, 2)}", "Ports, VLAN membership and PoE budget.",
                    kuma="Core Switch", connects=["gateway", "hypervisor", "nas", "gpu-box", "workstation"])],
     "reaches": ["gateway"]},
    {"id": "hypervisor", "name": "HYPERVISOR", "kind": "physical", "zone": "sky", "spark": True,
     "x": 50.0, "y": 26.0, "ip": net(33, 5),
     "role": "Hypervisor · eight guests",
     "lore": "The one machine that runs the rest. Patch it last and reboot it carefully.",
     "hw": "Proxmox VE 9 · Ryzen 9 7950X · 128 GB · 2× 2 TB NVMe",
     "children": GUESTS,
     "links": [link("Proxmox", f"https://{net(33, 5)}:8006",
                    "Guests, storage, snapshots and the backup jobs.", kuma="Hypervisor")],
     "reaches": ["gateway", "nas"],
     "accounts": [acct("root", sudo="none", note="Console only; SSH disabled for root."),
                  acct("admin", source="domain", sudo="password", groups=["sudo"], note="Day-to-day admin."),
                  acct("ops-agent", source="agent", sudo="nopasswd", groups=["docker"],
                       note="Automation account. Command-restricted key.")]},
    {"id": "nas", "name": "NAS", "kind": "physical", "zone": "sky", "spark": True,
     "x": 66.0, "y": 20.0, "ip": net(33, 10),
     "role": "Storage · 48 TB",
     "lore": "Every byte the house cannot afford to lose, snapshotted hourly and copied off-site nightly.",
     "hw": "TrueNAS SCALE · 4× 12 TB RAIDZ1 · 64 GB ECC",
     "links": [link("TrueNAS", f"https://{net(33, 10)}", "Pools, shares and snapshots.", kuma="NAS")],
     "reaches": ["gateway", "the-wild"],
     "accounts": [acct("admin", sudo="password", groups=["builtin_administrators"], note="Web UI admin."),
                  acct("media", source="service", note="Read-only share for the media server.")]},
    {"id": "dc", "name": "DIRECTORY", "kind": "vm", "zone": "sky", "parent": "hypervisor",
     "x": 40.0, "y": 18.0, "ip": net(33, 11),
     "role": "Directory + DNS + internal CA",
     "lore": "Every account and every internal name starts here.",
     "hw": "Debian 13 · 2 vCPU · 4 GB · Samba AD + step-ca",
     "links": [link("Directory", f"https://id.{DOMAIN}", "Sign-in for every service in the house.",
                    kuma="Directory")],
     "reaches": ["gateway"]},
    {"id": "monitor", "name": "MONITOR", "kind": "vm", "zone": "monitor-vlan", "parent": "hypervisor", "spark": True,
     "x": 76.0, "y": 32.0, "ip": net(30, 10),
     "role": "Monitoring · metrics, logs, uptime",
     "lore": "Prometheus, Loki and Uptime Kuma. When something is down, this is how you know.",
     "hw": "Debian 13 · 4 vCPU · 8 GB · Docker",
     "links": [link("Uptime Kuma", f"http://{net(30, 10)}:3001", "Up/down for every service on this map.",
                    kuma="Uptime Kuma", container="uptime-kuma"),
               link("Prometheus", f"http://{net(30, 10)}:9090", "Metrics from every host, kept thirty days.",
                    container="prometheus", require_group=ADMIN_GROUP),
               link("Loki", f"http://{net(30, 10)}:3100", "Logs from every container.",
                    container="loki", require_group=ADMIN_GROUP)],
     "reaches": ["gateway", "hypervisor", "nas", "edge"],
     "accounts": [acct("admin", source="domain", sudo="password", groups=["sudo", "docker"]),
                  acct("ops-agent", source="agent", sudo="none", groups=["docker"], note="Reads metrics only.")]},
    {"id": "downloads", "name": "DOWNLOADS", "kind": "vm", "zone": "sky", "parent": "hypervisor",
     "x": 58.0, "y": 34.0, "ip": net(33, 21),
     "role": "Downloads + automation",
     "lore": "Fetches what the media library asks for, behind its own VPN tunnel.",
     "hw": "Debian 13 · 2 vCPU · 4 GB · Docker",
     "links": [link("Downloader", f"http://{net(33, 21)}:8080", "Queue and history.", kuma="Downloads",
                    container="downloader")],
     "reaches": ["gateway", "nas"]},
    {"id": "internal-host", "name": "INTERNAL HOST", "kind": "vm", "zone": "sky", "parent": "hypervisor", "spark": True,
     "x": 42.0, "y": 34.0, "ip": net(33, 30),
     "role": "Internal apps · wiki, git, dashboards",
     "lore": "The house's own tools: the wiki, the git server and this map.",
     "hw": "Debian 13 · 4 vCPU · 8 GB · Docker",
     "links": [link("Forgejo", f"https://git.{DOMAIN}", "Every repository, including this map's.",
                    kuma="Forgejo", container="forgejo"),
               link("Wiki", f"https://wiki.{DOMAIN}", "Runbooks: how each service is rebuilt.",
                    kuma="Wiki", container="wiki"),
               link("Atlas", f"https://atlas.{DOMAIN}", "This map.", container="atlas",
                    require_group=ADMIN_GROUP)],
     "reaches": ["gateway", "nas", "monitor"]},
    {"id": "media", "name": "MEDIA", "kind": "vm", "zone": "dmz", "parent": "hypervisor",
     "x": 30.0, "y": 66.0, "ip": net(90, 30),
     "role": "Media server",
     "lore": "Films and shows for the house, read from the NAS.",
     "hw": "Debian 13 · 4 vCPU · 8 GB · Jellyfin",
     "links": [link("Jellyfin", f"https://media.{DOMAIN}", "The library.", kuma="Jellyfin",
                    container="jellyfin", path=["edge", "gateway", "the-wild"])],
     "reaches": ["gateway", "nas"]},
    {"id": "edge", "name": "EDGE", "kind": "vm", "zone": "dmz", "parent": "hypervisor", "spark": True,
     "x": 22.0, "y": 60.0, "ip": net(90, 10),
     "role": "Reverse proxy + intrusion detection",
     "lore": "The only door the internet may knock on. Caddy answers; CrowdSec watches.",
     "hw": "Debian 13 · 2 vCPU · 2 GB · Caddy + CrowdSec",
     "links": [link("CrowdSec", f"http://{net(90, 10)}:8080", "Bans and decisions at the edge.",
                    kuma="Edge", container="crowdsec", require_group=ADMIN_GROUP)],
     "reaches": ["gateway", "the-wild", "app-host", "media"],
     "accounts": [acct("admin", source="local", sudo="password", groups=["sudo"]),
                  acct("deploy", source="service", sudo="none", groups=["docker"], note="CI deploy key.")]},
    {"id": "app-host", "name": "APP HOST", "kind": "vm", "zone": "dmz", "parent": "hypervisor", "spark": True,
     "x": 34.0, "y": 56.0, "ip": net(90, 20),
     "role": "Public apps behind the edge",
     "lore": "Nextcloud and the family photo album, published through the edge.",
     "hw": "Debian 13 · 4 vCPU · 8 GB · Docker",
     "links": [link("Nextcloud", f"https://cloud.{DOMAIN}", "Files and calendars, from anywhere.",
                    kuma="Nextcloud", container="nextcloud", path=["edge", "gateway", "the-wild"]),
               link("Photos", f"https://photos.{DOMAIN}", "The family album.", kuma="Photos",
                    container="photos", path=["edge", "gateway", "the-wild"])],
     "reaches": ["gateway", "nas", "edge"]},
    {"id": "standby", "name": "STANDBY", "kind": "vm", "zone": "sky", "parent": "hypervisor",
     "x": 62.0, "y": 12.0, "ip": net(33, 40),
     "role": "Spare guest · powered off",
     "lore": "A clean guest kept ready for experiments. Off unless someone is trying something.",
     "hw": "Debian 13 · 2 vCPU · 4 GB",
     "links": []},
    {"id": "gpu-box", "name": "GPU BOX", "kind": "physical", "zone": "workstation-vlan",
     "x": 16.0, "y": 32.0, "ip": net(10, 40),
     "role": "Local AI models",
     "lore": "One graphics card, several language models, and the house's power bill.",
     "hw": "Ryzen 7 · RTX 4070 · 64 GB · Ollama",
     "links": [link("Ollama", f"http://{net(10, 40)}:11434", "Local models for the apps that ask.",
                    kuma="GPU Box")],
     "reaches": ["gateway"]},
    {"id": "workstation", "name": "WORKSTATION", "kind": "physical", "zone": "workstation-vlan",
     "x": 22.0, "y": 42.0, "ip": net(10, 21),
     "role": "Admin workstation",
     "lore": "Where the map is edited from. The only client allowed onto the management VLAN.",
     "hw": "Windows 11 · Ryzen 7 · 32 GB",
     "links": [],
     "reaches": ["gateway", "core-switch"]},
    {"id": "camera-hub", "name": "CAMERA HUB", "kind": "physical", "zone": "lookout",
     "x": 84.0, "y": 64.0, "ip": net(66, 5),
     "role": "Home automation + cameras",
     "lore": "Every sensor, camera and switch in the house, walled off from everything else.",
     "hw": "Raspberry Pi 5 · 8 GB · Home Assistant OS",
     "links": [link("Home Assistant", f"http://{net(66, 5)}:8123", "Sensors, cameras and automations.",
                    kuma="Home Assistant")],
     "reaches": ["gateway"]},
    {"id": "offsite", "name": "OFF-SITE", "kind": "network", "zone": "sky", "off_map": True,
     "x": 92.0, "y": 8.0, "ip": "—",
     "role": "Off-site backup",
     "lore": "Encrypted copies of the NAS, nightly, far away.",
     "hw": "Object storage · restic",
     "links": []},
    {"id": "nas-2", "name": "SECOND NAS", "kind": "physical", "zone": "sky", "planned": True,
     "x": 74.0, "y": 14.0, "ip": net(33, 12),
     "role": "Planned · replication target",
     "lore": "Not bought yet. Will hold a second copy of everything on the NAS.",
     "hw": "planned",
     "links": []},
    {"id": "the-wild", "name": "THE INTERNET", "kind": "network", "zone": "dmz", "hue": "#C0714E",
     "x": 10.0, "y": 84.0, "ip": "—",
     "role": "The internet",
     "lore": "Everything beyond the gateway.",
     "hw": "ISP fibre · 1 Gb symmetric",
     "links": []},
]

ROUTES = [
    {"from": "gateway", "to": "core-switch", "kind": "vlan"},
    {"from": "core-switch", "to": "hypervisor", "kind": "vlan"},
    {"from": "core-switch", "to": "nas", "kind": "vlan"},
    {"from": "core-switch", "to": "gpu-box", "kind": "vlan"},
    {"from": "core-switch", "to": "workstation", "kind": "vlan"},
    {"from": "gateway", "to": "camera-hub", "kind": "vlan"},
    {"from": "gateway", "to": "monitor", "kind": "vlan"},
    {"from": "gateway", "to": "edge", "kind": "vlan"},
    {"from": "gateway", "to": "dc", "kind": "vlan"},
    {"from": "gateway", "to": "internal-host", "kind": "vlan"},
    {"from": "gateway", "to": "downloads", "kind": "vlan"},
    {"from": "gateway", "to": "media", "kind": "vlan"},
    {"from": "gateway", "to": "app-host", "kind": "vlan"},
    {"from": "gateway", "to": "the-wild", "kind": "wan"},
    {"from": "nas", "to": "offsite", "kind": "wan"},
    {"from": "edge", "to": "app-host", "kind": "edge"},
    {"from": "edge", "to": "media", "kind": "edge"},
    {"from": "edge", "to": "gateway", "kind": "edge"},
    {"from": "monitor", "to": "hypervisor", "kind": "telemetry"},
    {"from": "monitor", "to": "nas", "kind": "telemetry"},
    {"from": "monitor", "to": "edge", "kind": "telemetry"},
    {"from": "monitor", "to": "app-host", "kind": "telemetry"},
    {"from": "workstation", "to": "edge", "kind": "mesh"},
    {"from": "workstation", "to": "monitor", "kind": "mesh"},
]

VMS = [
    {"id": "dc", "host": "hypervisor", "vcpu": 2, "ram_gb": 4, "demand_gb": 1.9, "state": "on"},
    {"id": "monitor", "host": "hypervisor", "vcpu": 4, "ram_gb": 8, "demand_gb": 5.1, "state": "on"},
    {"id": "downloads", "host": "hypervisor", "vcpu": 2, "ram_gb": 4, "demand_gb": 2.2, "state": "on"},
    {"id": "internal-host", "host": "hypervisor", "vcpu": 4, "ram_gb": 8, "demand_gb": 4.6, "state": "on"},
    {"id": "media", "host": "hypervisor", "vcpu": 4, "ram_gb": 8, "demand_gb": 3.8, "state": "on", "dynamic": "4–12"},
    {"id": "edge", "host": "hypervisor", "vcpu": 2, "ram_gb": 2, "demand_gb": 0.9, "state": "on"},
    {"id": "app-host", "host": "hypervisor", "vcpu": 4, "ram_gb": 8, "demand_gb": 5.4, "state": "on"},
    {"id": "standby", "host": "hypervisor", "vcpu": 2, "ram_gb": 4, "demand_gb": 0, "state": "off"},
]

RACKS = [
    {"id": "rack-a", "name": "Rack A", "location": "Home office"},
    {"id": "rack-b", "name": "Rack B", "location": "Home office"},
]
RACK = [
    {"u": "U12", "size": 1, "name": "Patch Panel", "node": "", "desc": "24-port keystone panel, every drop labelled."},
    {"u": "U11", "size": 1, "name": "Core Switch", "node": "core-switch", "desc": "24× 1GbE, 4× SFP+, PoE for the cameras."},
    {"u": "U9–10", "size": 2, "name": "Gateway", "node": "gateway", "desc": "Fanless router, six 2.5GbE ports."},
    {"u": "U5–8", "size": 4, "name": "Hypervisor", "node": "hypervisor", "desc": "4U tower on a shelf."},
    {"u": "U1–4", "size": 4, "name": "NAS", "node": "nas", "desc": "Four bays, one spare."},
    {"rack": "rack-b", "u": "U6", "size": 1, "name": "Patch Panel", "node": "", "desc": "12-port panel for the garage run."},
    {"rack": "rack-b", "u": "U4–5", "size": 2, "name": "GPU Box", "node": "gpu-box", "desc": "Two slots for whatever needs a graphics card."},
    {"rack": "rack-b", "u": "U3", "size": 1, "name": "Second NAS", "node": "nas-2", "desc": "The other copy of everything that matters."},
    {"rack": "rack-b", "u": "U1–2", "size": 2, "name": "Test Bench", "node": "", "desc": "Whatever is being tried this week."},
]
RACK_REAR = [
    {"name": "UPS", "node": "", "desc": "1500 VA, about 20 minutes for the rack."},
    {"name": "PDU", "desc": "Switched, eight outlets."},
    {"name": "Fibre ONT", "node": "gateway", "desc": "The ISP's box; the WAN side of the gateway."},
]

CHRONICLE = [
    {"title": "CPU by container", "chart": "containers.cpu", "solo": True, "url": f"https://grafana.{DOMAIN}/d/containers",
     "about": "Which container is busy right now."},
    {"title": "Memory by container", "chart": "containers.mem", "solo": True, "url": f"https://grafana.{DOMAIN}/d/containers",
     "about": "Resident memory per container."},
    {"title": "LLM calls", "chart": "llm.calls", "solo": True, "about": "Model calls that answered vs fell back."},
    {"title": "LLM calls per app", "chart": "llm.apps", "solo": True, "about": "Who is asking the models."},
    {"title": "Pending upgrades", "chart": "patch.pending", "solo": True, "url": f"https://grafana.{DOMAIN}/d/patch",
     "about": "Packages waiting on each host.", "note": "Patched Sundays."},
    {"title": "Uptime board", "url": f"http://{net(30, 10)}:3001/status/home", "note": "Uptime Kuma's status page."},
]

ABYSS = [
    {"title": "Active bans", "chart": "edge.bans", "solo": True, "url": f"https://grafana.{DOMAIN}/d/security",
     "about": "CrowdSec decisions in force, by origin."},
    {"title": "Detections", "chart": "edge.detections", "solo": True, "about": "Scenario overflows at the edge."},
    {"title": "Network traffic", "chart": "hosts.net", "solo": True, "about": "Bytes in and out, per host."},
    {"title": "Edge status codes", "chart": "edge.status", "solo": True, "about": "What the edge answered."},
    {"title": "Routers", "chart": "edge.routers", "solo": True, "about": "Requests per published service."},
    {"title": "Top clients", "chart": "edge.top_clients", "solo": True, "whois": True,
     "about": "Who asked the most, with a WHOIS lookup."},
    {"title": "Top probes", "chart": "edge.top_probes", "solo": True, "about": "The paths scanners try first."},
    {"title": "SSH accepted", "chart": "edge.ssh_granted", "solo": True, "about": "Successful SSH logins at the edge."},
    {"title": "SSH denied", "chart": "edge.ssh_denied", "solo": True, "about": "Refused SSH attempts."},
    {"title": "Scenarios", "chart": "edge.scenarios", "solo": True, "about": "Which detections fire most."},
    {"title": "Bans now", "chart": "edge.active_bans", "solo": True, "pane_group": "the edge count",
     "about": "One number: bans in force."},
    {"title": "Alerts", "chart": "edge.alerts", "solo": True, "pane_group": "the edge count",
     "about": "Alerts in the last day."},
    {"title": "Bouncer", "chart": "edge.bouncer", "solo": True, "pane_group": "the edge count",
     "about": "Requests the bouncer blocked."},
    {"title": "Lines parsed", "chart": "edge.parsed", "solo": True, "pane_group": "the edge count",
     "about": "Log lines CrowdSec read."},
    {"title": "Security report", "url": f"https://wiki.{DOMAIN}/security/weekly",
     "about": "The weekly security write-up.", "note": "Mondays."},
]

RITES = [
    {"name": "The Nightly Backup", "host": "HYPERVISOR", "when": "01:00", "cadence": "daily",
     "note": "Proxmox backs up every running guest to the NAS."},
    {"name": "The Off-site Copy", "host": "NAS", "when": "02:30", "cadence": "daily",
     "note": "restic sends the night's snapshot off-site, encrypted before it leaves."},
    {"name": "Hourly Snapshots", "host": "NAS", "when": "hourly :05", "cadence": "continuous",
     "note": "ZFS snapshots of every dataset, 48 hourly and 30 daily kept."},
    {"name": "The Patch Survey", "host": "all guests", "when": "Sun 04:15", "cadence": "weekly",
     "note": "apt on every guest, then a reboot if the kernel asks."},
    {"name": "SSH Cert Renewal", "host": "4 guests", "when": "Sun 03:00 UTC", "cadence": "weekly",
     "note": "Host certificates re-signed by the internal CA."},
    {"name": "Media Maintenance", "host": "MEDIA", "when": "daily 07:15", "cadence": "daily",
     "note": "Library scan and transcode clean-up."},
    {"name": "DNS Blocklist Update", "host": "DIRECTORY", "when": "03:30", "cadence": "daily",
     "note": "Refreshes the blocklists the DNS filter uses."},
    {"name": "Certificate Watch", "host": "MONITOR", "when": "06:00", "cadence": "daily",
     "note": "Warns when any certificate on the map is inside 21 days of expiry."},
    {"name": "The Weekly Report", "host": "MONITOR", "when": "Mon 13:00 UTC", "cadence": "weekly",
     "note": "Security and certificate summary, posted to the wiki.",
     "key": "the-weekly-report", "expect_every": "7d", "grace": "2d"},
    {"name": "Access Audit", "host": "all guests", "when": "Mon 13:30 UTC", "cadence": "weekly",
     "note": "Diffs accounts, keys and sudoers against each host's baseline."},
    {"name": "Pool Scrub", "host": "NAS", "when": "1st Sun 02:00", "cadence": "monthly",
     "note": "Reads every block and checks it against its checksum."},
    {"name": "The Morning Brief", "host": "INTERNAL HOST", "when": "13:00 UTC — 08:00 local", "cadence": "daily",
     "note": "A model summarises overnight alerts into one note.", "asks": "gpu-box", "model": "llama3.1:8b · 8k",
     "at": "13:00", "hold": 25},
    {"name": "The Hourly Triage", "host": "INTERNAL HOST", "when": "hourly at :35, 08:00–20:00 local",
     "cadence": "continuous", "note": "A model sorts new alerts by urgency.", "asks": "gpu-box",
     "model": "llama3.1:8b · 8k", "at": ":35", "between": "13:00–01:00", "hold": 5},
    {"name": "The Week in Review", "host": "INTERNAL HOST", "when": "Sun 22:00 UTC", "cadence": "weekly",
     "note": "A model writes the week's changes into the wiki.", "asks": "gpu-box", "model": "qwen3:14b · 32k",
     "at": "22:00", "days": "Sun", "hold": 15},
    {"name": "Config Commit", "host": "GATEWAY", "when": "on every save", "cadence": "continuous",
     "note": "The router's config is committed to git whenever it changes."},
    {"name": "Old Experiment", "host": "STANDBY", "when": "—", "cadence": "parked",
     "note": "A cron job kept for reference; nothing runs."},
]

CERTS = [
    {"name": f"*.{DOMAIN}", "kind": "tls", "issuer": "Let's Encrypt", "host": "EDGE",
     "expires": "2026-12-01", "renews": "Caddy, DNS-01", "note": "Every public name at the edge."},
    {"name": "Home Root CA", "kind": "ca", "issuer": "step-ca on DIRECTORY", "host": "DIRECTORY",
     "expires": "2036-09-24", "renews": "manual, ten years", "note": "Signs every internal certificate."},
    {"name": f"id.{DOMAIN}", "kind": "tls", "issuer": "Home Root CA", "host": "DIRECTORY",
     "expires": "2027-01-15", "renews": "step-ca ACME, 60 days", "note": "The sign-in page."},
    {"name": f"git.{DOMAIN}", "kind": "tls", "issuer": "Home Root CA", "host": "INTERNAL HOST",
     "expires": "2026-11-20", "renews": "step-ca ACME, 60 days", "note": "Forgejo."},
    {"name": "hypervisor host key", "kind": "ssh-host", "issuer": "Home Root CA", "host": "HYPERVISOR",
     "expires": "2026-10-28", "renews": "weekly rite", "note": "Host certificate for SSH."},
    {"name": "edge host key", "kind": "ssh-host", "issuer": "Home Root CA", "host": "EDGE",
     "expires": "2026-10-28", "renews": "weekly rite", "note": "Host certificate for SSH."},
]

# REGIONS: the server zone opens into a detailed map of its
# own. Its render is a TRUE enlargement of this map (render_region), so places
# map straight through the rectangle and no pins are needed.
REGIONS = [
    {"id": "server-room", "name": "Server room", "map": "demo-lab-server-room.webp",
     "x": 34.0, "y": 6.0, "w": 46.0, "h": 34.0, "auto": True},
]

# ── tripwires: one honeypot and two canary tokens, all invented ───────────────
# The scene needs something to show: an OpenCanary-style fake file server (its
# `sensor` is OpenCanary's default device.node_id), a decoy document and a
# cloud key that expires. The static feed below has the honeypot speaking, so
# the bundled demo shows one live trip with no network call. Tripwires are
# admin-only on the map, like everywhere else.
STONES = [
    {"id": "canary-fileserver", "name": "FILESRV-OLD", "kind": "honeypot-host", "family": "honeypot",
     "host": "hypervisor", "zone": "internal", "severity": "critical", "sensor": "opencanary-1",
     "placement": "a small guest on the hypervisor, answering SMB and SSH",
     "mimics": "a file server nobody got round to retiring",
     "note": "discovery: the first thing a scan of the server network finds"},
    {"id": "payroll-doc", "name": "salaries-2026.docx", "kind": "doc-msword", "family": "token",
     "host": "nas", "zone": "internal", "severity": "high",
     "planted": "the shared documents folder on the NAS",
     "mimics": "a spreadsheet everyone would open",
     "note": "collection: someone browsing the share"},
    {"id": "offsite-backup-key", "name": "backup.env", "kind": "cloud-key", "family": "token",
     "host": "app-host", "zone": "internal", "severity": "critical",
     "planted": "an old backup config on the app host", "expires": "2027-04-01",
     "mimics": "the key an off-site backup would use",
     "note": "credential access: a key that unlocks nothing"},
]

KUMA = {"Gateway": "gateway", "Core Switch": "core-switch", "Hypervisor": "hypervisor", "NAS": "nas",
        "Directory": "dc", "Uptime Kuma": "monitor", "Downloads": "downloads", "Forgejo": "internal-host",
        "Jellyfin": "media", "Edge": "edge", "Nextcloud": "app-host", "Home Assistant": "camera-hub"}


def dataset():
    return {
        "meta": {"title": "The Archipelago Atlas", "surveyed": "2026-10-18",
                 "art": "demo-lab render (build.py), label-free",
                 "map_image": "demo-lab.webp",
                 "tribute": {"total_gb": 128, "host_reserve_gb": 8, "cpu_cores": 16, "cpu_threads": 32}},
        "zones": ZONES, "nodes": NODES, "routes": ROUTES, "racks": RACKS, "rack": RACK, "vms": VMS,
        "signals": {"kuma": KUMA, "drift_ignore": ["offsite", "nas-2"]},
        "rack_rear": RACK_REAR, "chronicle": CHRONICLE, "abyss": ABYSS,
        "rites": RITES, "certs": CERTS,
        "regions": REGIONS,
        "stones": STONES,
    }


def signals():
    nodes = {n["id"]: {"state": "healthy", "uptime_30d": 99.9}
             for n in NODES if n["ip"] != "—" and not n.get("planned")}
    nodes["downloads"] = {"state": "degraded", "uptime_30d": 98.4}   # a believable board
    nodes["standby"] = {"state": "down", "uptime_30d": 12.0}
    nodes["the-wild"] = {"state": "healthy"}
    services = {l["kuma"]: {"state": "healthy"} for n in NODES for l in n["links"] if l.get("kuma")}
    services["Downloads"] = {"state": "degraded"}
    stones = {"canary-fileserver": {"state": "speaking", "last_spoke": "2026-10-18T03:12:00Z"}}
    return {"_comment": "Static health for the demo lab. Invented; no network calls.",
            "nodes": nodes, "services": services, "stones": stones,
            "metrics": {"watchfires_up": len(services) - 1, "watchfires_total": len(services)}}


def _hex(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def zone_masks(size):
    """Each zone as a raised plateau: a smooth island around where its places
    stand (0..1 per pixel), keyed by zone id."""
    import numpy as np

    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / size * 100.0
    masks = {}
    for z in ZONES:
        pts = [(n["x"], n["y"]) for n in NODES if n["zone"] == z["id"] and not n.get("off_map")]
        if not pts:
            continue
        field = np.zeros((size, size), dtype=np.float32)
        for (px, py) in pts:
            field += np.exp(-(((xx - px) ** 2) + ((yy - py) ** 2)) / (2 * 5.5 ** 2))
        t = np.clip((field - 0.30) / 0.22, 0.0, 1.0)
        masks[z["id"]] = t * t * (3 - 2 * t)                     # smoothstep
    return masks


def render_base(size=2048):
    """A label-free sand table in the design notes's range (warm sand under one pool
    of light, dark enough for the pale labels): raked rings in the sand, each zone
    a raised plateau rimmed in its own hue, the routes pressed in as grooves,
    and the edges falling away to the page's abyss. The Atlas draws every
    name; nothing here is text."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    rng = np.random.default_rng(20261018)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / (size - 1)
    coarse = Image.fromarray((rng.random((48, 48)) * 255).astype(np.uint8), "L")
    coarse = np.asarray(coarse.resize((size, size), Image.BICUBIC), dtype=np.float32) / 255.0
    grain = rng.random((size, size)).astype(np.float32)

    def blur(a, radius):
        return np.asarray(Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8), "L")
                          .filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255.0

    masks = zone_masks(size)
    land = np.zeros((size, size), dtype=np.float32)
    for m in masks.values():
        land = np.maximum(land, m)

    # the ground: dark sand under one pool of light. Raked in rings around the
    # table, and in ripples that follow each plateau out into the sand, the way
    # a rake flows around stones (contours of the blurred plateaus)
    sand = np.array([100, 80, 58], dtype=np.float32)
    light = np.exp(-(((x - 0.44) ** 2) + ((y - 0.42) ** 2)) / (2 * 0.32 ** 2))
    r = np.sqrt((x - 0.5) ** 2 + (y - 0.48) ** 2) + 0.004 * (coarse - 0.5)
    rings = np.sin(r * 2 * np.pi * 60)
    near = blur(land, size * 0.035)
    ripple = np.sin(np.sqrt(np.clip(near, 0, 1)) * 2 * np.pi * 9)
    reach = np.clip(near * 3.0, 0.0, 1.0)                      # ripples near the plateaus, rings beyond
    rake = rings * (1 - reach) + ripple * reach
    tone = 0.50 + 0.45 * light + 0.06 * rake + 0.04 * (coarse - 0.5) + 0.03 * (grain - 0.5)
    img = sand[None, None, :] * tone[..., None]

    # the plateaus: a cast shadow, a compacted top a little lighter than the
    # sand (dark enough that the Atlas's pale labels still read on it), a bevel
    # lit from the upper left, and a thin rim in the zone's hue
    off = int(size * 0.007)
    cast = np.zeros_like(land)
    cast[off:, off:] = land[:-off, :-off]
    img = img * (1 - 0.50 * blur(cast, size * 0.005)[..., None])
    soft = blur(land, size * 0.004)
    gy, gx = np.gradient(soft)
    bevel = np.clip((-gx - gy) * size * 0.012, -1.0, 1.0)     # + facing the light, - away
    top = np.array([128, 104, 76], dtype=np.float32)
    for z in ZONES:
        m = masks.get(z["id"])
        if m is None:
            continue
        hue = np.array(_hex(z["hue"]), dtype=np.float32)
        fill = (top * 0.86 + hue * 0.14)[None, None, :] * (0.70 + 0.36 * light[..., None]
                                                           + 0.05 * (grain[..., None] - 0.5))
        img = img * (1 - m[..., None]) + fill * m[..., None]
        rim = np.clip(1.0 - np.abs(m - 0.5) * 6.0, 0.0, 1.0)
        img = img * (1 - 0.55 * rim[..., None]) + (hue * 0.80)[None, None, :] * (0.55 * rim[..., None])
    img = img * (1 + 0.28 * bevel[..., None])

    # the roads between zones, pressed into the sand: one shallow bowed groove
    # per pair of zones, stopping at the plateaus (the Atlas draws the real
    # routes itself; these only say which grounds are joined)
    pos = {n["id"]: (n["x"] / 100 * size, n["y"] / 100 * size) for n in NODES if not n.get("off_map")}
    zone_of = {n["id"]: n["zone"] for n in NODES}
    grooves = Image.new("L", (size, size), 0)
    lips = Image.new("L", (size, size), 0)
    gd, ld = ImageDraw.Draw(grooves), ImageDraw.Draw(lips)
    joined = set()
    for i, rt in enumerate(ROUTES):
        if rt["kind"] not in ("vlan", "edge", "wan") or rt["from"] not in pos or rt["to"] not in pos:
            continue
        pair = frozenset((zone_of[rt["from"]], zone_of[rt["to"]]))
        if len(pair) < 2 or pair in joined:
            continue
        joined.add(pair)
        (x0, y0), (x1, y1) = pos[rt["from"]], pos[rt["to"]]
        bow = 0.10 if i % 2 else -0.10                             # alternate sides, deterministic
        cx, cy = (x0 + x1) / 2 - (y1 - y0) * bow, (y0 + y1) / 2 + (x1 - x0) * bow
        pts = [((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1,
                (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1) for t in np.linspace(0, 1, 64)]
        gd.line(pts, fill=255, width=int(size * 0.0032), joint="curve")
        ld.line([(px - 2, py - 3) for px, py in pts], fill=255, width=int(size * 0.0010), joint="curve")
    sand_only = (1 - soft)[..., None]
    g = np.asarray(grooves.filter(ImageFilter.GaussianBlur(2.0)), dtype=np.float32)[..., None] / 255.0 * sand_only
    lp = np.asarray(lips.filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32)[..., None] / 255.0 * sand_only
    img = img * (1 - 0.40 * g) + np.array([214, 188, 140], dtype=np.float32) * 0.16 * lp * (1 - g)

    # the edges fall away to the page (--abyss #0D0B07)
    d = np.sqrt((x - 0.5) ** 2 + (y - 0.5) ** 2)
    vig = np.clip((d - 0.30) / 0.42, 0.0, 1.0)[..., None]
    img = img * (1 - 0.85 * vig) + np.array([13, 11, 7], dtype=np.float32) * 0.85 * vig
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def draw_map(path, size=2048):
    render_base(size).save(path, "WEBP", quality=72, method=6)


def render_region(region, path, width=2048):
    """A region's detailed map, drawn as a floor plan: the walls of the room,
    raised-floor tiles, a rack under each physical place and a smaller unit
    under each guest, joined to an overhead cable tray. Label-free (the Atlas
    draws the names) and a TRUE enlargement of the main render's rectangle,
    so every place lands on its own rack with no pins."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    size = 2048
    base = render_base(size)
    box = tuple(int(round(v / 100 * size)) for v in (
        region["x"], region["y"], region["x"] + region["w"], region["y"] + region["h"]))
    crop = base.crop(box)
    height = int(round(width * crop.height / crop.width))
    paper = crop.resize((width, height), Image.LANCZOS).filter(ImageFilter.GaussianBlur(3))
    # settle the sand toward a dark drafting board so the plan reads first
    # (it sits inside the dark main map; the plan is drawn in light ink)
    board = (40, 33, 25)
    sheet = Image.new("RGB", (width, height), board)
    img = Image.blend(paper, sheet, 0.55)
    draw = ImageDraw.Draw(img, "RGBA")
    ink = (206, 188, 150)

    # raised floor: 600 mm tiles, every fourth line a little heavier
    for i, x in enumerate(range(0, width, 96)):
        draw.line([(x, 0), (x, height)], fill=ink + ((26,) if i % 4 else (48,)), width=1)
    for i, y in enumerate(range(0, height, 96)):
        draw.line([(0, y), (width, y)], fill=ink + ((26,) if i % 4 else (48,)), width=1)

    # the room
    m = 70
    draw.rounded_rectangle([m, m, width - m, height - m], radius=18, outline=ink + (230,), width=12)
    door = (width // 2 - 90, height - m - 6, width // 2 + 90, height - m + 6)
    draw.rectangle(door, fill=board + (255,))
    draw.arc([width // 2 - 90, height - m - 180, width // 2 + 90, height - m + 0], 0, 90, fill=ink + (160,), width=4)

    # where each place stands on this plan
    spots = []
    for n in NODES:
        px = (n["x"] - region["x"]) / region["w"]
        py = (n["y"] - region["y"]) / region["h"]
        if n.get("off_map") or not (0 <= px <= 1 and 0 <= py <= 1):
            continue
        spots.append((n, px * width, py * height))

    # overhead cable tray along the room, with a drop to every unit
    tray_y = m + 120
    draw.line([(m + 40, tray_y), (width - m - 40, tray_y)], fill=ink + (120,), width=16)
    draw.line([(m + 40, tray_y), (width - m - 40, tray_y)], fill=board + (220,), width=8)
    for _, cx, cy in spots:
        for yy in range(int(tray_y), int(cy) - 60, 26):
            draw.line([(cx, yy), (cx, yy + 13)], fill=ink + (110,), width=3)

    # the racks (physical) and smaller units (guests), centred on the place
    for n, cx, cy in spots:
        w, h = (150, 230) if n["kind"] == "physical" else (96, 120)
        x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        draw.rounded_rectangle([x0 + 8, y0 + 10, x1 + 8, y1 + 10], radius=8, fill=(0, 0, 0, 90))   # shadow
        draw.rounded_rectangle([x0, y0, x1, y1], radius=8, fill=(24, 20, 15, 240), outline=ink + (230,), width=4)
        for yy in np.arange(y0 + 18, y1 - 12, 22 if n["kind"] == "physical" else 26):
            draw.line([(x0 + 14, yy), (x1 - 14, yy)], fill=ink + (110,), width=3)
    img.save(path, "WEBP", quality=78, method=6)


def main():
    os.makedirs(os.path.join(SEED, "maps"), exist_ok=True)
    with open(os.path.join(SEED, "lab-data.demo.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(dataset(), f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(os.path.join(SEED, "signals.demo.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(signals(), f, ensure_ascii=False, indent=2)
        f.write("\n")
    draw_map(os.path.join(SEED, "maps", "demo-lab.webp"))
    for r in REGIONS:
        render_region(r, os.path.join(SEED, "maps", r["map"]))
    print("wrote demo-lab/seed/")


if __name__ == "__main__":
    main()
