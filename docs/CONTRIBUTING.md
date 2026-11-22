# Contributing to the Atlas

Thanks for helping. This page covers setting up a development copy, running
the checks, the code style the repository follows, and the few rules every
change has to meet. [architecture.md](architecture.md) explains where things
live.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
Security problems go through the private process in
[SECURITY.md](SECURITY.md), not a public issue.

## Development setup

You need Python 3.12 (what the image and CI use), Node.js 20 or later for the
front-end checks, and git. Docker is optional; you only need it to build the
image.

The app keeps all of its state beside the dataset file, so point `ATLAS_DATA`
at a directory **outside** the repository. The examples use `~/atlas-dev`
and the invented demo lab as a starting dataset.

### Linux and macOS

```sh
git clone https://github.com/outset-systems/atlas.git && cd atlas
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r Web/requirements.txt

mkdir -p ~/atlas-dev
cp demo-lab/seed/lab-data.demo.json ~/atlas-dev/lab-data.json

cd Web
export ATLAS_DATA=~/atlas-dev/lab-data.json ATLAS_HOST=127.0.0.1 ATLAS_ALLOW_INSECURE=1
python app.py
```

### Windows (PowerShell)

```powershell
git clone https://github.com/outset-systems/atlas.git; cd atlas
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r Web/requirements.txt

New-Item -ItemType Directory -Force "$HOME\atlas-dev" | Out-Null
Copy-Item demo-lab\seed\lab-data.demo.json "$HOME\atlas-dev\lab-data.json"

cd Web
$env:ATLAS_DATA = "$HOME\atlas-dev\lab-data.json"
$env:ATLAS_HOST = "127.0.0.1"
$env:ATLAS_ALLOW_INSECURE = "1"
python app.py
```

Then open <http://127.0.0.1:5006>. This runs `standalone` mode (no sign-in),
writable because of `ATLAS_ALLOW_INSECURE=1`, and bound to loopback.

To work on sign-in, also set `ATLAS_AUTH_MODE=accounts` and
`ATLAS_INSECURE_COOKIES=1` (plain http), and create a user from `Web/` in
the same shell, so it sees the same `ATLAS_DATA`:

```sh
python cli.py user-add dev --admin
```

`ATLAS_ACCOUNTS_DB` defaults to `accounts.db` beside `ATLAS_DATA`, so it also
stays out of the repository. Every other setting is in
[configuration.md](configuration.md).

The dev server reloads nothing by itself; restart it after a Python change.
Static files are served from `Web/static/` directly, so a JavaScript or CSS
change only needs a browser reload (a hard reload if the old file sticks).

### With Docker

```sh
docker compose -f compose.public.yaml up -d --build
```

See [install.md](install.md). Rebuild after each change.

## Running the checks

```sh
python -m compileall -q Web relay docs    # every file compiles
node tools/check-boot.mjs Web/static/js   # the boot calls all resolve
node tools/check-links.mjs Web/static/js  # every named import is an export
python docs/env-coverage.py               # every env var read is documented
```

CI runs these, and boots the app on the demo lab, on every push and pull
request (`.github/workflows/tests.yml`).

This repository is a generated release tree. The full test suite and the
source's commentary are kept in the maintainers' own repository, because both
grew around a real network and cannot be published. A change you send is
applied there and run against that suite before it is released.

## Code style

There is no formatter or linter configuration; follow the code around you.
What the repository does consistently:

**Python**

- Four-space indents, double-quoted strings, standard library first.
- Every environment variable is read in `settings.py` (or by the subsystem
  that owns it, such as `crypto_at_rest.py` or `ldap_backend.py`), and every
  new variable gets a row in `docs/configuration.md`. CI fails otherwise.
- Each module logs to `logging.getLogger("atlas.<layer>.<module>")`; the
  layers are `web`, `api`, `auth`, `data`, `io` and `live`.
- Routes reach shared objects through `context.atlas()`, never module
  globals.
- Anything that talks to an outside service fails quietly: a timeout or bad
  answer becomes "no data", logged, never an exception that breaks the map.
- Put the **why** in the pull request. Comments and docstrings are removed
  when a release tree is generated.
- Broad `except Exception` is allowed where a failure must never stop the
  map, and it is logged.

**JavaScript**

