# The Atlas API

Atlas never scans your network. What it holds is what a person charted and
approved, which makes it a good first question for a script or an AI agent:
ask the map what is here before acting on it.

This page covers what an API token can read. The machine-readable version is
[`openapi.json`](openapi.json) (OpenAPI 3.1), and a running Atlas serves the
same document at `/api/v2/openapi.json`.

## Turn it on, then get a token

Agent access is off on a new Atlas: every token is refused and the MCP endpoint
answers 404. An admin turns it on, and can turn it off again at any time, which
stops every token at once and keeps them.

1. Sign in as an admin.
2. Open Settings, then Connections.
3. Press **Turn on** beside "Agent access is off".
4. Choose what the token is for. **A local model or a script** makes a full
   token, which is what this page describes. **A cloud AI tool** makes a cloud
   token, which reads a reduced view through the MCP endpoint only and is
   refused on every path below with a 403:
   [Atlas for AI agents](mcp.md#what-a-cloud-token-reads) describes it.
5. Name the token, choose how long it lasts (30, 90 or 365 days, or never; 7 or
   30 days for a cloud token) and create it.

`ATLAS_AGENT_API=0` in the deployment keeps agent access off, and the Settings
screen cannot turn it on. `ATLAS_AGENT_API=1` starts it on. See
[the configuration reference](configuration.md).

The token is shown once. Atlas keeps only a hash of it, so a lost token is
revoked and replaced, not recovered. Revoking takes effect at once.

Tokens need accounts: a standalone Atlas with no sign-in has no admin to issue
one.

## What a token can and cannot do

- **It reads.** There is no write scope. Changes to the map are made by a
  person in a session.
- **It sees no more than a signed-in viewer with no groups, and a little
  less.** Places marked for a group are removed, along with every route,
  address, job and event that names them. Account rosters and tripwires are
  never sent to a token. Three more things a person reads and a token does not:
  - **Credentials in a URL.** A charted URL reaches a token without
    `user:pass@` and without its query string, whatever its scheme. A secret in
    a URL's path, or in a note that merely contains a URL, is not caught, so do
    not chart those.
  - **A job's own words.** What a scheduled job wrote about its run (its
    `note`) and the address it reported from are left out of `/api/v2/rites`.
  - **Who acknowledged an event.** An event says that it was acknowledged and
    when, not by whom or in what words. This holds for every viewer who is not
    an admin.
- **It opens eight doors**, listed below. Every other path ignores the token
  and answers as it would to a stranger.
- **It is limited to 120 requests a minute.** Past that the answer is 429 with
  `Retry-After: 60`. The limit is one budget for the token, however many
  workers serve it. An address that keeps presenting no token or a bad one to
  the MCP endpoint is told to wait a minute as well.
- **It can be bound to where it is used from.** A new token works only from the
  local network (loopback and the private address ranges) unless you untick
  that when you create it; `"networks": null` in the request asks for any
  address, and a list such as `["192.168.7.0/24"]` names networks. From
  anywhere else the token is refused with 403 and stays valid. This stops a
  leaked copy being used from outside. It does not limit what a tool on your
  network does with what it reads, and it trusts the address Atlas sees: behind
  a reverse proxy, name the proxy in `ATLAS_TRUSTED_PROXIES` or every caller
  looks local. Settings, Connections shows the address Atlas sees you at.
