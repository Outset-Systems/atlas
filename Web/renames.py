"""CARRYING RENAMES (2026-11-15, stage 3b; the owner: "a toggle to carry renames").

A service is known by its key (`signals.service_key`): its Kuma monitor's
name, or `<place id>/<label>`. Renaming a service's label, pointing it at
another monitor, taking the monitor's name off it, or renaming its place
changes the key, and every collection, repair window and alert rule naming
the old key would be left naming nothing.

With `meta.carry_service_renames` on, a write to a place's `links` (or its id)
works out which keys moved and carries them: collections in the same save,
the repair windows and the alert rules straight after it, each under its own
store's lock. Off (the default), what is left behind is only said
(a collection's ⋯, Settings › Alerts' Rules on something gone).

A link is "the same link" before and after when it has the same address and
that address is on one link only; otherwise the one at the same position,
when the list kept its length. A link that cannot be paired moves nothing.

THE WHOLE MAP DECIDES (2026-11-18). Two links may share a key (one monitor
named by links on several places), so one place's links cannot say whether a
key moved:

* A key some link still has after the write does not move: a link that kept
  it, or a new link that took it. Whatever names it still names something,
  and stays where it is (`map_moves` says which). A link that only came to
  the key in this write, from another key, is not "still has": two labels
  swapped each follow their own link.
* A key no link has any more goes to every key its links have now, in map
  order. A collection and a repair window list services, so they get them
  all; an alert rule names one, so it goes to the first (`splits` says so).

An undo is a write like any other: the keys it puts back are carried back the
same way, from the map as it was to the map as it is, so no list of what
moved has to be kept.
"""

from engines.places import service_key


def enabled(data):
    """True when the map asks for renames to be carried (`meta`)."""
    meta = data.get("meta") if isinstance(data, dict) else None
    return isinstance(meta, dict) and meta.get("carry_service_renames") is True


def _links(node):
    links = node.get("links") if isinstance(node, dict) else None
    return [l for l in links if isinstance(l, dict)] if isinstance(links, list) else []


def _places(data):
    nodes = data.get("nodes") if isinstance(data, dict) else None
    return [n for n in nodes if isinstance(n, dict) and isinstance(n.get("id"), str)] \
        if isinstance(nodes, list) else []


def _pairs(before, after_links, old_id, new_id):
    """[(old key, new key, the link as it is now)] for one place's links whose
    key changed, in the order the links have after the write."""
    old = _links(before)
    new = [l for l in after_links if isinstance(l, dict)] if isinstance(after_links, list) else old
    by_url = {}
    for l in new:
        url = l.get("url")
        if isinstance(url, str) and url:
            by_url.setdefault(url, []).append(l)
    old_urls = {}
    for l in old:
        url = l.get("url")
        if isinstance(url, str) and url:
            old_urls[url] = old_urls.get(url, 0) + 1
    place = {id(l): i for i, l in enumerate(new)}
    taken = set()
    pairs = []
    for i, l in enumerate(old):
        url = l.get("url")
        match = None
        if isinstance(url, str) and url and old_urls.get(url) == 1 and len(by_url.get(url, [])) == 1:
            match = by_url[url][0]
        elif len(old) == len(new):
            match = new[i]
        if match is not None and id(match) not in taken:
            taken.add(id(match))
            pairs.append((place[id(match)], l, match))
    out = []
    for _, was, now in sorted(pairs, key=lambda p: p[0]):
        a, b = service_key(old_id, was), service_key(new_id, now)
        if a != b:
            out.append((a, b, now))
    return out


def key_moves(before, after_links, old_id, new_id):
    """{old key: new key} for one place: `before` is the place as stored,
    `after_links` its links after the write (None: unchanged), `new_id` its id
    after it. Keys that did not change are left out. One place only: whether
    a key is still in use elsewhere, and a key that goes to several, are
    `map_moves`'s to say (here the first new key stands for them all)."""
    out = {}
    for a, b, _ in _pairs(before, after_links, old_id, new_id):
        out.setdefault(a, b)
    return out


