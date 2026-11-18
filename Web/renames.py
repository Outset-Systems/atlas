"""CARRYING RENAMES (2026-11-15, stage 3b; the owner: "a toggle to carry renames").

A service is known by its key (`signals.service_key`): its Kuma monitor's
name, or `<place id>/<label>`. Renaming a service's label, pointing it at
another monitor, or renaming its place changes the key, and every collection,
repair window and alert rule naming the old key would be left naming nothing.

With `meta.carry_service_renames` on, a write to a place's `links` (or its id)
works out which keys moved and carries them: collections in the same save,
the repair windows and the alert rules straight after it, each under its own
store's lock. Off (the default), what is left behind is only said
(a collection's ⋯, Settings › Alerts' Rules on something gone).

A link is "the same link" before and after when it has the same address and
that address is on one link only; otherwise the one at the same position,
when the list kept its length. A link that cannot be paired moves nothing.
"""

from engines.places import service_key


def enabled(data):
    """True when the map asks for renames to be carried (`meta`)."""
    meta = data.get("meta") if isinstance(data, dict) else None
    return isinstance(meta, dict) and meta.get("carry_service_renames") is True


def _links(node):
    links = node.get("links") if isinstance(node, dict) else None
    return [l for l in links if isinstance(l, dict)] if isinstance(links, list) else []


def key_moves(before, after_links, old_id, new_id):
    """{old key: new key} for one place: `before` is the place as stored,
    `after_links` its links after the write (None: unchanged), `new_id` its id
    after it. Keys that did not change are left out."""
    old = _links(before)
    new = [l for l in after_links if isinstance(l, dict)] if isinstance(after_links, list) else old
    pairs = []
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
    taken = set()
    for i, l in enumerate(old):
        url = l.get("url")
        match = None
        if isinstance(url, str) and url and old_urls.get(url) == 1 and len(by_url.get(url, [])) == 1:
            match = by_url[url][0]
        elif len(old) == len(new):
            match = new[i]
        if match is not None and id(match) not in taken:
            taken.add(id(match))
            pairs.append((l, match))
    out = {}
    for was, now in pairs:
        a, b = service_key(old_id, was), service_key(new_id, now)
        if a != b:
            out[a] = b
    return out


def _moved(keys, moves):
    """`keys` (a list) with each moved key replaced; None when none moved."""
    if not isinstance(keys, list) or not any(isinstance(k, str) and k in moves for k in keys):
        return None
    out = []
    for k in keys:
        k = moves.get(k, k) if isinstance(k, str) else k
        if k not in out:
            out.append(k)
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
    when none moved."""
    changed = False
    rules = []
    for r in doc.get("rules") or [] if isinstance(doc, dict) else []:
        target = r.get("target") if isinstance(r, dict) else None
        if (isinstance(target, dict) and target.get("kind") == "service"
                and isinstance(target.get("id"), str) and target["id"] in moves):
            r = {**r, "target": {**target, "id": moves[target["id"]]}}
            changed = True
        rules.append(r)
    return {**doc, "rules": rules} if changed else None
