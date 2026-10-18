"""The error envelope, defined once.

Every JSON error built here is `{"error": <sentence>}` plus, when there is more
to say, `reason` (why this was refused — the operator-facing half of a 403)
and/or `problems` (a list, for validation). Three of the four spellings that
used to coexist collapse into this one shape with optional keys: `{"error"}`,
`{"error","reason"}`, `{"error","problems"}`.

The fourth — the accounts surface's `{"ok": false, "error"}` — deliberately
stays. `auth_routes` handlers key their own success/failure off `ok` and the
sign-in JS reads it, so those bodies keep it; this builder is for everything
else. The one seam: a same-origin refusal on an `/api/auth/*` route comes from
`security.same_origin_refusal` (this builder) and so has no `ok`, while the
handler's own validation errors on the same route do — the front-end tolerates
both because it reads `.error` regardless. A future accounts client must not
assume `ok` is always present on that workstation.

`**extra` is for a key a specific route's client genuinely needs beside the
sentence (`needs_proof` on the directory save); the reserved keys above always
win over it, so it cannot reshape the envelope.
"""

from flask import jsonify


def fail(status, error, *, reason=None, problems=None, **extra):
    """`(json, status)` — return it straight from a view."""
    body = dict(extra)
    # the reserved keys win over **extra, never the other way round: a stray
    # extra={"error": ...} must not clobber the sentence or the validation list
    body["error"] = error
    if reason is not None:
        body["reason"] = reason
    if problems is not None:
        body["problems"] = problems
    return jsonify(body), status
