import ipaddress
import math
import re
from datetime import date, datetime



def f(name, type="text", label=None, required=False, help="", **kw):
    fld = {
        "name": name,
        "type": type,
        "label": label if label is not None else name.replace("_", " ").title(),
        "required": required,
    }
    if help:
        fld["help"] = help
    fld.update(kw)
    return fld


def section(key, singular, plural, fields, id_field="id", title_field="name",
            kind="list", lore="", subtitle="", noun=None, store="dataset"):
    return {
        "key": key,
        "kind": kind,
        "singular": singular,
        "plural": plural,
        "noun": noun or singular,
        "store": store,
        "id_field": id_field if kind == "list" else None,
        "title_field": title_field,
        "fields": fields,
        "lore": lore,
        "subtitle": subtitle,
    }


NODE_KINDS = ["physical", "vm", "network", "unknown"]
NODE_SHAPES = ["", "diamond", "triangle"]
ROUTE_KINDS = ["wan", "edge", "vlan", "mesh", "telemetry"]
CABLE_KINDS = ["copper", "fibre", "dac", "wireless", "virtual"]
CABLE_STATES = ["confirmed", "assumed"]
STUB_KINDS = ["internet", "switch", "patch", "outlet", "other"]
VLAN_MIN, VLAN_MAX = 1, 4094
VM_STATES = ["on", "off"]
RITE_CADENCES = ["continuous", "daily", "weekly", "monthly", "parked"]
CERT_KINDS = ["tls", "ssh-host", "ca"]
IFACE_KINDS = ["rj45", "sfp", "sfp+", "console", "power", "virtual"]
RACK_KINDS = ["auto", "compute", "forge", "gateway", "switch", "storage",
              "power", "enclosure", "patch"]
REAR_SIDES = ["rear", "inside"]
PREFIX_ROLES = ["prefix", "container", "reserved"]
RANGE_KINDS = ["dhcp", "reserved"]
NAME_EXPOSURES = ["", "public", "internal", "vpn"]
OPEN_IN = ["auto", "here", "tab"]
LINK_KINDS = ["", "service", "container"]
CHECK_TYPES = ["", "http", "tcp", "dns", "keyword", "json", "off"]
MAINTENANCE_REPEATS = ("none", "daily", "weekly", "monthly")
PERCENT_MIN, PERCENT_MAX = -40, 140

STONE_KINDS = ["windows-folder", "network-folder", "web-bug", "dns",
               "doc-msword", "doc-excel", "doc-pdf", "aws-keys", "ad-account",
               "sensitive-command", "kubeconfig", "other",
               "cloud-key", "db-row",
               "honeypot-host", "honeypot-ssh", "honeypot-smb", "honeypot-http",
               "honeypot-rdp", "honeypot-ftp", "honeypot-telnet", "honeypot-db"]
STONE_FAMILIES = ["honeypot", "token"]


def stone_family(stone):
    stone = stone if isinstance(stone, dict) else {}
    fam = stone.get("family")
    if fam in STONE_FAMILIES:
        return fam
    return "honeypot" if str(stone.get("kind") or "").startswith("honeypot") else "token"
STONE_ZONES = ["internal", "wan"]
STONE_SEVERITIES = ["info", "low", "medium", "high", "critical"]

def _check_fields(on_place):
    whose = "this place" if on_place else "this service"
    return [
        f("check", "select", options=CHECK_TYPES, default="", label="Check",
          help=("How Atlas asks " + whose + " itself. Blank: "
                + ("no check of its own; it takes the worst of its services."
                   if on_place else "a GET of its address (below 500 is up).")
                + " http = a GET judged by its status · tcp = a port answers · "
                  "dns = a name resolves · keyword = the page holds some text · "
                  "json = a JSON answer holds a value · off = never asked. "
                  "Kuma's own monitor, where one is named, wins.")),
        f("check_host", "text", label="Check address",
          help=("What it asks: an address or a name (tcp, dns), or a full http(s) "
                "address (http, keyword, json). Blank: "
                + ("this place's IP." if on_place else "the service's own address, else its place's IP."))),
        f("check_port", "int", label="Check port", min=1, max=65535,
          help="The port a tcp check opens. Blank: the address's own port."),
        f("check_expect", "text", label="Check expects",
          help="keyword: the text that must be on the page · json: `path=value`, e.g. "
               "`status.healthy=true` · dns: an address the name must resolve to · "
               "http: the statuses that count as up, e.g. `200-299,401` (blank: below 500)."),
        f("check_every", "int", label="Check every (s)", min=20, max=3600,
          help="Seconds between checks. Blank: 60."),
        f("check_retries", "int", label="Check retries", min=0, max=5,
          help="How many times a failing answer is asked again, 20 s apart, before "
               "the state changes. Blank: 1."),
        f("check_timeout", "number", label="Check timeout (s)", min=1, max=10,
          help="How long one answer may take. Blank: 3."),
    ]


FAVOURITES = ["", "internal", "external"]

LINK_FIELDS = [
    f("label", "text", required=True, help="The service name, as shown on the card."),
    f("url", "url", help="Where the service answers. http:// or https://. A service with "
                         "nothing to open (a database's port, a name server) may leave it "
                         "blank when its check is tcp or dns."),
    f("desc", "longtext", label="Description",
      help="What this service is *for*, in a sentence or two. Shown on its own "
           "pane when you open it from a place's card. Leave it blank and the "
           "pane falls back to stating where it runs — which the epigraph "
           "already said."),
    f("hue", "color", help="A colour for this service's dot. Defaults to the realm's."),
    f("kuma", "text", label="Kuma monitor",
      help="The exact Uptime-Kuma monitor NAME that watches this service. "
           "Omit it and the service simply shows no health dot."),
    f("container", "text",
      help="Docker container name, if cAdvisor scrapes it — powers 'view its metrics'."),
    f("kind", "select", options=LINK_KINDS, default="",
      help="What it is in NODES: a container (Docker) or another service. Blank: a "
           "container when it names one above, else a service. Neither is a place."),
    *_check_fields(False),
    f("connects", "strings", label="Reaches", ref="nodes",
      help="Places this one service talks to. Narrows the reach web in TOPOLOGY."),
    f("path", "strings", label="Route out", ref="nodes",
      help="The hops its traffic actually takes, IN ORDER, starting from this "
           "place — e.g. `router, proxy, internet` for "
           "something reached from the internet. Drawn as a chain instead of a "
           "star, so the map can say *through*. Every consecutive pair must be a "
           "charted route, or the map is drawing a route that isn't there."),
    f("open_in", "select", options=OPEN_IN, default="auto", label="Opens",
      help="`auto` asks the service whether it allows framing and shows it in "
           "THE VIEWING GLASS when it does. `here` insists. `tab` never frames "
           "it — for anything that only works with the whole window."),
    f("require_group", "text", label="Requires group",
      help="Hide this service from anyone whose Hub groups don't include it. "
           "Blank takes ATLAS_LINK_DEFAULT_GROUP where that is set; * shows it "
           "to everyone."),
    f("favourite", "select", options=FAVOURITES, default="", label="Favourite",
      help="Lists this service on OVERVIEW: `internal` for what is used inside "
           "the network, `external` for what is reached from outside. Blank: "
           "not listed. It needs a URL to be listed."),
    f("unmanaged", "bool", label="Unmanaged",
      help="Not ours to watch: this service takes no state and raises nothing."),
]

