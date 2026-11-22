from engines.places import service_key


def enabled(data):
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
    out = {}
    for a, b, _ in _pairs(before, after_links, old_id, new_id):
        out.setdefault(a, b)
    return out


def renamed_places(ops, before):
    known = {n["id"] for n in _places(before)}
    origin = {}
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
    to = moves.get(key) if isinstance(key, str) else None
    if isinstance(to, str):
        return [to]
    if isinstance(to, (list, tuple)):
        return [k for k in to if isinstance(k, str)] or None
    return None


def splits(moves):
    out = {}
    for key in moves:
        news = _news(moves, key)
        if news and len(news) > 1:
            out[key] = news
    return out


def _moved(keys, moves):
    if not isinstance(keys, list) or not any(_news(moves, k) for k in keys):
        return None
    out = []
    for k in keys:
        for now in _news(moves, k) or [k]:
            if now not in out:
                out.append(now)
    return out


def collection_ops(data, moves):
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
