# Security policy

## Supported versions

The Atlas is at its first public release. Only the latest release gets
security fixes.

| Version | Supported |
|---|---|
| 0.1.x (latest) | yes |
| anything older | no |

Fixes ship as a new patch release and a new image tag on
`ghcr.io/outset-systems/atlas`.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through GitHub: open the repository's **Security** tab
and choose **Report a vulnerability** (GitHub's private vulnerability
reporting). Only the maintainers can see the report. If you cannot use
GitHub, write to security@outset.systems.

Please include:

- the version or commit you tested, and how it was deployed (auth mode,
  behind a proxy or not);
- what an attacker needs (network position, an account, an admin account);
- steps to reproduce, and what you expected instead.

What to expect: an acknowledgement within a week, a first assessment within
two weeks, and a fix or a plan within 90 days. We will agree a disclosure date
with you and credit you in the release notes unless you prefer not to be
named.

## Scope

In scope:

- the web app in `Web/` and its HTTP API;
- the published container image and `compose.public.yaml` as shipped;
- the relay agent in `relay/`;
- the GitHub Actions workflows in `.github/`.

Out of scope:

- `standalone` mode serving the map without a sign-in. That is what the mode
  does; the app warns about it at start, and the shipped compose file uses
  `accounts` mode.
- An admin doing admin things (editing the map, managing users, pointing an
  integration at a URL). Admins are trusted.
- Problems that need the hub secret, the master key or shell access to the
  host or container.
- `hub` mode without `ATLAS_HUB_SECRET` when the port is reachable by
  something other than the hub. The documentation says to set the secret.
- Vulnerabilities in Prometheus, Loki, Uptime Kuma, a decoy service, a
  directory server or your reverse proxy, unless the Atlas makes them worse.
- Denial of service by sending a lot of traffic.

## Threat model

The Atlas holds a map of your network: host names, internal addresses,
service URLs, racks, certificates and schedules. That map is useful to an
attacker, so the main question is who can see it. In **standalone** mode
anyone who can reach the port can see and (with `ATLAS_ALLOW_INSECURE=1`)
change everything; it is meant for loopback or a trusted network only. In
**accounts** mode only signed-in users see the map; sign-in is throttled per
user and per client address, sessions expire, TOTP can be required, and
directory sign-in uses LDAPS only. The sign-in page reveals neither the map's
name nor, through its Content Security Policy, the services the map links
to. In **hub** mode the Atlas trusts a reverse proxy that signs each request
with a shared secret; whoever the hub lets through can see the map, and
anyone who can reach the port directly and knows the secret could claim any
identity. **Hybrid** accepts either. In every mode, places and links marked
`require_group` are hidden from viewers outside that group, only admins can
write, and every write must come from the Atlas's own page (a custom header
plus `Sec-Fetch-Site`), which blocks cross-site request forgery. Secrets
saved in the app (TOTP secrets, integration keys) are encrypted with a master
key kept in `/data/secrets/`, so a backup of `/data` is as sensitive as the
running instance.

## Hardening log

### 2026-11-01

A defensive review of the app, the image and the publishing tooling. Fixed in
this pass:

- `cryptography` is now required at `>=46.0.7` (the old upper bound kept the
  image on a release with open advisories). The app uses Fernet only.
- Hub signed-identity tokens are refused when they claim a lifetime over 300
  seconds, and a signed token with a malformed `exp`/`iat` is refused rather
  than raising.
- Changing or disabling a second factor (`/api/v2/auth/mfa/setup`,
  `/mfa/disable`) now requires the current password and, when a factor is
  already enabled, a fresh code from it. The code is consumed. Re-enrolling
  over a live factor without that proof is refused.
- The code typed to confirm an enrollment can no longer be replayed at the
  login that follows; backup codes are burnt in the same statement that
  checks them, so two workers cannot both accept one.
- Directory sign-in never records the reserved admin group as an ordinary
  clearance group; the admin flag is the only admin path.
- The Content Security Policy adds `base-uri 'none'`, `form-action 'self'`
  and `object-src 'none'`.
- LDAP group scoping matches the base DN on a component boundary.
- The public build gate allow-lists every binary that may ship, fails on a
  theme file other than the public one, and fails when an exclusion entry
  no longer matches anything.

Added the same day, for an Atlas that strangers can reach:

- `GET /api/v2/whois` allows 20 questions a minute per client on each worker,
  and `ATLAS_WHOIS=0` turns it off.
- Every request body is capped just above the largest map image.
- A read-only `standalone` instance has no admin, since nobody signs in there,
  so it refuses `/api/v2/admin/*` and the trust map. Its tripwire reads stay
  open because that mode already shows every visitor the whole map.
- `/admin/import/csv` and `/admin/discovery/as-nodes` go through the write
  gate like every other write.

A second review the same day closed these:

- `next` on the sign-in page refuses control characters and backslashes anywhere
  in the value, because a browser removes tabs and newlines before it reads a URL.
- A right password no longer resets the failure count while a code is still owed.
- Sign-in spends the same time on an unknown name as on a known one.
- In hub mode, a named `ATLAS_HUB_SECRET_FILE` that is missing or empty refuses
  every request instead of falling back to unsigned headers, and `/api/manifest`
  shows its schedule only to a verified caller.
- The `frame-src` header holds only the origins of places this viewer may see,
  and only for a caller who has proved who they are.
- Rites, chart legends, event causes, repair summaries and MCP events no longer
  name a place hidden from the viewer.

Known and accepted:

- There is no request rate limit apart from sign-in, ingest and whois; put the
  app behind a reverse proxy that provides one.
