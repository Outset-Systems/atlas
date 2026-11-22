## What this changes

<!-- One or two sentences. Link the issue if there is one: "Fixes #123". -->

## Why

<!-- The problem this solves, or the behaviour it corrects. -->

## How I tested it

<!-- Commands you ran, and anything you checked by hand in the browser. -->

- [ ] `python -m compileall -q Web relay docs` passes
- [ ] `node tools/check-boot.mjs Web/static/js` passes (if scripts changed)
- [ ] `python docs/env-coverage.py` passes (if a setting was added or renamed)

## Checklist

- [ ] New behaviour says how it was tested; a bug fix says how to reproduce the bug.
- [ ] Docs are updated (`docs/configuration.md` for any new environment variable).
- [ ] No inline scripts or `onclick=` attributes (the CSP blocks them).
- [ ] No real host names, IP addresses, domains, user names, secrets or
      screenshots of a real network; examples use `home.example` and
      `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`.
- [ ] No names, terms or artwork from games, books, films or other fiction.
- [ ] Every commit is signed off (`git commit -s`), certifying the
      [Developer Certificate of Origin](https://developercertificate.org/).
- [ ] I agree that this contribution is licensed under the MIT licence.
