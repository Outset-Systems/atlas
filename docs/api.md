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

Do that only where Atlas checks who is asking: `accounts` or `hybrid` mode, or
`hub` mode with `ATLAS_HUB_SECRET` set. In `hub` mode without that secret Atlas
believes a plain header, so anyone who can reach its port can claim to be an
admin. Atlas refuses tokens in that mode, so that nobody opens the port for one.

## The paths

| Path | What it answers |
|---|---|
| `GET /api/v2/lab-data` | The whole map: places, zones, routes, addresses, racks, certificates, scheduled jobs |
| `GET /api/v2/signals` | Live health of places and services, and whether each source answered |
| `GET /api/v2/rites` | Every scheduled job and whether it ran |
| `GET /api/v2/events` | The history of state changes, newest first |
| `GET /api/v2/places/roster` | Every place, one row each: live state, network, addresses, review, repairs, nearest certificate, sets |
| `GET /api/v2/overview` | The realm at a glance: places by state, what is down and what depends on it, unacknowledged events, repairs this week, lapsing certificates, review, changes, sources |
| `GET /api/v2/maps` | The pictures the map can be drawn on |
| `GET /api/v2/openapi.json` | The reference for this list |
| `POST /api/v2/mcp` | The MCP endpoint, for AI tools |

### The map: `/api/v2/lab-data`

One JSON document. The sections you will use most:

- `nodes`: the places. Each has an `id`, a `name`, a `zone`, usually an `ip`
  and a `role`, and `links`, which are the services on it.
- `zones`: the network segments places sit in.
- `routes`: which place connects to which, as `from` and `to`.
- `prefixes`, `interfaces`, `racks`, `certs`, `rites`: addresses, ports, the
  rack, certificates and scheduled jobs.

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
- `sets`: the sets it is in, and `depends_on`.

Beside the rows: `zones`, `sets` (named lists of places; a set is not an
access group) and `stamp`, the map's version.

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
- `sources`: `all_ok` and how many are `silent`. Which one is silent, and
  when each last answered, is for admins: a token gets an empty `items`.

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

The ALERTS view's own routes are listed here so an operator knows they exist.
They belong to the page, not to this contract, and every one of them refuses a
token (403): they sit behind the admin check, and an API token reads as a
viewer with no groups. Writes need the page's write header (`X-Atlas-Write`),
a same-origin request, and a writable Atlas (`ATLAS_READONLY` refuses them).
While alerts are off (`ATLAS_ALERTS` unset, or `ATLAS_ALERT_HOSTS` empty) the
read still answers, and the save and the test send answer 403 with how to
turn them on. See [Alerts](configuration.md#alerts) for the settings.

| Route | What it does |
|---|---|
| `GET /api/v2/admin/alerts` | `{doc, stamp, status, states}`. `doc` holds `rules`, `digest` and `destinations`. A destination's `secret` is the secret's name only, with `secret_bound` saying whether it is bound to the destination's address; the value is never returned. `status` says whether alerts are on, which hosts are allowed, whether `ATLAS_PUBLIC_URL` is set, the poll's interval, whether it runs in the worker that answered, when any worker last ran the alerts, and the ids of rules suspended because their target is no longer visible to a viewer with no groups. `states` are the states a rule may name. |
| `POST /api/v2/admin/alerts` | `{doc, expect}`: replace the whole document. `expect` is the `stamp` you read, and is required (400 without it); a document changed since answers 409. Problems answer 422 with `problems`. A secret is bound to the destination's address when it is named; a changed address drops the binding (the answer's `notes` say so) until the secret is named again: a new name, or `"bind": true` on that destination. |
| `POST /api/v2/admin/alerts/destinations/<id>/test` | Sends "Atlas test from <the map's title>" through the same path as an alert, at most 10 a minute per admin (shared with the other connection tests). Answers `{outcome, status, why}` only: `delivered`, `refused` with the HTTP status, `unreachable` or `blocked`, never anything the receiver said. |
| `GET /api/v2/admin/alerts/deliveries?limit=` | The delivery log, newest first, default 100, at most 1000: `at`, `rule` (its id; `test`, `digest` or `fold` for those sends), `destination` (its name), `events`, `outcome`, `status`, `why`, and `folded` on an "and N more" message. |

A rule is `{id, name, note, enabled, target: {kind: place|set|network, id},
to: [states], for_minutes: 0-1440, destination}`. The digest is `{enabled,
hour: 0-23 (the server's local time), destination, cert_days, review_days,
drift, uncharted}`; `uncharted` must be false for now. A destination is `{id,
name, kind: ntfy|gotify|webhook, url, secret}`; its URL may carry no user name,
password or query string, and its host and port must be in
`ATLAS_ALERT_HOSTS`.

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
