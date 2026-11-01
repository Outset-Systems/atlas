"""Group-based redaction — shared by every surface that serves the dataset:
the v2 read API, the signals feed, the annals, the card vitals.

Any node or service link carrying `require_group` is visible only to a viewer
whose Hub groups include it. Extracted from app.py (work item 7) so every API
enforces the *same* rule rather than a second copy of it: a security control
with two implementations is a security control with one bug waiting.

Standalone / LAN dev means no gate. Hub mode derives clearance from the SIGNED
identity and fails closed.
"""

import copy

from flask import request

import hub_auth.auth as auth
import schema
from hub_auth.auth import get_remote_groups, verify_token

import envnames  # noqa: E402

ADMIN_GROUP = envnames.env("ATLAS_ADMIN_GROUP")
SIGNED_HEADER = auth.SIGNED_HEADER

# `AUTH_MODE` and `AUTH_SECRET` are read through the module, not copied into
# this namespace at import. A copy would be a second source of truth for
# whether the gate is on — the exact "one control, two implementations" hazard
# this module was extracted to prevent, one level down. It also meant nothing
# could change the mode at runtime and have authorisation agree with
# authentication, which is why the two group-redaction tests could never see
# hub mode and had been failing silently.


def viewer_groups():
    """The viewer's groups, or None when no gate applies (standalone / dev).

    Hub mode reads the *signed* claims via hub_auth.get_remote_groups() —
    the same verified identity the auth gate itself enforces. This used to read
    the plaintext `X-Remote-Groups` header directly, which meant authentication
    was signed while authorisation was not, and had two consequences:

      1. A missing header returned None, and None means "sees everything". The
         Hub marks `X-Remote-User`/`X-Remote-Groups` as "kept for apps not yet
         on signing" — the day those legacy headers are dropped, every viewer
         would have been silently promoted to admin and the two admin-only
         write routes would have opened to all.
      2. Clearance came from an unsigned header while identity came from a
         signed token, i.e. the exact "one control, two implementations"
         hazard this module was extracted to prevent.

    In hub mode an unresolvable identity is now NO clearance rather than full
    clearance. Behaviour for real users is unchanged: the Hub puts the same
    group list in the signed token that it puts in the legacy header.

    Note we do NOT simply defer to get_remote_groups() when a secret is
    configured: that helper falls back to the plaintext `X-Remote-Groups` header
    whenever the signed token is absent or invalid (a kindness for hubs not yet
    signing), which is precisely the override this function exists to refuse.
    Once signing is in force, only the signature counts.

    An API token (api_tokens.py) is an empty set, not None: it sees what a viewer
    with no groups sees, in every mode, whoever issued it.

    Accounts mode (real sign-in, atlas_auth.py) resolves clearance from the
    session's account instead: assigned groups for local users, the cached
    directory groups for ldap users, with the admin flag standing in for
    ADMIN_GROUP so this module's checks work unchanged. Signed out = empty
    set = no clearance, never None.
    """
    import api_tokens
    if api_tokens.current():
        return set()
    import atlas_auth
    # accounts AND hybrid both resolve clearance from atlas_auth: a session's
    # account, or (hybrid) the Hub's SIGNED claims. ⚠ This must stay ahead of
    # the AUTH_MODE test below — that line returns None, and None here means
    # "sees everything", so a hybrid instance falling through to it would hand
    # full clearance and both admin-only write routes to every caller. That is
    # the §4.4.1b "standalone collapses open" failure, one mode further along.
    if atlas_auth.sessions_enabled():
        return atlas_auth.current_groups()
    if auth.AUTH_MODE != "hub":
        return None
    if auth.AUTH_SECRET:
        claims = verify_token(request.headers.get(SIGNED_HEADER, ""))
        if not claims:
            return set()
        raw = claims.get("g", [])
        if not isinstance(raw, list):
            raw = str(raw).split(",")
        return {str(g).strip() for g in raw if str(g).strip()}
    # No secret: legacy plaintext trust is all the Hub gives us (documented
    # fallback). Still fails closed on a missing header, unlike the original.
    return {g for g in get_remote_groups() if g}


