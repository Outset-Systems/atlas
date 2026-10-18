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
