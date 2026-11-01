"""v2's authentication and authorisation — every answer comes from the shared
`security.py` / `redaction.py` / `atlas_auth.py`.

This is the Flask stand-in for a framework "auth class": one object that says
who is calling and what they may do, resolved once per request and handed to
handlers. It is deliberately a thin adapter:

* **Authentication** is not done here at all. The app-wide gate
  (`atlas_auth.require_atlas_auth`, installed by `create_app()`) has already
  run by the time any v2 handler executes, in every mode — standalone, hub,
  accounts, hybrid. v2 adds no second gate, so there is no second place for the
  rules to drift.
* **Identity and clearance** are not resolved here either: a handler that
  needs them calls `security.actor()` and `redaction.viewer_groups()`.
* **Authorisation** comes from `security.is_admin()` and
  `security.write_refusal()`, unchanged, including their exact refusal bodies.

If a route ever needs an authorisation rule that does not exist in
`security.py` or `redaction.py`, the rule belongs there, not here: this module
adapts, it never decides.
"""

from functools import wraps

from flask import jsonify

import security


def admin_required(view):
    """403 anyone `security.is_admin()` does not vouch for.

    Same predicate and same body as the admin blueprint's `before_request`, so the editor's
    reads refuse identically on both sides of the migration.
    """
    @wraps(view)
    def guarded(*args, **kwargs):
        if not security.is_admin():
            return jsonify({"error": "admins only"}), 403
        return view(*args, **kwargs)
    return guarded


def write_required(view):
    """Refuse a write for every reason `security.write_refusal()` would —
    read-only instance, cross-site fetch, missing `X-Atlas-Write`, not an
    admin — with its exact `(json, status)`."""
    @wraps(view)
    def guarded(*args, **kwargs):
        refusal = security.write_refusal()
        if refusal:
            return refusal
        return view(*args, **kwargs)
    return guarded
