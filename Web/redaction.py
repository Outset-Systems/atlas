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
import re

from flask import request

import hub_auth.auth as auth
import schema
from hub_auth.auth import get_remote_groups, verify_token

import envnames

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


def no_store(resp):
    """A per-viewer response nothing may keep: `no-store`, and `Vary`. Returns it."""
    resp.headers["Cache-Control"] = "no-store"
    return vary_on_viewer(resp)


def private_no_cache(resp):
    """A per-viewer response a browser may keep but must revalidate every time,
    and a shared cache may not keep at all: `private, no-cache`, and `Vary`.
    Returns it."""
    resp.headers["Cache-Control"] = "private, no-cache"
    return vary_on_viewer(resp)


def sees_everything(groups):
    return groups is None or ADMIN_GROUP in groups


def cleared(entry, groups):
    """True if `entry` (a node or link dict) is visible to `groups`."""
    if sees_everything(groups):
        return True
    if not isinstance(entry, dict):
        return False      # a stray entry is no place (round 10): hidden, never a raise
    required = entry.get("require_group")
    if not required:
        return True
    # a hand edit's list or object: nobody's group, so hidden (closed), never a raise
    return isinstance(required, str) and required in groups


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


# ── What a URL carries besides an address ────────────────────────────────────
#
# A charted URL can hold a credential in two places: `user:pass@` before the
# host, and the query string (`?token=…`, a chart's `auth_token`). A person
# signed in needs the link to work, so they get it whole. An API token reads the
# map on behalf of a program that may send every answer to a model's vendor, and
# an agent that wants to know what runs where needs the scheme, the host, the
# port and the path, not the secret. So a token gets the URL without both.
#
# Any scheme: rtsp, ssh and postgres URLs carry passwords as readily as http
# ones. What this cannot see: a secret in the PATH (`/hooks/<secret>`), or a URL
# inside a sentence in a note. Those leave as written.
_URL = re.compile(r"^\s*([A-Za-z][A-Za-z0-9+.-]*)://(\S*)\s*$")


def bare_url(value):
    """`value` without userinfo, query or fragment when it is a URL; else as given."""
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
        # `user:pa/ss@host`: a password with a bare "/" in it. What follows the
        # colon is not a port, so the host is whatever comes after the "@".
        authority, slash, path = rest.split("@", 1)[1].partition("/")
    return f"{scheme}://{authority.rsplit('@', 1)[-1]}{slash}{path}"


def bare_urls(value):
    """Every string in a dataset that is a URL, made bare. In place; returns it."""
    if isinstance(value, dict):
        for key, inner in value.items():
            value[key] = bare_urls(inner)
    elif isinstance(value, list):
        for i, inner in enumerate(value):
            value[i] = bare_urls(inner)
    elif isinstance(value, str):
        return bare_url(value)
    return value


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

#: Sections whose references to places are attributes of the entry rather than
#: its reason to exist (see `_scrub_entry`'s `defining`): a hidden id is taken
#: out and the entry stays. A collection (2026-11-13, then called a set) is a
#: list of places by name of its own; one hidden member must not hide the
#: other members from the viewer.
_FILTERED_SECTIONS = {"nodes", "collections"}

#: Free text that can name a place in words, by section. No reference walker
#: can read prose, so an entry whose words name a hidden place goes whole, the
#: way rites always have (2026-11-13: certificates, collections, a rite's name and a
#: rack slot's words joined them; the 11-12 audit found each of them open).
_FREE_TEXT = {
    "rites": ("name", "host", "note"),
    "certs": ("name", "host", "note"),
    # the id too: it is made from the name, and a rename keeps it (2026-11-14)
    "collections": ("id", "name", "note"),
    "rack": ("name", "desc"),
    "rack_rear": ("name", "desc"),
}


#: The free-text fields that are ids the rail made from a name (`slugFor`):
#: matched against hidden slugs as ids are made, dashes only.
_ID_FIELDS = frozenset({"id"})

#: Sections that name places as the KEYS of a mapping, which the reference
#: walker cannot read (regions' `places`): the shape guard covers them too.
_PINNED = frozenset({"regions"})


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


class _Unseen:
    """"Is this reference one this viewer may not follow?" while anything is
    hidden: yes for every value that is not a visible place's id, so a hidden
    id written another way ("SECRET-PLACE", " secret-place") is withheld like
    the id itself (round 14). Empty values are no reference. Truthy exactly
    when something is hidden."""

    def __init__(self, visible, hidden):
        self._visible, self._hidden = visible, hidden
        self.exact = hidden      # the hidden ids as they are, for a malformed value

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