ACCOUNT_SOURCES = ["local", "domain", "service", "agent"]
ACCOUNT_SUDO = ["none", "password", "nopasswd"]

ACCOUNT_FIELDS = [
    f("name", "text", required=True, label="Account",
      help="The login exactly as it exists on the host — `admin`, `backup-bot`, "
           "`alice@corp.example`. Case matters where the directory says it does."),
    f("source", "select", options=ACCOUNT_SOURCES, default="local",
      help="`local` a real account in /etc/passwd · `domain` an AD identity "
           "the host accepts · `service` a daemon's own account, no human "
           "behind it · `agent` an automation identity (a bot or AI agent)."),
    f("sudo", "select", options=ACCOUNT_SUDO, default="none", label="Sudo",
      help="`none` cannot elevate · `password` can, and must type one · "
           "`nopasswd` elevates without being asked. The last one is the "
           "finding: it is the only kind of key that is also a skeleton key."),
    f("groups", "strings",
      help="The groups that actually grant something — docker, sudo, "
           "wheel. Not every group the account happens to be in."),
    f("note", "text",
      help="Why this account exists, or what is odd about it. Anything a "
           "reviewer should know about it belongs here."),
]

RANGE_FIELDS = [
    f("start", "ip", required=True),
    f("end", "ip", required=True),
    f("kind", "select", options=RANGE_KINDS, required=True, default="dhcp"),
    f("note", "text"),
]


