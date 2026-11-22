import re

from jsonio import iso_utc

KEY = "provenance"
SECTION = "nodes"
HAND = "hand"
REVIEW = "review"
FIELDS = ("charted_by", "charted_at", "source", "changed_by", "changed_at",
          "reviewed_by", "reviewed_at")
UNSEEN = "changed_since_review"
LAYOUT = frozenset({"x", "y"})

_ORIGIN = re.compile(r"[^a-z0-9 ._-]")


def origin_of(value):
    word = _ORIGIN.sub("", str(value or "").strip().lower())[:40].strip()
    return word or HAND


def _bare(node):
    return {k: v for k, v in node.items() if k != KEY and k not in LAYOUT}


def _by_id(data):
    return {n["id"]: n for n in data.get(SECTION) or []
            if isinstance(n, dict) and isinstance(n.get("id"), str)}


def _touched(ops, before, was, now_ids):
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
            try:
                row = rows[int(op["index"])]
                target = row.get("id") if isinstance(row, dict) else None
            except (TypeError, ValueError, IndexError):
                target = None
        if op.get("op") == REVIEW:
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


def _mark(node):
    mark = node.get(KEY) if isinstance(node, dict) else None
    return mark if isinstance(mark, dict) else None


def _own(node):
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
            node.pop(KEY, None)
            continue
        if trust:
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
                    mark[UNSEEN] = True
        if node_id in checked or (by_hand and node_id in named):
            mark = mark or {}
            mark.update({"reviewed": True, "reviewed_by": actor, "reviewed_at": when})
            mark.pop(UNSEEN, None)
        if mark is None:
            node.pop(KEY, None)
        else:
            node[KEY] = mark
    return after


def restamp_revert(current, snapshot, actor, now=None):
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


NAMES = ("charted_by", "changed_by", "reviewed_by")


def for_viewer(nodes):
    for node in nodes or []:
        mark = _mark(node)
        if mark is not None:
            node[KEY] = {k: v for k, v in mark.items() if k not in NAMES}


def describe(node):
    mark = _mark(node)
    if mark is None:
        return {"reviewed": None,
                "note": "Charted before the map kept provenance. Who and when are not known."}
    out = {k: str(mark[k]) for k in FIELDS if mark.get(k)}
    out["reviewed"] = mark.get("reviewed") if isinstance(mark.get("reviewed"), bool) else None
    if out["reviewed"] is False:
        out["note"] = "Written by an import and not yet checked by a person. Treat as unconfirmed."
    elif out["reviewed"] and not settled(node):
        out[UNSEEN] = True
        out["note"] = ("Reviewed by a person, and it has changed since. "
                       "Treat what changed as unconfirmed.")
    return out


def unchecked(node):
    return _mark(node) is not None and not settled(node)


def settled(node):
    mark = _mark(node)
    if mark is None or mark.get("reviewed") is not True:
        return False
    reviewed_at = str(mark.get("reviewed_at") or "")
    if not reviewed_at or mark.get(UNSEEN) is True:
        return False
    return reviewed_at >= str(mark.get("changed_at") or "")


def summary(nodes):
    counts = {"reviewed": 0, "unreviewed": 0, "unknown": 0}
    oldest_unreviewed = newest_change = None
    for node in nodes or []:
        mark = _mark(node)
        if mark is None or not isinstance(mark.get("reviewed"), bool):
            counts["unknown"] += 1
        elif mark["reviewed"]:
            counts["reviewed"] += 1
        else:
            counts["unreviewed"] += 1
            at = str(mark.get("charted_at") or "")
            if at and (oldest_unreviewed is None or at < oldest_unreviewed):
                oldest_unreviewed = at
        changed = str(mark.get("changed_at") or "") if mark is not None else ""
        if changed and (newest_change is None or changed > newest_change):
            newest_change = changed
    return {**counts, "oldest_unreviewed": oldest_unreviewed, "newest_change": newest_change}