def renamed_places(ops, before):
    """{old id: new id} for the places these ops rename: an upsert naming a
    place the map has (or one renamed earlier in the batch) whose body gives
    it another id."""
    known = {n["id"] for n in _places(before)}
    origin = {}                      # the id a place has now -> the id it had
    for op in ops if isinstance(ops, list) else []:
        if not (isinstance(op, dict) and op.get("op") == "upsert" and op.get("section") == "nodes"):
            continue
        body = op.get("body") if isinstance(op.get("body"), dict) else {}
        target, new = op.get("id"), body.get("id")
        if not (isinstance(target, str) and isinstance(new, str) and new and new != target):
            continue
        was = origin.pop(target, target if target in known else None)
        if was is not None:
            origin[new] = was
    return {old: new for new, old in origin.items() if old != new}


def map_moves(before, after, renamed=None):
    """({old key: [new keys, in map order]}, [keys that stayed]) for a whole
    write: `before` and `after` are the map on either side of it, `renamed`
    the places it gave another id ({old id: new id}); every other place is
    the one with the same id.

    A key is carried only when no link anywhere on the map still has it
    after the write: a link that kept it, or a new one that took it. A link
    that came to the key in this same write, from another key, does not hold
    it back: two labels swapped, or `A` renamed `B` while `B` is renamed `C`,
    each go where their own link went. A key that changed on some link and
    is still in use is in the second list, sorted, and moves nothing."""
    renamed = renamed if isinstance(renamed, dict) else {}
    back = {new: old for old, new in renamed.items()}
    was = {n["id"]: n for n in _places(before)}
    found, in_use = {}, set()
    for node in _places(after):
        nid = node["id"]
        links = _links(node)
        old_id = back.get(nid, nid)
        prior = was.get(old_id)
        pairs = []
        if prior is not None and not (nid in renamed and nid not in back) \
                and not (old_id == nid and prior.get("links") == node.get("links")):
            # (a new place under an id another one left is not paired with it)
            pairs = _pairs(prior, links, old_id, nid)
        arrived = {id(now) for _, _, now in pairs}
        in_use.update(service_key(nid, l) for l in links if id(l) not in arrived)
        for a, b, _ in pairs:
            news = found.setdefault(a, [])
            if b not in news:
                news.append(b)
    moves = {a: news for a, news in found.items() if a not in in_use}
    return moves, sorted(a for a in found if a in in_use)


def _news(moves, key):
    """The keys `key` moved to (a list; one key alone may be given as a
    string), or None when it did not move."""
    to = moves.get(key) if isinstance(key, str) else None
    if isinstance(to, str):
        return [to]
    if isinstance(to, (list, tuple)):
        return [k for k in to if isinstance(k, str)] or None
    return None


def splits(moves):
    """{old key: [new keys]} for the keys that went to more than one."""
    out = {}
    for key in moves:
        news = _news(moves, key)
        if news and len(news) > 1:
            out[key] = news
    return out


def _moved(keys, moves):
    """`keys` (a list) with each moved key replaced by every key it moved to;
    None when none moved."""
    if not isinstance(keys, list) or not any(_news(moves, k) for k in keys):
        return None
    out = []
    for k in keys:
        for now in _news(moves, k) or [k]:
            if now not in out:
                out.append(now)
    return out


def collection_ops(data, moves):
    """The upserts that carry `moves` in the collections' `services`."""
    ops = []
    listed = data.get("collections") if isinstance(data, dict) else None
    for c in listed if isinstance(listed, list) else []:
        if isinstance(c, dict) and isinstance(c.get("id"), str):
            services = _moved(c.get("services"), moves)
            if services is not None:
                ops.append({"op": "upsert", "section": "collections", "id": c["id"],
                            "body": {"services": services}})
    return ops


def carried_windows(windows, moves):
    """The windows with `moves` carried in their `services`; None when none moved."""
    changed = False
    out = []
    for w in windows if isinstance(windows, list) else []:
        services = _moved(w.get("services"), moves) if isinstance(w, dict) else None
        if services is not None:
            w = {**w, "services": services}
            changed = True
        out.append(w)
    return out if changed else None


def carried_rules(doc, moves):
    """The alerts document with `moves` carried in rules on a service; None
    when none moved. A rule names one service: where its key went to several,
    it goes to the first in map order."""
    changed = False
    rules = []
    for r in doc.get("rules") or [] if isinstance(doc, dict) else []:
        target = r.get("target") if isinstance(r, dict) else None
        news = _news(moves, target.get("id")) if (
            isinstance(target, dict) and target.get("kind") == "service") else None
        if news:
            r = {**r, "target": {**target, "id": news[0]}}
            changed = True
        rules.append(r)
    return {**doc, "rules": rules} if changed else None
