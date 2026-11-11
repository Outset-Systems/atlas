"""PROVENANCE — who charted a place, when, and whether a person has checked it.

The Atlas's claim is that the map is what someone approved. That is only worth
something to a reader who can see the approval: a place nobody has looked at
since an import wrote it is a guess, and a place last touched two years ago is
an old answer. So every place carries a small stamp, written here, at the moment
of the write, by the one path that changes the map (`dataset.DatasetStore`).

Stamped, not derived. The change log keeps 50 revisions, so an answer read back
out of it would forget the oldest places first.

    "provenance": {
      "charted_by": "ada",  "charted_at": "2026-11-09T21:14:03Z",
      "source": "hand",                 # or the import that wrote it: "unifi", "survey"
      "changed_by": "ada",  "changed_at": "...",
      "reviewed": true,     "reviewed_by": "ada", "reviewed_at": "..."
    }

THE RULES:

  * Only the server writes it. Whatever a client sends under this key is thrown
    away, so a form or a script cannot claim an approval that did not happen.
  * A place an import writes starts `reviewed: false`.
  * A person saving a place by hand reviews it, changed or not: opening it in
    the Desk and pressing Save is how you say "I have looked at this".
  * The same thing can be said without opening it: the `review` op names a
    place and changes nothing but its stamp. The Desk sends it for one row or
    for every row on screen, so a map charted before this existed can be
    checked in one sitting.
  * An import that adds to a reviewed place records the change and leaves the
    review standing. The review is of the place, not of each line on it. The
    stamp says so with `changed_since_review: true` until a person looks again,
    and `settled` is the test for "reviewed, and nothing has changed it since".
  * Dragging a marker is not a change to what the place is, and stamps nothing.
  * A place charted before this existed has no stamp, and readers are told so
    rather than handed an invented date.
  * The names (`*_by`) are for people who may see the whole map. Everyone else,
    an API token included, is told when and whether, not who (`for_viewer`,
    called from `redaction.redact_for_groups`): the change log is admin-only for
    the same reason, it names people.

WHO ELSE WRITES. The command line and the relay write around `DatasetStore`,
so they call the same `stamp` themselves: `cli.py import-json` before it loads
the file, and the netbox, nmap and csv importers through `store.restamp` once
their rows are in. What they add starts unreviewed, as "cli" or "relay".
`import-json --keep-stamps` is the one way a file's own stamps are believed, for
an operator restoring or moving a map: each place keeps the stamp the file gives
it, and a place the file does not stamp stays unstamped.

WHAT IT DOES NOT COVER. A dataset file edited by hand. A place written that way
carries whatever the file said, or nothing, and nothing here can tell.
"""

import re

from jsonio import iso_utc

KEY = "provenance"
SECTION = "nodes"
HAND = "hand"
#: The op that says "a person has checked this place" and changes nothing else.
REVIEW = "review"
#: Every text field a stamp may hold.
FIELDS = ("charted_by", "charted_at", "source", "changed_by", "changed_at",
          "reviewed_by", "reviewed_at")
#: Set, as `true`, when an import changes a place a person had already reviewed.
#: The review stands, and it is of what was there before. The next review or hand
#: save clears it. The stamps' times cannot say this alone: they are whole
#: seconds, and a review and an import can share one.
UNSEEN = "changed_since_review"
#: Where a marker sits says nothing about the place.
LAYOUT = frozenset({"x", "y"})

_ORIGIN = re.compile(r"[^a-z0-9 ._-]")


def origin_of(value):
    """A short, safe word for where a write came from. Blank means by hand."""
    word = _ORIGIN.sub("", str(value or "").strip().lower())[:40].strip()
    return word or HAND


def _bare(node):
    return {k: v for k, v in node.items() if k != KEY and k not in LAYOUT}


def _by_id(data):
    # a str id only: this runs before validation, and anything else is not a place
    return {n["id"]: n for n in data.get(SECTION) or []
            if isinstance(n, dict) and isinstance(n.get("id"), str)}


