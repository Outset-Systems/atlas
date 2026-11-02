# Configuration reference

The Atlas is configured with environment variables. This page lists every
variable the app in `Web/` reads, grouped by feature. `docs/env-coverage.py`
checks this page against the code, so a variable added to the app without a
row here fails CI.

How to read the tables:

- **Default** is what the app uses when the variable is unset. "(unset)" means
  the feature is off until you set it.
- **Secret** variables can also be given as a file: set `NAME_FILE` to a path
  (for example a Docker secret under `/run/secrets/`) instead of `NAME`. When
  both are set, `NAME` wins. Only variables that list a `_FILE` variant accept
  one.
- **Settings screen** says whether an admin can change the value at runtime
  from the Settings panel in the app. A value saved there is stored in `/data`
  and **overrides** the environment until it is cleared. The Deployment section
  of the same panel lists every variable, the layer its value came from
  (settings file, environment or default) and the value, with secrets shown
  only as set or unset.
- Boolean variables are on when set to `1` unless the row says otherwise.

Most values are read once when the app starts, so changing an environment
variable needs a new container (`docker compose -f compose.public.yaml up -d`
after editing `.env`). Values changed on the Settings screen apply without a
restart.

## Core

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_BRAND` | `The Atlas` | The name shown on pages a visitor sees before signing in (the sign-in page). The map's own name comes from the theme, so the sign-in page does not reveal it. | no | no |
| `ATLAS_THEME` | `plain` | Which theme file in `Web/themes/` supplies the words and emblems that describe your lab. `plain` names nothing. An unknown name falls back to `plain` and logs a warning. See [Theme](#theme). | no | no |
| `ATLAS_LOG_LEVEL` | `INFO` | Log level for the whole app (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | no | no |
| `ATLAS_LOG_LEVELS` | (unset) | Per-layer log levels, comma separated, for example `atlas.data=DEBUG,atlas.auth=WARNING`. Layers: `atlas.web`, `atlas.api`, `atlas.auth`, `atlas.data`, `atlas.io`, `atlas.live`, `atlas.settings`, and any module under them. Bad entries are ignored and logged. | no | no |
| `ATLAS_DEBUG` | (unset) | `1` turns on Flask debug mode for the development server (`python app.py`). Never set this in a container. | no | no |
| `ATLAS_HOST` | `0.0.0.0` | Bind address for the development server only. The container runs gunicorn, which binds `0.0.0.0:5006` regardless. | no | no |
| `ATLAS_PORT` | `5006` | Port for the development server only. In the container, change the published port in compose instead. | no | no |
| `ATLAS_READONLY` | depends on mode | `1` refuses every write, `0` allows writes. When unset, `standalone` mode is read-only (it has no sign-in, so anyone who can reach the port would be an admin) unless `ATLAS_ALLOW_INSECURE=1`; `accounts`, `hybrid` and `hub` modes are writable and check admin rights per request. | no | no |
| `ATLAS_ALLOW_INSECURE` | (unset) | `1` acknowledges that `standalone` mode serves the whole map with no sign-in. It silences the startup security warning and makes standalone writable. Use only on loopback or a trusted network. | no | no |

## Data and storage

Everything the app writes lives under the directory that holds the dataset,
`/data` by default. Mount a volume there. Most paths below default to a file
beside `ATLAS_DATA` and rarely need changing.

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_DATA` | `/data/lab-data.json` | The dataset file (file backend). Its directory is the data directory every other default below is relative to, including the accounts store and the key files. | no | no |
| `ATLAS_DATA_BACKEND` | `file` | `file` keeps the dataset as one JSON file. `db` keeps the same dataset in a SQL database through SQLAlchemy (needed for multiple sites and the relay ingest). | no | no |
| `ATLAS_DB_URL` | `sqlite:////data/atlas.db` | SQLAlchemy URL for the `db` backend and for `cli.py`'s dataset and importer commands, which work on this database only. A URL that carries a password is shown masked on the Settings screen. | treat as secret if it holds a password (no `_FILE` variant) | no |
| `ATLAS_SITE` | `default` | Which site the `db` backend serves, and which site the `relay` signals source reads. | no | no |
| `ATLAS_FALLBACK` | `empty` | What an instance with no dataset shows. `empty`: an empty map that invites you to start charting. `bundled`: the dataset baked into the image (the public image bundles an invented demo lab, plus a demo status feed that colours it while no source is configured and the instance is unseeded). The first save writes your own copy to `ATLAS_DATA` and silences the demo feed. | no | no |
| `ATLAS_POSITIONS` | `<data dir>/positions.json` | Hand-placed marker positions, stored over the dataset. | no | no |
| `ATLAS_RACK` | `<data dir>/rack.json` | Rack layout overlay. | no | no |
| `ATLAS_REVISIONS` | `<data dir>/revisions` | Directory of dataset snapshots written on every change (the change log). | no | no |
| `ATLAS_OBSERVED` | `<data dir>/observed.json` | What discovery and scans observed, used for drift reports. | no | no |
| `ATLAS_EVENTS` | `<data dir>/events.json` | The event history (faults, recoveries, acknowledgements). | no | no |
| `ATLAS_REPORTS` | `<data dir>/reports` | Directory of generated reports the app serves. | no | no |
| `ATLAS_MAINTENANCE` | `<data dir>/maintenance.json` | Planned maintenance windows. | no | no |
| `ATLAS_MAPS` | `<data dir>/maps` | Uploaded map images. Images bundled in the image win over uploads with the same name. A `<image>.style.json` beside an image can name that map style and give it zoom regions, see below. | no | no |
| `ATLAS_ACCOUNTS_DB` | `<data dir>/accounts.db` | The SQLite accounts store (`accounts` and `hybrid` modes): users, password hashes, encrypted TOTP secrets, the sign-in audit log. | no | no |
| `ATLAS_AUTH_CONFIG` | `<data dir>/auth-config.json` | Where Directory settings saved on the Settings screen are stored. | no | no |
| `ATLAS_INTEGRATIONS` | `<data dir>/integrations.json` | Where Sources and Realm settings saved on the Settings screen are stored. Secrets in it are encrypted with the master key. | no | no |
| `ATLAS_SCROLL_ROOT` | (unset) | A path prefix trimmed off document paths (the `scroll` field on a place) when they are displayed. The full path is still copied. | no | yes (Realm) |

