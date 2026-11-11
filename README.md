# Atlas

**A living map of your homelab.** Hosts, services, networks, racks,
certificates and scheduled jobs on one illustrated map, coloured with live
health from the monitoring you already run: Uptime Kuma for the markers,
Prometheus and Loki for the numbers.

**[Try the live demo](https://atlas.example.com/demo/)** ·
[Install](docs/install.md) ·
[Configuration](docs/configuration.md) ·
[API](docs/api.md) ·
[AI agents](docs/mcp.md) ·
[outset.systems/atlas](https://outset.systems/atlas/)

[![Release](https://img.shields.io/github/v/release/Outset-Systems/atlas?include_prereleases&label=release)](https://github.com/Outset-Systems/atlas/releases)
[![Tests](https://img.shields.io/github/actions/workflow/status/Outset-Systems/atlas/tests.yml?branch=main&label=tests)](https://github.com/Outset-Systems/atlas/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Stars](https://img.shields.io/github/stars/Outset-Systems/atlas?style=social)](https://github.com/Outset-Systems/atlas/stargazers)

![A tour of the demo lab: the map, its network, a host's card, and the server room it zooms into](docs/img/tour.gif)

| | | |
|---|---|---|
| ![A host's card](docs/img/card.png) **A place's card** | ![Racks](docs/img/racks.png) **Racks, in 2D and 3D** | ![Addresses](docs/img/addresses.png) **Addresses on real CIDR maths** |
| ![Topology](docs/img/topology.png) **Topology, from the internet in** | ![Calendar](docs/img/calendar.png) **A calendar that notices a missed job** | ![Tripwires](docs/img/tripwires.png) **Tripwires that light up when touched** |

Every name and address in these pictures is invented.

## Why a map

- **A dashboard shows tiles.** Atlas shows where each thing is, what it runs
  and what it depends on, so "the gateway is down, and nine places behind it"
  reads as one problem, not ten.
- **A drawn diagram goes stale.** Atlas's markers change with what your
  monitoring reports, and it says so when a source stops answering.
- **A scanner draws whatever it finds.** Atlas never scans your network. You
  chart it once, by hand or from an nmap sweep, a CSV or your router's DHCP
  leases, and it stays the way you meant it.

> **Status: v0.1, early.** It works and is in daily use, but this is
> the first public release: expect rough edges, missing docs and breaking
> changes between 0.x versions. The install guide has been followed word for
> word on a clean machine. Bug reports are very welcome.

## Features

- **One map of everything.** Places grouped into network zones, the links
  between them, and the services each one runs. Pan, zoom, search with `/`,
  and open any place for its details.
- **Live health.** Markers turn with the state Uptime Kuma reports. Prometheus
  and Loki fill the place cards' vitals and charts. A source that goes down
  only removes its markers; the map keeps working.
- **Tripwires.** Chart your honeypots (OpenCanary, a fake share) and canary
  tokens (a document, a URL, a cloud key), and the Atlas lights the one that
  is touched. Trips arrive through one signed webhook that OpenCanary,
  Canarytokens or any script can call, and the scene says so out loud when a
  feed stops answering or a webhook has never been reached. Admins only: where
  bait sits stays secret. The Atlas never plants bait itself
  ([turn it on](docs/install.md#turn-on-tripwires)).
- **Views for the details:** an IP address view built on real CIDR maths, rack
  elevations in 2D and 3D, the network topology from the internet inwards,
  certificate expiry, a calendar of scheduled jobs that notices when one did
  not run, an event history, and detailed maps for a room or a rack that open
  as you zoom in (with links straight to one, `#region=<id>`).
- **Light or dark panels.** ☀/☾ or `T`, following your system until you choose;
  the map itself stays a night map.
- **Your own map art, and its own words.** Bring any picture as a map style and
  place your markers on it. The Atlas speaks in lore (rites, realms, annals) or,
  with one setting, in standard words, and a style can bring words of its own.
- **Edit in the browser.** A guided first setup and forms for every field.
  Fill the map from a CSV device list, an nmap sweep or your router's DHCP
  leases (ISC, dnsmasq, Kea, Windows Server). A sweep or leases device arrives
  with a suggested type from its maker or its name, for you to check; a CSV
  row takes the type you gave it, `physical` if you gave none. The Atlas never
  scans the network itself. On the `db` backend, NetBox and nmap importers on
  the command line too.
  Every change to the map is validated and recorded, and the last 50 can be
  undone. Moved markers and rearranged racks are saved apart, with no undo.
- **Real sign-in.** Local accounts with TOTP, optional LDAPS directory
  sign-in, or single sign-on behind a reverse proxy that signs each request.
  Places can be hidden from viewers outside a group.
- **Small to run.** One container, one volume, no database server, no
  telemetry. It calls the services you point it at, and public whois servers
  when a viewer asks, which is on by default (`ATLAS_WHOIS=0` turns it off).
  Plain JavaScript, no build step.

**Coming in v0.2:** a documented API and an MCP server, so scripts and AI
agents can ask the map what is here, when it was charted and whether a person has
checked it, before they act. See [the API guide](docs/api.md) and
[Atlas for AI agents](docs/mcp.md).

## Quickstart

You need Docker with Compose v2.

```sh
git clone https://github.com/outset-systems/atlas.git && cd atlas
printf 'ATLAS_ADMIN_PASSWORD=%s\n' "$(openssl rand -base64 24)" > .env
docker compose -f compose.public.yaml up -d
```

Open <http://localhost:5006> and sign in as `admin` with the password in
`.env`. To look around the invented demo lab first, add
`ATLAS_FALLBACK=bundled` to `.env` and run the last command again.

The full guide, including TLS behind Caddy or nginx, backups and upgrades, is
[docs/install.md](docs/install.md).

## Configuration

Everything is set with environment variables; most integrations can also be
changed from the Settings panel while the app runs. Every variable, its
default and what it does: [docs/configuration.md](docs/configuration.md).

## Documentation

- [Installing](docs/install.md)
- [Configuration reference](docs/configuration.md)
- [Architecture](docs/architecture.md), for contributors
- [Contributing](docs/CONTRIBUTING.md)
- [Code of conduct](docs/CODE_OF_CONDUCT.md)

## Security

The map describes your network, so treat access to it like access to your
network diagrams. Run it in `accounts` mode (the default in
`compose.public.yaml`) behind TLS. Please report vulnerabilities privately as
described in [docs/SECURITY.md](docs/SECURITY.md), not in a public issue.

## License

MIT. See [LICENSE](LICENSE).
