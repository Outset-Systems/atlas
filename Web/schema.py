"""The field catalogue — one definition of what the dataset *is*.

Every editable section of `lab-data.json` is described here once: its fields,
their types, which other sections they point at, and which are required. Three
consumers were the reason for it (`redaction.py`, `openapi.py` and
`tripwires.py` read it now too):

  * `validation.py`  — turns the catalogue into the problem list, which is
    logged and counted on `/api/status` and `X-Atlas-Data-Problems`.
  * `dataset.py` — coerces and strictly checks a write before it lands.
  * `/api/v2/admin/context` — hands it to the browser (as its `schema` key), which
    renders every editor form and table from it. This line used to say
    `/api/admin/schema`, which is not a route that exists; corrected 2026-08-14
    while adding `stones`, because a reader greps for what the comment names.

That is the whole point: six editors built from one catalogue instead of six
hand-written forms that drift apart. Adding a field to the map is an entry
here, not a change in three places.

Doctrine carried over from the hand-edited era: the dataset is
richer than any schema we freeze. Unknown keys are **kept, not stripped** — a
section's `fields` list is what the editor knows how to show, never the limit
of what the file may hold.
"""

import ipaddress
import math
import re
from datetime import date, datetime

# ── Field constructors ───────────────────────────────────────────────────────
# A field is a plain dict so it serializes to the browser untouched.


def f(name, type="text", label=None, required=False, help="", **kw):
    """One field in a section. `label` defaults to a title-cased name."""
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
    """One editable section of the dataset.

    `singular`/`plural` are the in-world names the UI shows ("place", "vassal").
    `noun` is the plain word used in problem messages — it stays `node`, `zone`,
    `route` so the log reads the way it always has and the existing tests keep
    matching.
    """
    return {
        "key": key,
        "kind": kind,              # "list" (array of objects) | "object" (a mapping)
        "singular": singular,
        "plural": plural,
        "noun": noun or singular,
        # Which store owns this section. "dataset" goes through the ops engine
        # and the change log; anything else is its own small file with its own
        # endpoint. Maintenance windows are operational state that changes at
        # 2am, so they are deliberately not in the git-tracked dataset — but
        # they still get the generic table and form from this one catalogue.
        "store": store,
        "id_field": id_field if kind == "list" else None,
        "title_field": title_field,
        "fields": fields,
        "lore": lore,              # the in-world one-liner shown above the table
        "subtitle": subtitle,      # the plain-English one
    }


# ── Shared option lists ──────────────────────────────────────────────────────
NODE_KINDS = ["physical", "vm", "network", "unknown"]
NODE_SHAPES = ["", "diamond", "triangle"]
ROUTE_KINDS = ["wan", "edge", "vlan", "mesh", "telemetry"]
#: CABLES (2026-11-16): what a cable is made of, and how sure the map is of it.
CABLE_KINDS = ["copper", "fibre", "dac", "wireless", "virtual"]
CABLE_STATES = ["confirmed", "assumed"]
#: STUBS (2026-11-16): gear a cable reaches that is not charted as a place.
STUB_KINDS = ["internet", "switch", "patch", "outlet", "other"]
#: The lowest and highest VLAN id a cable may carry.
VLAN_MIN, VLAN_MAX = 1, 4094
VM_STATES = ["on", "off"]
#: `parked` is deliberately NOT a period. heartbeats.CADENCE_SECONDS knows the
#: other four and does not know this one, so `expectations()` returns
#: `(None, None)` and the rite reads **unwatched** — still listed, still
#: uncoloured, nothing expected of it. That is the honest state for a rite whose
#: home has gone away but which is coming back: retiring it would delete the row
#: and its history, while leaving it `daily` would have the map cry MISSED every
#: morning for a machine nobody is running. Added 2026-08-12, when The
#: Librarian's Round was parked off a workstation pending its the monitoring host successor.
#: Set the cadence back to a real period on the day it resumes.
RITE_CADENCES = ["continuous", "daily", "weekly", "monthly", "parked"]
CERT_KINDS = ["tls", "ssh-host", "ca"]
IFACE_KINDS = ["rj45", "sfp", "sfp+", "console", "power", "virtual"]
#: The faceplates THE ARMORY can draw; mirrors KIND_HUE in rack-model.js.
RACK_KINDS = ["auto", "compute", "forge", "gateway", "switch", "storage",
              "power", "enclosure", "patch"]
