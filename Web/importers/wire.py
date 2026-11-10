"""What every connection shares when it talks to its system.

A connection is one module in this package with three names (see
`connections.py` for the registry and docs/CONTRIBUTING.md for the walkthrough):

    SYSTEM                      the catalogue entry the Settings form is drawn from
    probe(base, creds, verify)  one or two read-only calls; returns a sentence
    survey(base, creds, verify) what the system knows; returns (candidates, notes)

`creds` is the system's secret and text fields, in the order `SYSTEM["fields"]`
lists them. `verify` is False only when the admin ticked the self-signed box.
Both functions raise `Refused` with a sentence the admin can act on, or let a
`requests` exception through; `connections._asking` turns either into an answer.
"""

TIMEOUT = 6


class Refused(Exception):
    """The system answered and said no. Its message is what the admin needs."""


def ok(resp, who):
    if resp.status_code in (401, 403):
        raise Refused(f"{who} refused the credential.")
    if 300 <= resp.status_code < 400:
        # Never followed: a redirect would carry the credential to wherever it points.
        raise Refused(f"{who} redirected to {resp.headers.get('Location', 'somewhere else')}. "
                      "Use the final URL.")
    resp.raise_for_status()
    return resp


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"
