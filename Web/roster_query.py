"""THE ROSTER's filter, sort and page, on the server (2026-11-15, stage 5).

The browser's rules are `static/js/roster-model.js` (`filterRows`,
`sortRows`); this is their port, for a reader that asks for one page of the
places table instead of every row (`GET /api/v2/places/roster?...`). NODES
still reads every row and sorts in the browser; this is for API readers, and
for NODES past a size nobody has asked it to reach yet.

**The filter is the browser's rule exactly**, held to it by the cases both
test files read (`tests/roster_query_cases.json`).

**The sort is the same keys and the same tie-breaks, with one difference that
cannot be taken out:** the browser compares text with `Intl.Collator` in the
reader's own locale, and the server has neither the locale nor ICU. Text here
compares by a natural key (a run of digits as its number, letters case-folded
with accents set aside first, then space and punctuation before digits before
letters, as ICU's root order puts them), which agrees with the browser on the
names in the cases; a name whose order a locale tailors (Swedish "å", say)
can land elsewhere.
"""

import datetime
import functools
import math
import re
import unicodedata

#: Worst first, as `roster-model.js` SEVERITY.
SEVERITY = ("down", "degraded", "maintenance", "slumbering", "healthy")
DAY_MS = 86_400_000
#: Old sort and filter names (collections were sets until 2026-11-14).
OLD_KEYS = {"sets": "collections", "set": "collection"}
#: The most rows one page may ask for.
MAX_LIMIT = 2000
#: The query parameters that put the roster in query mode.
PARAMS = ("text", "state", "zone", "kind", "collection", "set", "unchecked", "stale_days",
          "sort", "dir", "limit", "offset")


class QueryError(ValueError):
    """A parameter the roster cannot use (answered 400)."""


# ── JavaScript's readings ─────────────────────────────────────────────────────

def _blank(v):
    return v is None or (isinstance(v, str) and v == "") or (isinstance(v, float) and math.isnan(v))