PREFIX_ROLES = ["prefix", "container", "reserved"]
RANGE_KINDS = ["dhcp", "reserved"]
#: How a service's button behaves — see LINK_FIELDS["open_in"] and glass.js.
OPEN_IN = ["auto", "here", "tab"]
#: What a service link is in NODES (2026-11-15). Blank reads its `container`.
LINK_KINDS = ["", "service", "container"]
#: THE WATCH's kinds of check (2026-11-15, watch.py). Blank is the default.
CHECK_TYPES = ["", "http", "tcp", "dns", "keyword", "json", "off"]
#: How a maintenance window recurs.
MAINTENANCE_REPEATS = ("none", "daily", "weekly", "monthly")
#: The lowest and highest value a `percent` field may hold. Named once because
#: `overlays.py` holds a saved marker's y to the same two numbers.
PERCENT_MIN, PERCENT_MAX = -40, 140

# ── tripwires (the `stones` section; the decoy feed is one source) ──────────
#: What kind of bait a stone is. Mirrors the token types the decoy feed charts; kept
#: loose rather than pinned to a provider's exact catalogue, because the point
#: of the field is "what would an intruder think they found".
STONE_KINDS = ["windows-folder", "network-folder", "web-bug", "dns",
               "doc-msword", "doc-excel", "doc-pdf", "aws-keys", "ad-account",
               "sensitive-command", "kubeconfig", "other",
               # TRIPWIRES (v0.1): two more canary tokens, then the honeypots —
               # fake hosts and services that answer (OpenCanary and friends).
               # Appended, never reordered: an existing stone keeps its kind.
               "cloud-key", "db-row",
               "honeypot-host", "honeypot-ssh", "honeypot-smb", "honeypot-http",
               "honeypot-rdp", "honeypot-ftp", "honeypot-telnet", "honeypot-db"]
#: TRIPWIRES: the two families. A stone with no `family` takes it from its
#: kind (`stone_family`), so every stone charted before the field existed
#: already belongs to one.
STONE_FAMILIES = ["honeypot", "token"]


def stone_family(stone):
    """`honeypot` or `token` for a stone, old shape or new: the explicit
    `family` when it is a known one, else derived from the kind."""
    stone = stone if isinstance(stone, dict) else {}
    fam = stone.get("family")
    if fam in STONE_FAMILIES:
        return fam
    return "honeypot" if str(stone.get("kind") or "").startswith("honeypot") else "token"
#: Where a stone sits, which is what decides the escalation policy: ANY trip on
#: an `internal` stone reaches a human. `wan` is the only zone whose trips may
#: ever be filed quietly.
STONE_ZONES = ["internal", "wan"]
#: How loud a trip here should be. `critical` is the wake-a-human tier.
STONE_SEVERITIES = ["info", "low", "medium", "high", "critical"]

def _check_fields(on_place):
    """THE WATCH's settings (2026-11-15, watch.py), on a service or a place.
    Every one may be left blank: a service with an http(s) address is asked
    as it always was, and a place with no check takes its services' state."""
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


