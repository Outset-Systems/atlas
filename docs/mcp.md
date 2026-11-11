# Atlas for AI agents (MCP)

An agent that runs commands on your lab should know what it is about to touch.
Atlas gives it that: what is here, what each thing is for, what depends on it,
whether it is healthy, and whether a person has checked the entry. Atlas never
scans your network, so what the agent reads is what you charted and approved.

The agent can read. It cannot change the map, and nothing here opens, closes or
reconfigures anything on your network.

## What leaves your network

Use a local model. Atlas never calls a model itself; a tool result goes
wherever the model that asked for it runs.

- **A local model** (Ollama, LM Studio, your own harness on your own hardware):
  answers stay on your network.
- **A cloud model** (Claude Code, Codex, Gemini CLI and the like): every answer
  The agent reads is sent to that model's vendor, and the vendor's own terms
  decide how long it is kept.

Atlas cannot see where a client sends what it reads, so you say it when you
create the token. A token is one of two kinds, and its kind cannot be changed
afterwards:

| | A full token | A cloud token |
|---|---|---|
| Made for | a local model, or a script on your network | a cloud AI tool |
| Places | every place a viewer with no groups could see | only places a person has checked, with nothing changed since |
| Fields | the map as charted: addresses, MAC addresses, URLs, hardware, notes | name, kind, zone, role, what it depends on, its roads, its services' names, health, when it was checked |
| Doors | the MCP endpoint and the read routes | the MCP endpoint only |
| Lifetime | 30, 90 or 365 days, or never | 7 or 30 days |

A cloud token still sends the names of the places you checked, what they are
for, how they connect and whether they are well. It reduces what a vendor
receives. It does not make sending a map to a vendor safe.

Give each tool its own token, name it after the tool, and revoke it when you
stop using that tool.

### What a cloud token reads

**Only places a person has checked.** A place an import wrote and nobody has
looked at is withheld. So is a place charted before Atlas kept provenance, and
a checked place that has changed since (an import added to it, say). Nothing about a withheld
place is sent: not its name, not its state, not an event that names it, and a
checked place that depends on it is listed without that dependency. The agent
is told how many places are withheld, so it does not read your lab as smaller
than it is, and Settings, Connections shows the same count before you create
the token. To make a place readable, check it in the Desk (below).

**A short list of fields.** For each place: its id, name, kind, zone, role,
parent and dependencies, and whether it is planned. For each service: its
name. For each road: its two ends and its kind. For each scheduled job: its
name, how often it runs and whether it ran. No IP or MAC address, no URL, no
hardware or firmware, no note or description, no monitor name, no rack, port,
prefix or certificate, and no key Atlas does not know. A cloud agent cannot
look a place up by its address.

**Three things carry no review of their own.** A network's name is sent only
when a readable place sits in it. A scheduled job is sent by its name, unless
that name names a withheld place. The map's title is sent.

**The same nine tools.** `atlas_health` names a service by its label and its
place, and `atlas_events` names each row from the map as it is now, because
the stored history carries monitor names and old names.

## Set it up

Agent access is off on a new Atlas. As an admin, open Settings, Connections and
press **Turn on**. Turning it off again stops every tool at once and keeps the
tokens. A deployment can hold it off with `ATLAS_AGENT_API=0`
([configuration](configuration.md)).

Then create an API token on the same screen: choose **A local model or a
script** or **A cloud AI tool**, and the screen shows the setup lines for that
kind. The token is shown once. [The API guide](api.md) explains what a token
can and cannot see.

Settings, Connections also shows these lines filled in for your address.

**A local model: any client that speaks MCP over HTTP**

```
URL:    https://atlas.example.net/api/v2/mcp
Header: Authorization: Bearer atl_...
```

**Claude Code** (cloud: what it reads goes to Anthropic, so give it a cloud token)

```sh
claude mcp add --transport http atlas https://atlas.example.net/api/v2/mcp \
  --header "Authorization: Bearer $ATLAS_TOKEN"
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
directly. That proxy's login cannot be answered with a token. Do that only in
`accounts` or `hybrid` mode, or in `hub` mode with `ATLAS_HUB_SECRET` set: in
`hub` mode without that secret Atlas believes a plain header, anyone who can
reach its port can claim to be an admin, and Atlas refuses tokens.

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

`changed_since_review: true` beside `reviewed: true` means the place has
changed since a person checked it, most often because an import added to it.
The review stands for what was there; what changed is a guess until someone
looks again. The Desk lists such a place as waiting for a look.

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

A cloud token sees less than this list: see
[What a cloud token reads](#what-a-cloud-token-reads). The limits on any token:

- places marked for a group, and every route, job and event that names them;
- account rosters;
- tripwires;
- the names of the people who charted or reviewed a place;
- what a scheduled job wrote about its own run (its note) and the address it
  reported from, since a job's words are not the map owner's;
- who acknowledged an event, and what they wrote;
- the `user:pass@` and the query string of a charted URL. A secret in a URL's
  path, or in a note, is not caught;
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
