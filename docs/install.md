# Installing the Atlas

> **Status: tested on a clean machine.** On 2026-10-18 these steps ran word
> for word on a clean Ubuntu 24.04 system with nothing cached: Docker Engine
> 29.9 and Compose 5.6 installed from Docker's apt repository, then the
> quickstart, sign-in, the demo lab and the uninstall, all as written (about a
> minute end to end on a fast connection). Earlier the same day they also ran
> on an existing Docker host, including the short-password case. Not yet
> tried: a full virtual machine with Docker running as a system service, and
> Docker Desktop on macOS or Windows. The SSH tunnel and tripwires sections
> came after that run, and so did the move to Compose 2.24 or newer, which has
> been run on an existing Docker host but not yet on a clean one. If a step does not work as written, please open an
> issue.

The Atlas runs as one container with one volume. The compose file in the
repository root, `compose.public.yaml`, starts it in **accounts** mode (real
sign-in), bound to `127.0.0.1` only, with its data in a named Docker volume.

## Requirements

- Docker Engine with Compose 2.24 or newer (`docker compose version` shows
  it). Docker Desktop should work too, though it is untested; see the status
  note above.
- `git`, to clone the repository.
- About 1 GB of free disk for the image build, and a few hundred MB of RAM.
  The image is based on `python:3.12-slim` and builds on `amd64` and `arm64`.
