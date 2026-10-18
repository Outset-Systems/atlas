# atlas-relay

Pushes a site's live data to a **hosted** Atlas. Runs on the customer LAN, reads what only
that LAN can reach (Uptime-Kuma, Prometheus, NetBox, an nmap sweep), and sends it outbound
over HTTPS to `/api/v2/ingest/*` with a per-site token.

**Nothing listens.** No inbound firewall hole, no VPN, no port forward, and no credential for
the customer's network ever leaves it — the relay holds the Kuma/NetBox keys locally and
ships only the resulting data. If the relay stops, the server ages it out after five minutes
and the map falls back to static rather than showing stale health as live.

You do not need this for a self-hosted Atlas that can already reach its own sources — set
`ATLAS_SIGNALS_SOURCES` on the server instead. The relay is for the hosted case.

## Requirements

Python 3.11+ (3.10 works with `tomli`, or use a `.json` config). No third-party packages for
the relay itself; the Kuma/Prometheus/NetBox collectors use `requests`, which the Atlas
`Web/requirements.txt` already pins. `nmap` on PATH only if `[scan]` is enabled.

The relay imports the Atlas adapters from the repo's `Web/` tree rather than reimplementing
them — one Kuma parser, one nmap parser, one place for bugs to be fixed. Run it from a
checkout, or point `ATLAS_WEB_DIR` (or `server.web_dir`) at that directory.

## Setup

On the server, mint a token for the site — it is shown once and only its hash is stored:

```bash
python Web/cli.py token-issue --site lab --label "app-host relay"
```

On the relay host, copy `relay.example.toml` to `relay.toml`, fill it in, and keep the token
in its own `chmod 600` file rather than inline. Then:

```bash
python relay/atlas_relay.py --config relay.toml --once --dry-run   # collect, print, send nothing
python relay/atlas_relay.py --config relay.toml --once             # one real pass
python relay/atlas_relay.py --config relay.toml                    # run forever
```

`--once` exits non-zero if any task failed, so it works as a cron job or systemd timer;
without it the relay loops on each task's own interval (signals 30s, inventory 6h, scan 24h
by default) and backs off exponentially on failure, to 15 minutes.

`atlas-relay.service` is an example unit: unprivileged user, no capabilities, hardened
sandbox. Install it by hand — nothing here deploys itself.

## What each task sends

| task | reads | pushes to | notes |
|---|---|---|---|
| `[signals]` | Kuma, Prometheus, a static file | `/ingest/signals` | the live layer; make it frequent |
| `[inventory]` | NetBox | `/ingest/inventory` | server owns the mapping; never deletes, retires |
| `[scan]` | `nmap -sn` | `/ingest/observed` | reports devices matching no node — the drift signal |

`[scan]` defaults to a ping sweep (`-sn`), never a port scan; set `nmap_args` yourself if you
want more, and know that raw-socket modes need `CAP_NET_RAW`. `promote = true` turns
discovered strangers into real map nodes automatically — leave it off until you trust the
sweep, since a guest VLAN will otherwise fill the map with phones.

## Troubleshooting

- **`server rejected the token`** — the relay stops retrying fast on 401/403 because a
  credential problem will not fix itself. Check `python Web/cli.py token-list` on the server;
  a revoked token stays revoked.
- **`every source was silent`** — the relay pushed nothing because every collector failed.
  That is deliberate: silence beats sending an empty feed that would blank the map.
- **`cannot find the Atlas Web/ directory`** — set `ATLAS_WEB_DIR` or `server.web_dir`.
- **Nothing on the map** — confirm the server has `relay` in `ATLAS_SIGNALS_SOURCES` and that
  `ATLAS_SITE` matches the token's site.
