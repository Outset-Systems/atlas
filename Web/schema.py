"""The field catalogue — one definition of what the dataset *is*.

Every editable section of `lab-data.json` is described here once: its fields,
their types, which other sections they point at, and which are required. Three
consumers read this and nothing else:

  * `validation.py`  — turns the catalogue into the problem list served on
    `/api/status` and `X-Atlas-Data-Problems`.
  * `store/dataset.py` — coerces and strictly checks a write before it lands.
  * `/api/admin/context` — hands it to the browser (as its `schema` key), which
    renders every editor form and table from it. This line used to say
    `/api/admin/schema`, which is not a route that exists; corrected 2026-08-14
    while adding `stones`, because a reader greps for what the comment names.

That is the whole point: six editors built from one catalogue instead of six
hand-written forms that drift apart. Adding a field to the map is an entry
here, not a change in three places.

Doctrine carried over from the hand-edited era (ALIVE.md §0.5): the dataset is
richer than any schema we freeze. Unknown keys are **kept, not stripped** — a
section's `fields` list is what the editor knows how to show, never the limit
of what the file may hold.
"""

import ipaddress
import re

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
PREFIX_ROLES = ["prefix", "container", "reserved"]
RANGE_KINDS = ["dhcp", "reserved"]
#: How a service's button behaves — see LINK_FIELDS["open_in"] and glass.js.
OPEN_IN = ["auto", "here", "tab"]

# ── decoys (the decoy feed) ──────────────────────────────────────────────────
#: What kind of bait a stone is. Mirrors the token types the decoy feed charts; kept
#: loose rather than pinned to a provider's exact catalogue, because the point
#: of the field is "what would an intruder think they found".
STONE_KINDS = ["windows-folder", "network-folder", "web-bug", "dns",
               "doc-msword", "doc-excel", "doc-pdf", "aws-keys", "ad-account",
               "sensitive-command", "kubeconfig", "other"]
#: Where a stone sits, which is what decides the escalation policy: ANY trip on
#: an `internal` stone reaches a human. `wan` is the only zone whose trips may
#: ever be filed quietly.
STONE_ZONES = ["internal", "wan"]
#: How loud a trip here should be. `critical` is the wake-a-human tier.
STONE_SEVERITIES = ["info", "low", "medium", "high", "critical"]