SECTIONS = {

    "zones": section(
        "zones", "realm", "realms", noun="zone",
        lore="every realm of the map — a VLAN, a broadcast domain, a colour",
        subtitle="VLANs / network segments. Every place belongs to one.",
        fields=[
            f("id", "slug", required=True, help="Short unique key, e.g. `monitoring`."),
            f("name", "text", required=True, help="Display name, e.g. `Monitoring`."),
            f("vlan", "scalar", required=True, label="VLAN",
              help="VLAN id. Use `—` for a segment that isn't one."),
            f("subnet", "cidr", required=True,
              help="The realm's primary prefix, e.g. `10.0.20.0/24`. "
                   "Use `—` for a segment with no addressing."),
            f("hue", "color", required=True, help="The realm's colour, used everywhere."),
            f("net_hue", "color", label="Route colour",
              help="Optional separate colour for this realm's routes on the network layer."),
            f("lore", "longtext", required=True, help="The in-world line shown on its card."),
            f("label_x", "percent", label="Label X", required=True,
              help="Where the realm's name sits on the map, 0–100% across."),
            f("label_y", "percent", label="Label Y", required=True,
              help="…and 0–100% down."),
            f("hide_label", "bool", label="Hide the label",
              help="Keep the realm, drop its name from the map."),
            f("origin", "text", label="Imported from",
              help="The system and record this came from, set by a connection import, "
                   "e.g. `netbox:vlan:20`. A later review knows it by this."),
        ]),

    "regions": section(
        "regions", "region", "regions", noun="region",
        lore="the parts of the map that open into a map of their own",
        subtitle="Zoom into the rectangle and its detailed map takes over.",
        fields=[
            f("id", "slug", required=True, help="Short unique key, e.g. `server-room`."),
            f("name", "text", required=True,
              help="What the frame and the breadcrumb say, e.g. `Server room`."),
            f("map", "text", required=True, label="Detailed map",
              help="The render to draw for this region: a file name from the gallery "
                   "(upload it there first), e.g. `server-room.webp`."),
            f("parent", "ref", ref="regions", label="Inside",
              help="Blank = drawn on the main map. Otherwise the region whose map "
                   "this one sits on."),
            f("x", "percent", required=True, label="Left",
              help="The rectangle on the parent map: its left edge, 0–100% across."),
            f("y", "percent", required=True, label="Top",
              help="…its top edge, 0–100% down."),
            f("w", "percent", required=True, label="Width",
              help="…its width, in % of the parent map's width."),
            f("h", "percent", required=True, label="Height",
              help="…its height, in % of the parent map's height."),
            f("auto", "bool", label="Open by zooming", default=True,
              help="Zooming in until the rectangle fills the window opens it. "
                   "Off = only the frame's button opens it."),
            f("fold", "bool", label="Fold on the parent map",
              help="On the map this region sits on, draw only its places that have a route "
                   "to somewhere outside it. The rest are drawn once you open the region."),
            f("hidden", "bool", label="Hidden to start with",
              help="Not drawn until a viewer shows it (ATLAS, MAP EDITOR, Zoom maps): no "
                   "frame, no opening by zoom, and no folding. A viewer's own choice is "
                   "kept in their browser."),
            f("places", "json", label="Pinned places",
              help="`{\"place-id\": {\"x\": 40, \"y\": 62}}` — where a place sits on THIS "
                   "map. Leave blank when the detailed map is a true enlargement: places "
                   "are then mapped through the rectangle. Drag them in edit mode to pin."),
        ]),

    "nodes": section(
        "nodes", "place", "places", noun="node",
        lore="every place charted — hosts, appliances, vassals, the world beyond",
        subtitle="Hosts, VMs, network gear. The markers on the map.",
        fields=[
            f("id", "slug", required=True, help="Short unique key, e.g. `app-host`."),
            f("name", "text", required=True, help="Display name. Shown in UPPERCASE."),
            f("kind", "select", options=NODE_KINDS, required=True, default="physical",
              help="physical = iron · vm = a guest · network = gear or the world beyond · "
                   "unknown = found by a scan, not yet classified."),
            f("zone", "ref", ref="zones", required=True, label="Realm",
              help="Which realm it belongs to."),
            f("x", "percent", required=True, help="Map position, 0–100% across."),
            f("y", "percent", required=True,
              help="Map position, 0–100% down. Past 100 puts it in the void below."),
            f("role", "text", required=True,
              help="What it does, in a phrase. The part before `·` becomes its epigraph."),
            f("lore", "longtext", label="Notes", help="A line about it, shown on its card."),
            f("ip", "ip", label="IP",
              help="Its address, or `—` for none. A whole prefix is allowed for a "
                   "place that *is* a network (an overlay's 100.64.0.0/10)."),
            f("hw", "text", label="Hardware", help="The mono data line: OS · RAM · disks."),
            f("location", "text", label="Location",
              help="Where it physically stands, e.g. `Home office`, for a machine that is "
                   "not in a rack: a single-board computer, an access point, a desk "
                   "machine. What sits in a rack is where the rack is, whatever this "
                   "says. HARDWARE and RESOURCES list by location; blank is the map's "
                   "default one."),
            f("ram_gb", "number", label="Memory (GB)", min=0,
              help="How much memory the machine has. With the three fields below it is "
                   "what RESOURCES divides among the machine's guests, and what it "
                   "counts as compute when the machine runs none."),
            f("ram_reserve_gb", "number", label="Memory held back (GB)", min=0,
              help="Kept for the machine itself; free headroom is what is left after it."),
            f("cpu_cores", "number", label="Cores", min=0,
              help="Physical cores. Shown as the iron behind the thread count."),
            f("cpu_threads", "number", label="Threads", min=0,
              help="Logical processors: what a vCPU is assigned against, so this is "
                   "the denominator of the vCPU count."),
            f("mac", "text", label="MAC",
              help="Its hardware address, e.g. `02:00:5e:10:20:30`. A connection import "
                   "fills it in; a later review knows the place by it even after its "
                   "address changes."),
            f("hue", "color", help="Override the marker colour. Defaults to the realm's."),
            f("shape", "select", options=NODE_SHAPES,
              help="Marker shape. Blank = the default circle."),
            f("parent", "ref", ref="nodes",
              help="Its host, if this is a vassal. Draws it as a child in TOPOLOGY, "
                   "and means its alarms fold into the host's when the host goes dark."),
            f("depends_on", "strings", ref="nodes", label="Depends on",
              help="Places this one cannot work without. When one of them goes dark, "
                   "this place's alarm folds into theirs instead of adding to the noise. "
                   "Declare only real needs — a guessed dependency hides a real outage."),
            f("children", "strings", ref="nodes",
              help="The reverse of parent — rarely needed, kept for hand-edited maps."),
            f("reaches", "strings", ref="nodes",
              help="Places it can talk to. Lights the reachability web."),
            f("scroll", "path", help="Path to its documentation. Click-to-copy on the card."),
            f("spark", "bool", label="Show live vitals",
              help="Draw a CPU + RAM gauge on its card (needs node-exporter and LAN HTTP)."),
            f("planned", "bool", help="Charted but not yet built — drawn faint."),
            f("off_map", "bool", label="Off the map",
              help="Charted, but not drawn. Its services still list in THE INDEX; its marker and its routes are skipped. For a place that is decided but not yet laid."),
            f("require_group", "text", label="Requires group",
              help="Hide this place from anyone whose Hub groups don't include it."),
            f("unmanaged", "bool", label="Unmanaged",
              help="Not ours to watch: it stays on the map, greyed, takes no state from "
                   "any source and raises nothing. (Maintenance is 'expected down, for now'.)"),
            *_check_fields(True),
            f("links", "objects", of=LINK_FIELDS, label="Services",
              help="Everything hosted here. Each becomes a card button and an Index row."),
            f("monitors", "strings", label="Kuma monitors",
              help="The Uptime Kuma monitors that light this marker, by their exact name. "
                   "The worst of them wins. A connection review fills this in; "
                   "`signals.kuma` still works beside it."),
            f("accounts", "objects", of=ACCOUNT_FIELDS, label="Accounts",
              help="Who can get into this place, and how far in. Drawn in the "
                   "ACCOUNTS scene. Redacted for anyone not cleared to see "
                   "everything — chart the posture, never a credential."),
            f("origin", "text", label="Imported from",
              help="The system and record this came from, set by a connection import, "
                   "e.g. `proxmox:qemu/101`. A later review knows it by this."),
        ]),

    "routes": section(
        "routes", "route", "routes", noun="route",
        id_field=None, title_field=None,
        lore="the routes between places — what the network layer draws",
        subtitle="Network links. Drawn on the map's ◈ layer and in TOPOLOGY.",
        fields=[
            f("from", "ref", ref="nodes", required=True),
            f("to", "ref", ref="nodes", required=True),
            f("kind", "select", options=ROUTE_KINDS, default="vlan",
              help="wan = the world · edge = the way in · vlan = inside a realm · "
                   "mesh = an overlay · telemetry = a scrape path."),
        ]),

    "cables": section(
        "cables", "cable", "cables", noun="cable",
        title_field=None,
        lore="the cables between places, port to port, as they are laid",
        subtitle="Physical connections: which port is plugged into which. "
                 "Each end is a place or a stub.",
        fields=[
            f("id", "slug", required=True,
              help="Short unique key, e.g. `gw-to-switch`. How the cable is named in the change log."),
            f("a", "ref", ref="nodes", label="End A: place", follows=True,
              help="The place at one end. Leave blank when this end is a stub."),
            f("a_stub", "ref", ref="stubs", label="End A: stub", follows=True,
              help="The stub at this end, when it is not a place."),
            f("a_port", "text", label="End A: port",
              help="The port at this end, e.g. `8` or `eth0`. The name of one of the "
                   "place's ports when it has them; any name is allowed."),
            f("b", "ref", ref="nodes", label="End B: place", follows=True,
              help="The place at the other end. Leave blank when this end is a stub."),
            f("b_stub", "ref", ref="stubs", label="End B: stub", follows=True,
              help="The stub at this end, when it is not a place."),
            f("b_port", "text", label="End B: port",
              help="The port at this end."),
            f("kind", "select", options=CABLE_KINDS, default="copper",
              help="copper = an ordinary patch lead · fibre · dac = a direct-attach "
                   "copper cable · wireless = a radio link · virtual = inside one box."),
            f("vlan", "scalar", label="Untagged VLAN",
              help="The VLAN carried untagged, e.g. `10`. Blank for none."),
            f("tagged", "json", label="Tagged VLANs",
              help="The VLANs carried tagged, as a list, e.g. `[10, 20]`. Blank for "
                   "none. A cable with both is a trunk, drawn `U1 T10,20`."),
            f("poe_w", "number", label="PoE (W)", min=0,
              help="Watts of power over the cable, when it carries any."),
            f("speed", "text", help="e.g. `1G`, `2.5G`, `10G`."),
            f("state", "select", options=CABLE_STATES, default="confirmed",
              help="confirmed = someone has seen it · assumed = believed, not checked "
                   "(drawn dashed)."),
            f("source", "text", default="hand",
              help="Who says this cable is there: `hand` when a person charted it, "
                   "or the connection that reported it, e.g. `unifi`."),
            f("note", "text"),
        ]),

    "stubs": section(
        "stubs", "stub", "stubs", noun="stub",
        lore="what the cables reach that is not a place",
        subtitle="Gear on the wiring that is not charted as a place: the line in, a "
                 "wall jack, a desk switch. No marker, no row in NODES, never watched.",
        fields=[
            f("id", "slug", required=True, help="Short unique key, e.g. `isp-line`."),
            f("name", "text", required=True, help="What it is called, e.g. `Fibre line in`."),
            f("kind", "select", options=STUB_KINDS, default="other",
              help="internet = the provider's line · switch = a small switch nobody "
                   "watches · patch = a patch panel · outlet = a wall jack · other."),
            f("note", "text"),
        ]),

    "prefixes": section(
        "prefixes", "prefix", "prefixes", noun="prefix",
        title_field="cidr",
        lore="every ground surveyed — the realm's addressing, block by block",
        subtitle="IPAM. Prefixes of any length, with DHCP pools and reservations.",
        fields=[
            f("id", "slug", required=True, help="Short unique key, e.g. `admin-v4`."),
            f("cidr", "cidr", required=True, label="CIDR",
              help="Any prefix length, v4 or v6 — `10.0.20.0/24`, `10.0.0.0/8`, `fd00::/64`."),
            f("zone", "ref", ref="zones", label="Realm",
              help="The realm this prefix serves, if one."),
            f("name", "text", help="What it's for, e.g. `Admin VLAN`."),
            f("role", "select", options=PREFIX_ROLES, default="prefix",
              help="container = a supernet holding others · prefix = a real segment · "
                   "reserved = set aside, never assigned."),
            f("note", "text"),
            f("ranges", "objects", of=RANGE_FIELDS, label="Pools & reservations",
              help="DHCP pools and reserved ranges inside this prefix."),
        ]),

    "interfaces": section(
        "interfaces", "port", "ports", noun="interface",
        id_field=None, title_field="name",
        lore="every port on every vessel — the copper truth",
        subtitle="Physical and virtual ports. Draws the port map in ADDRESSES.",
        fields=[
            f("device", "ref", ref="nodes", required=True, help="Which place owns this port."),
            f("name", "text", required=True, help="Port name or number, e.g. `1` or `eth0`."),
            f("kind", "select", options=IFACE_KINDS, default="rj45"),
            f("vlan", "scalar", label="VLAN", help="The VLAN on this port; blank for a trunk."),
            f("poe", "bool", label="PoE"),
            f("speed", "text", help="e.g. `1G`, `2.5G`, `10G`."),
            f("peer", "text", help="What's on the other end, in words."),
            f("note", "text"),
        ]),

    "racks": section(
        "racks", "rack", "racks", noun="rack",
        lore="where the iron stands",
        subtitle="Each rack and where it stands. HARDWARE shows them as `Location — Name`.",
        fields=[
            f("id", "slug", required=True, help="Short unique key, e.g. `rack-a`."),
            f("name", "text", required=True, help="The rack's own name, e.g. `Rack A`."),
            f("location", "text",
              help="Where it stands, e.g. `Home office`. Everything in the rack is there. "
                   "Blank uses the map's default location."),
        ]),

    "rack": section(
        "rack", "vessel", "vessels", noun="rack slot",
        id_field=None, title_field="name",
        lore="the iron in its niches — the front elevation",
        subtitle="Rack slots, front of rack. HARDWARE draws these.",
        fields=[
            f("rack", "ref", ref="racks", label="Rack",
              help="Which rack it sits in. Blank means the first rack."),
            f("u", "text", label="U slot", required=True,
              help="`U7` for one unit, `U3–U4` for two. The Rearrange tool writes this too."),
            f("name", "text", required=True, help="What sits here."),
            f("size", "int", default=1, min=1, max=48, help="How many U it occupies."),
            f("node", "ref", ref="nodes",
              help="The place this vessel is, if it's charted on the map."),
            f("desc", "text", label="Description",
              help="What this slot holds, in your words. Shown in the HARDWARE pane "
                   "for every vessel; for an uncharted one it also stands in for the role."),
            f("kind", "select", options=RACK_KINDS, default="auto",
              help="Which faceplate it wears. `auto` reads the name and Description."),
            f("depth_mm", "int", label="Depth (mm)", min=0, max=1500,
              help="How deep it runs, for the 3D rack. Blank uses a typical depth for its kind."),
        ]),

    "rack_rear": section(
        "rack_rear", "rear fitting", "rear fittings",
        id_field=None, title_field="name",
        lore="what hangs behind the rack",
        subtitle="Rear-of-rack items — PDUs, shelves, anything without a front U.",
        fields=[
            f("rack", "ref", ref="racks", label="Rack",
              help="Which rack it hangs behind. Blank means the first rack."),
            f("name", "text", required=True),
            f("desc", "text", label="Description"),
            f("node", "ref", ref="nodes"),
            f("side", "select", options=REAR_SIDES, default="rear", label="Where",
              help="`rear` hangs behind the rack. `inside` is in the cabinet and on neither "
                   "face: a shelf, a mini PC on a tray, a power strip on its floor."),
        ]),

    "vms": section(
        "vms", "vassal", "vassals", noun="vm",
        lore="the host's memory, divided among those it carries",
        subtitle="Virtual machines and their allocations. RESOURCES draws these.",
        fields=[
            f("id", "ref", ref="nodes", required=True,
              help="The charted place this vassal is. Must match a place id."),
            f("host", "ref", ref="nodes", required=True, help="The hypervisor carrying it."),
            f("vcpu", "int", label="vCPU", required=True, min=1),
            f("ram_gb", "number", label="RAM (GB)", required=True, min=0),
            f("demand_gb", "number", label="In use (GB)", min=0,
              help="What it actually consumes — draws the fill inside its bar."),
            f("disk_gb", "number", label="Disk (GB)", min=0),
            f("dynamic", "text", help="Dynamic-memory range, e.g. `2–6`."),
            f("state", "select", options=VM_STATES, default="on", required=True),
        ]),

    "certs": section(
        "certs", "cert", "certs",
        id_field=None, title_field="name",
        lore="the seals that vouch for the realm",
        subtitle="Certificates — who signed them, what presents them, when they lapse.",
        fields=[
            f("name", "text", required=True,
              help="What it vouches for: `www.example.com`, `nas.corp.example`."),
            f("kind", "select", options=CERT_KINDS, required=True, default="tls"),
            f("issuer", "text", required=True,
              help="Who signed it: `Let's Encrypt`, `Example CA`."),
            f("host", "text", help="Where it is presented from."),
            f("place", "ref", ref="nodes", label="Place",
              help="The place this certificate is for"),
            f("expires", "text", required=True,
              help="The day it lapses, ISO: `2026-09-02`."),
            f("renews", "text",
              help="What renews it and when. Blank means a human does — which is "
                   "the thing this section exists to make visible."),
            f("note", "text", help="One line."),
        ]),
    "rites": section(
        "rites", "rite", "rites",
        id_field=None, title_field="name",
        lore="what the realm does for itself, and when",
        subtitle="Scheduled automations — cron jobs, timers, backups.",
        fields=[
            f("name", "text", required=True),
            f("cadence", "select", options=RITE_CADENCES, required=True, default="daily"),
            f("when", "text", required=True, help="When it turns, in words: `Wed 04:40 UTC`."),
            f("host", "text", required=True, help="Where it runs."),
            f("note", "text", help="What it does, in one line."),
            f("key", "text",
              help="The name it reports under. Defaults to the slugified name — set "
                   "this before renaming a rite, or its history detaches."),
            f("expect_every", "text", label="Expect every",
              help="How often it should actually turn: `24h`, `7d`, `15m`. Blank "
                   "inherits the cadence (daily = 24h, weekly = 7d). This is what "
                   "makes a missed turning visible."),
            f("grace", "text",
              help="How late it may be before it counts as missed. Blank = a "
                   "quarter of the interval, never under 15m."),
            f("asks", "ref", ref="nodes", label="Asks",
              help="The place whose model this rite calls, if it calls one: the GPU box. "
                   "Naming it puts the rite on that place's calendar."),
            f("model", "text",
              help="What it asks for: `mistral:7b · 8k`. Colours the lane — a "
                   "very large model is drawn in the warning tone."),
            f("at", "text", label="Clock (UTC)",
              help="`09:15` to start then; `:10` for an hourly rite. Blank = no clock "
                   "(on request, or no fixed time) — listed under the day, not drawn."),
            f("days", "text",
              help="`Mon–Fri`, `Sun`, `weekdays`. Blank = every day."),
            f("between", "text", label="Between (UTC)",
              help="For an hourly rite, the window it keeps: `20:00–04:00` (wraps past "
                   "midnight). Blank = all day."),
            f("hold", "int", label="Keeps the model busy (min)", min=1, max=1440,
              help="Minutes a run typically keeps the model busy — the width of its "
                   "block. Blank = 10."),
        ]),

    "stones": section(
        "stones", "stone", "stones", noun="stone",
        id_field="id", title_field="name",
        lore="the silent watchers, and what they guard",
        subtitle="tripwires — honeypots and canary tokens, bait with no "
                 "legitimate caller. Anything that touches one is an event, "
                 "not a maybe.",
        fields=[
            f("id", "text", required=True,
              help="Stable id, matching the decoy feed's own registry: `files-old-share`. "
                   "The live feed keys on this — rename it and the stone goes quiet "
                   "on the map while still ringing in the engine."),
            f("name", "text", required=True,
              help="What the bait calls itself, as an intruder would see it: "
                   "`Old-Passwords`. It MIMICS a real thing; it never names one. "
                   "A honeyfile that names a real file server briefs the intruder "
                   "instead of catching them."),
            f("kind", "select", options=STONE_KINDS, required=True,
              default="web-bug", help="What sort of bait it is."),
            f("host", "ref", ref="nodes", label="Guards",
              help="The place this stone watches. Internal bookkeeping — unlike "
                   "`name`, this never leaves the realm, which is why it may say "
                   "what it really is."),
            f("zone", "select", options=STONE_ZONES, required=True,
              default="internal",
              help="`internal` means every trip reaches a human, no exceptions. "
                   "`wan` is the only zone whose trips may be filed quietly."),
            f("severity", "select", options=STONE_SEVERITIES, required=True,
              default="high", help="How loud a trip here should be."),
            f("placement", "text",
              help="Where it sits, described generically: `a decoy folder on the "
                   "file store`. Same rule as `name` — describe, don't locate."),
            f("mimics", "text",
              help="What real thing it imitates. The honest answer to 'why would "
                   "anyone open this?'"),
            f("retired", "bool",
              help="A stone that caught the wrong actor is RETIRED, not tuned. "
                   "Retired stones stay charted — their trips still point "
                   "somewhere — but they leave the map."),
            f("note", "text", help="One line. Which stage of the kill chain, usually."),
            f("family", "select", options=[""] + STONE_FAMILIES,
              help="`honeypot` — a fake host or service that answers. `token` — "
                   "a file, URL, name or key that calls home when used. Blank = "
                   "from the kind (`honeypot-*` kinds are honeypots)."),
            f("sensor", "text", label="Reported as",
              help="What the monitoring tool calls this tripwire, so a trip it "
                   "reports lands here: OpenCanary's `device.node_id` (or "
                   "`node_id:port` for one of its services), a Canarytokens "
                   "token id, or the token's reminder text. Blank = the id."),
            f("planted", "text",
              help="Where a token sits, described generically: `the finance "
                   "share`. Describe, don't locate — same rule as `placement`."),
            f("expires", "date",
              help="The day a token stops being worth anything (a key rotated "
                   "out, a document past its story). YYYY-MM-DD; blank = never."),
        ]),

    "collections": section(
        "collections", "collection", "collections", noun="collection",
        lore="named lists of places, for the table and for alerts",
        subtitle="Named lists of places, for the table and for alerts. Not access: "
                 "who may see a place is its access group.",
        fields=[
            f("id", "slug", required=True, help="Short unique key, e.g. `storage`."),
            f("name", "text", required=True,
              help="What the collection is called, e.g. `Storage`."),
            f("places", "strings", ref="nodes", label="Places",
              help="The places in this collection, by id."),
            f("note", "longtext", help="What the collection is for."),
            f("services", "strings", label="Services",
              help="Services in this collection. By key: a Kuma monitor's name, or `<place id>/<label>` for a built-in check (the key the feed files the service under)."),
            f("unmanaged", "bool", label="Unmanaged",
              help="Every place and service in it is unmanaged: on the map, greyed, watched by nothing."),
        ]),

    "names": section(
        "names", "name", "names", noun="name",
        id_field="name", title_field="name",
        lore="what each name in the realm is meant to answer to",
        subtitle="What each name is meant to be: reached from the internet, only "
                 "inside, or over a VPN. A rule like *.example.com covers the domain "
                 "and every name under it; an exact name wins over a rule.",
        fields=[
            f("name", "text", required=True,
              help="A name, `cloud.example.com`, or a rule for a whole domain, "
                   "`*.example.com`."),
            f("exposure", "select", options=NAME_EXPOSURES, default="",
              help="`public`: meant to answer from the internet. `internal`: only "
                   "inside. `vpn`: over a VPN. Blank, on a rule only: not decided yet."),
            f("note", "longtext", help="Why, in a line."),
        ]),

    "chronicle": section(
        "chronicle", "watching", "watchings", noun="watching",
        id_field=None, title_field="title",
        lore="the realm's watchings, scried live",
        subtitle="Dashboards shown in the sky. Embedded ones rotate in the carousel.",
        fields=[
            f("title", "text", required=True),
            f("note", "text", help="The one-line caption on its button."),
            f("url", "link", help="Where `open ›` (or the button) takes you. Optional "
                                  "for a native watching, which needs none."),
            f("embed", "link", help="An embeddable URL — makes it a live inline panel."),
            f("chart", "text", label="Native chart",
              help="A key from the Atlas's own catalogue (`/api/v2/charts`) — the "
                   "watching is drawn in the map's ink from Prometheus/Loki instead "
                   "of framing Grafana. Blank = matched when the "
                   "embed URL names a panel this catalogue lists."),
            f("range", "text", help="Grafana window override, e.g. `now-24h`."),
            f("solo", "bool", label="Single panel", help="Render it as one panel, not a full board."),
            f("about", "longtext", help="What am I looking at? Shown behind the ⓘ."),
            f("pane_group", "text", label="Shares a slide",
              help="Watchings with the same group name render together as ONE "
                   "carousel slide — quarter-panes in a grid, titled by the "
                   "group name. Blank = its own slide."),
            f("open_in", "select", options=OPEN_IN, default="auto", label="Opens",
              help="`auto` asks the dashboard whether it allows framing and shows "
                   "it in THE VIEWING GLASS when it does. `here` insists. `tab` "
                   "never frames it — for consoles that refuse the glass."),
            f("broken", "bool", label="Flag as broken",
              help="Mark it dark and refuse to embed it — for a dashboard that isn't reporting."),
        ]),

    "abyss": section(
        "abyss", "scrying", "scryings", noun="scrying",
        id_field=None, title_field="title",
        lore="security & the outer veil, scried from the deep",
        subtitle="Dashboards shown below the Depths. Same shape as the Chronicle.",
        fields=[
            f("title", "text", required=True),
            f("note", "text"),
            f("url", "link",
              help="An absolute URL, or a path this app serves like `report/security`. "
                   "Optional for a native watching, which needs none."),
            f("embed", "link"),
            f("chart", "text", label="Native chart",
              help="A key from `/api/v2/charts`; blank = matched from the embed URL."),
            f("range", "text"),
            f("solo", "bool", label="Single panel"),
            f("whois", "bool", label="THE NAMING DEEP",
              help="Put the whois box beside this panel, so an address shown on "
                   "it can be handed to the registries without leaving the map. "
                   "Meant for a panel that lists addresses — one row per "
                   "address."),
            f("about", "longtext"),
            f("pane_group", "text", label="Shares a slide"),
            f("open_in", "select", options=OPEN_IN, default="auto", label="Opens"),
            f("broken", "bool", label="Flag as broken"),
        ]),

    "maintenance": section(
        "maintenance", "repair", "repairs", noun="window", store="maintenance",
        title_field="reason",
        lore="what the realm has closed for work, and when it opens again",
        subtitle="Scheduled maintenance. Alarms are suppressed while a window is "
                 "open, and it closes itself when it ends.",
        fields=[
            f("id", "slug", required=True, help="Short unique key, e.g. `sunday-patching`."),
            f("reason", "text", required=True,
              help="What the work is. Shown wherever the window is."),
            f("nodes", "strings", ref="nodes", label="Places",
              help="Which places are down for it. Their alarms stay quiet while it's open. "
                   "Name places, collections, or both."),
            f("collections", "strings", ref="collections", label="Collections",
              help="Whole collections: whatever is in one when the window is open is covered."),
            f("services", "strings", label="Services",
              help="Single services, its place left watched. By key: a Kuma monitor's name, or `<place id>/<label>` for a built-in check (the key the feed files the service under)."),
            f("starts", "datetime", required=True, help="When it opens (UTC)."),
            f("ends", "datetime",
              help="When it closes (UTC). Required on purpose for every window but "
                   "maintenance mode: a window with no end is a suppression somebody "
                   "has to remember to remove."),
            f("open", "bool", label="Maintenance mode",
              help="On until someone turns it off: no end. The daily digest names one "
                   "left on more than a week."),
            f("repeat", "select", options=list(MAINTENANCE_REPEATS),
              default="none", help="Recurring windows re-open on the same schedule."),
            f("note", "text", help="Anything the next person should know."),
        ]),

    "meta": section(
        "meta", "atlas setting", "atlas settings", kind="object",
        id_field=None, title_field=None,
        lore="the surveyor's own notes",
        subtitle="Names and constants for the whole map.",
        fields=[
            f("title", "text", required=True, help="The name of this atlas."),
            f("carry_service_renames", "bool", label="Carry service renames",
              help="When a service is renamed (its label, its monitor, or its place's id), "
                   "the collections, repair windows and alert rules naming it follow the new "
                   "name. Off, they keep the old one, and Atlas says what was left behind."),
            f("shadow_kuma", "bool", label="Check beside Kuma",
              help="Atlas also asks what a Kuma monitor watches, by the service's own "
                   "address or check, and NODES shows how often the two agree. Kuma's "
                   "answer stays the one on the map. For deciding whether Atlas can "
                   "take over from Kuma."),
            f("map_art", "json", label="Map names",
              help="`[{\"name\": \"floor-2.webp\", \"label\": \"Second floor\"}]`: what a map "
                   "image is called in the list of map styles, in place of its file name. "
                   "Set from the map editor, under Map style, Rename."),
            f("surveyed", "text", help="When the map was last walked, `YYYY-MM-DD`."),
            f("art", "text", help="Which base render is in use — a note to your future self."),
            f("map_image", "text", label="Base render",
              help="The picture the map is drawn on — a bare filename, e.g. "
                   "`floor-2.webp`. Blank uses the render the Atlas ships with. "
                   "Upload your own in the Desk. Places are positioned in fractions "
                   "of the image, so swapping it keeps every marker where it is."),
            f("tribute", "object", label="Resources", of=[
                f("total_gb", "number", label="Host memory (GB)", min=0,
                  help="How much the hypervisor has in total."),
                f("host_reserve_gb", "number", label="Reserved for the host (GB)", min=0,
                  help="Held back for the hypervisor itself — free headroom is what's left."),
                f("cpu_cores", "number", label="Host cores", min=0,
                  help="Physical cores on the hypervisor. Shown as the iron behind "
                       "the vCPU count; blank simply hides that line."),
                f("cpu_threads", "number", label="Host threads", min=0,
                  help="Logical processors — what a vCPU is actually assigned "
                       "against. This is the denominator of the vCPU score, so a "
                       "wrong number here reads as false headroom."),
              ], help="One machine's numbers, from before a place could carry its own "
                      "(Memory, Cores and Threads on the place). They still stand for "
                      "a map with one host that declares none: set them on the place "
                      "instead, and leave these."),
        ]),
}