def _holds_hidden(value, hidden):
    """True when `value`, or anything inside a list or object it holds, is a
    hidden id. Never raises on a value a set cannot hold."""
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
    """Clean one field in place. False ⇒ the holder must go (see `_scrub_entry`)."""
    if name not in holder:
        return True
    value = holder[name]
    if ftype != "strings" and isinstance(value, (list, dict)):
        # A list or an object where one id belongs (2026-11-13): validation
        # refuses it now, but a map saved before that can hold one, and
        # `value in hidden` raised on it (a 500 for every restricted reader).
        # It names no place anyone can look up, so it is never served to a
        # restricted reader, and an entry it ties to a hidden place goes.
        # the value itself is never served (popped below), so whether the
        # entry goes is judged by the exact hidden ids: a field name inside it
        # ("id") is no reference (round 14)
        if defining and _holds_hidden(value, getattr(hidden, "exact", hidden)):
            return False
        holder.pop(name, None)
        return True
    if ftype == "strings" and isinstance(value, str):
        # A hand-edited `"depends_on": "vault"`: one id where a list belongs.
        # Validation only warns about it, so it is served, and it must be
        # judged like the list it stands for (the 11-12 audit's first item).
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
        block["kuma"] = {m: n for m, n in kuma.items() if not _holds_hidden(n, hidden)}


def hidden_node_ids(data, groups):
    """Ids of the places this viewer may not see. Empty when they see everything."""
    if sees_everything(groups):
        return set()
    out = set()
    for n in data.get("nodes", []):
        # any scalar id (a hand edit's 7 is still hidden; round 10 had kept
        # only text and let it through), never a list (unhashable)
        if not (isinstance(n, dict) and isinstance(n.get("id"), (str, int, float))
                and not isinstance(n.get("id"), bool)) or cleared(n, groups):
            continue
        out.add(n["id"])
        if not isinstance(n["id"], str):
            # and as text: a region pin is a JSON key, always text, and a
            # member may be written "7" for the place 7 (round 12)
            out.add(str(n["id"]))
    return out


def hidden_words(data, groups):
    """A pattern for the hidden places' names, ids and addresses, for callers
    with free text to check. None when nothing is hidden, and for a viewer who
    sees everything."""
    if sees_everything(groups):
        return None
    words = set()
    for n in data.get("nodes", []):
        if isinstance(n, dict) and not cleared(n, groups):
            ip = str(n.get("ip") or "").split("/")[0].strip()
            # every "no value" mark, not only the dash: a hidden place whose ip
            # is "-" made "-" a hidden word and dropped every rite with a hyphen
            words |= {str(w) for w in (n.get("id"), n.get("name"), ip)
                      if w and str(w).strip() not in schema.NONE_MARKS}
    if not words:
        return None
    # A WORD ENDS AT ANYTHING BUT A LETTER OR A DIGIT (2026-11-13). The edges
    # were `\w` and `-` before, so a hidden name joined to other text by a dash
    # or an underscore (`vault-https`, `backup_vault`, `10.0.0.9-ping`) was not
    # found. Now a dash, an underscore and a dot are separators on both sides.
    # A digit still joins, so `10.0.0.9` is not found inside `10.0.0.90`. The
    # cost is the safe one: a visible word with a hidden name as one of its
    # parts is withheld too.
    edge = r"[^\W_]"
    return re.compile(rf"(?<!{edge})(?:" + "|".join(map(re.escape, sorted(words)))
                      + rf")(?!{edge})", re.IGNORECASE)


#: List punctuation: the marks that join one name to the next ("Core, Switch",
#: "Rack (A)", "kept for: X"). In a list-aware slug a run of separators that
#: holds one becomes `~`, every other run a dash.
_LIST_MARKS = re.compile(r"[\n,;:()\[\]]")