# The link sub-object, reused by nodes.
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
           "place — e.g. `gateway, edge, traefik, pangolin, the-wild` for "
           "something reached from the internet. Drawn as a chain instead of a "
           "star, so the map can say *through*. Every consecutive pair must be a "
           "charted route, or the map is drawing a route that isn't there."),
    f("open_in", "select", options=OPEN_IN, default="auto", label="Opens",
      help="`auto` asks the service whether it allows framing and shows it in "
           "THE VIEWING GLASS when it does. `here` insists. `tab` never frames "
           "it — for anything that only works with the whole window."),
    f("require_group", "text", label="Requires group",
      help="Hide this service from anyone whose Hub groups don't include it."),
    f("unmanaged", "bool", label="Unmanaged",
      help="Not ours to watch: this service takes no state and raises nothing."),
]

# Who can get into a place, and how far in. Charted by hand from the
# access-posture baseline a weekly audit rite can diff —
# the Atlas has always tracked that the audit BEAT, never what it found, so
# "who holds a key to the app host" was a question the map could not answer.
#
# ⚑ This is the most sensitive thing in the dataset. It is a list of the
# accounts on a host and how much each can do, which is a target list read the
# wrong way round. `redaction.py` strips it for anyone who is not cleared to
# see everything, and it fails CLOSED — see `redact_for_groups`. Chart the
# posture, never a credential: there is deliberately no field for a password,
# a key, or a hash, and none should be added.
ACCOUNT_SOURCES = ["local", "domain", "service", "agent"]
# Sudo is a THREE-state fact and the middle one is the ordinary case; flattening
# it to a bool is how "has sudo" stops distinguishing the account that must type
# a password from the one that never does.
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
           "docker-admins. Not every group the account happens to be in."),
    f("note", "text",
      help="Why this account exists, or what is odd about it. A repurposed "
           "account that kept a group it no longer needs belongs here."),
]

# An address range inside a prefix (DHCP pool or a reservation).
RANGE_FIELDS = [
    f("start", "ip", required=True),
    f("end", "ip", required=True),
    f("kind", "select", options=RANGE_KINDS, required=True, default="dhcp"),
    f("note", "text"),
]


