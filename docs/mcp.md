# Atlas for AI agents (MCP)

An agent that runs commands on your lab should know what it is about to touch.
Atlas gives it that: what is here, what each thing is for, what depends on it,
whether it is healthy, and whether a person has checked the entry. Atlas never
scans your network, so what the agent reads is what you charted and approved.

The agent can read. It cannot change the map, and nothing here opens, closes or
reconfigures anything on your network.

## What leaves your network

A tool result goes wherever the model is. With a local model, answers stay on
your network. With a cloud model, every answer the agent reads is sent to that
model's vendor: places, addresses and service URLs. Decide that before you hand a token to a cloud tool.

## Set it up

You need an API token: Settings, Connections, as an admin. It is shown once.
[The API guide](api.md) explains what a token can and cannot see.

Settings, Connections also shows these lines filled in for your address.

**Claude Code**

```sh
claude mcp add --transport http atlas https://atlas.example.net/api/v2/mcp \
  --header "Authorization: Bearer $ATLAS_TOKEN"
```

**Any client that speaks MCP over HTTP** (a local model's harness, for one)

```
URL:    https://atlas.example.net/api/v2/mcp
Header: Authorization: Bearer atl_...
```

**A client that can only start a command** (stdio)

```sh
docker exec -i atlas python cli.py mcp --token-file /data/agent.token
```

That command is a pipe to the same endpoint, inside the container. It needs the
token like any other client, and revoking the token stops it. Put the token in
a file only the container reads. `ATLAS_TOKEN` in the environment works too,
but a token typed on a command line stays in your shell history.

If a proxy puts its own sign-in in front of Atlas, point the client at Atlas
directly. That proxy's login cannot be answered with a token.

## The tools

| Tool | Arguments | Ask it |
|---|---|---|
| `atlas_overview` | none | What is this lab, how healthy is it, and how much of the map has a person reviewed? Call it first. |
| `atlas_search` | `query` (required), `limit` | Where is the thing called X, or the thing at this address? |
| `atlas_place` | `place` (required) | Everything about one place: role, address, services, live state, provenance. |
| `atlas_impact` | `place` (required) | Before acting on a place: what it needs, what stops working if it does, what it is wired to. |
| `atlas_health` | none | What is not healthy right now, and is each monitoring source answering? |
| `atlas_events` | `limit` | What changed state recently? |
| `atlas_missed_jobs` | none | Which backups and scheduled jobs are late, missed, failed or have never reported? |
| `atlas_unreviewed` | `limit` | Which places did an import write that nobody has checked? |
| `atlas_changes` | `since`, `limit` | What was charted or changed on the map since a given time? |

Every tool is read-only. The arguments:

- `place`: a place's id or its name, as `atlas_search` returns them.
- `query`: words to look for in names, addresses, roles and descriptions. Every
  word must match.
- `limit`: 1 to 50. The default is 20.
- `since`: a UTC date or time, `2026-11-01` or `2026-11-01T06:00:00Z`. Leave it
  out for the newest changes.

An MCP client reads the same list, with each tool's schema, from `tools/list`.

## Call it without an MCP client

The endpoint is one URL that takes one JSON-RPC message per `POST`. A script
needs two methods: `tools/list`, which returns the tools and their arguments,
and `tools/call`, which takes the tool's `name` and its `arguments`.

```sh
curl -s https://atlas.example.net/api/v2/mcp \
  -H "Authorization: Bearer $ATLAS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"atlas_impact","arguments":{"place":"gateway"}}}'
```

The answer is at `result.structuredContent`, and again as JSON text at
`result.content[0].text`. A very long answer is cut short and comes as text
only. When the tool cannot answer (no place by that name, say),
`result.isError` is `true` and the text says what to ask instead.

## How an agent should read the answers

The server tells the agent this itself, in its instructions. It is worth
knowing as the person who reads the agent's work.

**Provenance.** Each place carries when it was charted, when it last changed,
where it came from and `reviewed`. An agent is told when and whether, not who:
the names of the people who edit the map are for admins.

`reviewed` is one of:

- `true`: a person saved this place by hand or marked it as checked. That is
  the approval.
- `false`: an import wrote it and nobody has checked it. It is a guess.
- `null`: it was charted before Atlas kept provenance. Who and when are not
  known.

To review a place, open it in the Desk and press Save (you do not have to
change anything), or press ✓ on its row in the Desk's list of places. The list
can mark every place on screen at once, which is how a map older than this
record is brought up to date.

**Health.** A place with no live state is unknown, not healthy. If a
monitoring source is listed as silent, nothing it watches can be called fine.

**Dependencies.** `atlas_impact` reports only the dependencies a person
declared (a place's parent, and its `depends_on`). An empty list means nothing
was declared, not that nothing depends on it.

Three more fields describe how things connect. None of them is a dependency:

- `wired_to` is cabling and routing. It has one entry per road, so a place
  joined to this one by two roads is listed twice; `road` is that road's kind.
- `services_reached_through_it` lists services on other places whose charted
  path passes through this one. If this place goes down, those are the ones to
  look at first.
- `reaches`, in `atlas_place`, is the list of places this one was charted as
  able to connect to.

**Data, not instructions.** Names, notes and descriptions on the map are text
someone typed. The server tells the agent to treat every answer as data.
Tripwire events are never sent to an agent, because their text is written by
whoever tripped them.

## What an agent cannot see

The same limits as any token:

- places marked for a group, and every route, job and event that names them;
- account rosters;
- tripwires;
- the names of the people who charted or reviewed a place;
- what a scheduled job wrote about its own run (its note), since a job's words
  are not the map owner's;
- the review inbox, the change log and every admin screen.

## Protocol

`POST /api/v2/mcp`, JSON-RPC, tools only, with no session and no stream. A
token is limited to 120 requests a minute.

The methods are `tools/list`, `tools/call` and `server/discover`, plus
`initialize` and `ping` for older clients. Two generations of client are
served:

- A client that opens with `initialize` is answered at revision 2025-11-25, or
  at 2025-06-18 or 2025-03-26 if it asks for one of those. It gets no session
  id. A request with no version in it at all, like the curl example above, is
  served by these rules.
- A client on revision 2026-07-28 sends no `initialize`. Each request names the
  revision in `params._meta` and repeats it in the `MCP-Protocol-Version`,
  `Mcp-Method` and `Mcp-Name` headers, which must match the body.