def slug(text, lists=False):
    """`text` as a slug, the way the rail makes a collection's id
    (`roster-model.slugFor`): accents dropped, lower case, every run of
    anything but a letter or a digit one dash, no dash at either end.

    `lists=True` is for free text: a run of separators that holds list
    punctuation becomes `~` instead, so "Core, Switch" is `core~switch`,
    which a hidden "Core Switch" (`core-switch`) never matches, while
    "Rack(A)" and "Rack (A)" are both `rack~a` (2026-11-14 review, round 7)."""
    import unicodedata
    # lower case first, then NFKD, the rail's order (`slugFor`): "NAS™" is
    # `nas` there, and `nastm` the other way round (round 9)
    plain = unicodedata.normalize("NFKD", str(text or "").lower())
    # every mark (category M), as the rail's `\p{M}`: combining class alone
    # keeps U+20E3 and U+FE0F (round 12)
    plain = "".join(ch for ch in plain if unicodedata.category(ch)[0] != "M")
    if not lists:
        return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    return re.sub(r"[^a-z0-9]+", lambda m: "~" if _LIST_MARKS.search(m.group()) else "-",
                  plain).strip("-~")


def _slug_worthy(word):
    """Whether a hidden id, name or address gets a slug at all. Not when it
    has a letter of another script than Latin that a slug drops (東京 Alpha
    and 東京Alpha would both become plain `alpha` and withhold the visible
    Alpha; 客厅NAS would become `nas`; Сервер 1 would become `1`), nor when the
    slug is under three characters (C++ -> `c`) or has no letter (an address:
    a date can spell 10-12-13-45). The exact pattern (`hidden_words`) still
    covers every one of those. A Latin letter the slug drops (ø, ß) keeps the
    slug, because the rail's ids drop it the same way (Søren -> `s-ren`,
    Straße -> `stra-e`). Rounds 7 and 8 of the 2026-11-14 review."""
    import unicodedata
    symbol = False
    # every apostrophe is the ASCII one here: ʼ (a modifier letter) must not
    # read as a letter of another script (round 12)
    word = _APOSTROPHES.sub("'", str(word))
    for ch in word:
        if slug(ch) or ch.isspace():
            continue
        # it decomposes to plain ASCII the rail drops the same way (™ -> TM)
        if all(c.isascii() for c in unicodedata.normalize("NFKD", ch)):
            continue
        kind = unicodedata.category(ch)
        # a dropped letter or digit of another script shrinks the name to its
        # Latin part (東京Alpha -> `alpha`, ٣ Alpha -> `alpha`); Latin letters
        # (ø, ß) and punctuation do not
        if (kind[0] == "L" and not unicodedata.name(ch, "").startswith("LATIN")) or kind[0] == "N":
            return False
        if kind == "So":
            symbol = True
    s = slug(word)
    if symbol and "-" not in s:
        # a symbol leaves a single word ("🔒 Alpha" -> `alpha`, which would
        # withhold "Alpha team"); with two or more words left the slug still
        # names the place ("📺 Living Room TV" -> `living-room-tv`), and
        # leaking it is the worse mistake (round 10)
        return False
    return sum(ch.isalnum() for ch in s) >= 3 and any(ch.isalpha() for ch in s)


_APOSTROPHES = re.compile(r"['\u2019\u02bc]")


class HiddenSlugs:
    """The hidden places' ids, names and addresses as slugs, in two forms:
    for an id (made by the rail, dashes only, cut at 48 characters) and for
    free text (list-aware). `in_id` and `in_text` take the text as written."""

    def __init__(self, words):
        bound = r"(?<![a-z0-9])(?:{})(?![a-z0-9])"
        # each name also without its apostrophes: "Dad's PC" is `dad-s-pc`
        # and `dads-pc` (round 11)
        words = set(words) | {s for s in (_APOSTROPHES.sub("", w) for w in words)
                              if _slug_worthy(s)}   # "🔒 Moms" is no slug, nor is "🔒 Mom's" stripped
        ids = {slug(w) for w in words}
        ids |= {s[:48].strip("-") for s in ids if len(s) > 48}
        self._ids = re.compile(bound.format("|".join(map(re.escape, sorted(ids)))))
        # free text matches both: the list-aware slug ("Rack(A)" is a hidden
        # "Rack (A)") and the dash-only one ("mirror of nas-backup" is a hidden
        # "NAS (Backup)"); a list of two names ("Core, Switch") is `core~switch`
        # and contains neither form of a hidden "Core Switch" (round 8)
        texts = {slug(w, lists=True) for w in words} | {slug(w) for w in words}
        self._texts = re.compile(bound.format("|".join(map(re.escape, sorted(texts)))))

    def in_id(self, text):
        bare = _APOSTROPHES.sub("", str(text or ""))
        return bool(self._ids.search(slug(text)) or self._ids.search(slug(bare)))

    def in_text(self, text):
        # the text without its apostrophes too: "Dad's PC" names a hidden "Dads PC"
        bare = _APOSTROPHES.sub("", str(text or ""))
        return bool(self._texts.search(slug(text, lists=True))
                    or self._texts.search(slug(bare, lists=True)))