# ── The catalogue ────────────────────────────────────────────────────────────
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

    # REGIONS (v1.49.0): a rectangle on a map that has its
    # own, more detailed map. Zoom in and it takes over; zoom out and you are
    # back. Regions nest through `parent`.
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
                   "place that *is* a network (Tailscale's 100.64.0.0/10)."),
            f("hw", "text", label="Hardware", help="The mono data line: OS · RAM · disks."),
            f("mac", "text", label="MAC",
              help="Its hardware address, e.g. `00:11:32:aa:bb:cc`. A connection import "
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
                   "mesh = Tailscale · telemetry = a scrape path."),
        ]),

    # CABLES (2026-11-16): a physical connection, port to port. A route says two
    # places talk; a cable says which port is plugged into which. Each end is a
    # place (`a`) or a stub (`a_stub`), never both, and a port name (`a_port`)
    # that is the `name` of one of that place's `interfaces` when there is one.
    # The ends are `follows`: renaming the place or stub they name carries
    # them, and removing it (with cascade) removes the cable in the same save
    # (`dataset.py`). Two fields per end, not one, because a `ref` names one
    # section and every reader of the catalogue (the Desk's pickers, the
    # validator, redaction) is built on that.
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

    # STUBS (2026-11-16): gear a cable reaches that nobody charts as a place:
    # the provider's line, a wall jack, a small switch under a desk. Kept with
    # the cables and drawn only in TOPOLOGY: no marker on the map, no row in
    # NODES, no state, never watched. Not "unmanaged", which is a place that is
    # not ours to watch. Anything with an address or a rack slot is a place.
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
        subtitle="Each rack and where it stands. RACKS shows them as `Location — Name`.",
        fields=[
            f("id", "slug", required=True, help="Short unique key, e.g. `rack-a`."),
            f("name", "text", required=True, help="The rack's own name, e.g. `Rack A`."),
            f("location", "text",
              help="Where it stands, e.g. `Server room`. Blank uses the theme's default."),
        ]),

    "rack": section(
        "rack", "vessel", "vessels", noun="rack slot",
        id_field=None, title_field="name",
        lore="the iron in its niches — the front elevation",
        subtitle="Rack slots, front of rack. RACKS draws these.",
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
              help="What this slot holds, in your words. Shown in the RACKS pane "
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
            f("dynamic", "text", help="Dynamic-memory range, e.g. `4–12`."),
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
              help="Who signed it: `Let's Encrypt`, `step-ca`, `the domain controller-CA`."),
            f("host", "text", help="Where it is presented from."),
            # 2026-11-13: tied to a place by id, so it is hidden with its place
            # (`redaction.py` drops a certificate whose place is hidden) and the
            # places table can show the nearest expiry (`certs.py`). `host`
            # stays: it is words, and an older certificate has only those.
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
            f("when", "text", required=True, help="When it turns, in words: `Sun 03:00 UTC`."),
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
            # THE FORGE'S DAY (v1.40.0): a rite that asks a place for its model
            # joins that place's calendar — RITES draws the day large, the
            # place's card draws it small. All optional; a rite with none of
            # these is exactly the rite it was.
            f("asks", "ref", ref="nodes", label="Asks",
              help="The place whose model this rite calls, if it calls one: the GPU box. "
                   "Naming it puts the rite on that place's calendar."),
            f("model", "text",
              help="What it asks for: `qwen3:14b · 32k`. Colours the lane — the heavy "
                   "30B model that never fit the card is drawn in the warning tone."),
            f("at", "text", label="Clock (UTC)",
              help="`13:45` to start then; `:35` for an hourly rite. Blank = no clock "
                   "(on request, or a week after boot) — listed under the day, not drawn."),
            f("days", "text",
              help="`Mon–Fri`, `Sun`, `weekdays`. Blank = every day."),
            f("between", "text", label="Between (UTC)",
              help="For an hourly rite, the window it keeps: `13:00–01:00` (wraps past "
                   "midnight). Blank = all day."),
            f("hold", "int", label="Holds the forge (min)", min=1, max=1440,
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
              help="Stable id, matching the decoy feed's own registry: `nas-restore-share`. "
                   "The live feed keys on this — rename it and the stone goes quiet "
                   "on the map while still ringing in the engine."),
            f("name", "text", required=True,
              help="What the bait calls itself, as an intruder would see it: "
                   "`Restoration-Keys`. It MIMICS a real thing; it never names one. "
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
            # TRIPWIRES (v0.1) — all optional, so every stone charted before
            # them is still a whole stone.
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

    # COLLECTIONS (2026-11-13 as "sets", renamed 2026-11-14): a named list of
    # places, kept in one record so renaming or deleting it is one write and a
    # rule elsewhere can name it by id. A place may be in more than one; a
    # collection holds no collections. Not access: `require_group` decides who
    # sees a place, and redaction drops a member this viewer may not see while
    # keeping the collection. A dataset that still says `sets` is read as
    # collections (`upgrade`).
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

    "chronicle": section(
        "chronicle", "watching", "watchings", noun="watching",
        id_field=None, title_field="title",
        lore="the realm's watchings, scried live",
        subtitle="Dashboards shown in the sky. Embedded ones rotate in the carousel.",
        fields=[
            f("title", "text", required=True),
            f("note", "text", help="The one-line caption on its button."),
            f("url", "link", help="Where `open ›` (or the button) takes you. Optional "
                                  "since v1.36.0 — a native watching needs none."),
            f("embed", "link", help="An embeddable URL — makes it a live inline panel."),
            f("chart", "text", label="Native chart",
              help="A key from the Atlas's own catalogue (`/api/v2/charts`) — the "
                   "watching is drawn in the map's ink from Prometheus/Loki instead "
                   "of framing Grafana. Blank = matched automatically when the "
                   "embed URL names a panel the catalogue knows."),
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
                   "Optional since v1.36.0 — a native watching needs none."),
            f("embed", "link"),
            f("chart", "text", label="Native chart",
              help="A key from `/api/v2/charts`; blank = matched from the embed URL."),
            f("range", "text"),
            f("solo", "bool", label="Single panel"),
            f("whois", "bool", label="THE NAMING DEEP",
              help="Put the whois box beside this panel, so an address shown on "
                   "it can be handed to the registries without leaving the map. "
                   "Meant for a panel that lists addresses — TOP CLIENTS is the "
                   "one it was built for."),
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
              ], help="The numbers RESOURCES divides among the vassals."),
        ]),
}

