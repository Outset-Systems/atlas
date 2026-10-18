# Installing the Atlas

> **Status: tested once, not yet on a fresh VM.** On 2026-10-18 these steps
> ran start to finish on a second Docker host (Ubuntu, Compose 2.40): build,
> healthy container, sign-in, the demo lab and the short-password case all
> worked as written. That host already had the base image, so a first build
> elsewhere takes a few minutes longer. A run on a fresh VM is still planned
> before v0.1. If a step does not work as written, please open an issue.

The Atlas runs as one container with one volume. The compose file in the
repository root, `compose.public.yaml`, starts it in **accounts** mode (real
sign-in), bound to `127.0.0.1` only, with its data in a named Docker volume.

## Requirements

- Docker Engine with the Compose v2 plugin (`docker compose version` should
  work). Docker Desktop on macOS or Windows is fine.
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
[First sign-in](#first-sign-in). No `openssl`? Write the line by hand:
`ATLAS_ADMIN_PASSWORD=...`.

Prefer to see every setting? Copy `.env.example` to `.env` instead and fill
in `ATLAS_ADMIN_PASSWORD`; the file explains each line. Port 5006 already in
use on this machine? Set `ATLAS_PUBLISH=127.0.0.1:5007` (any free port) in
`.env` and use that port in the commands below.

The first `up` builds the image, which takes a few minutes. Check it is
running:

```sh
docker compose -f compose.public.yaml ps        # STATUS should say "healthy"
curl -s http://localhost:5006/api/v2/health
```

### Variables the compose file reads

Set these in `.env` (or your shell) before `up`. They are compose settings;
the app's own variables are in [configuration.md](configuration.md).

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

1. Open <http://localhost:5006>. You get the sign-in page.
2. Sign in as `admin` (or your `ATLAS_ADMIN_USER`) with the password from
   `.env`.
3. Open **Settings** (the gear button). Your account section has a
   "Change password" form; the Users section adds more people.
4. The map starts empty and offers a guided first setup: name your lab, add a
   network segment, then add its places by hand or from a pasted CSV device
   list. After that, the editor in Settings changes anything on the map, and
   every change is recorded and can be undone.

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
`10.77.x.x`). The first change you save turns that demo into your own copy, so
switch back to `empty` before you start charting your own lab, or delete the
volume (see [Uninstall](#uninstall)) to start over.

## Put it behind a reverse proxy

To reach the Atlas from other machines, terminate TLS in a reverse proxy and
leave the container on loopback. The proxy must pass the original host and
set `X-Forwarded-Proto` (the app uses it to know the browser is on https) and
`X-Forwarded-For`.

Serve the Atlas at the root of its own host name (for example
`atlas.home.example`). Running it under a sub-path has not been tested.

### Caddy

Caddy gets a certificate automatically and sets the forwarding headers for
you:

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
3. Pull and rebuild:

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
```

Then delete the cloned directory, including `.env`.

## Running without the compose file

The image needs only a volume at `/data` and the environment variables you
choose. The same setup with `docker run`:

```sh
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
