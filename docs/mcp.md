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

| Tool | Ask it |
|---|---|
| `atlas_overview` | What is this lab, how healthy is it, and how much of the map has a person reviewed? Call it first. |
| `atlas_search` | Where is the thing called X, or the thing at this address? |
| `atlas_place` | Everything about one place: role, address, services, live state, provenance. |
| `atlas_impact` | Before acting on a place: what it needs, what stops working if it does, what it is wired to. |
| `atlas_health` | What is not healthy right now, and is each monitoring source answering? |
| `atlas_events` | What changed state recently? |
| `atlas_missed_jobs` | Which backups and scheduled jobs are late, missed, failed or have never reported? |
| `atlas_unreviewed` | Which places did an import write that nobody has checked? |
| `atlas_changes` | What was charted or changed on the map since a given time? |

Every tool is read-only and takes at most a place, a search phrase, a time or a
limit.

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
was declared, not that nothing depends on it. `wired_to` is cabling and
routing, which is topology and not need.

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

`POST /api/v2/mcp`, JSON-RPC, tools only. It serves the 2026-07-28 revision
and the earlier `initialize` handshake, with no session and no stream. A token
is limited to 120 requests a minute.