def hidden_slugs(data, groups):
    """`hidden_words` for text written as a slug: an id made from a name
    ("Vault Box" -> `vault-box-backups`, "Café" -> `cafe-server`) does not
    contain the name as written. A `HiddenSlugs`, or None when nothing is
    hidden or no hidden word gets a slug (rounds 4 to 7)."""
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
    """Kuma monitor names charted on a service this viewer is cleared for.

    The signals feed is keyed by monitor name, not node id, so this is the seam
    that turns a clearance into "which health entries may they see". A monitor
    the map does not chart at all is in nobody's set — an uncharted monitor is
    survey information about the estate, not a service the viewer was given.

    A link that names no monitor is in the set under its own key
    (`signals.service_key`), which is what a built-in check reports it by."""
    import signals
    out = set()
    for node in data.get("nodes", []):
        if not cleared(node, groups):
            continue
        links = node.get("links") if isinstance(node.get("links"), list) else []
        for link in links:
            if isinstance(link, dict) and cleared(link, groups):
                out.add(signals.service_key(node.get("id"), link))
    hidden = hidden_node_ids(data, groups)
    # while anything is hidden, a monitor counts only when its place is a
    # visible place: "SECRET-PLACE" for a hidden secret-place is withheld,
    # as /lab-data withholds it (round 15)
    visible = {n.get("id") for n in data.get("nodes", [])
               if isinstance(n, dict) and isinstance(n.get("id"), str) and cleared(n, groups)}
    for monitor, node_id in signals.monitor_map(data).items():
        if (node_id in visible) if hidden else True:
            out.add(monitor)
    return out


def redact_for_groups(data):
    """Return (dataset, cache_key) with entries the viewer isn't cleared for removed."""
    import api_tokens
    return redact(data, viewer_groups(), bool(api_tokens.current()))


def clearance_key(groups, token=False):
    """The cache key `redact` returns for this viewer, without redacting: a
    memo keyed per clearance (the CSP's frame-src list) can look itself up
    before paying for a deep copy of the whole map (2026-11-13: at 10,000
    places that copy ran on every response, static files included)."""
    if sees_everything(groups):
        return ""
    return group_key(groups) + ("+token" if token else "")