- A browser. Sign-in uses a `Secure` cookie, so over plain http only
  `http://localhost` works (in Chrome and Firefox). Anything else needs TLS in
  front, see [Put it behind a reverse proxy](#put-it-behind-a-reverse-proxy).

The app needs no outbound internet access to run. The optional real-world map
survey asks OpenStreetMap services for map data when you use it.

## Start it

```sh
git clone https://github.com/outset-systems/atlas.git && cd atlas
printf 'ATLAS_ADMIN_PASSWORD=%s\n' "$(openssl rand -base64 24)" > .env
docker compose -f compose.public.yaml up -d
```

The second line writes a random first-admin password into `.env`, which
Compose reads automatically. Use any password of **12 characters or more**.
A shorter one is refused: the app still starts, but without an admin, and
`docker compose -f compose.public.yaml logs atlas` says why. Fix the line
and run the `up -d` command again: the admin is created on that start,
because none exists yet. Or create the admin by hand as shown under
[First sign-in](#first-sign-in). No `openssl`, or on PowerShell? Write the
line by hand: `ATLAS_ADMIN_PASSWORD=...`. Avoid `$`, `#` and spaces in a
hand-written value, or put the value in single quotes.

Prefer to see every setting? Copy `.env.example` to `.env` instead and fill
in `ATLAS_ADMIN_PASSWORD`; the file explains each line. Port 5006 already in
use on this machine? Set `ATLAS_PUBLISH=127.0.0.1:5007` (any free port) in
`.env` and use that port in the commands below.

The first `up` builds the image, which takes a few minutes. Check it is
running:

```sh
docker compose -f compose.public.yaml ps        # STATUS says "healthy" within a minute
curl -s http://localhost:5006/api/v2/health
```

### Variables the compose file reads

Set these in `.env` (or your shell) before `up`. They are compose settings.
Everything else in [configuration.md](configuration.md) can go in `.env` too,
because the file reaches the app whole. `up -d` applies a change; `restart`
does not.

| Variable | Default | Meaning |
|---|---|---|
| `ATLAS_ADMIN_USER` | `admin` | User name of the first admin. |
| `ATLAS_ADMIN_PASSWORD` | (empty) | That admin's password, 12+ characters. Used only while no admin exists. |
| `ATLAS_PUBLISH` | `127.0.0.1:5006` | Host address and port to publish. `5006` alone listens on every interface. |
| `ATLAS_MFA_REQUIRED` | (empty) | `admins` or `all` makes those users enroll TOTP at sign-in. |
| `ATLAS_FALLBACK` | `empty` | `bundled` opens on the invented demo lab instead of a blank map. |
| `ATLAS_BRAND` | `The Atlas` | The name on the sign-in page. |
| `ATLAS_TRUSTED_PROXIES` | (empty) | Address(es) of your reverse proxy, see below. |
| `ATLAS_INSECURE_COOKIES` | (empty) | `1` for testing over plain http from another machine. |

## First sign-in

**Docker on a server, not your desktop?** Sign-in needs `localhost` or TLS, so
reach the loopback port over SSH, then use the same address below:

```sh
ssh -L 5006:127.0.0.1:5006 you@your-server
```

For a quick test across a trusted LAN instead, set both `ATLAS_PUBLISH=5006`
and `ATLAS_INSECURE_COOKIES=1` in `.env`, then `up -d`. The first alone gives a
sign-in page that loops. For anything lasting, use a
[reverse proxy](#put-it-behind-a-reverse-proxy).

1. Open <http://localhost:5006>. You get the sign-in page.
2. Sign in as `admin` (or your `ATLAS_ADMIN_USER`) with the password from
   `.env`.
3. Open **Settings** (the gear button). Your account section has a
   "Change password" form; the Users section adds more people.
4. The map starts empty and offers a guided first setup: name your lab, choose
   how to start (a scan file, your router's leases, a CSV device list, or by
   hand), confirm the networks, then the devices. After that, every change is
   recorded and can be undone.
5. To add a place later: **Settings → Edit the map → Open the map editor**
   (or press `E`), then **+ new place**. Id, name, kind, realm, position and
   role are required; the rest can wait.

**Turn on TOTP for admins.** Add `ATLAS_MFA_REQUIRED=admins` (or `all`) to
`.env` and run `docker compose -f compose.public.yaml up -d` again. At
their next sign-in, each affected user is walked through enrolling an
authenticator app. There is no opt-in button in Settings yet, so this
variable is the way to enroll.

The bootstrap variables do nothing once an admin exists, so leaving them in
`.env` does not create a back door. You can still delete the password line
once you have signed in.

**No password set?** The app starts without an admin and nobody can sign in.
Create one from the command line instead (it prompts for the password):

```sh
docker compose -f compose.public.yaml exec atlas python cli.py user-add admin --admin
```

The same tool lists, changes and removes accounts: `user-list`,
`user-passwd`, `user-mod --reset-mfa`, `user-del`.

**Want to look around first?** Set `ATLAS_FALLBACK=bundled` in `.env` and run
`up -d` again. The map opens on an invented demo lab (`home.example`,
`10.77.x.x`), with live-looking health from a demo status feed in the image
(used only while no other source is configured). The first change you save
turns that demo into your own copy and silences the demo feed, so
switch back to `empty` before you start charting your own lab. To start over
instead, delete the volume (see [Uninstall](#uninstall)). That deletes the admin
too, so keep `ATLAS_ADMIN_PASSWORD` in `.env` for the next `up`.

## Turn on tripwires

Tripwires light a marker when a honeypot or canary token is touched. Trips reach
the Atlas through a webhook, which is off until it has a secret:

```sh
printf 'ATLAS_TRIPWIRES_WEBHOOK=1\nATLAS_TRIPWIRES_SECRET=%s\n' "$(openssl rand -hex 24)" >> .env
docker compose -f compose.public.yaml up -d
docker compose -f compose.public.yaml exec atlas python cli.py tripwires-key
```

The last line prints the webhook key that senders use. Now open the Tripwires
scene, where **SET UP** gives the block to paste for OpenCanary, the URL for
Canarytokens, and a `curl` line for any script.

- **A sender must be able to reach the Atlas.** The blocks use the address your
  browser used, so open the Atlas through your
  [reverse proxy](#put-it-behind-a-reverse-proxy) first. `localhost` only works
  on this machine, and SET UP warns you when that is what it shows.
- **Test it.** Run the `curl` line once. Until something arrives, the scene says
  it is waiting for a first signal. Afterwards a quiet scene means nothing has
  been touched. The test shows up as an unmatched trip, which you can
  acknowledge.

## Put it behind a reverse proxy

To reach the Atlas from other machines, terminate TLS in a reverse proxy and
leave the container on loopback. The proxy must pass the original host and
set `X-Forwarded-Proto` (the app uses it to know the browser is on https) and
`X-Forwarded-For`.

Serve the Atlas at the root of its own host name (for example
`atlas.home.example`). Running it under a sub-path has not been tested.

### Caddy

Caddy gets a certificate automatically for a public name, and sets the
forwarding headers for you. For a name only your LAN can resolve, add
`tls internal` inside the block and trust Caddy's root certificate:

```caddyfile
atlas.home.example {
    reverse_proxy 127.0.0.1:5006
}
```

### nginx

```nginx
server {
    listen 443 ssl;
    server_name atlas.home.example;

    ssl_certificate     /etc/ssl/certs/atlas.home.example.pem;
    ssl_certificate_key /etc/ssl/private/atlas.home.example.key;

    # map image uploads are capped at 24 MB by the app
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:5006;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # the real-world survey can take up to two minutes
        proxy_read_timeout 130s;
    }
}
```

### Trusted proxy setting

The sign-in throttle and the audit log key on the client's address. Behind a
proxy, every request comes from the proxy, so tell the Atlas which address
that is and it will read the real client from `X-Forwarded-For`:

```sh
# in .env
ATLAS_TRUSTED_PROXIES=172.18.0.1
```

Use the address **the container sees** the proxy connect from, which is not
always the proxy's own address:

- Proxy on the same host, connecting to `127.0.0.1:5006`: Docker forwards the
  connection, and the container usually sees the gateway address of the
  compose network. Find it with
  `docker network inspect atlas_default --format '{{(index .IPAM.Config 0).Gateway}}'`.
- Proxy in a container on the same Docker network: that container's address.
- To check, look at the first field of a request line in
  `docker compose -f compose.public.yaml logs atlas`: that is the address the
  app sees.

You can list several addresses or CIDRs, comma separated. A hop count (a bare
number) is refused. Leave it blank when nothing is in front of the app; a
header from an address not on the list is ignored, so a wrong value fails
safe (every client looks like the proxy) rather than open.

## Backups

All state is in the `atlas_atlas-data` volume, mounted at `/data`. Back up the
whole volume. The files that matter:

| Path in `/data` | What it is |
|---|---|
| `lab-data.json` | The dataset: your places, services, networks, racks. |
| `positions.json`, `rack.json` | Hand-placed marker positions and rack layout. |
| `revisions/` | Snapshots of the dataset after every change. |
| `events.json`, `heartbeats.json`, `maintenance.json`, `observed.json` | Event history, job heartbeats, maintenance windows, discovery results. |
| `tripwires.json`, `api-tokens.json`, `beats/` | When each tripwire sender was last heard, API tokens, job drop files. |
| `maps/`, `reports/` | Uploaded map images and generated reports. |
| `accounts.db` | Users, password hashes, encrypted TOTP secrets, sign-in audit. |
| `auth-config.json`, `integrations.json` | Settings saved from the Settings screen (secrets encrypted). |
| `secrets/master.key` | **The encryption key.** |
| `secrets/session.key` | The session signing key. |
| `atlas.db` | The dataset, if you switched to `ATLAS_DATA_BACKEND=db`. |

**Keep `secrets/master.key` with every backup of `accounts.db`.** It encrypts
the TOTP secrets in `accounts.db` and the secrets in `integrations.json`. A
backup restored without the key it was written with still lets people sign in
with their passwords, but every TOTP enrollment and every saved integration
key is lost: users must re-enroll MFA, and you must re-enter the keys. If you
supply the key yourself with `ATLAS_ENCRYPTION_KEY_FILE`, back up that file
too. Losing `session.key` only signs everyone out.

The backup holds password hashes and keys, so store it somewhere private.

A simple backup, with the app stopped so the SQLite files are consistent:

```sh
docker compose -f compose.public.yaml stop
docker run --rm -v atlas_atlas-data:/data:ro -v "$PWD":/backup alpine \
  tar czf /backup/atlas-backup-$(date +%Y%m%d).tar.gz -C /data .
docker compose -f compose.public.yaml start
```

To restore into an empty volume:

```sh
docker compose -f compose.public.yaml down
docker run --rm -v atlas_atlas-data:/data -v "$PWD":/backup alpine \
  sh -c 'cd /data && tar xzf /backup/atlas-backup-YYYYMMDD.tar.gz && chown -R 1000:1000 /data'
docker compose -f compose.public.yaml up -d
```

The app runs as user id 1000, hence the `chown`.

## Upgrading

1. Back up (above).
2. Read the release notes for the version you are moving to.
3. Check `docker compose version` says 2.24 or newer. If you edited
   `compose.public.yaml`, move those settings to `.env` first: `git pull`
   stops at a file you changed.
4. Pull and rebuild:

   ```sh
   git pull
   docker compose -f compose.public.yaml up -d --build
   ```

The file backend needs no migration step. If you use the `db` backend, apply
schema migrations after the new container starts:

```sh
docker compose -f compose.public.yaml exec atlas alembic upgrade head
```

To go back, check out the previous tag, rebuild, and restore the backup you
took in step 1.

## Uninstall

```sh
docker compose -f compose.public.yaml down        # stop and remove the container, keep the data
docker compose -f compose.public.yaml down -v     # also delete the data volume (cannot be undone)
docker image rm atlas:local                       # remove the built image
docker builder prune                              # optional: remove the build cache
```

Then delete the cloned directory, including `.env`.

## Running without the compose file

The image needs only a volume at `/data` and the environment variables you
choose. It asks for sign-in by default (`ATLAS_AUTH_MODE=accounts`), so give
the first admin a password, or nobody can sign in. The same setup with
`docker run`, reading that password from a file you create first:

```sh
printf '%s' "$(openssl rand -base64 24)" > admin_password.txt
docker build --target public -t atlas:local .
docker volume create atlas-data
docker run -d --name atlas --restart unless-stopped \
  -p 127.0.0.1:5006:5006 -v atlas-data:/data \
  -e ATLAS_AUTH_MODE=accounts \
  -e ATLAS_BOOTSTRAP_ADMIN_USER=admin \
  -e ATLAS_BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/admin_password \
  -v "$PWD/admin_password.txt":/run/secrets/admin_password:ro \
  atlas:local
```