SIGNAL_FIELDS = [
    f("kuma", "json", label="Monitor → place map",
      help="`{\"Monitor Name\": \"place-id\"}` — ties a Kuma monitor to a marker."),
    f("drift_ignore", "strings", label="Silenced monitors",
      help="Kuma monitors you deliberately don't chart. Keeps the drift chip "
           "honest. ⚠ Matched EXACTLY against the monitor name — an entry with "
           "a note appended (`Checks [STALE: …]`) silences nothing, because no "
           "monitor is called that. Put the reason in the commit, not in the string. "
           "Charting a monitor on a link already clears it, so an entry for a "
           "charted monitor is redundant too."),
]

SAFE_TYPES = frozenset({"bool", "number", "int", "percent", "select", "color", "date",
                        "datetime", "ip", "cidr"})
HIDING_KINDS = frozenset({"safe", "ref", "words", "slug", "url", "keys", "pins", "admin"})

HIDING = {
    "zones": {"id": "safe", "name": "safe", "vlan": "safe", "lore": "words", "origin": "words"},
    "regions": {"id": "safe", "name": "safe", "map": "safe", "parent": "safe", "places": "pins"},
    "nodes": {
        "id": "safe", "name": "safe", "zone": "safe", "role": "words", "lore": "words",
        "hw": "words", "location": "words", "mac": "safe", "scroll": "safe",
        "require_group": "safe",
        "check_host": "words", "check_expect": "safe", "monitors": "words",
        "origin": "words", "accounts": "admin",
        "links": {"label": "words", "url": "url", "desc": "words", "kuma": "words",
                  "container": "words", "check_host": "words", "check_expect": "safe",
                  "require_group": "safe"},
    },
    "routes": {},
    "cables": {"id": "slug", "a_stub": "safe", "a_port": "words", "b_stub": "safe",
               "b_port": "words", "vlan": "safe", "tagged": "safe", "speed": "safe",
               "source": "safe", "note": "words"},
    "stubs": {"id": "slug", "name": "words", "note": "words"},
    "prefixes": {"id": "safe", "zone": "safe", "name": "safe", "note": "words",
                 "ranges": {"note": "words"}},
    "interfaces": {"name": "words", "vlan": "safe", "speed": "safe", "peer": "words",
                   "note": "words"},
    "racks": {"id": "safe", "name": "safe", "location": "words"},
    "rack": {"rack": "safe", "u": "safe", "name": "words", "desc": "words"},
    "rack_rear": {"rack": "safe", "name": "words", "desc": "words", "side": "safe"},
    "vms": {"dynamic": "safe"},
    "certs": {"name": "words", "issuer": "safe", "host": "words", "expires": "safe",
              "renews": "safe", "note": "words"},
    "rites": {"name": "words", "when": "words", "host": "words", "note": "words",
              "key": "slug", "expect_every": "safe", "grace": "safe", "model": "safe",
              "at": "safe", "days": "safe", "between": "safe"},
    "stones": "admin",
    "collections": {"id": "slug", "name": "words", "note": "words", "services": "keys"},
    "names": {"name": "words", "note": "words"},
    "chronicle": {"title": "safe", "note": "words", "url": "url", "embed": "url",
                  "chart": "safe", "range": "safe", "about": "words", "pane_group": "safe"},
    "abyss": {"title": "safe", "note": "words", "url": "url", "embed": "url",
              "chart": "safe", "range": "safe", "about": "words", "pane_group": "safe"},
    "maintenance": {"id": "slug", "reason": "words", "collections": "safe",
                    "services": "keys", "note": "words"},
    "meta": {"title": "safe", "surveyed": "safe", "art": "safe", "map_image": "safe",
             "tribute": "safe", "map_art": "safe"},
}

