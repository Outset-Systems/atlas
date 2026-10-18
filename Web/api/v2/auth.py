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
* **Identity and clearance** come from `security.actor()` and
  `redaction.viewer_groups()`.
* **Authorisation** comes from `security.is_admin()` and
  `security.write_refusal()`, unchanged, including their exact refusal bodies.

If a route ever needs an authorisation rule that does not exist in
`security.py` or `redaction.py`, the rule belongs there, not here: this module
adapts, it never decides.
"""

from dataclasses import dataclass
from functools import wraps

from flask import jsonify

import security
from redaction import viewer_groups


@dataclass(frozen=True)
class Viewer:
    """Who is asking, as the shared helpers understand it.

    `groups is None` means "no gate applies" (standalone / dev) — the same
    sentinel `redaction.viewer_groups()` uses, kept rather than normalised to an
    empty set because the two mean opposite things: None sees everything, an
    empty set sees nothing cleared.
    """
    actor: str
    groups: frozenset | None
    is_admin: bool

    def cleared_for(self, group):
        """True if this viewer may see an entry that `require_group`s `group`."""
        return self.groups is None or self.is_admin or group in self.groups


def current_viewer():
    """Resolve the caller through the shared helpers, once.

    `is_admin` is `security.is_admin()` — the SAME predicate `admin_required`
    and `write_required` gate on — not a second computation off `groups`. The
    two happen to agree today (both reduce to `sees_everything(viewer_groups())`),
    but a v2 handler that authorizes off `current_viewer().is_admin` must get
    exactly what the decorators enforce, with no chance of drift."""
    groups = viewer_groups()
    return Viewer(
        actor=security.actor(),
        groups=None if groups is None else frozenset(groups),
        is_admin=security.is_admin(),
    )


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