#: Every request header that can change what a redacted response contains.
#: Any response whose body depends on the viewer MUST carry this, or a shared
#: cache in front of the app (the edge proxy this is being hardened for) is
#: entitled to serve one viewer's copy to the next. `Cookie` covers the Atlas
#: session, the signed token covers hub/hybrid, and the two plaintext headers
#: cover a Hub that is not signing yet.
VIEWER_VARY = f"Cookie, {SIGNED_HEADER}, X-Remote-User, X-Remote-Groups"


def vary_on_viewer(resp):
    """Mark a response as per-viewer. Returns it, so it can wrap a return."""
    resp.headers["Vary"] = VIEWER_VARY
    return resp


def sees_everything(groups):
    return groups is None or ADMIN_GROUP in groups


def cleared(entry, groups):
    """True if `entry` (a node or link dict) is visible to `groups`."""
    if sees_everything(groups):
        return True
    required = entry.get("require_group")
    return not required or required in groups


def group_key(groups):
    """Cache key fragment so viewers with different clearances don't share an ETag.

    The no-clearance case must NOT collapse to "" — that is the admin key, and an
    empty group set is now reachable (hub mode, unresolvable identity), so the
    two would have shared an ETag and served an admin's cached dataset to a
    viewer with no clearance at all.
    """
    if sees_everything(groups):
        return ""
    return "|".join(sorted(groups)) or "-none-"


# ── Scrubbing references to hidden places ───────────────────────────────────
#
# Dropping a node from `nodes[]` is only half of hiding it. Its id is also
# written into every section that points AT a place — `routes.from/to`,
# `interfaces.device`, `rack.node`, `vms.id/host`, `maintenance.nodes`, and the
# node's own `parent`/`depends_on`/`children`/`reaches`/`links.connects`/
# `links.path`. Leaving those behind hands the viewer the hidden place's id and
# its position in the topology, which is most of what the redaction was for.
#
# The field list is taken from the schema (`ref="nodes"`) rather than written
# out here on purpose: this is the "one control, two implementations" hazard the
# module docstring warns about, and a new node-reference field added to the
# catalogue must not silently become a new leak.

#: Fields whose value is an ORDERED chain of places, where dropping one element
#: would silently assert an adjacency that does not exist (`links.path` draws
#: "through" — see its schema help). These are dropped whole, never filtered.
_ORDERED_REF_FIELDS = {"path"}


def _node_refs(section_key):
    """[(field, subfield|None, type)] for every ref from a section to nodes."""
    out = []
    for fld in schema.fields_of(section_key):
        if fld.get("ref") == "nodes":
            out.append((fld["name"], None, fld["type"]))
        for sub in fld.get("of", []) or []:
            if sub.get("ref") == "nodes":
                out.append((fld["name"], sub["name"], sub["type"]))
    return out


def _scrub_entry(entry, refs, hidden, defining):
    """Strip hidden ids from one entry. False ⇒ the entry itself must go.

    `defining` says whether a reference to a place is the entry's REASON to
    exist. Outside the `nodes` section it always is: a road, a rack unit, a
    vassal, an interface, a repair window are each about the place they name,
    and their own label is usually that place's name. Blanking the id there
    would hide the reference and keep the disclosure — "Secret box" still sits
    in the rack. Inside `nodes`, by contrast, the reference is one attribute of
    a place the viewer IS cleared for, so only the value is removed.
    """
    for name, sub, ftype in refs:
        if sub is not None:
            items = entry.get(name)
            if isinstance(items, list):
                entry[name] = [
                    item for item in items
                    if not isinstance(item, dict)
                    or _scrub_value(item, sub, ftype, hidden, defining)]
            continue
        if not _scrub_value(entry, name, ftype, hidden, defining):
            return False
    return True


def _scrub_value(holder, name, ftype, hidden, defining):
    """Clean one field in place. False ⇒ the holder must go (see `_scrub_entry`)."""
    if name not in holder:
        return True
    value = holder[name]
    if ftype == "strings":
        if not isinstance(value, list):
            return True
        kept = [v for v in value if v not in hidden]
        if len(kept) == len(value):
            return True
        if defining:
            return False
        if name in _ORDERED_REF_FIELDS:
            holder.pop(name, None)          # a partial chain would be a lie
            return True
        holder[name] = kept
        return True
    if value in hidden:
        if defining:
            return False
        holder.pop(name, None)
    return True