WORDS_DROP_ENTRY = frozenset({"cables", "stubs", "interfaces", "rack", "rack_rear", "vms",
                              "certs", "rites", "collections", "maintenance", "names"})


def hiding(section_key, field_name, sub_name=None):
    declared = HIDING.get(section_key)
    if declared == "admin":
        return "admin"
    fld = field(section_key, field_name)
    if fld is None:
        return None
    if sub_name is not None:
        sub = next((s for s in fld.get("of") or [] if s.get("name") == sub_name), None)
        if sub is None:
            return None
        said = ((declared or {}).get(field_name) or {})
        if said == "admin":
            return "admin"
        said = said.get(sub_name) if isinstance(said, dict) else None
        if said:
            return said
        if sub.get("ref") == "nodes":
            return "ref"
        return "safe" if sub.get("type") in SAFE_TYPES else None
    said = (declared or {}).get(field_name)
    if isinstance(said, str):
        return said
    if fld.get("ref") == "nodes":
        return "ref"
    if fld.get("type") in SAFE_TYPES:
        return "safe"
    if isinstance(said, dict) or fld.get("type") == "objects":
        return "parts" if fld.get("of") else None
    return None


SECTION_ORDER = ["nodes", "zones", "regions", "prefixes", "routes", "interfaces",
                 "cables", "stubs", "racks", "rack", "rack_rear", "vms", "rites", "certs", "collections", "names",
                 "stones", "maintenance", "chronicle", "abyss", "meta"]