def _touched(ops, before, was, now_ids):
    """(ids a write named, {new id: old id} for renames, ids a person checked).

    A rename is believed only when it is one: an UPSERT whose target was on the
    map before and is not on it now. An insert that merely carries someone
    else's id in `op.id` is a new place, and gets a new place's stamp.
    """
    named, renamed, checked = set(), {}, set()
    rows = before.get(SECTION) if isinstance(before.get(SECTION), list) else []
    for op in ops or []:
        if not isinstance(op, dict) or op.get("section") != SECTION:
            continue
        if op.get("op") not in ("upsert", "insert", REVIEW):
            continue
        body = op.get("body") if isinstance(op.get("body"), dict) else {}
        target = op.get("id") if op.get("op") != "insert" else None
        if target is None and op.get("op") != "insert" and op.get("index") is not None:
            # addressed by position: the place is whoever stood there
            try:
                row = rows[int(op["index"])]
                target = row.get("id") if isinstance(row, dict) else None
            except (TypeError, ValueError, IndexError):
                target = None
        if op.get("op") == REVIEW:
            # "I have looked at this": no body, so nothing to rename or change
            if isinstance(target, str):
                checked.add(target)
            continue
        new = body.get("id", target)
        if not isinstance(new, str):
            continue
        named.add(new)
        if (isinstance(target, str) and target != new
                and target in was and target not in now_ids):
            renamed[new] = target
    return named, renamed, checked


def _own(node):
    """The stamp a file carries for a place, cut down to what a stamp may hold."""
    mark = node.get(KEY)
    if not isinstance(mark, dict):
        return None
    out = {k: str(mark[k])[:80] for k in FIELDS if isinstance(mark.get(k), str) and mark[k]}
    if isinstance(mark.get("reviewed"), bool):
        out["reviewed"] = mark["reviewed"]
    if mark.get(UNSEEN) is True:
        out[UNSEEN] = True
    return out or None


def stamp(before, after, ops, actor, origin=None, now=None, trust=False):
    """Write the stamps onto `after`, in place. `before` is the map as it was.

    `trust` is for the operator at the command line restoring or moving a map:
    a place the file stamps keeps the file's stamp. Nothing a browser or a
    token can reach passes it.
    """
    origin = origin_of(origin)
    by_hand = origin == HAND
    when = now or iso_utc()
    was = _by_id(before)
    named, renamed, checked = _touched(ops, before, was, set(_by_id(after)))
    for node in after.get(SECTION) or []:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            node.pop(KEY, None)          # not a place validation will accept; claim nothing
            continue
        if trust:
            # the file is the record: its stamp stands, and no stamp stays none
            own = _own(node)
            if own:
                node[KEY] = own
            else:
                node.pop(KEY, None)
            continue
        prior = was.get(renamed.get(node_id, node_id))
        kept = prior.get(KEY) if isinstance(prior, dict) and isinstance(prior.get(KEY), dict) else None
        if prior is None:
            mark = {"charted_by": actor, "charted_at": when, "source": origin,
                    "changed_by": actor, "changed_at": when, "reviewed": False}
        else:
            mark = dict(kept) if kept else None
            if _bare(node) != _bare(prior):
                mark = mark or {}
                mark.update({"changed_by": actor, "changed_at": when})
                if not by_hand and mark.get("reviewed") is True:
                    mark[UNSEEN] = True      # the review is of what was here before this
        if node_id in checked or (by_hand and node_id in named):
            mark = mark or {}
            mark.update({"reviewed": True, "reviewed_by": actor, "reviewed_at": when})
            mark.pop(UNSEEN, None)
        if mark is None:
            node.pop(KEY, None)          # nothing known, and nothing a client may invent
        else:
            node[KEY] = mark
    return after