def _scrub_signals_block(d, hidden):
    """`signals` is not in the catalogue (it round-trips untouched; the editor
    has no page for it) — the schema cannot describe it, so it is scrubbed by
    hand. `signals.kuma` maps a monitor NAME to a node id, so it
    leaks both the hidden id and the name of the monitor watching it."""
    block = d.get("signals")
    if not isinstance(block, dict):
        return
    kuma = block.get("kuma")
    if isinstance(kuma, dict):
        block["kuma"] = {m: n for m, n in kuma.items() if n not in hidden}


def hidden_node_ids(data, groups):
    """Ids of the places this viewer may not see. Empty when they see everything."""
    if sees_everything(groups):
        return set()
    return {n.get("id") for n in data.get("nodes", []) if not cleared(n, groups)}


def visible_monitors(data, groups):
    """Kuma monitor names charted on a service this viewer is cleared for.

    The signals feed is keyed by monitor name, not node id, so this is the seam
    that turns a clearance into "which health entries may they see". A monitor
    the map does not chart at all is in nobody's set — an uncharted monitor is
    survey information about the estate, not a service the viewer was given."""
    out = set()
    for node in data.get("nodes", []):
        if not cleared(node, groups):
            continue
        for link in node.get("links") or []:
            if cleared(link, groups) and link.get("kuma"):
                out.add(link["kuma"])
    hidden = hidden_node_ids(data, groups)
    for monitor, node_id in ((data.get("signals") or {}).get("kuma") or {}).items():
        if node_id not in hidden:
            out.add(monitor)
    return out


def redact_for_groups(data):
    """Return (dataset, cache_key) with entries the viewer isn't cleared for removed."""
    groups = viewer_groups()
    if sees_everything(groups):
        return data, ""
    d = copy.deepcopy(data)
    # TRIPWIRES ARE ADMIN-ONLY, WHOLESALE (v0.1). Where a honeypot sits and
    # where a canary token is planted is the deception layout itself: there
    # is no per-entry version of it worth giving, and a scrubbed stone still
    # says that bait exists here and how much. Same blunt rule as the
    # account roster below, and on the same not-`sees_everything` path.
    d.pop("stones", None)
    hidden = hidden_node_ids(d, groups)
    d["nodes"] = [n for n in d.get("nodes", []) if cleared(n, groups)]
    for n in d["nodes"]:
        if n.get("links"):
            n["links"] = [l for l in n["links"] if cleared(l, groups)]
        # THE ACCOUNT ROSTER IS ADMIN-ONLY, WHOLESALE (2026-08-25).
        #
        # Deliberately NOT per-entry `require_group` the way links are: a list
        # of who can get into a host and how far in is a target list read the
        # wrong way round, and a per-entry gate leaks the whole roster the
        # first time someone forgets to set it on one row. There is no partial
        # answer worth giving here, so the rule is the blunt one — cleared to
        # see everything, or you see none of it.
        #
        # This runs on the NOT-`sees_everything` path only (the function
        # returns early above for an admin), so it strips for exactly the
        # viewers who must not have it, and fails closed with
        # `viewer_groups()`: an unresolvable identity in hub mode is no
        # clearance, not full clearance.
        n.pop("accounts", None)
    if hidden:
        for key, value in list(d.items()):
            if not isinstance(value, list):
                continue
            refs = _node_refs(key)
            if not refs:
                continue
            defining = key != "nodes"
            d[key] = [e for e in value
                      if not isinstance(e, dict)
                      or _scrub_entry(e, refs, hidden, defining)]
        _scrub_signals_block(d, hidden)
        # REGIONS (v1.49.0): `places` is a json object keyed BY place id, so
        # the ref walker above cannot see it — a pin would name a hidden place
        # (and say where it sits) to a viewer not cleared for it.
        for r in d.get("regions") or []:
            pins = r.get("places") if isinstance(r, dict) else None
            if isinstance(pins, dict):
                r["places"] = {k: v for k, v in pins.items() if k not in hidden}
    return d, group_key(groups)