FILE_ORDER = ("meta", "zones", "regions", "nodes", "routes", "prefixes", "interfaces",
              "cables", "stubs", "racks", "rack", "rack_rear", "vms", "signals", "chronicle", "abyss", "rites",
              "certs", "collections", "names", "stones")


RENAMED_SECTIONS = {"sets": "collections"}


def upgrade(data):
    if not isinstance(data, dict):
        return data
    for old, new in RENAMED_SECTIONS.items():
        if old not in data:
            continue
        legacy = data[old]
        current = data.get(new)
        if new not in data:
            merged = legacy
        elif isinstance(current, list) and isinstance(legacy, list):
            have = {e["id"] for e in current if isinstance(e, dict) and isinstance(e.get("id"), str)}
            merged = current + [e for e in legacy
                                if not (isinstance(e, dict) and isinstance(e.get("id"), str)
                                        and e["id"] in have)]
        elif isinstance(legacy, list):
            merged = legacy
        else:
            merged = current
        keep_at = new if new in data else old
        rebuilt = {}
        for k, v in data.items():
            if k == keep_at:
                rebuilt[new] = merged
            elif k not in (old, new):
                rebuilt[k] = v
        data.clear()
        data.update(rebuilt)
    return data


def servable(data):
    if not isinstance(data, dict):
        return data
    for key, sec in SECTIONS.items():
        if sec.get("kind", "list") == "list" and key in data and not isinstance(data[key], list):
            data[key] = []
    node_fields = [(f["name"], f["type"]) for f in fields_of("nodes")]
    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        for name, ftype in node_fields:
            if name not in node:
                continue
            if ftype == "objects" and not isinstance(node[name], list):
                node[name] = []
            elif ftype == "strings" and not isinstance(node[name], (list, str)):
                node[name] = []
    return data