# The link sub-object, reused by nodes.
LINK_FIELDS = [
    f("label", "text", required=True, help="The service name, as shown on the card."),
    f("url", "url", required=True, help="Where the service answers. http:// or https://"),
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
    f("connects", "strings", label="Reaches", ref="nodes",
      help="Places this one service talks to. Narrows the reach web on THE PATH."),
    f("path", "strings", label="Road out", ref="nodes",
      help="The hops its traffic actually takes, IN ORDER, starting from this "
           "place — e.g. `gateway, edge, traefik, pangolin, the-wild` for "
           "something reached from the internet. Drawn as a chain instead of a "
           "star, so the map can say *through*. Every consecutive pair must be a "
           "charted route, or the map is drawing a road that isn't there."),
    f("open_in", "select", options=OPEN_IN, default="auto", label="Opens",
      help="`auto` asks the service whether it allows framing and shows it in "
           "THE VIEWING GLASS when it does. `here` insists. `tab` never frames "
           "it — for anything that only works with the whole window."),
    f("require_group", "text", label="Requires group",
      help="Hide this service from anyone whose Hub groups don't include it."),
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
                   "Leave blank for a segment with no addressing."),
            f("hue", "color", required=True, help="The realm's colour, used everywhere."),
            f("net_hue", "color", label="Road colour",
              help="Optional separate colour for this realm's roads on the network layer."),
            f("lore", "longtext", required=True, help="The in-world line shown on its card."),
            f("label_x", "percent", label="Label X", required=True,
              help="Where the realm's name sits on the map, 0–100% across."),
            f("label_y", "percent", label="Label Y", required=True,
              help="…and 0–100% down."),
            f("hide_label", "bool", label="Hide the label",
              help="Keep the realm, drop its name from the map."),
        ]),

    # REGIONS (v1.49.0, PLAN-REGIONS.md): a rectangle on a map that has its
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
            f("zone", "ref", ref="zones", required=True, help="Which realm it belongs to."),
            f("x", "percent", required=True, help="Map position, 0–100% across."),
            f("y", "percent", required=True,
              help="Map position, 0–100% down. Past 100 puts it in the void below."),
            f("role", "text", required=True,
              help="What it does, in a phrase. The part before `·` becomes its epigraph."),
            f("lore", "longtext", required=True, help="The in-world flavour line on its card."),
            f("ip", "ip", label="IP",
              help="Its address, or `—` for none. A whole prefix is allowed for a "
                   "place that *is* a network (Tailscale's 100.64.0.0/10)."),
            f("hw", "text", label="Hardware", help="The mono data line: OS · RAM · disks."),
            f("hue", "color", help="Override the marker colour. Defaults to the realm's."),
            f("shape", "select", options=NODE_SHAPES,
              help="Marker shape. Blank = the default circle."),
            f("parent", "ref", ref="nodes",
              help="Its host, if this is a vassal. Draws it as a child on THE PATH, "
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
              help="Charted, but not drawn. Its services still list in THE INDEX; its marker and its roads are skipped. For a place that is decided but not yet laid."),            f("require_group", "text", label="Requires group",
              help="Hide this place from anyone whose Hub groups don't include it."),
            f("links", "objects", of=LINK_FIELDS, label="Services",
              help="Everything hosted here. Each becomes a card button and an Index row."),
            f("accounts", "objects", of=ACCOUNT_FIELDS, label="Accounts",
              help="Who can get into this place, and how far in. Drawn in the "
                   "ACCOUNTS scene. Redacted for anyone not cleared to see "
                   "everything — chart the posture, never a credential."),
        ]),

    "routes": section(
        "routes", "road", "roads", noun="route",
        id_field=None, title_field=None,
        lore="the roads between places — what the network layer draws",
        subtitle="Network links. Drawn on the map's ◈ layer and on THE PATH.",
        fields=[
            f("from", "ref", ref="nodes", required=True),
            f("to", "ref", ref="nodes", required=True),
            f("kind", "select", options=ROUTE_KINDS, default="vlan",
              help="wan = the world · edge = the way in · vlan = inside a realm · "
                   "mesh = Tailscale · telemetry = a scrape path."),
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
            f("zone", "ref", ref="zones", help="The realm this prefix serves, if one."),
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
        subtitle="Physical and virtual ports. Draws the port map in THE LEDGER.",
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

    "rack": section(
        "rack", "vessel", "vessels", noun="rack slot",
        id_field=None, title_field="name",
        lore="the iron in its niches — the front elevation",
        subtitle="Rack slots, front of rack. THE ARMORY draws these.",
        fields=[
            f("u", "text", label="U slot", required=True,
              help="`U7` for one unit, `U3–U4` for two. The Rearrange tool writes this too."),
            f("name", "text", required=True, help="What sits here."),
            f("size", "int", default=1, min=1, max=48, help="How many U it occupies."),
            f("node", "ref", ref="nodes",
              help="The place this vessel is, if it's charted on the map."),
            f("desc", "text", label="Description",
              help="What this slot holds, in your words. Shown in the Armory's pane "
                   "for every vessel; for an uncharted one it also stands in for the role."),
        ]),

    "rack_rear": section(
        "rack_rear", "rear fitting", "rear fittings",
        id_field=None, title_field="name",
        lore="what hangs behind the rack",
        subtitle="Rear-of-rack items — PDUs, shelves, anything without a front U.",
        fields=[
            f("name", "text", required=True),
            f("desc", "text", label="Description"),
            f("node", "ref", ref="nodes"),
        ]),

    "vms": section(
        "vms", "vassal", "vassals", noun="vm",
        lore="the host's memory, divided among those it carries",
        subtitle="Virtual machines and their allocations. THE TRIBUTE draws these.",
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
        subtitle="decoys — bait with no legitimate caller. Anything that "
                 "touches one is an event, not a maybe.",
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
            f("host", "node", label="Guards",
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
            f("nodes", "strings", ref="nodes", required=True, label="Places",
              help="Which places are down for it. Their alarms stay quiet while it's open."),
            f("starts", "datetime", required=True, help="When it opens (UTC)."),
            f("ends", "datetime", required=True,
              help="When it closes (UTC). Required on purpose — a window with no "
                   "end is a suppression somebody has to remember to remove."),
            f("repeat", "select", options=list(("none", "daily", "weekly", "monthly")),
              default="none", help="Recurring windows re-open on the same schedule."),
            f("note", "text", help="Anything the next person should know."),
        ]),

    "meta": section(
        "meta", "realm setting", "realm settings", kind="object",
        id_field=None, title_field=None,
        lore="the surveyor's own notes",
        subtitle="Names and constants for the whole map.",
        fields=[
            f("title", "text", required=True, help="The name of this atlas."),
            f("surveyed", "text", help="When the map was last walked, `YYYY-MM-DD`."),
            f("art", "text", help="Which base render is in use — a note to your future self."),
            f("map_image", "text", label="Base render",
              help="The picture the map is drawn on — a bare filename, e.g. "
                   "`floor-2.webp`. Blank uses the render the Atlas ships with. "
                   "Upload your own in the Desk. Places are positioned in fractions "
                   "of the image, so swapping it keeps every marker where it is."),
            f("tribute", "object", label="The Tribute", of=[
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
              ], help="The numbers THE TRIBUTE divides among the vassals."),
        ]),
}

# Sections that hold live-signal wiring rather than inventory. Edited through
# their own small panel, not the generic table.
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

# Order the editor presents them in — inventory first, then the wiring.
SECTION_ORDER = ["nodes", "zones", "regions", "prefixes", "routes", "interfaces",
                 "rack", "rack_rear", "vms", "rites", "certs", "stones",
                 "maintenance", "chronicle", "abyss", "meta"]

#: Sections the dataset writer must ignore — they live in their own stores.
NON_DATASET = tuple(k for k, s in SECTIONS.items() if s["store"] != "dataset")

# Order they sit in the *file*, which is a different question: the dataset is
# read by people, and it opens with `meta` and the realms, not with the places.
# The write path uses this to decide where a brand-new section goes; using the
# presentation order put the first `prefixes[]` above `meta`.
FILE_ORDER = ("meta", "zones", "regions", "nodes", "routes", "prefixes", "interfaces",
              "rack", "rack_rear", "vms", "signals", "chronicle", "abyss", "rites",
              "certs", "stones")

# Sections the dataset may carry that the catalogue does not model. They round-
# trip untouched; the editor simply has no page for them.
UNMODELLED_TOP_KEYS = ("signals",)


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
    """The whole catalogue, JSON-ready, for `/api/admin/schema`."""
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


def check_value(fld, value):
    """Return an error string for `value` under field `fld`, or None if fine.

    Absence is not this function's business — `required` is checked by the
    caller, which knows whether the key was present at all.
    """
    t = fld["type"]
    name = fld["name"]

    if t in ("text", "longtext", "path", "slug"):
        if not isinstance(value, str):
            return f"{name} must be text"
        if t == "slug" and value and not _SLUG_RE.match(value):
            return (f"{name} {value!r} is not a valid id — lowercase letters, digits, "
                    "dot, dash and underscore only, starting with a letter or digit")
        return None

    if t == "datetime":
        if not isinstance(value, str):
            return f"{name} must be a timestamp"
        if value in NONE_MARKS:
            return None
        from datetime import datetime
        try:
            datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return f"{name} {value!r} is not a date and time (YYYY-MM-DDTHH:MM)"
        return None

    if t == "scalar":
        # Text *or* a number. The dataset writes `"vlan": 4` and `"vlan": "—"`
        # in the same field, and both are correct.
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return f"{name} must be text or a number"
        return None

    if t == "url":
        if not isinstance(value, str) or not value.startswith(("http://", "https://")):
            return f"{name} must be a url starting http:// or https://"
        return None

    if t == "link":
        # An absolute URL, or a relative path this app serves (the Abyss's
        # `report/security`). Protocol-relative `//host` is refused — it would
        # silently follow the page's scheme off-origin.
        if not isinstance(value, str):
            return f"{name} must be text"
        if value.startswith(("http://", "https://")):
            return None
        if value.startswith("//") or ":" in value.split("/")[0]:
            return f"{name} must be an http(s) url or a relative path"
        return None

    if t == "color":
        if not isinstance(value, str) or not _HEX_RE.match(value):
            return f"{name} must be a hex colour like #C9A554"
        return None

    if t == "bool":
        return None if isinstance(value, bool) else f"{name} must be true or false"

    if t in ("int", "number"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{name} must be a number"
        if t == "int" and not float(value).is_integer():
            return f"{name} must be a whole number"
        if "min" in fld and value < fld["min"]:
            return f"{name} must be at least {fld['min']}"
        if "max" in fld and value > fld["max"]:
            return f"{name} must be at most {fld['max']}"
        return None

    if t == "percent":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{name} must be a number"
        # y may exceed 100 by design — THE WILD lives in the void below the map.
        if not (-40 <= value <= 140):
            return f"{name} {value} is off the table"
        return None

    if t == "select":
        opts = fld.get("options", [])
        if value in NONE_MARKS and "" in opts:
            return None
        if value not in opts:
            return f"unknown {name} {value!r}"
        return None

    if t == "ip":
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

    if t == "cidr":
        if not isinstance(value, str):
            return f"{name} must be text"
        if value in NONE_MARKS:
            return None
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            return f"{name} {value!r} is not a prefix like 10.0.20.0/24"
        return None

    if t == "strings":
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            return f"{name} must be a list of text values"
        return None

    if t == "objects":
        if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
            return f"{name} must be a list of entries"
        return None

    if t == "object":
        if not isinstance(value, dict):
            return f"{name} must be a group of settings"
        return None

    if t == "json":
        return None

    return None


def check_entry(section_key, entry, strict=False):
    """Every problem with one entry of a section, as plain strings.

    `strict` also rejects entries that are not dicts and required-but-blank
    values. Non-strict is the historic read path: report, never refuse.
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
                for subfld in fld.get("of", []):
                    sname = subfld["name"]
                    if sname not in sub or sub[sname] is None:
                        if subfld.get("required"):
                            out.append(f"{name}[{i}]: missing {sname}")
                        continue
                    suberr = check_value(subfld, sub[sname])
                    if suberr:
                        out.append(f"{name}[{i}]: {suberr}")
        elif fld["type"] == "object":
            for subfld in fld.get("of", []):
                sname = subfld["name"]
                if sname not in value or value[sname] is None:
                    if subfld.get("required"):
                        out.append(f"{name}: missing {sname}")
                    continue
                suberr = check_value(subfld, value[sname])
                if suberr:
                    out.append(f"{name}: {suberr}")
    return out


def refs_of(section_key):
    """[(field_name, target_section)] for every reference a section can hold,
    including references inside its sub-objects (as `links.connects`)."""
    out = []
    for fld in fields_of(section_key):
        if fld.get("ref"):
            out.append((fld["name"], fld["ref"]))
        for sub in fld.get("of", []) or []:
            if sub.get("ref"):
                out.append((f"{fld['name']}.{sub['name']}", sub["ref"]))
    return out


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