def redact(data, groups, token=False):
    """`redact_for_groups` for a viewer handed in rather than read from the
    request: `groups` as `viewer_groups` gives them, `token` true when the
    reader is an API token. Reads nothing but its arguments."""
    if sees_everything(groups):
        return data, clearance_key(groups, token)
    d = copy.deepcopy(data)
    # the monitors the operator chose to ignore are an admin's list (the feed
    # keeps drift for admins only): no viewer below admin gets it (round 15)
    if isinstance(d.get("signals"), dict):
        d["signals"].pop("drift_ignore", None)
    # A section under an old name would pass the walkers below untouched (they
    # know today's names only), hidden members and all: read it as today's
    # first. Every loader already does; this is the belt (2026-11-14 review).
    schema.upgrade(d)
    # TRIPWIRES ARE ADMIN-ONLY, WHOLESALE (v0.1). Where a honeypot sits and
    # where a canary token is planted is the deception layout itself: there
    # is no per-entry version of it worth giving, and a scrubbed stone still
    # says that bait exists here and how much. Same blunt rule as the
    # account roster below, and on the same not-`sees_everything` path.
    d.pop("stones", None)
    hidden = hidden_node_ids(d, groups)
    names = hidden_words(d, groups)
    slugs = hidden_slugs(d, groups)
    # a stray non-object entry (validation only warns) is no place: dropped,
    # never a raise that 500s every restricted reader (round 9)
    d["nodes"] = [n for n in d.get("nodes", []) if isinstance(n, dict) and cleared(n, groups)]
    # PROVENANCE: when and whether, not who. The change log is admin-only because
    # it names people, and a stamp's `*_by` is the same names on another page.
    import provenance
    provenance.for_viewer(d["nodes"])
    # A COLLECTION LISTS ONLY PLACES THIS VIEWER MAY SEE (round 13): a member
    # written in another case or with a space ("SECRET-PLACE") is no place's
    # id, and the reference walker below matches ids exactly. While anything
    # is hidden, keep only the members that are visible places' ids.
    visible_ids = {n.get("id") for n in d["nodes"] if isinstance(n.get("id"), (str, int, float))}
    if isinstance(d.get("collections"), list) and len(d["nodes"]) < len(data.get("nodes") or []):
        for c in d["collections"]:
            if isinstance(c, dict) and "places" in c:
                c["places"] = [p for p in schema.as_list(c["places"])
                               if isinstance(p, (str, int, float)) and p in visible_ids]
    # A COLLECTION'S SERVICES (stage 3b) are keys, and `<place>/<label>` carries
    # the place's id: keep only the keys of links on this viewer's own map
    # (an allowlist), whatever else is hidden. The feed's own allowlist, on the
    # whole map: here `d` still holds a link behind its own group and the
    # monitors `signals.kuma` charts on hidden places (stage 3b review)
    if isinstance(d.get("collections"), list):
        seen_keys = visible_monitors(data, groups)
        for c in d["collections"]:
            if isinstance(c, dict) and "services" in c:
                c["services"] = [k for k in schema.as_list(c["services"])
                                 if isinstance(k, str) and k in seen_keys]
    # a rite's `host` is free text, so no node reference covers it: a rite that
    # names a hidden place in words goes as surely as one that points at it.
    # The same for a certificate, a set and a rack slot (`_FREE_TEXT`).
    if names:
        def says_hidden(entry, fields):
            # field by field: the gap between two fields is neither a space in
            # a hidden name nor a dash in its slug ("lab" + "Core switches"
            # is not "Lab core", 2026-11-14 review)
            for f in fields:
                text = str(entry.get(f) or "")
                if names.search(text):
                    return True
                # an id is matched as the rail makes ids, free text list-aware
                if slugs and (slugs.in_id(text) if f in _ID_FIELDS else slugs.in_text(text)):
                    return True
            return False

        for key, fields in _FREE_TEXT.items():
            if isinstance(d.get(key), list):
                d[key] = [e for e in d[key] if not (isinstance(e, dict) and says_hidden(e, fields))]
    for n in d["nodes"]:
        if n.get("links"):
            links = n["links"] if isinstance(n["links"], list) else []
            n["links"] = [l for l in links if isinstance(l, dict) and cleared(l, groups)]
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
        visible = set()
        for n in d["nodes"]:
            if isinstance(n.get("id"), (str, int, float)) and not isinstance(n.get("id"), bool):
                visible.add(n["id"])
                if not isinstance(n["id"], str):
                    visible.add(str(n["id"]))   # a pin key is text: "7" for the place 7
        unseen = _Unseen(visible, hidden)
        # A LIST SECTION THAT IS NOT A LIST, OR HOLDS SOMETHING NOT AN ENTRY
        # (2026-11-14 review, round 4). Validation only warns, so a hand edit
        # is served; the walkers below read lists of objects and would pass
        # anything else through whole. While something is hidden, a section
        # that names places (by reference or in words) and is not a list of
        # objects goes, and so does an entry that is not an object.
        for key in list(d):
            section = schema.get(key)
            if not section or section.get("kind", "list") != "list":
                continue
            if not (_node_refs(key) or key in _FREE_TEXT or key in _PINNED):
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
        # A PORT'S WORDS (2026-11-11). `peer` and `note` say what is on the other
        # end in prose, and a connection import now writes them: "VAULT and 3
        # guests" on a visible switch names a hidden place, its port and what it
        # hosts. No reference walker can see prose, and matching it against the
        # hidden names misses a place the controller calls something else. So
        # the rule is the blunt one, as for `accounts`: while anything is hidden
        # from this viewer, they get the ports and not the words on them.
        for port in d.get("interfaces") or []:
            if isinstance(port, dict):
                port.pop("peer", None)
                port.pop("note", None)
        # REGIONS (v1.49.0): `places` is a json object keyed BY place id, so
        # the ref walker above cannot see it — a pin would name a hidden place
        # (and say where it sits) to a viewer not cleared for it.
        for r in d.get("regions") or []:
            pins = r.get("places") if isinstance(r, dict) else None
            if isinstance(pins, dict):
                r["places"] = {k: v for k, v in pins.items() if k not in unseen}
            elif isinstance(r, dict) and "places" in r:
                r.pop("places")             # a hand edit's list: no pins rather than a guess
    if token:
        # A TOKEN READS A LITTLE LESS THAN A PERSON WITH NO GROUPS (2026-11-11), so
        # it must not share that person's cache key: an ETag or a cache built on
        # the group set alone would hand one of them the other's body.
        return bare_urls(d), clearance_key(groups, token)
    return d, clearance_key(groups, token)