def get(key):
    return SECTIONS.get(key)


def fields_of(key):
    s = SECTIONS.get(key)
    return s["fields"] if s else []


def field(section_key, field_name):
    for fld in fields_of(section_key):
        if fld["name"] == field_name:
            return fld
    return None


def catalogue():
    return {
        "order": SECTION_ORDER,
        "sections": {k: SECTIONS[k] for k in SECTION_ORDER if k in SECTIONS},
        "signals": SIGNAL_FIELDS,
    }


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
NONE_MARKS = ("—", "-", "")


_MAC_DIGITS = re.compile(r"[0-9a-f]{12}")


def mac_key(text):
    digits = re.sub(r"[\s:.\-]", "", str(text or "")).lower()
    if not _MAC_DIGITS.fullmatch(digits):
        return ""
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2))


def _check_text(fld, value):
    name = fld["name"]
    if not isinstance(value, str):
        return f"{name} must be text"
    if fld["type"] == "slug" and value and not _SLUG_RE.match(value):
        return (f"{name} {value!r} is not a valid id — lowercase letters, digits, "
                "dot, dash and underscore only, starting with a letter or digit")
    return None


def _check_datetime(fld, value):
    name = fld["name"]
    if not isinstance(value, str):
        return f"{name} must be a timestamp"
    if value in NONE_MARKS:
        return None
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return f"{name} {value!r} is not a date and time (YYYY-MM-DDTHH:MM)"
    return None


