# The Atlas API

Atlas never scans your network. What it holds is what a person charted and
approved, which makes it a good first question for a script or an AI agent:
ask the map what is here before acting on it.

This page covers what an API token can read. The machine-readable version is
[`openapi.json`](openapi.json) (OpenAPI 3.1), and a running Atlas serves the
same document at `/api/v2/openapi.json`.

## Get a token

1. Sign in as an admin.
2. Open Settings, then Connections.
3. Name the token, choose how long it lasts (30, 90 or 365 days, or never) and
   create it.

The token is shown once. Atlas keeps only a hash of it, so a lost token is
revoked and replaced, not recovered. Revoking takes effect at once.

Tokens need accounts: a standalone Atlas with no sign-in has no admin to issue
one.

## What a token can and cannot do

- **It reads.** There is no write scope. Changes to the map are made by a
  person in a session.
- **It sees what a signed-in viewer with no groups sees.** Places marked for a
  group are removed, along with every route, address, job and event that names
  them. Account rosters and tripwires are never sent to a token.
- **It opens seven doors**, listed below. Every other path ignores the token
  and answers as it would to a stranger.
- **It is limited to 120 requests a minute.** Past that the answer is 429 with
  `Retry-After: 60`.

What a tool reads leaves with it. A cloud AI tool sends what it reads to its
model's vendor, so a token handed to one takes this map off your network.

## Try it

```sh
export ATLAS=https://atlas.example.net
export TOKEN=atl_...

curl -s -H "Authorization: Bearer $TOKEN" "$ATLAS/api/v2/lab-data"
```

If a proxy puts its own sign-in in front of Atlas, point the script at Atlas
directly. That proxy's login cannot be answered with a token.

## The paths

| Path | What it answers |
|---|---|
| `GET /api/v2/lab-data` | The whole map: places, zones, routes, addresses, racks, certificates, scheduled jobs |
| `GET /api/v2/signals` | Live health of places and services, and whether each source answered |
| `GET /api/v2/rites` | Every scheduled job and whether it ran |
| `GET /api/v2/events` | The history of state changes, newest first |
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
(`reviewed_at` says when). Who charted,
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

### Scheduled jobs: `/api/v2/rites`

Each job as charted, plus a `verdict`: `kept`, `late`, `missed`, `failed`,
`awaited` (watched, never reported) or `unwatched` (nothing is expected of
it). `age_s` is the seconds since it last reported.

### History: `/api/v2/events`

```sh
curl -s -H "Authorization: Bearer $TOKEN" "$ATLAS/api/v2/events?limit=20&unacked=1"
```

- `limit`: how many, default 100. The history keeps 2,000.
- `unacked=1`: only events nobody has acknowledged.

Each event says what changed (`kind`, `target`, `name`), from which state to
which, and when it was first observed. A `cause` means another fault explains
this one.

### AI tools: `/api/v2/mcp`

The endpoint speaks the Model Context Protocol over HTTP, both the 2026-07-28
revision and the earlier `initialize` handshake. It offers nine read-only
tools. [Atlas for AI agents](mcp.md) has the setup, the tools and how an agent
should read the answers.

## Errors

| Status | Meaning |
|---|---|
| 401 | No token, or one that is not valid or has expired |
| 403 | A token tried something other than a read |
| 429 | Too many requests on this token; wait a minute |
| 500 | The dataset on disk could not be read |

A 401, 403 or 429 carries `{"error": ..., "reason": ...}`.

## What is stable

Atlas is 0.x, so anything can change between minor versions. Within that:

- The paths on this page, their parameters, the fields named in
  `openapi.json` and the MCP tool names do not change without a line in the
  release notes.
- `info.version` in `openapi.json` is the contract's own version and moves
  only when the contract does.
- Every other path under `/api/v2` belongs to the page. It changes with the
  page, with no notice, and a token cannot reach it anyway.