### Keys the app generates

Two keys are created on first start if you do not supply them. Both live in
`<data dir>/secrets/` and must be backed up with the rest of `/data`.

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_ENCRYPTION_KEY` | generated into `<data dir>/secrets/master.key` | The Fernet master key that encrypts TOTP secrets and the secrets saved on the Settings screen. **If you lose it, every enrolled TOTP secret and every saved integration secret becomes unreadable**: users must re-enroll MFA and you must re-enter the keys. If `ATLAS_ENCRYPTION_KEY_FILE` is set but the file is missing or empty, the app refuses to start rather than generate a different key. | yes, `ATLAS_ENCRYPTION_KEY_FILE` | no |
| `ATLAS_SECRET_KEY` | generated into `<data dir>/secrets/session.key` | Signs session cookies (`accounts` and `hybrid` modes). Changing it signs everyone out. | yes, `ATLAS_SECRET_KEY_FILE` | no |

## Authentication

`ATLAS_AUTH_MODE` picks one of four modes. The image and `compose.public.yaml`
default to `accounts`, so a new install always asks for sign-in; `standalone` is
the default only when you run the code directly from a checkout (development).

| Mode | Who can see the map | Sign-in |
|---|---|---|
| `standalone` | Anyone who can reach the port. Read-only unless `ATLAS_ALLOW_INSECURE=1`. | None. Use on loopback or a trusted network only. |
| `accounts` (image default) | Signed-in users. | The Atlas's own accounts (local passwords, optionally LDAPS), with optional TOTP. |
| `hub` | Whoever an upstream single-sign-on gateway (the "hub") forwards. | Done by the hub, which sends a signed identity header. The Atlas has no sign-in page in this mode. |
| `hybrid` | Hub users, plus anyone who signs in with an Atlas account. | Hub identity when the signed header is present, the Atlas sign-in page when it is not. |

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_AUTH_MODE` | `accounts` in the image, `standalone` from a checkout | `standalone`, `accounts`, `hub` or `hybrid`. Any other value makes every gated request fail with a 500 (fail closed). | no | no |
| `ATLAS_ADMIN_GROUP` | `atlas-admins` | The group that makes a viewer an Atlas admin when the identity comes from the hub (or from `ATLAS_STANDALONE_GROUPS`). Also the default for `ATLAS_LDAP_ADMIN_GROUPS`. | no | no |
| `ATLAS_TRUSTED_PROXIES` | (unset) | Comma-separated IPs or CIDRs of the reverse proxies whose `X-Forwarded-For` header the app believes, for example `172.18.0.2` or `172.18.0.0/16`. Used for the sign-in throttle and the audit log. Unset trusts no proxy and uses the socket peer. A bare number (a hop count) is refused and logged. See [install.md](install.md#put-it-behind-a-reverse-proxy). | no | no |
| `ATLAS_INSECURE_COOKIES` | (unset) | `1` (or `true`, `yes`) drops the `Secure` flag from the session cookie, for testing over plain http. Without it, most browsers discard the cookie on plain http to anything but `localhost`, and sign-in returns you to the sign-in page. Do not use behind TLS. | no | no |

### Standalone identity

In `standalone` mode there is no sign-in; these name the single implied user.

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_STANDALONE_USER` | `local` | The user name recorded as the author of changes. | no | no |
| `ATLAS_STANDALONE_GROUPS` | (empty) | Comma-separated groups for that user. | no | no |

### Accounts mode (and the sign-in half of hybrid)

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_BOOTSTRAP_ADMIN_USER` | `admin` when a bootstrap password is set | First run only: while there is no active admin, create this local admin at start (or promote the account if it already exists). Inert once any admin exists, so it is safe to leave set. With no admin and no bootstrap password in `accounts` mode, the log says how to create one. | no | no |
| `ATLAS_BOOTSTRAP_ADMIN_PASSWORD` | (unset) | The bootstrap admin's password, at least 12 characters. A shorter password is refused: the app logs an error and starts without an admin. Prefer the `_FILE` form. | yes, `ATLAS_BOOTSTRAP_ADMIN_PASSWORD_FILE` | no |
| `ATLAS_MFA_REQUIRED` | (empty) | Who must enroll TOTP before they can use the map: empty (nobody; anyone may enroll), `all` (also `1`, `yes`, `on`), `admins`, or a sign-in source (`local` or `ldap`). Read live. | no | no |
| `ATLAS_LOGIN_MAX_USER` | `5` | Failed sign-ins allowed per user name within the window. | no | no |
| `ATLAS_LOGIN_MAX_IP` | `20` | Failed sign-ins allowed per client IP within the window. | no | no |
| `ATLAS_LOGIN_WINDOW_MIN` | `15` | The throttle window, in minutes. | no | no |
| `ATLAS_SESSION_IDLE_MIN` | `60` | A session ends after this many idle minutes. | no | no |
| `ATLAS_SESSION_ABS_HOURS` | `12` | A session ends this many hours after sign-in, active or not. | no | no |
| `ATLAS_AUTH_BACKENDS` | `local` | Sign-in backends in the order tried: `local`, `ldap`, or `local,ldap`. `ldap` is live only when `ATLAS_LDAP_URL` and `ATLAS_LDAP_BASE_DN` are also set. | no | yes (Directory) |

You can also manage accounts from the command line inside the container:
`python cli.py user-add <name> --admin`, `user-list`, `user-passwd`,
`user-mod` (promote, deactivate, reset MFA) and `user-del`.

### LDAP (directory sign-in)

The Atlas binds to the directory as the user signing in. There is no service
account and no stored bind password. Only `ldaps://` is accepted; plain
`ldap://` is refused.

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_LDAP_URL` | (unset) | Directory URL, for example `ldaps://dc.home.example:636`. | no | yes (Directory) |
| `ATLAS_LDAP_BASE_DN` | (unset) | Base DN, for example `DC=home,DC=example`. Group membership is honoured only from under this DN unless `ATLAS_LDAP_GROUP_SCOPE=any`. | no | yes (Directory) |
| `ATLAS_LDAP_UPN_DOMAIN` | derived from the base DN | The domain appended to a bare user name to form the UPN (`DC=home,DC=example` gives `home.example`). | no | yes (Directory) |
| `ATLAS_LDAP_CA_FILE` | (unset) | A CA bundle for a private CA. Certificates are always verified; this only chooses which roots. | no | yes (Directory) |
| `ATLAS_LDAP_ACCESS_GROUPS` | (unset) | Comma-separated groups; when set, a user must be in one of them to sign in. When unset, anyone who can bind may sign in. Use `;` as the separator when entries are full DNs. | no | yes (Directory) |
| `ATLAS_LDAP_ADMIN_GROUPS` | value of `ATLAS_ADMIN_GROUP` | Groups (bare CN or full DN) whose members are Atlas admins. | no | yes (Directory) |
| `ATLAS_LDAP_GROUP_SCOPE` | `base` | `base` honours `memberOf` only from under the base DN. `any` honours it from anywhere in the forest, which lets anyone who can create a group with the right name elsewhere become admin. | no | no |
| `ATLAS_LDAP_TIMEOUT` | `5` | Directory connect and bind timeout, in seconds. | no | yes (Directory) |

### Hub mode (and the hub half of hybrid)

The hub is a reverse proxy that signs each request with a short-lived
HMAC-SHA256 token carrying the user, email and groups. The format is
`base64url(json) + "." + base64url(hmac)` with `u`, `e`, `g`, `iat` and `exp`
claims; `Web/hub_auth/auth.py` has the reference `mint_token`.

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_HUB_SECRET` | (unset) | The shared secret the hub signs identity tokens with. **Set it.** In `hub` mode without it the app falls back to trusting plaintext `X-Remote-User` / `X-Remote-Email` / `X-Remote-Groups` headers, which is safe only if nothing but the hub can reach the port. In `hybrid` mode without it, hub sign-in is disabled and everyone uses the sign-in page. | yes, `ATLAS_HUB_SECRET_FILE` | no |
| `ATLAS_HUB_AUTH_HEADER` | `X-Hub-Auth` | The request header that carries the signed token. | no | no |
| `HUB_URL` | (unset) | Where the hub lives, used for the "sign out at the hub" link. A request's `X-Hub-URL` header takes precedence. | no | yes (Realm) |
| `ATLAS_HUB_URL` | (unset) | The hub's base URL for the calendar feed: when set, `/api/v2/calendar` asks the hub for the combined day of every app it fronts (signed as a machine identity with `ATLAS_HUB_SECRET`) and falls back to the Atlas's own schedule when the hub does not answer. Separate from `HUB_URL`. | no | no |

## Integrations

Live health comes from optional sources. Each one is off until its URL is set
and its name is listed in `ATLAS_SIGNALS_SOURCES`. A source that is down or
misconfigured only removes its markers; the map still draws.

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_SIGNALS_SOURCES` | (empty) | Comma-separated list of live sources to poll: `prometheus`, `kuma`, `deception` (the decoy feed), `relay` (pushes stored by the ingest API, `db` backend), `static` (a JSON file). Empty means a static map, except on the bundled demo (`ATLAS_FALLBACK=bundled`, not yet seeded), which reads the image's demo feed and reports it as the `demo` source. | no | yes (Sources) |
| `ATLAS_SIGNALS_FILE` | `/data/signals.json` | The JSON file the `static` source reads. | no | no |
| `ATLAS_PROM_URL` | (unset) | Prometheus base URL, for example `http://prometheus:9090`. Feeds host health markers, the card vitals and the built-in charts. | no | yes (Sources) |
| `ATLAS_LOKI_URL` | (unset) | Loki base URL, for example `http://loki:3100`. Feeds the log-derived charts. | no | yes (Sources) |
| `ATLAS_KUMA_URL` | (unset) | Uptime Kuma base URL, for example `http://uptime-kuma:3001`. The app reads Kuma's `/metrics`. | no | yes (Sources) |
| `ATLAS_KUMA_API_KEY` | (unset) | A Kuma API key (sent as the HTTP Basic password, as Kuma expects). | yes, `ATLAS_KUMA_API_KEY_FILE` | yes (Sources, stored encrypted) |
| `ATLAS_DECOYS_URL` | (unset) | Base URL of a decoy (honeypot) service whose JSON feed of tripped decoys the `deception` source reads from `<url>` + `ATLAS_DECOYS_PATH`. One of the [tripwire](#tripwires) sources. | no | yes (Sources) |
| `ATLAS_DECOYS_PATH` | `/api/stones` | The path on `ATLAS_DECOYS_URL` that serves the decoy feed. Must be an absolute path (`/...`) with no host, query or spaces; anything else falls back to the default. | no | yes (Sources) |
| `ATLAS_DECOYS_KEY` | (unset) | The read key sent to the decoy service. | yes, `ATLAS_DECOYS_KEY_FILE` | yes (Sources, stored encrypted) |
| `ATLAS_DECOYS_KEY_HEADER` | `X-Api-Key` | The header the decoy read key is sent in. | no | no |
| `ATLAS_LLM_CONTAINERS` | `.+` | A Loki regex over container names, for the charts that count language-model calls in your logs. The default matches every container. | no | no |
| `ATLAS_LLM_LOG_TAG` | `llm` | The prefix of the `<tag> ok` / `<tag> FALLBACK` log lines those charts count. | no | no |
| `ATLAS_ANNALS_POLL` | `60` | Seconds between background polls that keep the event history and the scheduled-job checks current while nobody has the map open. `0` disables; values under 15 fall back to 60. | no | no |
| `NETBOX_TOKEN` | (unset) | NetBox API token, for `python cli.py import-netbox` only. The web app never reads it. | yes, `NETBOX_TOKEN_FILE` | no |
| `ATLAS_PROXMOX_URL` | (unset) | Proxmox VE base URL, for Settings → Connections. Can also be saved there. | no | yes (Connections) |
| `ATLAS_PROXMOX_TOKEN` | (unset) | Proxmox API token, `user@pam!name=secret`, with the PVEAuditor role. Encrypted when saved in the app. Or `ATLAS_PROXMOX_TOKEN_FILE`. | yes | yes (Connections) |
| `ATLAS_PROXMOX_INSECURE` | (unset) | `1` skips the certificate check, for Proxmox's default self-signed certificate. | no | yes (Connections) |
| `ATLAS_PORTAINER_URL` | (unset) | Portainer base URL, for Settings → Connections. | no | yes (Connections) |
| `ATLAS_PORTAINER_KEY` | (unset) | Portainer access token. It has its owner's rights, so make it from a read-only user. Or `ATLAS_PORTAINER_KEY_FILE`. | yes | yes (Connections) |
| `ATLAS_PORTAINER_INSECURE` | (unset) | `1` skips the certificate check. | no | yes (Connections) |
| `ATLAS_KOMODO_URL` | (unset) | Komodo Core base URL, for Settings → Connections. | no | yes (Connections) |
| `ATLAS_KOMODO_KEY` | (unset) | Komodo API key, from a user with read access only. Or `ATLAS_KOMODO_KEY_FILE`. | yes | yes (Connections) |
| `ATLAS_KOMODO_SECRET` | (unset) | The secret that goes with `ATLAS_KOMODO_KEY`. Or `ATLAS_KOMODO_SECRET_FILE`. | yes | yes (Connections) |
| `ATLAS_KOMODO_INSECURE` | (unset) | `1` skips the certificate check. | no | yes (Connections) |
| `ATLAS_NETBOX_URL` | (unset) | NetBox base URL, for Settings → Connections. | no | yes (Connections) |
| `ATLAS_NETBOX_API_TOKEN` | (unset) | NetBox API token with Write enabled off, for the connection test and review. Separate from `NETBOX_TOKEN`, which is the CLI import's. Or `ATLAS_NETBOX_API_TOKEN_FILE`. | yes | yes (Connections) |
| `ATLAS_NETBOX_INSECURE` | (unset) | `1` skips the certificate check. | no | yes (Connections) |

A stored credential goes only to the address it was saved with. To point a system at a new
address, in Settings → Connections or Sources, type its credential again: a blank secret box
means "keep the stored one", so a test or a save that changes the URL and leaves it blank is
refused. This keeps a saved secret write-only, even from an admin.

### Reviewing what a system knows

Each system in Settings → Connections has a **Review** button. It reads what the system
knows with the saved settings, so save first, and lists it beside what the map already has.
Nothing reaches the map until you tick it and press **Add to the map**. It runs when
you press it and never in the background, so the map does not change under you.

| System | Places | Other |
|---|---|---|
| Proxmox VE | nodes, virtual machines, containers | a guest's host is set as its `parent` |
| Portainer | environments | stacks, as services on their environment |
| Komodo | servers | stacks, as services on their server |
| NetBox | devices, virtual machines | VLANs, as realms, with the subnet of their first prefix |

- **Already on the map** means the same record was imported before, or the address matches,
  or the name matches. Those rows cannot be ticked. A tick only adds: an import never
  changes or removes what is already charted.
- **Same name, different address** is listed with a warning. Tick it to add a second place.
- **A stack needs a host**, so ticking one ticks its host, unless the host is already charted.
  Its link opens the stack in Portainer or Komodo, because neither says where a stack answers.
- **Ignore** hides a row from later reviews. Ignored rows stay listed at the foot of the review,
  where you can bring them back. The list is the same one The Survey uses.
- **A guest's address** is best effort. Proxmox lists no addresses for guests, so a running
  container is asked directly, and a virtual machine needs the QEMU guest agent and a role
  that may read it. A guest that does not say lands with no address.
- A place whose address falls in no realm's subnet lands in the realm you choose, or in
  Uncharted, which is created if the map has not got it.

An import is one entry in the change log, with the note `imported from <system>`, and can be
undone there or with the **Undo** beside the result. The Undo refuses if the map has changed
since, because undoing restores the whole map as it was. The system is read again at import, so
what lands is what it says at that moment, and an import of more than 500 changes is refused.

## Embedding (the viewing glass)

The map can open a service's web page in a pane over the map instead of a new
tab. The browser enforces this through the `frame-src` part of the Content
Security Policy, which the app builds from these settings.

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_EMBED_HOSTS` | (empty) | Extra origins the map may frame, space separated, for example `https://grafana.home.example`. | no | yes (Realm) |
| `ATLAS_EMBED_SERVICES` | `1` | `1` also allows framing the origins your dataset already links to. `0` limits framing to `ATLAS_EMBED_HOSTS`, and every service button opens a new tab. | no | yes (Realm) |
| `ATLAS_EMBED_PROBE` | `1` | `1` asks a service whether it allows framing before offering the pane. `0` skips the check and falls back to a tab when the pane stays blank. | no | yes (Realm) |
| `ATLAS_WHOIS` | `1` | `1` lets a viewer ask public whois servers from the Chronicle, 20 questions a minute per client on each worker. `0` removes the pane and refuses the route. Set it to `0` on an Atlas strangers can reach. | no | yes (Realm) |

The policy that lists dataset origins is only sent to signed-in viewers in
`accounts` and `hybrid` modes; the sign-in page gets `frame-src 'self'`.

## Ingest and heartbeats

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_INGEST_ENABLED` | (unset) | `1` turns on the relay ingest API (`/api/v2/ingest/{signals,inventory,observed}`), which accepts signals, inventory and observations pushed by the relay agent with a per-site token (`python cli.py token-issue`). Needs `ATLAS_DATA_BACKEND=db`; ignored otherwise. The tripwires webhook beside it has its own switch, `ATLAS_TRIPWIRES_WEBHOOK`. | no | no |
| `ATLAS_BEAT_TOKEN` | (unset) | Shared token that lets a scheduled job report "I ran" with `POST /api/v2/rites/<key>/beat` (`Authorization: Bearer <token>` or an `X-Atlas-Beat` header). Unset turns the endpoint off (503). In `accounts` and `hybrid` modes the sign-in gate answers before the token is checked, so use the beats directory there. | yes, `ATLAS_BEAT_TOKEN_FILE` | yes (Realm, stored encrypted) |
| `ATLAS_BEATS` | `<data dir>/heartbeats.json` | Where received heartbeats are stored. | no | no |
| `ATLAS_BEATS_DIR` | `<data dir>/beats` | Drop directory: a job that cannot reach the app reports by creating a file named after its key here (`touch /data/beats/<key>`). The app picks the file up and deletes it. | no | no |

## Tripwires

[The install guide](install.md#turn-on-tripwires) has the steps to turn this on.
The rest of this section is the reference.

Tripwires are honeypots and canary tokens charted in the dataset's `stones`
section. Trips reach the map from the decoy feed above, or from any tool
through a webhook, `POST /api/v2/ingest/tripwires`, which understands
OpenCanary's `WebhookHandler`, Canarytokens' webhook, and a generic
`{"tripwire_id", "at", "kind"}`. Each trip becomes an event in the event
history (`ATLAS_EVENTS`), on either data backend. Tripwires and their trips are
shown to admins only. The webhook sits under the ingest prefix, so it bypasses
the sign-in gate and its credential is the whole boundary:

- `X-Atlas-Signature: sha256=<hex HMAC-SHA256 of the raw body>` keyed with
  `ATLAS_TRIPWIRES_SECRET`, for scripts that can sign;
- `Authorization: Bearer <key>` (OpenCanary), or `?key=<key>` on the URL
  (Canarytokens, which cannot send headers), where `<key>` is the webhook key
  printed by `python cli.py tripwires-key`. It is derived from the secret, so
  the secret itself never travels and changing the secret changes the key.
  A URL key can appear in proxy access logs; prefer the header where the
  sender supports one.
- on the `db` backend, a site token minted with
  `python cli.py token-issue --site <site> --scopes tripwires` also works as
  the bearer or `key`.

Bodies over 64 KB get 413, more than 60 requests a minute per credential 429.
Copy-paste configuration for each sender (the OpenCanary logger handler, the
Canarytokens webhook URL, the generic shape) is under SET UP in the Tripwires
scene, read from the admin-only `GET /api/v2/tripwires/setup`; secrets are never
in it.

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_TRIPWIRES_WEBHOOK` | (unset) | `1` turns the webhook on. It stays off (404) until a credential could be valid: a secret, or the `db` backend for site tokens. | no | no |
| `ATLAS_TRIPWIRES_SECRET` | (unset) | The webhook secret, at least 16 characters (`python cli.py tripwires-key --new-secret` prints a random one). Signs `X-Atlas-Signature` and derives the webhook key. | yes, `ATLAS_TRIPWIRES_SECRET_FILE` | no |
| `ATLAS_TRIPWIRES_STATE` | `<events dir>/tripwires.json` | When each sender (OpenCanary, Canarytokens, generic) was last heard and last tripped. Small; one row per sender. | no | no |

## Metrics

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_METRICS_TOKEN` | (unset) | Turns on `GET /metrics` (Prometheus format: request counts and latency by route, chart fetches, source health, build info) for scrapers that send `Authorization: Bearer <token>`. Unset, `/metrics` answers 404. | yes, `ATLAS_METRICS_TOKEN_FILE` | no |
| `PROMETHEUS_MULTIPROC_DIR` | `/tmp/atlas-metrics` (set in the image) | Directory for prometheus_client's multi-process mode, so `/metrics` sums both gunicorn workers. Leave the image's value alone. | no | no |

## Theme

`ATLAS_THEME` (listed under [Core](#core)) picks a JSON file in
`Web/themes/<name>.json`; names are lowercase letters, digits and dashes. A
theme only needs the keys it changes; everything else falls back to
`plain.json`. To use your own theme with the container, mount the file
read-only at `/app/themes/<name>.json` and set `ATLAS_THEME=<name>`.

## App manifest links

These two only decorate the app's machine-readable manifest
(`/api/manifest`), which a dashboard or hub can read to draw a card for the
Atlas.

| Variable | Default | What it does | Secret | Settings screen |
|---|---|---|---|---|
| `ATLAS_LAB_URL` | (unset) | The URL of this instance, shown as the card's link. | no | no |
| `ATLAS_PRODUCTION_URL` | (unset) | A second URL for the card, such as a public demo. | no | no |

## The relay agent (outside `Web/`)

The optional push agent in `relay/` runs on another machine and reads two
variables of its own. The web app does not read them.

| Variable | Default | What it does | Secret |
|---|---|---|---|
| `ATLAS_RELAY_TOKEN` | (unset) | The per-site ingest token, if it is not in the relay's TOML config. | yes |
| `ATLAS_WEB_DIR` | (unset) | Where to find a checkout of `Web/` when the relay imports shared code from it. | no |

## API tokens and MCP

Settings → Connections issues tokens for scripts, local models and coding harnesses
(admins only). A token is shown once and stored as a hash. It is read-only, it sees what
a signed-in viewer with no groups sees, and it reaches only `lab-data`, `maps`, `signals`,
`rites` and `events` under `/api/v2`, plus the MCP endpoint:

```
POST /api/v2/mcp        Authorization: Bearer <token>
```

The endpoint speaks MCP over HTTP, both the 2026-07-28 revision and the earlier
`initialize` handshake, and offers five read-only tools: `atlas_overview`, `atlas_search`,
`atlas_place`, `atlas_health` and `atlas_events`. Settings shows the setup for each client.
A cloud tool sends what it reads to its model's vendor, so a token handed to one takes
this map off your network.

If a proxy puts its own sign-in in front of the Atlas, point the tool at the Atlas directly:
that proxy's login cannot be answered with a token.

## Map styles with their own zoom

A region is a rectangle on one picture, so regions follow the art. The regions in your dataset
belong to the map's own default image. When a viewer picks another style from Settings, the map
shows that style's regions instead, or none.

A style brings its regions in a file beside the image, written by you and never uploaded. For
`island.webp`, that is `island.style.json`:

```json
{
  "label": "The Island",
  "regions": [
    {"id": "harbour", "name": "The Harbour", "map": "harbour.webp",
     "x": 40, "y": 55, "w": 20, "h": 15, "auto": true},
    {"id": "docks", "name": "The Docks", "map": "docks.webp", "parent": "harbour",
     "x": 10, "y": 30, "w": 50, "h": 40, "auto": true}
  ]
}
```

`x`, `y`, `w` and `h` are percent of the parent map, the same units the map editor uses. `label` is
the name in the style list, and the map takes that name while the style is chosen. `auto` opens the region when you zoom into it. An image a region names
is left out of the style list, because you reach it by zooming in. A file that cannot be read costs
the style its zoom, never the map.

A style can also arrange the map to suit its picture. `places` moves markers, by place id, and
`zones` moves the network names, by network id, in percent of the map. A region takes `places` too,
in percent of the region's own picture, for where a place sits once you zoom in:

```json
{
  "label": "The Island",
  "places": {"router": {"x": 42, "y": 61}, "nas": {"x": 30, "y": 48}},
  "zones": {"servers": {"x": 36, "y": 40}}
}
```

This changes the picture only, never your data. A place the file does not name stays where it is,
and a place it does name cannot be dragged while that style is chosen, because the drag would save
to the map's own spot.

A style can bring its own words too. `words` maps a word the Atlas uses to the one this picture
uses, in the case it finds it: `{"realm": "kingdom", "realms": "kingdoms", "tripwires": "little birds"}`.
Plain words only, up to 40 of them, and they change the Atlas's own labels, never a name in your
data. A viewer who turns on **Use standard words** under THE MAP in settings gets standard words on
every map instead. `"tripwire": "eye"` swaps the bird that marks a tripwire for an eye.

`"bright": true` tells the Atlas the picture is a light one. Names then sit on a dark plate, and the
picture dims while the network layer is up or a place is split into its services.