# Sections that hold live-signal wiring rather than inventory. Not drawn by the
# generic table, and no panel edits them: `catalogue()` hands them to the
# browser and `openapi.py` describes them.
SIGNAL_FIELDS = [
    f("kuma", "json", label="Monitor → place map",
      help="`{\"Monitor Name\": \"place-id\"}` — ties a Kuma monitor to a marker."),
    f("drift_ignore", "strings", label="Silenced monitors",
      help="Kuma monitors you deliberately don't chart. Keeps the drift chip "
           "honest. ⚠ Matched EXACTLY against the monitor name — an entry with "
           "a note appended (`Checks [STALE: …]`) silences nothing, because no "
           "monitor is called that. Four such entries sat here doing nothing "
           "until 2026-08-09. Put the reason in the commit, not in the string. "
           "Charting a monitor on a link already clears it, so an entry for a "
           "charted monitor is redundant too."),
]

# ── WHAT A FIELD IS TO A VIEWER WHO MAY NOT SEE EVERYTHING (2026-11-18) ─────
# The refactor's stage 4. Every field above says, here, what it is to a person
# or a token that some place is hidden from, and `redaction.py` reads this and
# nothing else to decide what to do with it. A field that says nothing fails
# `test_hiding.py`, so a new field cannot reach a restricted viewer unread:
# before this, a field was given until someone remembered to hide it.
#
#   safe   cannot name a place: a number, a choice, a colour, a date, the
#          entry's own id or name, a network's address. Given as it is.
#   ref    names a place by id (`ref="nodes"`): the reference walk takes a
#          hidden id out, or the entry with it (`redaction._scrub_entry`).
#   words  free text that can name a place: when it names a hidden one (its
#          name, id or address, `redaction.hidden_words`), the field goes, or
#          the whole entry where the section is about the place it names
#          (`WORDS_DROP_ENTRY`; a link on a place always goes whole).
#   slug   an id made from a name (`gw-to-vault`): `words`, matched the way
#          the rail makes ids.
#   url    an address that may carry a hidden place's name or address, and
#          a credential: `words`, and a token gets it without the credential.
#   keys   service keys (`<place>/<label>`): `words`, and a collection keeps
#          only the keys of services the viewer can see.
#   pins   a place id as the KEY of an object (a region's pins): a hidden one
#          is taken out.
#   admin  never given below admin, whatever is hidden.
#
# A field of a type in `SAFE_TYPES` is `safe` unless it says otherwise, and a
# field with `ref="nodes"` is `ref`; every other field is named below.
SAFE_TYPES = frozenset({"bool", "number", "int", "percent", "select", "color", "date",
                        "datetime", "ip", "cidr"})
HIDING_KINDS = frozenset({"safe", "ref", "words", "slug", "url", "keys", "pins", "admin"})