def _check_date(fld, value):
    name = fld["name"]
    if not isinstance(value, str):
        return f"{name} must be a date"
    if value.strip() in NONE_MARKS:
        return None
    try:
        date.fromisoformat(value.strip())
    except ValueError:
        return f"{name} {value!r} is not a date (YYYY-MM-DD)"
    return None


def _check_scalar(fld, value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return f"{fld['name']} must be text or a number"
    return None


def _check_url(fld, value):
    if value == "" and not fld.get("required"):
        return None
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return f"{fld['name']} must be a url starting http:// or https://"
    return None


def carries_credentials(value):
    if isinstance(value, str):
        text = value.strip()
        if not text.lower().startswith(("http://", "https://")):
            return False
        rest = text.split("://", 1)[1].split("?", 1)[0].split("#", 1)[0]
        authority, _, path = rest.partition("/")
        if "@" in authority:
            return True
        return ("@" in path and not authority.startswith("[")
                and re.search(r":(?!\d*$)", authority) is not None)
    if isinstance(value, dict):
        return any(carries_credentials(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(carries_credentials(v) for v in value)
    return False


URL_CREDENTIALS = ("a URL here carries a user name or password (the user:pass@host form). "
                   "Remove it from the URL and keep the credential in the service itself; "
                   "everyone and everything that reads the map would read it too")


def _check_link(fld, value):
    name = fld["name"]
    if not isinstance(value, str):
        return f"{name} must be text"
    if value.startswith(("http://", "https://")):
        return None
    if value.startswith("//") or ":" in value.split("/")[0]:
        return f"{name} must be an http(s) url or a relative path"
    return None


def _check_color(fld, value):
    if not isinstance(value, str) or not _HEX_RE.match(value):
        return f"{fld['name']} must be a hex colour like #C9A554"
    return None


def _check_bool(fld, value):
    return None if isinstance(value, bool) else f"{fld['name']} must be true or false"


def _check_number(fld, value):
    name = fld["name"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{name} must be a number"
    if isinstance(value, float) and not math.isfinite(value):
        return f"{name} must be a number"
    if fld["type"] == "int" and not float(value).is_integer():
        return f"{name} must be a whole number"
    if "min" in fld and value < fld["min"]:
        return f"{name} must be at least {fld['min']}"
    if "max" in fld and value > fld["max"]:
        return f"{name} must be at most {fld['max']}"
    return None


def _check_percent(fld, value):
    name = fld["name"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{name} must be a number"
    if not (PERCENT_MIN <= value <= PERCENT_MAX):
        return f"{name} {value} is off the table"
    return None


def _check_select(fld, value):
    name = fld["name"]
    opts = fld.get("options", [])
    if value in NONE_MARKS and "" in opts:
        return None
    if value not in opts:
        return f"unknown {name} {value!r}"
    return None


def _check_ip(fld, value):
    name = fld["name"]
    if not isinstance(value, str):
        return f"{name} must be text"
    if value in NONE_MARKS:
        return None
    try:
        ipaddress.ip_address(value)
        return None
    except ValueError:
        pass
    try:
        ipaddress.ip_network(value, strict=False)
        return None
    except ValueError:
        return f"{name} {value!r} is not an ip address"


def _check_cidr(fld, value):
    name = fld["name"]
    if not isinstance(value, str):
        return f"{name} must be text"
    if value in NONE_MARKS:
        return None
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError:
        return f"{name} {value!r} is not a prefix like 10.0.20.0/24"
    return None


def _check_strings(fld, value):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        return f"{fld['name']} must be a list of text values"
    return None


def _check_objects(fld, value):
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        return f"{fld['name']} must be a list of entries"
    return None


def _check_object(fld, value):
    if not isinstance(value, dict):
        return f"{fld['name']} must be a group of settings"
    return None


def _check_ref(fld, value):
    if not isinstance(value, str):
        return f"{fld['name']} must be one id, as text"
    return None


_CHECKS = {
    "text": _check_text, "longtext": _check_text, "path": _check_text, "slug": _check_text,
    "datetime": _check_datetime,
    "date": _check_date,
    "scalar": _check_scalar,
    "url": _check_url,
    "link": _check_link,
    "color": _check_color,
    "bool": _check_bool,
    "int": _check_number, "number": _check_number,
    "percent": _check_percent,
    "select": _check_select,
    "ip": _check_ip,
    "cidr": _check_cidr,
    "strings": _check_strings,
    "objects": _check_objects,
    "object": _check_object,
    "ref": _check_ref,
}


def check_value(fld, value):
    check = _CHECKS.get(fld["type"])
    return check(fld, value) if check else None


def _check_sub(prefix, holder, subfields, out):
    for subfld in subfields:
        sname = subfld["name"]
        if sname not in holder or holder[sname] is None:
            if subfld.get("required"):
                out.append(f"{prefix}: missing {sname}")
            continue
        suberr = check_value(subfld, holder[sname])
        if suberr:
            out.append(f"{prefix}: {suberr}")


def check_entry(section_key, entry, strict=False):
    s = SECTIONS.get(section_key)
    if s is None:
        return []
    if not isinstance(entry, dict):
        return [f"{s['singular']} entry must be an object, got {type(entry).__name__}"]

    out = []
    for fld in s["fields"]:
        name = fld["name"]
        present = name in entry
        if not present:
            if fld.get("required"):
                out.append(f"missing {name}")
            continue
        value = entry[name]
        if value is None:
            if fld.get("required"):
                out.append(f"missing {name}")
            continue
        if strict and fld.get("required") and value == "" and fld["type"] != "bool":
            out.append(f"{name} cannot be blank")
            continue
        err = check_value(fld, value)
        if err:
            out.append(err)
            continue
        if fld["type"] == "objects":
            for i, sub in enumerate(value):
                _check_sub(f"{name}[{i}]", sub, fld.get("of", []), out)
        elif fld["type"] == "object":
            _check_sub(name, value, fld.get("of", []), out)
    return out


def ref_fields(section_key):
    out = []
    for fld in fields_of(section_key):
        if fld.get("ref"):
            out.append((fld["name"], None, fld["ref"], fld["type"]))
        for sub in fld.get("of", []) or []:
            if sub.get("ref"):
                out.append((fld["name"], sub["name"], sub["ref"], sub["type"]))
    return out


def followers(target):
    return [(key, fld["name"]) for key in SECTIONS for fld in fields_of(key)
            if fld.get("follows") and fld.get("ref") == target]


def vlan_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, int) and VLAN_MIN <= value <= VLAN_MAX:
        return value
    return None


def refs_of(section_key):
    return [(name if sub is None else f"{name}.{sub}", target)
            for name, sub, target, _ in ref_fields(section_key)]


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def blank(section_key):
    out = {}
    for fld in fields_of(section_key):
        if "default" in fld:
            out[fld["name"]] = fld["default"]
        elif fld.get("required"):
            out[fld["name"]] = {"bool": False, "int": 0, "number": 0,
                                "percent": 50.0, "objects": [], "strings": []}.get(
                                    fld["type"], "")
    return out