def _js_str(v):
    """`String(v)` for the values a row holds."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _falsy(v):
    return v is None or v is False or v == "" or v == 0 or (isinstance(v, float) and math.isnan(v))


def _time(v):
    """`Date.parse` for the stamps the server writes (ISO, UTC), in ms."""
    if not isinstance(v, str) or not v:
        return None
    text = v[:-1] + "+00:00" if v.endswith("Z") else v
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return when.timestamp() * 1000


_IPV4 = re.compile(r"^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})(?:/[0-9]{1,2})?$")


def ipv4_number(text):
    m = _IPV4.match(_js_str(text).strip() if text is not None else "")
    if not m:
        return None
    parts = [int(p) for p in m.groups()]
    if any(p > 255 for p in parts):
        return None
    return ((parts[0] * 256 + parts[1]) * 256 + parts[2]) * 256 + parts[3]


# ── standing (roster-model.js `standing`, `rowStanding`, `rowWaiting`) ────────

def _standing(reviewed, reviewed_at, changed_since_review):
    if not isinstance(reviewed, bool):
        return "unknown"
    if not reviewed:
        return "unchecked"
    at = "" if _falsy(reviewed_at) else _js_str(reviewed_at)
    # the row carries no `changed_at`: String(undefined || '') > reviewed is never true
    if changed_since_review is True or not at:
        return "changed"
    return "checked"


def row_standing(row):
    if not isinstance(row, dict) or not isinstance(row.get("reviewed"), bool):
        return "unknown"
    mine = _standing(row.get("reviewed"), row.get("reviewed_at"), row.get("changed_since_review"))
    unchecked = row.get("unchecked")
    if not isinstance(unchecked, bool):
        return mine
    if not unchecked:
        return "checked"
    return "changed" if mine == "checked" else mine


def row_waiting(row):
    unchecked = row.get("unchecked") if isinstance(row, dict) else None
    return unchecked if isinstance(unchecked, bool) else row_standing(row) != "checked"


def stale_for(row, days, now_ms):
    at = _time(row.get("reviewed_at")) if row.get("reviewed") else None
    if at is None:
        return True
    return now_ms - at >= days * DAY_MS


def row_state(row):
    if row.get("unmanaged") is True:
        return "unmanaged"
    return row.get("state") if row.get("state") in SEVERITY else "unknown"


# ── the filter ────────────────────────────────────────────────────────────────

def haystack(row):
    parts = [row.get("name"), row.get("id"), *(row.get("addresses") or []), row.get("role"),
             row.get("zone_name")]
    return " ".join(_js_str(v) for v in parts if not _blank(v)).lower()


def filter_rows(rows, f, now_ms):
    words = str(f.get("text") or "").strip().lower().split()
    stale = f.get("stale_days") or 0
    out = []
    for row in rows:
        if words:
            hay = haystack(row)
            if not all(w in hay for w in words):
                continue
        if f.get("state") and row_state(row) != f["state"]:
            continue
        if f.get("zone") and row.get("zone") != f["zone"]:
            continue
        if f.get("kind") and row.get("kind") != f["kind"]:
            continue
        if f.get("collection") and f["collection"] not in (row.get("collections") or []):
            continue
        if f.get("unchecked") and not row_waiting(row):
            continue
        if stale > 0 and not stale_for(row, stale, now_ms):
            continue
        out.append(row)
    return out


# ── the sort ──────────────────────────────────────────────────────────────────

def _address_key(row):
    first = next((a for a in (row.get("addresses") or []) if not _blank(a)), None)
    if _blank(first):
        return None
    n = ipv4_number(first)
    return [1, _js_str(first).lower()] if n is None else [0, n]


def _lower_or_none(v):
    return None if _blank(v) else _js_str(v).lower()


def _key_name(r, _ctx):
    name = r.get("name")
    return _js_str(name if not _falsy(name) else (r.get("id") if not _falsy(r.get("id")) else "")).lower()


def _key_zone(r, _ctx):
    if _blank(r.get("zone_name")) and _blank(r.get("zone")):
        return None
    zn = r.get("zone_name")
    return _js_str(zn if not _falsy(zn) else r.get("zone")).lower()


def _key_kind(r, _ctx):
    text = " ".join(_js_str(v) for v in (r.get("kind"), r.get("role")) if not _blank(v)).lower()
    return text or None


def _number(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _key_maintenance(r, _ctx):
    m = r.get("maintenance") or {}
    if not isinstance(m, dict):
        m = {}
    if not _falsy(m.get("now")):
        return -math.inf
    return None if _blank(m.get("next")) else _time(m.get("next"))


def _key_cert(r, _ctx):
    c = r.get("cert")
    return _number(c.get("days")) if isinstance(c, dict) else None


def _key_collections(r, ctx):
    names = {s.get("id"): (s.get("name") or s.get("id")) for s in ctx if isinstance(s, dict)}
    listed = [names.get(i) or i for i in (r.get("collections") or [])]
    return ", ".join(_js_str(n) for n in listed).lower() if listed else None


KEYS = {
    "state": lambda r, _c: SEVERITY.index(r.get("state")) if r.get("state") in SEVERITY else None,
    "name": _key_name,
    "zone": _key_zone,
    "kind": _key_kind,
    "addresses": lambda r, _c: _address_key(r),
    "services": lambda r, _c: _number(r.get("services")),
    "confirmed_by": lambda r, _c: _lower_or_none(r.get("confirmed_by")),
    "reviewed": lambda r, _c: _time(r.get("reviewed_at")),
    "maintenance": _key_maintenance,
    "cert": _key_cert,
    "collections": _key_collections,
}
SORT_KEYS = tuple(KEYS)

# a run of digits, a run of letters, or one other character. A run of letters
# compares as one string: what may follow a letter (space, punctuation, a
# digit) all sorts before any letter, so "a-" < "ab" as one run or as two
_RUN = re.compile(r"[0-9]+|[^\W\d_]+|.", re.S)
#: ASCII space and punctuation in ICU's root order (CLDR), which is not the
#: code points': "_" before "-" before "." is what puts "a_b" before "a-b".
_PUNCT = " \t\n_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"
_PUNCT_RANK = {ch: i for i, ch in enumerate(_PUNCT)}


def _bare(run):
    """Letters with their accents set aside, case-folded: ICU's primary weight."""
    if run.isascii():
        return run.lower()
    return "".join(c for c in unicodedata.normalize("NFKD", run) if not unicodedata.combining(c)).casefold()


