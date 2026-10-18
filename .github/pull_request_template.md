## What this changes

<!-- One or two sentences. Link the issue if there is one: "Fixes #123". -->

## Why

<!-- The problem this solves, or the behaviour it corrects. -->

## How I tested it

<!-- Commands you ran, and anything you checked by hand in the browser. -->

- [ ] `cd Web && python -m pytest -q` passes
- [ ] `node --test Web/tests/*.mjs` passes (if front-end models changed)
- [ ] `python docs/env-coverage.py` passes (if a setting was added or renamed)

## Checklist

- [ ] New behaviour has a test; a bug fix has a test that failed before it.
- [ ] Docs are updated (`docs/configuration.md` for any new environment variable).
- [ ] No inline scripts or `onclick=` attributes (the CSP blocks them).
- [ ] No real host names, IP addresses, domains, user names, secrets or
      screenshots of a real network; examples use `home.example` and
      `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`.
- [ ] No names, terms or artwork from games, books, films or other fiction.
- [ ] I agree that this contribution is licensed under the MIT licence.
