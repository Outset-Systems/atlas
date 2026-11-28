# atlas-relay

Pushes a site's live data to a **hosted** Atlas. Runs on the customer LAN, reads what only
that LAN can reach (Uptime-Kuma, Prometheus, NetBox, Hyper-V, an nmap sweep), and sends it outbound
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
python Web/cli.py token-issue --site branch --label "branch-office relay"
```

On the relay host, copy `relay.example.toml` to `relay.toml`, fill it in, and keep the token
in its own `chmod 600` file rather than inline. Then:

```bash
python relay/atlas_relay.py --config relay.toml --once --dry-run   # collect, print, send nothing
python relay/atlas_relay.py --config relay.toml --once             # one real pass
python relay/atlas_relay.py --config relay.toml                    # run forever
```

`--once` exits non-zero if any task failed, so it works as a cron job or systemd timer;
without it the relay loops on each task's own interval (signals 30s, inventory 6h, scan 24h,
hyperv 6h by default) and backs off exponentially on failure, to 15 minutes.

`atlas-relay.service` is an example unit: unprivileged user, no capabilities, hardened
sandbox. Install it by hand — nothing here deploys itself.

## What each task sends

| task | reads | pushes to | notes |
|---|---|---|---|
| `[signals]` | Kuma, Prometheus, a static file | `/ingest/signals` | the live layer; make it frequent |
| `[inventory]` | NetBox | `/ingest/inventory` | server owns the mapping; never deletes, retires |
| `[scan]` | `nmap -sn` | `/ingest/observed` | reports devices matching no node — the drift signal |
| `[hyperv]` | Hyper-V hosts, over WinRM | `/ingest/hyperv` | kept for review; an admin ticks what lands on the map |

`[scan]` defaults to a ping sweep (`-sn`), never a port scan; set `nmap_args` yourself if you
want more, and know that raw-socket modes need `CAP_NET_RAW`. `promote = true` turns
discovered strangers into real map nodes automatically — leave it off until you trust the
sweep, since a guest VLAN will otherwise fill the map with phones.

## Hyper-V

`[hyperv]` reads each listed host with one fixed, read-only PowerShell script (`Get-VMHost`,
`Get-VM`, `Get-VMNetworkAdapter`) over WinRM, and pushes the result. It needs one extra
package on the relay: `pip install pypsrp` (`"pypsrp[kerberos]"` for Kerberos, which also needs
the system Kerberos libraries). Standalone hosts only for now; failover clusters and SCVMM are
not built.

On each Hyper-V host, once, in an elevated PowerShell:

```powershell
Enable-PSRemoting -Force
New-LocalUser atlas-read -Password (Read-Host -AsSecureString)   # or a domain account
Add-LocalGroupMember -Group "Hyper-V Administrators" -Member atlas-read
Add-LocalGroupMember -Group "Remote Management Users" -Member atlas-read
```

How the relay signs in:

| hosts are | `auth` | `transport` | also needed |
|---|---|---|---|
| domain-joined | `kerberos` | `http` or `https` | the relay can get a ticket (`kinit`, or a keytab) |
| workgroup, or named by IP | `ntlm` | `https` | an HTTPS listener on the host, and its certificate in `ca_file` |
| a lab you do not mind an impostor answering in | `ntlm` | `http` | `allow_unverified_ntlm = true` |

`basic` and `credssp` are refused: both hand the password to the host. A guest's address comes
from the guest itself, through the Data Exchange integration service (`hv_kvp_daemon` on
Linux); a guest without it lands with no address.

Try it without sending anything, then look at what it would send:

```bash
python relay/atlas_relay.py --config relay.toml --once --dry-run --verbose --dump ./out
cat out/hyperv.json
```

If the Atlas cannot take relay pushes (the `file` backend), carry that file to it instead:
`python Web/cli.py hyperv-load out/hyperv.json`, then Settings → Connections → Hyper-V → Review.

## Troubleshooting

- **`hyperv: <host>: it refused the account`** — the user name or password is wrong, or the
  account is not in Remote Management Users on that host.
- **`hyperv: <host>: nothing answered on port 5986`** — no HTTPS listener (`winrm enumerate
  winrm/config/listener` on the host), or the firewall. Port 5985 is the HTTP listener.
- **`hyperv: <host>: Hyper-V refused the read`** — the account signed in but is not in
  Hyper-V Administrators.

- **`server rejected the token`** — the relay stops retrying fast on 401/403 because a
  credential problem will not fix itself. Check `python Web/cli.py token-list` on the server;
  a revoked token stays revoked.
- **`every source was silent`** — the relay pushed nothing because every collector failed.
  That is deliberate: silence beats sending an empty feed that would blank the map.
- **`cannot find the Atlas Web/ directory`** — set `ATLAS_WEB_DIR` or `server.web_dir`.
- **Nothing on the map** — confirm the server has `relay` in `ATLAS_SIGNALS_SOURCES` and that
  `ATLAS_SITE` matches the token's site.