def _text_key(s):
    out = []
    for run in _RUN.findall(s):
        if run[0] in "0123456789":
            out.append((1, int(run), ""))
        elif run.isalpha():
            out.append((2, 0, _bare(run)))
        else:
            out.append((0, _PUNCT_RANK.get(run, len(_PUNCT) + ord(run)), ""))
    return out


def _order(v):
    """A sort key that orders values as the browser's `compare` does: numbers
    by value, text by the natural key, then accents, then case (lower first);
    text that differs only in leading zeros ties, as in the collator, and the
    name and id tie-breaks decide. A list element by element. A key, not a
    comparator: `cmp_to_key` made a page of 10,000
    rows slower than the whole roster."""
    if isinstance(v, list):
        return (2, tuple(_order(x) for x in v))
    if _number(v) is not None:
        return (0, v)
    return _text_order(_js_str(v))


_DIGITS = re.compile(r"[0-9]+")


@functools.lru_cache(maxsize=65536)
def _text_order(s):
    # remembered: the next page of the same roster sorts the same names.
    # The accent and case tie-breaks read the digits as numbers, as the
    # collator does: "sw-01" and "sw-1" are equal there, so the id decides.
    plain = _DIGITS.sub(lambda m: str(int(m.group())), s)
    return (1, tuple(_text_key(s)), plain.casefold(), plain.swapcase())


def sort_rows(rows, key="name", direction="asc", collections=()):
    """Blank keys last either way; ties by the name, then the id, ascending."""
    pick = KEYS.get(OLD_KEYS.get(key, key)) or KEYS["name"]
    # the tie-break first, then a stable sort on the column: equal keys keep it
    # (Python's sort is stable with reverse=True too)
    base = sorted(rows, key=lambda r: (_order(_key_name(r, None)), _order(_js_str(r.get("id")))))
    keyed = [(row, pick(row, collections)) for row in base]
    filled = [(row, k) for row, k in keyed if not _blank(k)]
    empty = [row for row, k in keyed if _blank(k)]
    filled.sort(key=lambda x: _order(x[1]), reverse=direction == "desc")
    return [row for row, _ in filled] + empty


# ── the query ─────────────────────────────────────────────────────────────────

def wanted(args):
    """True when a request names any query parameter."""
    return any(name in args for name in PARAMS)


def _int(args, name, default, low, high=None):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise QueryError(f"{name} must be a whole number") from None
    if value < low or (high is not None and value > high):
        raise QueryError(f"{name} must be from {low}" + (f" to {high}" if high is not None else " up"))
    return value


def parse(args):
    """The filter, sort and page a request asks for (`args` a mapping)."""
    sort = OLD_KEYS.get(args.get("sort") or "name", args.get("sort") or "name")
    if sort not in KEYS:
        raise QueryError(f"sort must be one of: {', '.join(SORT_KEYS)}")
    direction = args.get("dir") or "asc"
    if direction not in ("asc", "desc"):
        raise QueryError("dir must be asc or desc")
    unchecked = (args.get("unchecked") or "").lower()
    if unchecked not in ("", "0", "1", "true", "false"):
        raise QueryError("unchecked must be 1 or 0")
    return {
        "filter": {
            "text": args.get("text") or "",
            "state": args.get("state") or "",
            "zone": args.get("zone") or "",
            "kind": args.get("kind") or "",
            "collection": args.get("collection") or args.get("set") or "",
            "unchecked": unchecked in ("1", "true"),
            "stale_days": _int(args, "stale_days", 0, 0),
        },
        "sort": sort,
        "dir": direction,
        "limit": _int(args, "limit", None, 1, MAX_LIMIT),
        "offset": _int(args, "offset", 0, 0),
    }


def apply(roster, query, now_ms=None):
    """`roster` (as `roster.build` makes it) cut to `query` (as `parse` makes
    it): the rows filtered, sorted and paged, with `total` (how many matched),
    `offset` and `limit` beside them."""
    now_ms = now_ms if now_ms is not None else datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000
    rows = filter_rows(roster["rows"], query["filter"], now_ms)
    rows = sort_rows(rows, query["sort"], query["dir"], roster.get("collections") or [])
    start = query["offset"]
    end = None if query["limit"] is None else start + query["limit"]
    return {**roster, "rows": rows[start:end], "total": len(rows), "offset": start,
            "limit": query["limit"]}