HIDING = {
    # A network's, a region's, a prefix's, a rack's or a watching's own name is
    # what it is called, as a place's is: given with it. Taking it away hid
    # nothing (2026-11-18: a cloud token read the zone "The Surface" as its
    # id, `workstation-vlan`, the same word); what is written ABOUT it is words.
    "zones": {"id": "safe", "name": "safe", "vlan": "safe", "lore": "words", "origin": "words"},
    "regions": {"id": "safe", "name": "safe", "map": "safe", "parent": "safe", "places": "pins"},
    "nodes": {
        # a place's own id and name are what makes it visible: given with it
        "id": "safe", "name": "safe", "zone": "safe", "role": "words", "lore": "words",
        "hw": "words", "mac": "safe", "scroll": "safe", "require_group": "safe",
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
    "rack_rear": {"rack": "safe", "name": "words", "desc": "words"},
    "vms": {"dynamic": "safe"},
    "certs": {"name": "words", "issuer": "safe", "host": "words", "expires": "safe",
              "renews": "safe", "note": "words"},
    "rites": {"name": "words", "when": "words", "host": "words", "note": "words",
              "key": "slug", "expect_every": "safe", "grace": "safe", "model": "safe",
              "at": "safe", "days": "safe", "between": "safe"},
    "stones": "admin",
    "collections": {"id": "slug", "name": "words", "note": "words", "services": "keys"},
    "chronicle": {"title": "safe", "note": "words", "url": "url", "embed": "url",
                  "chart": "safe", "range": "safe", "about": "words", "pane_group": "safe"},
    "abyss": {"title": "safe", "note": "words", "url": "url", "embed": "url",
              "chart": "safe", "range": "safe", "about": "words", "pane_group": "safe"},
    "maintenance": {"id": "slug", "reason": "words", "collections": "safe",
                    "services": "keys", "note": "words"},
    "meta": {"title": "safe", "surveyed": "safe", "art": "safe", "map_image": "safe",
             "tribute": "safe"},
}

#: Sections whose entries are ABOUT the places they name: one whose words name
#: a hidden place goes whole, as one that points at it by id does. Everywhere
#: else (a place, a network, a region, a prefix, a rack, a watching) the
#: entry is the viewer's own and only the field goes.
WORDS_DROP_ENTRY = frozenset({"cables", "stubs", "interfaces", "rack", "rack_rear", "vms",
                              "certs", "rites", "collections", "maintenance"})


def hiding(section_key, field_name, sub_name=None):
    """What `field_name` (or its `sub_name`) in `section_key` is to a viewer
    who may not see everything: one of `HIDING_KINDS`, or None when the
    catalogue declares nothing for it (which `test_hiding.py` refuses)."""
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
            return "admin"                    # a part of what only an admin gets
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
        # a list of entries: what it is lies in its parts
        return "parts" if fld.get("of") else None
    return None


# Order the editor presents them in — inventory first, then the wiring.
SECTION_ORDER = ["nodes", "zones", "regions", "prefixes", "routes", "interfaces",
                 "cables", "stubs", "racks", "rack", "rack_rear", "vms", "rites", "certs", "collections", "stones",
                 "maintenance", "chronicle", "abyss", "meta"]

# Order they sit in the *file*, which is a different question: the dataset is
# read by people, and it opens with `meta` and the realms, not with the places.
# The write path uses this to decide where a brand-new section goes; using the
# presentation order put the first `prefixes[]` above `meta`.
FILE_ORDER = ("meta", "zones", "regions", "nodes", "routes", "prefixes", "interfaces",
              "cables", "stubs", "racks", "rack", "rack_rear", "vms", "signals", "chronicle", "abyss", "rites",
              "certs", "collections", "stones")


#: Section keys that were renamed: old key -> new key. A dataset written before
#: the rename is read as if it used the new key (`upgrade`), and its next save
#: writes the new one.
RENAMED_SECTIONS = {"sets": "collections"}   # 2026-11-14


def upgrade(data):
    """Bring a dataset read from disk, a database or an import up to today's
    section names, in place, and return it. An old key's entries join the new
    key's, after them, skipping an id the new key already has, so a file that
    somehow carries both loses nothing it can keep. The section keeps its place
    in the file (a hand-edited map does not see a whole block move on its first
    save), and no list the caller holds is changed: a merge makes a new list,
    so `upgrade(dict(data))` leaves `data` exactly as it was. Anything that is
    not a dict passes through untouched for the validator to name."""
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
            merged = legacy         # the new key holds no list: the old one's stands
        else:
            merged = current        # the new key's value stands; the old one goes
        # rebuild in order: the new key where the old one was (or where it
        # already stood, when both were there)
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
    """The loaded map in a shape every reader can walk, in place, AFTER
    validation has named its problems (round 14 of the 2026-11-14 review). A
    hand edit can write a list section as a number (`"nodes": 5`) or a list
    field of a place as one (`"links": 5`); validation only warns, so the map
    is served, and dozens of readers loop over those. Each becomes an empty
    list. A `strings` field written as one id stays: it is read as a list of
    one (`as_list`)."""
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
    """The section descriptor for a top-level dataset key, or None."""
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
    """The whole catalogue, JSON-ready — the editor reads it inside
    `/api/v2/admin/context`."""
    return {
        "order": SECTION_ORDER,
        "sections": {k: SECTIONS[k] for k in SECTION_ORDER if k in SECTIONS},
        "signals": SIGNAL_FIELDS,
    }


# ── Value checking ───────────────────────────────────────────────────────────
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# The dataset's idiom for "no value here" — a real em-dash, not a missing key.
NONE_MARKS = ("—", "-", "")


_MAC_DIGITS = re.compile(r"[0-9a-f]{12}")


def mac_key(text):
    """One spelling of a MAC address, `aa:bb:cc:dd:ee:ff`, or "" when `text`
    is not one (2026-11-18). A place charted as `00-11-32-AA-BB-CC`,
    `0011.32aa.bbcc` or `00:11:32:aa:bb:cc` is the same card: the live source,
    the review and the importers each compared their own spelling, so a place
    charted with dashes was never matched to what UniFi reports (the 11-12
    audit, Live 11). For matching only: the map keeps what was typed."""
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
    # A calendar day, `YYYY-MM-DD` (TRIPWIRES: a token's `expires`). Blank
    # or the dataset's em-dash means none.
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
    # Text *or* a number. The dataset writes `"vlan": 4` and `"vlan": "—"`
    # in the same field, and both are correct.
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return f"{fld['name']} must be text or a number"
    return None


def _check_url(fld, value):
    if value == "" and not fld.get("required"):
        return None        # blank: a field that may be left out (a service's url, 2026-11-15)
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return f"{fld['name']} must be a url starting http:// or https://"
    return None


def carries_credentials(value):
    """Whether any http(s) URL inside `value`, at any depth, has a user name or
    password before its host (`https://user:pass@host/`).

    The write path asks this of what is being saved (`dataset.py`), not of the
    whole document: a map is read by viewers, tokens and exports, so a password
    typed into a link is a password published, and the moment to say so is when
    it is typed. An old file that already holds one still loads and still saves;
    a token is served such a URL without the credential either way
    (`redaction.bare_urls`).
    """
    if isinstance(value, str):
        text = value.strip()
        if not text.lower().startswith(("http://", "https://")):
            return False
        rest = text.split("://", 1)[1].split("?", 1)[0].split("#", 1)[0]
        authority, _, path = rest.partition("/")
        if "@" in authority:
            return True
        # `user:pa/ss@host`: a password with a bare "/" in it ends the
        # authority early, so the "@" lands in the path. The same rule
        # `redaction.bare_url` strips it by: an "@" in the path and a colon
        # in the authority with no port after it (2026-11-19, the 11-12
        # audit's Known limits 7: such a URL saved, password and all).
        return ("@" in path and not authority.startswith("[")
                and re.search(r":(?!\d*$)", authority) is not None)
    if isinstance(value, dict):
        return any(carries_credentials(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(carries_credentials(v) for v in value)
    return False


#: What the Desk is told. It does not repeat the URL: the answer is logged.
URL_CREDENTIALS = ("a URL here carries a user name or password (the user:pass@host form). "
                   "Remove it from the URL and keep the credential in the service itself; "
                   "everyone and everything that reads the map would read it too")


def _check_link(fld, value):
    # An absolute URL, or a relative path this app serves (the Abyss's
    # `report/security`). Protocol-relative `//host` is refused — it would
    # silently follow the page's scheme off-origin.
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
    # NaN and Infinity are floats to Python's JSON reader, and neither is less
    # than a minimum nor more than a maximum: both once passed (2026-11-18)
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
    # y may exceed 100 by design — THE WILD lives in the void below the map.
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
    # A place that *is* a network carries a prefix here (Tailscale's
    # 100.64.0.0/10), which is a legitimate answer to "where is it".
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
    # One id, as text (2026-11-13). This type had no check, so a list was saved
    # in a certificate's `place` and then broke every reader that looks the id
    # up. A field that holds several ids is `strings`, not `ref`.
    if not isinstance(value, str):
        return f"{fld['name']} must be one id, as text"
    return None


#: The check for each field type. A type with no entry (`json`) holds
#: anything as far as this table is concerned.
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
    """Return an error string for `value` under field `fld`, or None if fine.

    Absence is not this function's business — `required` is checked by the
    caller, which knows whether the key was present at all.
    """
    check = _CHECKS.get(fld["type"])
    return check(fld, value) if check else None


def _check_sub(prefix, holder, subfields, out):
    """Check one sub-object against its own field list, appending to `out`."""
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
    """Every problem with one entry of a section, as plain strings.

    An entry that is not an object is a problem either way. `strict` adds one
    check: a required value that is present but blank. Nothing is refused
    here; the caller decides what a problem means (the read path reports, the
    write path refuses).
    """
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
        # sub-objects carry their own field list
        if fld["type"] == "objects":
            for i, sub in enumerate(value):
                _check_sub(f"{name}[{i}]", sub, fld.get("of", []), out)
        elif fld["type"] == "object":
            _check_sub(name, value, fld.get("of", []), out)
    return out


def ref_fields(section_key):
    """[(field, subfield | None, target_section, type)] for every reference a
    section can hold. `subfield` is set for a reference inside a sub-object
    (`links` / `connects`); `type` is the type of the field holding the id."""
    out = []
    for fld in fields_of(section_key):
        if fld.get("ref"):
            out.append((fld["name"], None, fld["ref"], fld["type"]))
        for sub in fld.get("of", []) or []:
            if sub.get("ref"):
                out.append((fld["name"], sub["name"], sub["ref"], sub["type"]))
    return out


def followers(target):
    """[(section, field)] for every reference marked `follows` that points at
    `target`: the entry holding it is renamed with what it names, and removed
    with it (a cable's ends, 2026-11-16)."""
    return [(key, fld["name"]) for key in SECTIONS for fld in fields_of(key)
            if fld.get("follows") and fld.get("ref") == target]


def vlan_number(value):
    """`value` as a VLAN id (an int from VLAN_MIN to VLAN_MAX), or None when it
    is not one. A whole number and the same number as text (`10`, `"10"`) are
    the same VLAN, as a zone's `vlan` is written either way."""
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
    """[(field_name, target_section)] for every reference a section can hold,
    including references inside its sub-objects (as `links.connects`)."""
    return [(name if sub is None else f"{name}.{sub}", target)
            for name, sub, target, _ in ref_fields(section_key)]


def as_list(value):
    """A reference field's value as a list: one id, a list of them, or none."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def blank(section_key):
    """A new, empty entry with every default filled in."""
    out = {}
    for fld in fields_of(section_key):
        if "default" in fld:
            out[fld["name"]] = fld["default"]
        elif fld.get("required"):
            out[fld["name"]] = {"bool": False, "int": 0, "number": 0,
                                "percent": 50.0, "objects": [], "strings": []}.get(
                                    fld["type"], "")
    return out
