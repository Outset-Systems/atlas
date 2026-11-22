import copy
import re

from flask import request

import hub_auth.auth as auth
import schema
from hub_auth.auth import get_remote_groups, verify_token

import envnames

ADMIN_GROUP = envnames.env("ATLAS_ADMIN_GROUP")
LINK_DEFAULT_GROUP = envnames.env("ATLAS_LINK_DEFAULT_GROUP", "").strip()
EVERYONE = "*"
SIGNED_HEADER = auth.SIGNED_HEADER



def viewer_groups():
    import api_tokens
    if api_tokens.current():
        return set()
    import atlas_auth
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
    return {g for g in get_remote_groups() if g}


VIEWER_VARY = f"Cookie, {SIGNED_HEADER}, X-Remote-User, X-Remote-Groups"


def vary_on_viewer(resp):
    resp.headers["Vary"] = VIEWER_VARY
    return resp


def no_store(resp):
    resp.headers["Cache-Control"] = "no-store"
    return vary_on_viewer(resp)


def private_no_cache(resp):
    resp.headers["Cache-Control"] = "private, no-cache"
    return vary_on_viewer(resp)


def sees_everything(groups):
    return groups is None or ADMIN_GROUP in groups


def cleared(entry, groups):
    if sees_everything(groups):
        return True
    if not isinstance(entry, dict):
        return False
    required = entry.get("require_group")
    if not required:
        return True
    return isinstance(required, str) and required in groups


def link_cleared(link, groups):
    if sees_everything(groups):
        return True
    if not isinstance(link, dict):
        return False
    required = link.get("require_group")
    if required == EVERYONE:
        return True
    if not required and LINK_DEFAULT_GROUP:
        return LINK_DEFAULT_GROUP in groups
    return cleared(link, groups)


def group_key(groups):
    if sees_everything(groups):
        return ""
    return "|".join(sorted(groups)) or "-none-"


_URL = re.compile(r"^\s*([A-Za-z][A-Za-z0-9+.-]*)://(.*?)\s*$", re.S)


def bare_url(value):
    if not isinstance(value, str):
        return value
    m = _URL.match(value)
    if not m:
        return value
    scheme, rest = m.groups()
    cut = min((i for i in (rest.find("?"), rest.find("#")) if i != -1), default=len(rest))
    rest = rest[:cut]
    authority, slash, path = rest.partition("/")
    if "@" not in authority and "@" in path and not authority.startswith("[") \
            and re.search(r":(?!\d*$)", authority):
        authority, slash, path = rest.split("@", 1)[1].partition("/")
    return f"{scheme}://{authority.rsplit('@', 1)[-1]}{slash}{path}"