- Plain ES modules, no build step, no framework, no new dependencies from a
  CDN. A vendored library goes in `static/js/vendor/` with its licence.
- Two-space indents, single quotes, semicolons.
- Modules share state through `A` and `CFG` from `config.js`; attach a
  module's public functions to `A`, and call other modules with
  `A.someFunction?.()`.
- No inline `<script>`, no `onclick=` attributes, no `eval`. The Content
  Security Policy blocks them, so they will not run.
- Use relative URLs (`api/v2/...`), never a leading `/`.

**Text files** use LF line endings (`.gitattributes` enforces it).

## Commit messages

One line of the form `area: what changed`, in lower case, under about 72
characters, for example `ledger: draw /22 prefixes on real CIDR maths` or
`docs: trusted-proxy example for Caddy`. Common areas: the module or feature
name, `api`, `security`, `docs`, `ci`. Add a body when the reason is
not obvious from the diff: what was wrong, and why this is the fix. One
logical change per commit.

## Sign off your commits (DCO)

Every commit in a pull request must carry a `Signed-off-by:` line with your
real name and e-mail, certifying the
[Developer Certificate of Origin 1.1](https://developercertificate.org/): in
short, that you wrote the change or otherwise have the right to submit it
under the project's licence. `git commit -s` adds the line for you; to sign
off commits you already made, `git rebase --signoff main`.

Pull requests with unsigned commits will be asked to add the sign-off before
review.

## Pull requests

- Keep a pull request to one change. Open an issue first for anything large.
- Fill in the template: what changed, why, how you tested it.
- CI must pass: the checks and the secret scan.
- Say how you tested new behaviour, and how to reproduce a bug you fixed.
- Update the docs in the same pull request when behaviour or settings change.

## Adding a connection

A connection lets Atlas read a system you already run (Proxmox, UniFi, NetBox)
and offer what it finds for review. Atlas never scans, and a connection never
writes to the map on its own: it produces rows, an admin ticks the ones to
keep, and those land as unreviewed places.

One system is one module in `Web/importers/`, named for its key. Read
`Web/importers/portainer.py` first: it is the smallest complete one. A module
has three names, described in `Web/importers/wire.py`:

- `SYSTEM`: the catalogue entry. Its key, its name, how to get a read-only
  credential, and its fields. Settings draws the form from this.
- `probe(base, creds, verify)`: one or two read-only calls. Returns a sentence
  such as "Portainer: 2 environments, 5 stacks".
- `survey(base, creds, verify)`: reads what the system knows and returns
  `(candidates, notes)`. Build candidates with the helpers in
  `Web/importers/review.py` (`place`, `service`, `zone`, `port`, `route`).

Then:

1. Add the module to `CONNECTORS` in `Web/connections.py`.
2. Document each `ATLAS_*` setting in `docs/configuration.md`, or the
   env-coverage check fails.
3. Include an invented example of the system's answer in the pull request,
   so a test can be written for it. Never a recording of a real system.

Rules every connection keeps:

- Ask for the system's read-only kind of credential, and say which in
  `SYSTEM["credential"]`.
- Never follow a redirect: it would carry the credential somewhere else. Use
  `wire.ok()`, which refuses one.
- Use `wire.TIMEOUT` on every call.
- Raise `wire.Refused` with a sentence the admin can act on.
- If the system's API is unofficial, say so in
  `docs/configuration.md`.

## Nothing personal, nothing borrowed

The Atlas is a generic tool, and the repository must stay that way:

- **No real data.** No real host names, IP addresses, domains, user names,
  e-mail addresses, keys, tokens or screenshots of a real network, in code,
  seed data, commit messages, pull requests or issues. Use `home.example`
  and the documentation ranges `192.0.2.0/24`, `198.51.100.0/24` and
  `203.0.113.0/24` (the demo lab uses `172.28.x.x`).
- **No franchise material.** No names, terms, artwork or icons from games,
  books, films or other fiction, in code, seed data or the default theme.
  Your own theme file can say whatever you like; keep it out of the
  repository.
- **No personal names** in code or data, except the credit you get in
  release notes.

Pull requests that add any of these will be asked to remove them before
review. `.github/workflows/secrets.yml` scans every push for credentials.

## Licence

The Atlas is released under the MIT licence (`LICENSE`). By contributing,
and by signing off your commits, you agree that your contribution is
licensed the same way.
