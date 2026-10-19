# Contributing to the Atlas

Thanks for helping. This page covers setting up a development copy, running
the tests, the code style the repository follows, and the few rules every
change has to meet. [architecture.md](architecture.md) explains where things
live.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
Security problems go through the private process in
[SECURITY.md](SECURITY.md), not a public issue.

## Development setup

You need Python 3.12 (what the image and CI use), Node.js 20 or later for the
front-end tests, and git. Docker is optional; you only need it to build the
image.

The app keeps all of its state beside the dataset file, so point `ATLAS_DATA`
at a directory **outside** the repository. The examples use `~/atlas-dev`
and the invented demo lab as a starting dataset.

### Linux and macOS

```sh
git clone https://github.com/outset-systems/atlas.git && cd atlas
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r Web/requirements.txt pytest

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
pip install -r Web/requirements.txt pytest

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

## Running the tests

```sh
cd Web && python -m pytest -q          # the Python suite
node --test Web/tests/*.mjs            # front-end models (from the repo root)
node tools/check-boot.mjs Web/static/js
python docs/env-coverage.py            # every env var read is documented
```

All four run in CI on every push and pull request
(`.github/workflows/tests.yml`). Some tests are marked
`@pytest.mark.private_only` and are skipped in this repository; that is
expected.

Writing tests:

- Build an app with `tests/appfixture.py`'s `fresh_app(...)`, passing the
  environment the test needs. Do not set `os.environ` and import `app`
  directly: several modules read settings at import time and `fresh_app`
  reloads them.
- Use the demo lab's place ids (`gateway`, `hypervisor`, `nas`, `edge`,
  `app-host` …) and the documentation address ranges in new fixtures.
- Front-end logic that can be pure (maths, parsing, layout) goes in a
  `*-model.js` file with no DOM access, tested with `node:test` in
  `Web/tests/test_*.mjs`.

## Code style

There is no formatter or linter configuration; follow the code around you.
What the repository does consistently:

**Python**

- Four-space indents, double-quoted strings, standard library first.
- Every environment variable is read in `settings.py` (or by the subsystem
  that owns it, such as `crypto_at_rest.py` or `ldap_backend.py`), and every
  new variable gets a row in `docs/configuration.md`. CI fails otherwise.
- Each module logs to `logging.getLogger("atlas.<layer>.<module>")`; the
  layers are listed at the top of `app.py`, and
  `tests/test_logging_tree.py` checks the convention.
- Routes reach shared objects through `context.atlas()`, never module
  globals.
- Anything that talks to an outside service fails quietly: a timeout or bad
  answer becomes "no data", logged, never an exception that breaks the map.
- Comments and docstrings explain **why**. When code guards against a
  specific failure, say what the failure was.
- Broad `except Exception` is allowed where a failure must never stop the
  map, with a `# noqa: BLE001` comment saying why.

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
name, `api`, `security`, `tests`, `docs`, `ci`. Add a body when the reason is
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
- CI must pass: the tests, the env-coverage check and the secret scan.
- New behaviour needs a test. A bug fix needs a test that failed before.
- Update the docs in the same pull request when behaviour or settings change.

## Nothing personal, nothing borrowed

The Atlas is a generic tool, and the repository must stay that way:

- **No real data.** No real host names, IP addresses, domains, user names,
  e-mail addresses, keys, tokens or screenshots of a real network, in code,
  tests, seed data, comments, commit messages or issues. Use `home.example`
  and the documentation ranges `192.0.2.0/24`, `198.51.100.0/24` and
  `203.0.113.0/24` (the demo lab uses `10.77.x.x`).
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