def bare_urls(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            value[key] = bare_urls(inner)
    elif isinstance(value, list):
        for i, inner in enumerate(value):
            value[i] = bare_urls(inner)
    elif isinstance(value, str):
        return bare_url(value)
    return value



_ORDERED_REF_FIELDS = {"path"}

_FILTERED_SECTIONS = {"nodes", "collections"}

_WORDY = frozenset({"words", "slug", "url"})


def _wordy(section_key):
    said = schema.HIDING.get(section_key)
    if not isinstance(said, dict):
        return [], {}
    own = [(name, kind) for name, kind in said.items() if isinstance(kind, str) and kind in _WORDY]
    parts = {name: [(part, kind) for part, kind in sub.items() if kind in _WORDY]
             for name, sub in said.items() if isinstance(sub, dict)}
    return own, {name: subs for name, subs in parts.items() if subs}


def _keyed(section_key):
    said = schema.HIDING.get(section_key)
    return [name for name, kind in said.items() if kind == "keys"] if isinstance(said, dict) else []


def _names_hidden(value, kind, names, slugs):
    if value is None or value == "":
        return False
    if isinstance(value, (list, tuple)):
        return any(_names_hidden(v, kind, names, slugs) for v in value)
    if isinstance(value, dict):
        return any(_names_hidden(v, kind, names, slugs) for v in value.values())
    text = str(value)
    if names is not None and names.search(text):
        return True
    if slugs:
        return slugs.in_id(text) if kind == "slug" else slugs.in_text(text)
    return False


_PINNED = frozenset({"regions"})


def _node_refs(section_key):
    out = []
    for fld in schema.fields_of(section_key):
        if fld.get("ref") == "nodes":
            out.append((fld["name"], None, fld["type"]))
        for sub in fld.get("of", []) or []:
            if sub.get("ref") == "nodes":
                out.append((fld["name"], sub["name"], sub["type"]))
    return out


class _Unseen:

    def __init__(self, visible, hidden):
        self._visible, self._hidden = visible, hidden
        self.exact = hidden

    def __contains__(self, value):
        if value is None or value == "":
            return False
        try:
            return value not in self._visible
        except TypeError:
            return True

    def __bool__(self):
        return bool(self._hidden)


def _scrub_entry(entry, refs, hidden, defining):
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


def _holds_hidden(value, hidden):
    if isinstance(value, dict):
        return any(_holds_hidden(k, hidden) or _holds_hidden(v, hidden)
                   for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_holds_hidden(v, hidden) for v in value)
    try:
        return value in hidden
    except TypeError:
        return False


def _scrub_value(holder, name, ftype, hidden, defining):
    if name not in holder:
        return True
    value = holder[name]
    if ftype != "strings" and isinstance(value, (list, dict)):
        if defining and _holds_hidden(value, getattr(hidden, "exact", hidden)):
            return False
        holder.pop(name, None)
        return True
    if ftype == "strings" and isinstance(value, str):
        if value not in hidden:
            return True
        if defining:
            return False
        holder.pop(name, None)
        return True
    if ftype == "strings":
        if not isinstance(value, list):
            if not _holds_hidden(value, hidden):
                return True
            if defining:
                return False
            holder.pop(name, None)
            return True
        kept = [v for v in value if not _holds_hidden(v, hidden)]
        if len(kept) == len(value):
            return True
        if defining:
            return False
        if name in _ORDERED_REF_FIELDS:
            holder.pop(name, None)
            return True
        holder[name] = kept
        return True
    if value in hidden:
        if defining:
            return False
        holder.pop(name, None)
    return True


def _scrub_signals_block(d, hidden):
    block = d.get("signals")
    if not isinstance(block, dict):
        return
    kuma = block.get("kuma")
    if isinstance(kuma, dict):
        block["kuma"] = {m: n for m, n in kuma.items() if not _holds_hidden(n, hidden)}


def _stub_ends(cable):
    out = set()
    for side in ("a_stub", "b_stub"):
        value = cable.get(side)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            return None
        out.add(value)
    return out


def _scrub_wiring(d, whole, hidden):
    stubs = d.get("stubs") if isinstance(d.get("stubs"), list) else None
    here = {s.get("id") for s in stubs or [] if isinstance(s.get("id"), str)}
    if isinstance(d.get("cables"), list):
        kept = []
        for c in d["cables"]:
            ends = _stub_ends(c)
            if ends is not None and ends <= here:
                kept.append(c)
        d["cables"] = kept
        for c in kept:
            c.pop("note", None)
    if stubs is None:
        return

    piece = {}

    def find(s):
        while piece.setdefault(s, s) != s:
            piece[s] = piece[piece[s]]
            s = piece[s]
        return s

    tainted, every = set(), False
    listed = whole.get("cables") if isinstance(whole, dict) else None
    for c in listed if isinstance(listed, list) else []:
        if not isinstance(c, dict):
            continue
        ends = _stub_ends(c)
        if ends is None:
            every = True
            continue
        if not ends:
            continue
        ends = sorted(ends)
        for other in ends[1:]:
            piece[find(other)] = find(ends[0])
        for side in ("a", "b"):
            place = c.get(side)
            if place not in (None, "") and (not isinstance(place, str) or place in hidden):
                tainted.add(ends[0])
    tainted = {find(s) for s in tainted}

    reached, joins = set(), {}
    for c in d.get("cables") if isinstance(d.get("cables"), list) else []:
        ends = _stub_ends(c) or set()
        if any(isinstance(c.get(side), str) and c.get(side) for side in ("a", "b")):
            reached |= ends
        for s in ends:
            joins.setdefault(s, set()).update(ends - {s})
    walk = list(reached)
    while walk:
        for s in joins.get(walk.pop(), ()):
            if s not in reached:
                reached.add(s)
                walk.append(s)

    def stays(s):
        return isinstance(s.get("id"), str) and (
            s["id"] in reached or not (every or find(s["id"]) in tainted))

    d["stubs"] = [s for s in stubs if stays(s)]
    if isinstance(d.get("cables"), list):
        left = {s["id"] for s in d["stubs"]}
        d["cables"] = [c for c in d["cables"] if (_stub_ends(c) or set()) <= left]


def _words_pass(d, names, slugs, hidden_keys):
    for key in schema.SECTIONS:
        value = d.get(key)
        if value is None or schema.HIDING.get(key) == "admin":
            continue
        own, parts = _wordy(key)
        keyed = _keyed(key)
        if not (own or parts or keyed):
            continue
        whole = key in schema.WORDS_DROP_ENTRY
        entries = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        kept = []
        for entry in entries:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            gone = False
            for field in keyed:
                if any(isinstance(k, str) and k in hidden_keys
                       for k in schema.as_list(entry.get(field))):
                    if whole:
                        gone = True
                        break
                    entry[field] = [k for k in schema.as_list(entry.get(field))
                                    if not (isinstance(k, str) and k in hidden_keys)]
            if gone:
                continue
            if names is not None or slugs:
                for field, kind in own:
                    if field in entry and _names_hidden(entry[field], kind, names, slugs):
                        if whole:
                            gone = True
                            break
                        entry.pop(field)
                if gone:
                    continue
                for field, subs in parts.items():
                    items = entry.get(field)
                    if not isinstance(items, list):
                        continue
                    if key == "nodes" and field == "links":
                        entry[field] = [item for item in items if not (
                            isinstance(item, dict)
                            and any(part in item and _names_hidden(item[part], kind, names, slugs)
                                    for part, kind in subs))]
                        continue
                    for item in items:
                        if isinstance(item, dict):
                            for part, kind in subs:
                                if part in item and _names_hidden(item[part], kind, names, slugs):
                                    item.pop(part)
            kept.append(entry)
        if isinstance(value, list):
            d[key] = kept


def _declared_only(d):
    for top in list(d):
        if top not in schema.SECTIONS and top != "signals":
            d.pop(top)
    signals = d.get("signals")
    if isinstance(signals, dict):
        for name in list(signals):
            if name != "kuma":
                signals.pop(name)
    elif "signals" in d:
        d.pop("signals")
    for key in list(d):
        said = schema.HIDING.get(key)
        if said == "admin":
            d.pop(key)
            continue
        if key not in schema.SECTIONS:
            continue
        fields = {f["name"]: f for f in schema.fields_of(key)}
        allowed = set(fields) | ({"provenance"} if key == "nodes" else set())
        if isinstance(said, dict):
            allowed -= {name for name, kind in said.items() if kind == "admin"}
        value = d[key]
        for entry in value if isinstance(value, list) else [value] if isinstance(value, dict) else []:
            if not isinstance(entry, dict):
                continue
            for name in [n for n in entry if n not in allowed]:
                entry.pop(name)
            for name, fld in fields.items():
                parts = {s["name"] for s in fld.get("of") or []}
                if not parts or not isinstance(entry.get(name), list):
                    continue
                for item in entry[name]:
                    if isinstance(item, dict):
                        for part in [p for p in item if p not in parts]:
                            item.pop(part)


def hidden_node_ids(data, groups):
    if sees_everything(groups):
        return set()
    out = set()
    for n in data.get("nodes", []):
        if not (isinstance(n, dict) and isinstance(n.get("id"), (str, int, float))
                and not isinstance(n.get("id"), bool)) or cleared(n, groups):
            continue
        out.add(n["id"])
        if not isinstance(n["id"], str):
            out.add(str(n["id"]))
    return out


def hidden_words(data, groups):
    if sees_everything(groups):
        return None
    words = set()
    for n in data.get("nodes", []):
        if isinstance(n, dict) and not cleared(n, groups):
            ip = str(n.get("ip") or "").split("/")[0].strip()
            words |= {str(w) for w in (n.get("id"), n.get("name"), ip)
                      if w and str(w).strip() not in schema.NONE_MARKS}
    if not words:
        return None
    edge = r"[^\W_]"
    return re.compile(rf"(?<!{edge})(?:" + "|".join(map(re.escape, sorted(words)))
                      + rf")(?!{edge})", re.IGNORECASE)


_LIST_MARKS = re.compile(r"[\n,;:()\[\]]")


def slug(text, lists=False):
    import unicodedata
    plain = unicodedata.normalize("NFKD", str(text or "").lower())
    plain = "".join(ch for ch in plain if unicodedata.category(ch)[0] != "M")
    if not lists:
        return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    return re.sub(r"[^a-z0-9]+", lambda m: "~" if _LIST_MARKS.search(m.group()) else "-",
                  plain).strip("-~")


def _slug_worthy(word):
    import unicodedata
    symbol = False
    word = _APOSTROPHES.sub("'", str(word))
    for ch in word:
        if slug(ch) or ch.isspace():
            continue
        if all(c.isascii() for c in unicodedata.normalize("NFKD", ch)):
            continue
        kind = unicodedata.category(ch)
        if (kind[0] == "L" and not unicodedata.name(ch, "").startswith("LATIN")) or kind[0] == "N":
            return False
        if kind == "So":
            symbol = True
    s = slug(word)
    if symbol and "-" not in s:
        return False
    return sum(ch.isalnum() for ch in s) >= 3 and any(ch.isalpha() for ch in s)


_APOSTROPHES = re.compile(r"['\u2019\u02bc]")


class HiddenSlugs:

    def __init__(self, words):
        bound = r"(?<![a-z0-9])(?:{})(?![a-z0-9])"
        words = set(words) | {s for s in (_APOSTROPHES.sub("", w) for w in words)
                              if _slug_worthy(s)}
        ids = {slug(w) for w in words}
        ids |= {s[:48].strip("-") for s in ids if len(s) > 48}
        self._ids = re.compile(bound.format("|".join(map(re.escape, sorted(ids)))))
        texts = {slug(w, lists=True) for w in words} | {slug(w) for w in words}
        self._texts = re.compile(bound.format("|".join(map(re.escape, sorted(texts)))))

    def in_id(self, text):
        bare = _APOSTROPHES.sub("", str(text or ""))
        return bool(self._ids.search(slug(text)) or self._ids.search(slug(bare)))

    def in_text(self, text):
        bare = _APOSTROPHES.sub("", str(text or ""))
        return bool(self._texts.search(slug(text, lists=True))
                    or self._texts.search(slug(bare, lists=True)))


def hidden_slugs(data, groups):
    if sees_everything(groups):
        return None
    words = set()
    for n in data.get("nodes", []):
        if isinstance(n, dict) and not cleared(n, groups):
            ip = str(n.get("ip") or "").split("/")[0].strip()
            for w in (n.get("id"), n.get("name"), ip):
                if w and str(w).strip() not in schema.NONE_MARKS and _slug_worthy(w):
                    words.add(str(w))
    return HiddenSlugs(words) if words else None


def visible_monitors(data, groups):
    from engines.base import monitor_map
    from engines.places import service_key
    out = set()
    withheld = set()
    for node in data.get("nodes", []):
        if not isinstance(node, dict) or not cleared(node, groups):
            continue
        links = node.get("links") if isinstance(node.get("links"), list) else []
        for link in links:
            if not isinstance(link, dict):
                continue
            key = service_key(node.get("id"), link)
            (out if link_cleared(link, groups) else withheld).add(key)
    hidden = hidden_node_ids(data, groups)
    visible = {n.get("id") for n in data.get("nodes", [])
               if isinstance(n, dict) and isinstance(n.get("id"), str) and cleared(n, groups)}
    withheld -= out
    for monitor, node_id in monitor_map(data).items():
        if monitor not in withheld and ((node_id in visible) if hidden else True):
            out.add(monitor)
    return out


_REPORT_DOOR = re.compile(r"^(?:\./|/)?report/([^/?#]+)")


def _drop_report_doors(d):
    import demoreports
    import reports
    open_to_all = demoreports.NAMES if demoreports.enabled() else ()

    def staged(value):
        found = _REPORT_DOOR.match(value.strip()) if isinstance(value, str) else None
        return bool(found) and found[1] in reports.REPORTS and found[1] not in open_to_all

    for section in ("chronicle", "abyss"):
        if not isinstance(d.get(section), list):
            continue
        kept = []
        for entry in d[section]:
            doors = [k for k in ("url", "embed") if isinstance(entry, dict) and staged(entry.get(k))]
            if doors and not entry.get("chart"):
                continue
            if doors:
                entry = {k: v for k, v in entry.items() if k not in doors}
            kept.append(entry)
        d[section] = kept


def redact_for_groups(data):
    import api_tokens
    groups = viewer_groups()
    out, key = redact(data, groups, bool(api_tokens.current()))
    if groups is None:
        import security
        if not security.is_admin():
            out = dict(out)
            _drop_report_doors(out)
            key += "+no-admin"
    return out, key


def clearance_key(groups, token=False):
    if sees_everything(groups):
        return ""
    links = f"+links:{LINK_DEFAULT_GROUP}" if LINK_DEFAULT_GROUP else ""
    return group_key(groups) + links + ("+token" if token else "")


def redact(data, groups, token=False):
    if sees_everything(groups):
        return data, clearance_key(groups, token)
    d = copy.deepcopy(data)
    if isinstance(d.get("signals"), dict):
        d["signals"].pop("drift_ignore", None)
    schema.upgrade(d)
    d.pop("stones", None)
    _drop_report_doors(d)
    hidden = hidden_node_ids(d, groups)
    names = hidden_words(d, groups)
    slugs = hidden_slugs(d, groups)
    d["nodes"] = [n for n in d.get("nodes", []) if isinstance(n, dict) and cleared(n, groups)]
    import provenance
    provenance.for_viewer(d["nodes"])
    visible_ids = {n.get("id") for n in d["nodes"] if isinstance(n.get("id"), (str, int, float))}
    if isinstance(d.get("collections"), list) and len(d["nodes"]) < len(data.get("nodes") or []):
        for c in d["collections"]:
            if isinstance(c, dict) and "places" in c:
                c["places"] = [p for p in schema.as_list(c["places"])
                               if isinstance(p, (str, int, float)) and p in visible_ids]
    if isinstance(d.get("collections"), list):
        seen_keys = visible_monitors(data, groups)
        for c in d["collections"]:
            if isinstance(c, dict) and "services" in c:
                c["services"] = [k for k in schema.as_list(c["services"])
                                 if isinstance(k, str) and k in seen_keys]
    _declared_only(d)
    if hidden:
        for port in d.get("interfaces") or []:
            if isinstance(port, dict):
                port.pop("peer", None)
                port.pop("note", None)
    hidden_keys = visible_monitors(data, None) - visible_monitors(data, groups)
    if names or slugs or hidden_keys:
        _words_pass(d, names, slugs, hidden_keys)
    for n in d["nodes"]:
        if n.get("links"):
            links = n["links"] if isinstance(n["links"], list) else []
            n["links"] = [l for l in links if isinstance(l, dict) and link_cleared(l, groups)]
        n.pop("accounts", None)
    if hidden:
        visible = set()
        for n in d["nodes"]:
            if isinstance(n.get("id"), (str, int, float)) and not isinstance(n.get("id"), bool):
                visible.add(n["id"])
                if not isinstance(n["id"], str):
                    visible.add(str(n["id"]))
        unseen = _Unseen(visible, hidden)
        for key in list(d):
            section = schema.get(key)
            if not section or section.get("kind", "list") != "list":
                continue
            if not (_node_refs(key) or any(_wordy(key)) or key in _PINNED):
                continue
            if not isinstance(d[key], list):
                d.pop(key)
            else:
                d[key] = [e for e in d[key] if isinstance(e, dict)]
        for key, value in list(d.items()):
            if not isinstance(value, list):
                continue
            refs = _node_refs(key)
            if not refs:
                continue
            defining = key not in _FILTERED_SECTIONS
            d[key] = [e for e in value
                      if not isinstance(e, dict)
                      or _scrub_entry(e, refs, unseen, defining)]
        _scrub_signals_block(d, unseen)
        _scrub_wiring(d, data, unseen)
        for r in d.get("regions") or []:
            pins = r.get("places") if isinstance(r, dict) else None
            if isinstance(pins, dict):
                r["places"] = {k: v for k, v in pins.items() if k not in unseen}
            elif isinstance(r, dict) and "places" in r:
                r.pop("places")
    if token:
        return bare_urls(d), clearance_key(groups, token)
    return d, clearance_key(groups, token)