def restamp_revert(current, snapshot, actor, now=None):
    """A revert is a change too. The snapshot brings its old stamps back with it;
    every place it alters or restores is marked as changed now, by whoever
    reverted, so "what changed since" does not miss it."""
    when = now or iso_utc()
    was = _by_id(current)
    for node in snapshot.get(SECTION) or []:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            continue
        prior = was.get(node["id"])
        if prior is None or _bare(prior) != _bare(node):
            mark = dict(node[KEY]) if isinstance(node.get(KEY), dict) else {}
            mark.update({"changed_by": actor, "changed_at": when})
            node[KEY] = mark
    return snapshot


#: Who, as opposed to when and whether.
NAMES = ("charted_by", "changed_by", "reviewed_by")


def for_viewer(nodes):
    """Take the names out, in place, for a reader who may not see the whole map."""
    for node in nodes or []:
        mark = node.get(KEY) if isinstance(node, dict) else None
        if isinstance(mark, dict):
            node[KEY] = {k: v for k, v in mark.items() if k not in NAMES}


def describe(node):
    """A place's stamp as a reader is told it. Never raises, never invents."""
    mark = node.get(KEY) if isinstance(node, dict) else None
    if not isinstance(mark, dict):
        return {"reviewed": None,
                "note": "Charted before the map kept provenance. Who and when are not known."}
    out = {k: str(mark[k]) for k in ("charted_by", "charted_at", "source", "changed_by", "changed_at",
                                     "reviewed_by", "reviewed_at") if mark.get(k)}
    out["reviewed"] = mark.get("reviewed") if isinstance(mark.get("reviewed"), bool) else None
    if out["reviewed"] is False:
        out["note"] = "Written by an import and not yet checked by a person. Treat as unconfirmed."
    elif out["reviewed"] and not settled(node):
        # the mark an import leaves, or a stamp whose times say the same thing
        out[UNSEEN] = True
        out["note"] = ("Reviewed by a person, and it has changed since. "
                       "Treat what changed as unconfirmed.")
    return out


def settled(node):
    """True when a person has reviewed this place AND nothing has changed it since.

    `reviewed` alone is not that. An import that adds to a reviewed place leaves
    the review standing (see THE RULES above), so a service a container named
    itself, or a fact a controller reported, can sit on a place that says
    `reviewed: true` without anyone having looked at it. The stamp still tells
    the two apart. `stamp` sets `changed_since_review` when an import changes a
    reviewed place, and clears it at the next review or hand save. For a stamp
    written before that mark existed the times decide: an import moves
    `changed_at` and not `reviewed_at`. Either one is enough to say no.

    Used where every word on a place has to have been in front of a person:
    the view an API token for a cloud tool gets (`cloud_view.py`). A stamp with
    no `reviewed_at` proves nothing, so it does not count.
    """
    mark = node.get(KEY) if isinstance(node, dict) else None
    if not isinstance(mark, dict) or mark.get("reviewed") is not True:
        return False
    reviewed_at = str(mark.get("reviewed_at") or "")
    if not reviewed_at or mark.get(UNSEEN) is True:
        return False
    # stamps are `...Z` and compare as text (`iso_utc`)
    return reviewed_at >= str(mark.get("changed_at") or "")


def summary(nodes):
    """The whole map's standing, for a reader deciding how far to trust it."""
    counts = {"reviewed": 0, "unreviewed": 0, "unknown": 0}
    oldest_unreviewed = newest_change = None
    for node in nodes or []:
        mark = node.get(KEY) if isinstance(node, dict) else None
        if not isinstance(mark, dict) or not isinstance(mark.get("reviewed"), bool):
            counts["unknown"] += 1
        elif mark["reviewed"]:
            counts["reviewed"] += 1
        else:
            counts["unreviewed"] += 1
            at = str(mark.get("charted_at") or "")
            if at and (oldest_unreviewed is None or at < oldest_unreviewed):
                oldest_unreviewed = at
        changed = str(mark.get("changed_at") or "") if isinstance(mark, dict) else ""
        if changed and (newest_change is None or changed > newest_change):
            newest_change = changed
    return {**counts, "oldest_unreviewed": oldest_unreviewed, "newest_change": newest_change}