- **Everything it reads is written down.** Each request a token makes adds a
  line to `token-reads.jsonl` in the data directory: when, which token, the
  address, the path or the MCP tool with its arguments, the answer's status,
  size and SHA-256, and how many charted places the answer named. A refusal of
  a valid token is logged with its reason. The answers themselves are not
  kept. An admin reads the lines for a token in Settings, Connections ("What it
  read") or at `GET /api/v2/admin/tokens/reads`. Lines are kept for
  `ATLAS_AGENT_LOG_DAYS` (90). Revoking a token does not erase what it read.

What a tool reads leaves with it. A cloud AI tool sends what it reads to its
model's vendor, so a token handed to one takes this map off your network:
names, IP and MAC addresses, service URLs and the notes you wrote. Use a local
model where you can. Atlas cannot tell where a client sends what it reads.

## Try it

```sh
export ATLAS=https://atlas.example.net
export TOKEN=atl_...

curl -s -H "Authorization: Bearer $TOKEN" "$ATLAS/api/v2/lab-data"
```

If a proxy puts its own sign-in in front of Atlas, point the script at Atlas
directly. That proxy's login cannot be answered with a token.

Atlas checks who is asking in every mode that has sign-in: `accounts`, and
`hub` or `hybrid` (both refuse to start without `ATLAS_HUB_SECRET`).

## The paths

| Path | What it answers |
|---|---|
| `GET /api/v2/lab-data` | The whole map: places, zones, routes, addresses, racks, certificates, scheduled jobs |
| `GET /api/v2/signals` | Live health of places and services, and whether each source answered |
| `GET /api/v2/rites` | Every scheduled job and whether it ran |
| `GET /api/v2/events` | The history of state changes, newest first |
| `GET /api/v2/places/roster` | Every place, one row each: live state, network, addresses, review, repairs, nearest certificate, collections |
| `GET /api/v2/overview` | The realm at a glance: places by state, what is down and what depends on it, unacknowledged events, repairs this week, lapsing certificates, review, changes, sources, favourites |
| `GET /api/v2/maps` | The pictures the map can be drawn on |
| `GET /api/v2/openapi.json` | The reference for this list |
| `POST /api/v2/mcp` | The MCP endpoint, for AI tools |

### The map: `/api/v2/lab-data`

One JSON document. The sections you will use most:

- `nodes`: the places. Each has an `id`, a `name`, a `zone`, usually an `ip`
  and a `role`, and `links`, which are the services on it.
- `zones`: the network segments places sit in.
- `routes`: which place connects to which, as `from` and `to`.
- `cables`: the physical wiring, port to port. Each end is a place (`a`, `b`)
  or a stub (`a_stub`, `b_stub`), with its port (`a_port`, `b_port`), and the
  cable's `kind`, `vlan`, `tagged`, `poe_w`, `speed` and `state`. `stubs` are
  the gear the cables reach that is not a place (`id`, `name`, `kind`). A cable
  with a place you may not see at either end is not sent, and while anything is
  hidden from you a cable's `note` is not sent either.
- `prefixes`, `interfaces`, `racks`, `certs`, `rites`: addresses, ports, the
  rack, certificates and scheduled jobs.
- `names` (what each name is meant to be) is never sent to a token.

No field is promised present. Atlas serves a hand-edited dataset as it is and
keeps keys it does not know, so read defensively.

Each place may carry `provenance`, stamped by Atlas whenever the place changes:

```json
"provenance": {
  "charted_at": "2026-11-09T21:14:03Z", "source": "unifi",
  "changed_at": "2026-11-09T21:14:03Z",
  "reviewed": false
}
```

`reviewed` is false for a place an import wrote and nobody has checked, and
true once a person saves it by hand or marks it as checked in the Desk
(`reviewed_at` says when). `changed_since_review: true` is added when a place has
changed since it was reviewed, most often because an import added to it: the
review stands, and what changed is unconfirmed until the next one. Who charted,
changed and reviewed a place is kept too, and shown to admins only: a token
is told when and whether, not who. A place with no `provenance` was charted before Atlas kept it:
treat who and when as unknown. Nothing a client sends under this key is kept.

The reply carries an `ETag`. Send it back as `If-None-Match` and an unchanged
map answers 304 with no body:

```sh
curl -s -o map.json -D - -H "Authorization: Bearer $TOKEN" "$ATLAS/api/v2/lab-data" | grep -i etag
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
     -H 'If-None-Match: "<the etag>"' "$ATLAS/api/v2/lab-data"
```

### Live health: `/api/v2/signals`

```sh
curl -s -H "Authorization: Bearer $TOKEN" "$ATLAS/api/v2/signals"
```

`nodes` and `services` map an id to a `state`: `healthy`, `degraded`, `down`,
`slumbering` or `maintenance`. `sources` names each monitoring source as `ok`
or `silent`.

**A place with no entry is unknown, not healthy.** If a source is `silent`,
nothing it watches can be called fine. This call never fails: a source that
does not answer is reported, and the rest of the feed is still sent.

`confirmed_by` maps a place's id to the source whose answer gave it its state
in this feed. A place under repair is not in it: its state comes from the
window.

`sources_at` gives each source the time it last answered, or null if it has
not since the server started. Each server process keeps its own, in memory.

### The places table: `/api/v2/places/roster`

```sh
curl -s -H "Authorization: Bearer $TOKEN" "$ATLAS/api/v2/places/roster"
```

One row per place, made from the map and the live health above and cut the
same way, so a place a token may not see has no row and is not named in any
other. Each row holds:

- `state` and `cause` from the live health, and `confirmed_by`, the source
  that gave the state.
- `zone` and `zone_name`, `kind`, `role`.
- `addresses`: the place's `ip` and `mac`, then `ipv6`, `hostname` and `fqdn`
  when a hand edit added them. Only the ones with a value.
- `services`: how many services the place lists.
- `charted_source`, `reviewed`, `reviewed_at`, `changed_since_review` and
  `unchecked`, from its `provenance`. Who reviewed it is for admins.
- `maintenance`: `now` when a repair window is open on it, and `next`, when
  the next one opens.
- `cert`: the certificate tied to this place that lapses first, with `days`
  left (negative once lapsed). Only a certificate whose `place` names the
  place counts; one that names it only in `host` is not guessed at.
- `collections`: the collections it is in, and `depends_on`.
- `premise`: the premise it stands in (its own `premise`, its rack's, its
  host's, or the one premise its older `location` text names), or null;
  `premise_path`, that premise's ids from the site down; `device`, what it is
  as a device (`laptop`, `printer` …) or null.

Beside the rows: `zones`, `collections` (named lists of places; a collection
is not an access group), `premises` (every premise: `id`, `name`, `level`,
`parent`) and `stamp`, the map's version. `?premise=<id>` keeps the places in
that premise or under it, and `?device=<word>` one kind of device.

The map's `premises` section (2026-11-22) is where things physically stand:
`site`, `building`, `floor`, `room`, `desk`, each with a `parent` of a broader
level. A premise named after a place a reader may not see is not sent to
them, and a site's `lat` and `lon` are sent to admins only. Before 2026-11-14
the two `collections` keys were called `sets`; a map file that still has a
`sets` section is read as collections and saved back under the new name.

### The realm at a glance: `/api/v2/overview`

```sh
curl -s -H "Authorization: Bearer $TOKEN" "$ATLAS/api/v2/overview"
```

The facts OVERVIEW shows, made from the map and the live health above and cut
the same way, so a place a token may not see is in no part of it. It stores
nothing and asks no source anything new.

- `states`: how many of your places are `healthy`, `degraded`, `down`,
  `slumbering` or under `maintenance`, how many have no state (`unknown`, not
  healthy) and the `total`.
- `down`: each place that is down or degraded on its own account, down first.
  A place whose fault another place you can see explains is that place's
  fallout and is left out. `downstream` lists every place that needs it,
  directly or through another, from `parent` and `depends_on` only.
  `declared: false` means nothing is declared to depend on it, which is not the
  same as nothing being affected.
- `unacked`: how many events nobody has acknowledged, of any gravity, and the
  newest eight.
- `maintenance`: repair windows open now (`now: true`) or opening within seven
  days, with this occurrence's `starts` and `ends` and the places in each. A
  window that names only places you may not see is left out, and so is one
  whose reason names one.
- `certs`: certificates with 30 days or fewer left, lapsed ones included
  (`days` is negative), soonest first, with the place each is tied to.
- `review`: `unchecked` (written or changed by an import and not checked
  since), `stale` (no review, or none in 90 days) and up to eight of the stale
  ones, never-reviewed first. When, never who.
- `changes`: for a token, `count_7d`, how many of its places changed in seven
  days. It names nobody. An admin in the browser gets the change log instead.
- `sources`: `all_ok` and how many are `silent`. Which one is silent, when
  each last answered and where its own console opens (`url`, `open_in`) are
  for admins: a token gets an empty `items`.
- `favourites`: the services marked as a favourite on the map
  (`links[].favourite`), as `internal` and `external` lists of `{label, url,
  open_in, place}`, in the map's order. Only services the reader may see, and
  an address charted on two places is listed once.

`generated_at` says when it was made. `admin` is always false for a token, and
the map's drift from its sources, which an admin also sees here, is not sent.

### Scheduled jobs: `/api/v2/rites`

Each job as charted, plus a `verdict`: `kept`, `late`, `missed`, `failed`,
`awaited` (watched, never reported) or `unwatched` (nothing is expected of
it). `age_s` is the seconds since it last reported. `last` holds when the job
last reported, how it ended and how long it took; `runs` is the recent history
of the same. A token is not sent the text the job wrote or where it posted from.

### History: `/api/v2/events`

```sh
curl -s -H "Authorization: Bearer $TOKEN" "$ATLAS/api/v2/events?limit=20&unacked=1"
```

- `limit`: how many, default 100. The history keeps 2,000.
- `unacked=1`: only events nobody has acknowledged.

Each event says what changed (`kind`, `target`, `name`), from which state to
which, and when it was first observed. A `cause` means another fault explains
this one. `outlived: true` marks a place still down after the fault that
explained it has cleared: its own outage starts there, so `from` and `to` are
both `down`. `ack.at` is when someone acknowledged it; who, and what they wrote,
are for admins, and so is where an alert about it was sent.

### AI tools: `/api/v2/mcp`

The endpoint speaks the Model Context Protocol over HTTP, both the 2026-07-28
revision and the earlier `initialize` handshake. It offers nine read-only
tools. [Atlas for AI agents](mcp.md) has the setup, the tools and how an agent
should read the answers.

## Alerts: admins only, never a token

The alerts' own routes (used by NODES and Settings › Alerts) are listed here so an operator knows they exist.
They belong to the page, not to this contract, and every one of them refuses a
token (403): they sit behind the admin check, and an API token reads as a
viewer with no groups. Writes need the page's write header (`X-Atlas-Write`),
a same-origin request, and a writable Atlas (`ATLAS_READONLY` refuses them).
While alerts are off (`ATLAS_ALERTS` unset, or `ATLAS_ALERT_HOSTS` empty) the
read still answers, and the save and the test send answer 403 with how to
turn them on. See [Alerts](configuration.md#alerts) for the settings.

| Route | What it does |
|---|---|
| `GET /api/v2/admin/alerts` | `{doc, stamp, status, states, kinds}`. `doc` holds `rules`, `digest` and `destinations`. A destination's `secret` is the secret's name only, with `secret_bound` saying whether it is bound to the destination's address; the value is never returned. `status` says whether alerts are on, which hosts are allowed, whether `ATLAS_PUBLIC_URL` is set, the poll's interval, whether it runs in the worker that answered, when any worker last ran the alerts, and the ids of rules suspended because their target is no longer visible to a viewer with no groups. `states` are the states a rule may name. `kinds` are the kinds of destination that can send, in the order offered, each `{kind, label, fields}` as declared in `Web/senders/`; Settings › Alerts draws its destination form from them. |
| `POST /api/v2/admin/alerts` | `{doc, expect}`: replace the whole document. `expect` is the `stamp` you read, and is required (400 without it); a document changed since answers 409. Problems answer 422 with `problems`. A secret is bound to the destination's address when it is named; a changed address drops the binding (the answer's `notes` say so) until the secret is named again: a new name, or `"bind": true` on that destination. |
| `POST /api/v2/admin/alerts/destinations/<id>/test` | Sends "Atlas test from <the map's title>" through the same path as an alert, at most 10 a minute per admin (shared with the other connection tests). Answers `{outcome, status, why}` only: `delivered`, `refused` with the HTTP status, `unreachable` or `blocked`, never anything the receiver said. |
| `GET /api/v2/admin/alerts/deliveries?limit=` | The delivery log, newest first, default 100, at most 1000: `at`, `rule` (its id; `test`, `digest` or `fold` for those sends), `destination` (its name), `events`, `outcome`, `status`, `why`, and `folded` on an "and N more" message. |

A rule is `{id, name, note, enabled, target: {kind: place|collection|network, id},
to: [states], for_minutes: 0-1440, destination}`. The digest is `{enabled,
hour: 0-23 (the server's local time), destination, cert_days, review_days,
drift, uncharted}`; `uncharted` must be false for now. A destination is `{id,
name, kind: ntfy|gotify|webhook, url, secret}`; its URL may carry no user name,
password or query string, and its host and port must be in
`ATLAS_ALERT_HOSTS`.

## One check: the page's, never a token

Atlas's own checks answer through `/api/v2/signals`; the first two routes here ask about one of them, the third asks one place's chain. They belong to the page, and none is a token's door: a token is not looked at on them, so the request is refused as one with no session.

| Route | What it does |
|---|---|
| `GET /api/v2/checks/<key>` | The last answer of the check the map gives `key` (a place id, or a service key: `<place id>/<label>`, or the monitor its link names), for any signed-in viewer: `key`, `thing` (place or service), `authority` (`place`, `service`, or `shadow`/`shadow-place` beside a monitor, admins only), `type`, `asks` (the URL, address and port, or name, in words), `url`, `host`, `port`, `expect`, `every`, `retries`, `timeout`, `state` (what the live feed serves now), `stale`, `said` (the last answer), `fails`, `since`, `asked_at`, `heard_at`, `ms`, `error` (fixed words, never what the service sent), `status`, `tls` (the certificate seen; its `names` only for a viewer who sees everything) and `on` (the checks source is on). An unknown key, a thing with no check and a thing the viewer may not see all answer the same 404 `{"error": "no such check"}`. |
| `POST /api/v2/admin/checks/run` | `{"key": ...}` and nothing else (400 otherwise): ask that check now and store the answer where a round would, so one failed ask is one failure of its retries. Admins only, with the write rules of every admin POST. Answers the GET's shape plus `asked: true`; `asked: false, stored: true` with the stored answer when another worker holds the store; 429 with `Retry-After` when the check was asked less than 20 seconds ago or `ATLAS_CHECKS_PER_MINUTE` checks were asked in the last minute; 409 with `why` when a Kuma monitor watches it (`kuma`, and the `monitor`) and "Check beside Kuma" is off, when it is unmanaged, or when the checks source is off; 404 as above. |
| `POST /api/v2/admin/diagnose` | Where does it break? `{"id": "<place id>"}` and nothing else (400 otherwise: the body names a place, never an address). Asks one place's chain from the Atlas host, in order, and stops at the first step that fails: each thing on its path from the head of the network down to it, nearest the head first (`hop`); its charted DNS name, when its own check or one of its services names one (`dns`); the place itself, by its own check asked as `checks/run` asks it (and stored the same way), else a tcp connection to its address on a port the map charts for it (`place`); and, only when `ATLAS_DIAGNOSE_OUTSIDE` names an outside address, that address (`internet`). Each step asked costs one check of the `ATLAS_CHECKS_PER_MINUTE` budget; only the place's own check is stored. Admins only, with the write rules of every admin POST. Answers `{id, name, asked: true, steps, broke_at, path}`: each step is `{step, thing, name, asks, state, why, ms, error}`, `state` is `up`, `down` or `skipped`, `why` says why a step was skipped (`stub`, `no-address`, `no-port` (no check of its own, and no service Atlas asks at its address to lend a port), `off` (its check is `off`), `hidden` (its `thing` and `name` are null), `planned`, `unmanaged`, `kuma` (a Kuma monitor watches it and "Check beside Kuma" is off), `not-asked` (its address may not be asked, or it gave no answer at all), `busy` (another worker asked its check a moment ago), `stopped` (an earlier step failed), `late` (the steps before it took the chain past 45 seconds)), `error` says in fixed words why a step was down; `broke_at` is the index of the step that failed, or null; `path` is `{things, links}`, head first, null in place of anything that names a place the viewer may not see, and empty for a place nothing reaches. 429 with `Retry-After` and `why`: `soon` when the place, or its own check, was asked less than 20 seconds ago, `spent` when the minute's budget cannot cover every step (nothing is asked). The steps are weighed and counted against the budget together, before the first is asked. A hop asked less than 20 seconds ago is not asked again: its last answer stands. 409 with `why`: `unmanaged`, `planned`, or `off` (the checks source is off). 404 `{"error": "no such place"}` for an id that is no place the viewer may see. |

## TOPOLOGY's layout: the page's, never a token

Where an admin put each card on the TOPOLOGY canvas (2026-11-17), kept in its own file (`ATLAS_TOPOLOGY_LAYOUT`) beside the marker positions. It is not map data: a write makes no revision and has no undo. Neither route is a token's door.

| Route | What it does |
|---|---|
| `GET /api/v2/topology/layout` | `{v: 1, cards: {<id>: {x, y}}, stamp}` for any signed-in viewer: the cards of the places and stubs on that viewer's own map only, so a place hidden from them, and a stub whose every cable reaches one, is left out. `x` and `y` are the card's top-left corner in the canvas's units (a card is 176 by 64). `stamp` is a short hash of the file. A thing with no card here is laid out by the canvas itself. |
| `POST /api/v2/topology/layout` | `{cards, expect, replace}`. `cards` maps an id to `{x, y}` (finite numbers within 1,000,000, kept to a tenth) or to `null` (forget that card, so it is laid out again); `replace: true` makes `cards` the whole layout, so `{"cards": {}, "replace": true}` throws it away. `expect` is the `stamp` you read: a layout changed since answers 409 `{error, stamp}` with the stamp on file now, and nothing is saved. An id that is no place or stub on the map is not kept. Answers `{ok, saved, total, stamp}`. A body of another shape is a 400 with one sentence. Admins only, with the write rules of every admin POST (`X-Atlas-Write`, same origin, `ATLAS_READONLY` refuses it). |

## TOPOLOGY's connections sheet: the page's, never a token

The TOPOLOGY view's Connections CSV button (2026-11-17). Any signed-in viewer may ask, and gets the rows of their own map: it is built from the dataset as `/api/v2/lab-data` gives that viewer, so a place hidden from them is in no column, not as a row, not as what a row is connected to, and not inside another row's path (its cables went with it, and the row that hung from it is left blank). It is not a token's door: a token is not looked at here, so a request with only a token is refused as one with no session. A tool reads the same thing from `/api/v2/lab-data`.

| Route | What it does |
|---|---|
| `GET /api/v2/topology/connections.csv` | One row per place, and per stub that has a cable, sorted by name. The columns are Device, Connected to, Port, Far port, VLAN, PoE (W) and Path to the head: the cable the device hangs from on its way up to the head of the network, its own port and the port at the other end, the cable's VLANs as the canvas writes them (`U10`, `U1 T10,20`), its watts, and the names from the device up to the head joined with ` › `. A device that hangs by no cable (a head, or one joined only by a route or a host) has those columns blank: never a guess. A cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return is written with a `'` before it, so a spreadsheet does not run it. UTF-8 with a byte-order mark, CRLF lines, `Content-Disposition: attachment; filename="<map>-connections-<YYYY-MM-DD>.csv"` (the server's own day), `Cache-Control: no-store`. |

## THE NAMES: the page's, never a token

Every name the map uses, and what it is meant to be (2026-11-22). The map's
`names` section says it, by name or by domain: `{"name": "*.example.com",
"exposure": "internal"}` covers the domain and every name under it, an exact
name wins over a rule, and `exposure` is `public`, `internal`, `vpn`, or blank
on a rule ("not decided yet"). A token is sent neither the section nor the list.

| Route | What it does |
|---|---|
| `GET /api/v2/names` | For any signed-in viewer, built from their own map: `{generated_at, names, counts}`. One row per name a service's URL, a check or a certificate uses: `name`, `intent` (`public`, `internal`, `vpn`, `unset`, or `outside` when no entry covers it), `rule` (the entry that decided), `wildcard`, `in_use` (a URL or a check uses it, not only a certificate), `found` (`url`, `check`, `cert`), `uses` (`{place, place_name, service, via}`: `service` is null for a place's own check, `via` says `url` and/or `check`) and `cert` (the nearest certificate that vouches for it: `{name, expires, days}`, or null). `counts` has one number per intent and the `total`. An address and a single-label host are not names. Never stored. |

## Errors

| Status | Meaning |
|---|---|
| 401 | No token, or one that is not valid or has expired |
| 403 | A token tried something other than a read, agent access is off, a cloud token asked for a path other than the MCP endpoint, or the token is bound to networks the request did not come from |
| 404 | On `/api/v2/mcp`: agent access is off |
| 429 | Too many requests on this token, or too many without a valid token from this address; wait a minute |
| 500 | The dataset on disk could not be read |

A 401, 403, 404 or 429 from the token gate carries `{"error": ..., "reason": ...}`.

## What is stable

Atlas is 0.x, so anything can change between minor versions. Within that:

- The paths on this page, their parameters, the fields named in
  `openapi.json` and the MCP tool names do not change without a line in the
  release notes.
- `info.version` in `openapi.json` is the contract's own version and moves
  only when the contract does.
- Every other path under `/api/v2` belongs to the page. It changes with the
  page, with no notice, and a token cannot reach it anyway.
