"""The parity harness: one request, two paths, one verdict.

    from parity import Accepted, Call, assert_parity

    assert_parity(client, "/api/status", "/api/v2/health")
    assert_parity(client, "/api/positions", "/api/v2/layout/positions",
                  Call("POST", json={"a": {"x": 1, "y": 2}}, headers=WRITE),
                  accepted=[Accepted("$.total", "v2 counts overlays, v1 counts places",
                                     v1=3, v2=4)])

`compare()` issues the same request against both paths on the same test
client (so both see the same session, headers and mode), then compares:

* the status code,
* the response headers named in `headers=` (`Content-Type` by default —
  add `Cache-Control`, `Vary`, `ETag` for the groups where they matter),
* the body — **structurally** when both sides are JSON, so key order is
  never a difference; byte-for-byte otherwise.

Structural rules, because these are exactly the places a port goes wrong:

* `null` and *absent* are different things. A key present with `null` on one
  side and missing on the other is reported as `absent in v2` (or v1), never
  as equal.
* `true` is not `1`, `1` is not `1.0`, `1` is not `"1"`. Types are compared
  before values; Python would happily call the first two equal.
* Lists are compared by position; a longer list shows each extra item as
  `absent` on the short side.

**Accepted differences** are declared in code with a reason, as `Accepted`
objects. An accepted difference is *recorded* in the result and in the report,
never silently dropped; and an acceptance that did not occur is reported as
**stale** and fails the assertion, so a declaration cannot outlive the
divergence it excused (mark it `optional=True` if it is genuinely
conditional, e.g. db mode only).

Paths are JSONPath-ish: `$` is the body root, `.key` a dict key (`["a key"]`
if it is not an identifier), `[3]` a list index. In an `Accepted` pattern,
`.*` matches any one key and `[*]` any one index. Three non-body paths exist:
`status`, `header:<Name>`, and `body` (for non-JSON or JSON-vs-not bodies).
"""

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping


class _Sentinel:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


#: A key (or list slot) that does not exist on that side. Distinct from None.
ABSENT = _Sentinel("ABSENT")
#: In `Accepted`, "any value" — the default for v1/v2 expectations.
ANY = _Sentinel("ANY")

# ── Paths ────────────────────────────────────────────────────────────────────
# A path is a tuple of segments. ("$",) is the JSON root; body segments are
# ("k", key) for a dict key and ("i", index) for a list index. The three
# non-body paths are ("status",), ("header", name) and ("body",).

_IDENT = re.compile(r"^[A-Za-z0-9_\-]+$")
_SEG = re.compile(r'\.([A-Za-z0-9_\-]+|\*)|\[(\d+|\*)\]|\["((?:[^"\\]|\\.)*)"\]')


def render_path(path):
    """`("$", ("k","card"), ("i",0))` → `$.card[0]`."""
    if path[0] != "$":
        return ":".join(str(p) for p in path)
    out = "$"
    for kind, value in path[1:]:
        if kind == "i":
            out += f"[{value}]"
        elif value == "*" or _IDENT.match(str(value)):
            out += f".{value}"
        else:
            out += f"[{json.dumps(str(value))}]"
    return out


def parse_path(text):
    """The inverse of `render_path`, with `*` wildcards allowed in patterns."""
    text = text.strip()
    if text == "status" or text == "body":
        return (text,)
    if text.startswith("header:"):
        return ("header", text[len("header:"):].strip())
    if not text.startswith("$"):
        raise ValueError(f"not a parity path: {text!r}")
    segs = ["$"]
    pos = 1
    while pos < len(text):
        m = _SEG.match(text, pos)
        if not m:
            raise ValueError(f"cannot parse path {text!r} at offset {pos}")
        key, idx, quoted = m.groups()
        if idx is not None:
            segs.append(("i", "*" if idx == "*" else int(idx)))
        elif quoted is not None:
            segs.append(("k", json.loads(f'"{quoted}"')))
        else:
            segs.append(("k", key))
        pos = m.end()
    return tuple(segs)


def _path_matches(pattern, path):
    if len(pattern) != len(path):
        return False
    for p, s in zip(pattern, path):
        if p == s:
            continue
        if isinstance(p, tuple) and isinstance(s, tuple) and p[0] == s[0] and p[1] == "*":
            continue
        return False
    return True


# ── Differences and acceptances ─────────────────────────────────────────────

@dataclass(frozen=True)
class Difference:
    path: tuple
    v1: Any
    v2: Any
    note: str

    @property
    def where(self):
        return render_path(self.path)


@dataclass(frozen=True)
class Accepted:
    """A known, intentional divergence — declared where the test lives.

    `path` is a pattern (see module docstring). `v1`/`v2` narrow the acceptance
    to specific values; leave them `ANY` to accept any difference at that path.
    `reason` is mandatory and appears in the report: a future reader should
    not have to rediscover why v2 was allowed to differ.
    """
    path: str
    reason: str
    v1: Any = ANY
    v2: Any = ANY
    optional: bool = False

    def __post_init__(self):
        if not self.reason or not self.reason.strip():
            raise ValueError("an accepted difference needs a reason")
        object.__setattr__(self, "_pattern", parse_path(self.path))

    def matches(self, diff):
        if not _path_matches(self._pattern, diff.path):
            return False
        if self.v1 is not ANY and not _same(self.v1, diff.v1):
            return False
        if self.v2 is not ANY and not _same(self.v2, diff.v2):
            return False
        return True


def _same(a, b):
    """Equality that respects the sentinels and JSON's type distinctions."""
    if a is ABSENT or b is ABSENT:
        return a is b
    if type(a) is not type(b):
        return False
    return a == b


def _tname(value):
    if value is ABSENT:
        return "absent"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def diff_json(v1, v2):
    """Every structural difference between two decoded JSON values."""
    out = []
    _walk(v1, v2, ("$",), out)
    return out


def _walk(a, b, path, out):
    if a is ABSENT or b is ABSENT:
        if a is not b:
            out.append(Difference(path, a, b, "absent in v2" if b is ABSENT else "absent in v1"))
        return
    if type(a) is not type(b):
        out.append(Difference(path, a, b, f"type: {_tname(a)} vs {_tname(b)}"))
        return
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b), key=str):
            _walk(a.get(key, ABSENT), b.get(key, ABSENT), path + (("k", key),), out)
    elif isinstance(a, list):
        for i in range(max(len(a), len(b))):
            _walk(a[i] if i < len(a) else ABSENT,
                  b[i] if i < len(b) else ABSENT,
                  path + (("i", i),), out)
    elif a != b:
        out.append(Difference(path, a, b, "value"))


# ── The request ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Call:
    """The request to issue against both paths. Mirrors the Flask test
    client's `open()` keywords; anything left None is not passed."""
    method: str = "GET"
    headers: Mapping[str, str] | None = None
    json: Any = None
    data: Any = None
    query_string: Any = None
    content_type: str | None = None

    def send(self, client, path):
        kwargs = {"method": self.method}
        if self.headers:
            kwargs["headers"] = dict(self.headers)
        if self.json is not None:
            kwargs["json"] = self.json
        if self.data is not None:
            kwargs["data"] = self.data
        if self.query_string is not None:
            kwargs["query_string"] = self.query_string
        if self.content_type:
            kwargs["content_type"] = self.content_type
        return client.open(path, **kwargs)

    def describe(self, path):
        text = f"{self.method} {path}"
        if self.query_string:
            qs = self.query_string
            if isinstance(qs, Mapping):
                qs = "&".join(f"{k}={v}" for k, v in qs.items())
            text += f"?{qs}"
        return text


# ── The verdict ──────────────────────────────────────────────────────────────

_SHOW_MAX = 72
_DIFF_MAX_LINES = 80


def _show(value):
    if value is ABSENT:
        return "ABSENT"
    if value is None:
        return "null"
    if isinstance(value, bytes):
        text = repr(value)
    else:
        try:
            text = json.dumps(value, sort_keys=True, default=str)
        except (TypeError, ValueError):
            text = repr(value)
    if len(text) > _SHOW_MAX:
        text = text[:_SHOW_MAX - 1] + "…"
    return text


@dataclass
class ParityResult:
    v1_path: str
    v2_path: str
    call: Call
    v1_response: Any
    v2_response: Any
    v1_body: Any
    v2_body: Any
    both_json: bool
    differences: list = field(default_factory=list)       # unaccepted
    accepted_hits: list = field(default_factory=list)     # (Difference, Accepted)
    stale: list = field(default_factory=list)             # Accepted, never matched

    @property
    def ok(self):
        return not self.differences and not self.stale

    def report(self):
        """The thing you read when it fails. Designed to be read many times."""
        v1 = self.call.describe(self.v1_path)
        v2 = self.call.describe(self.v2_path)
        lines = [
            f"PARITY {'OK' if self.ok else 'FAILURE'}: {v1}  vs  {v2}",
            f"  {len(self.differences)} unaccepted difference(s), "
            f"{len(self.accepted_hits)} accepted, {len(self.stale)} stale acceptance(s)",
            f"  status: v1={self.v1_response.status_code} v2={self.v2_response.status_code}",
        ]
        if self.differences:
            width = max(len(d.where) for d in self.differences)
            lines.append("")
            for d in self.differences:
                lines.append(f"  {d.where:<{width}}  v1={_show(d.v1)}  v2={_show(d.v2)}  ({d.note})")
        if self.accepted_hits:
            lines.append("")
            lines.append("  accepted (declared):")
            for d, acc in self.accepted_hits:
                lines.append(f"    {d.where}  v1={_show(d.v1)}  v2={_show(d.v2)}  — {acc.reason}")
        if self.stale:
            lines.append("")
            lines.append("  stale acceptances — declared but did not occur "
                         "(drop them, or mark optional=True if conditional):")
            for acc in self.stale:
                lines.append(f"    {acc.path}  — {acc.reason}")
        if self.differences and self.both_json:
            lines.append("")
            lines.extend(self._unified())
        return "\n".join(lines)

    def _unified(self):
        a = json.dumps(self.v1_body, sort_keys=True, indent=2, default=str).splitlines()
        b = json.dumps(self.v2_body, sort_keys=True, indent=2, default=str).splitlines()
        out = list(difflib.unified_diff(
            a, b, fromfile=f"v1 {self.call.describe(self.v1_path)}",
            tofile=f"v2 {self.call.describe(self.v2_path)}", lineterm="", n=2))
        if len(out) > _DIFF_MAX_LINES:
            hidden = len(out) - _DIFF_MAX_LINES
            out = out[:_DIFF_MAX_LINES] + [f"(… {hidden} more diff line(s))"]
        return ["  " + line for line in out]


def _decode(resp):
    """(body, is_json). JSON only when the response says it is JSON and it
    parses; anything else is compared as bytes."""
    if resp.mimetype == "application/json":
        try:
            return json.loads(resp.get_data(as_text=True)), True
        except ValueError:
            pass
    return resp.get_data(), False


def compare(client, v1_path, v2_path, call=Call(), accepted=(),
            headers=("Content-Type",)):
    """Issue `call` against both paths and return a `ParityResult`."""
    r1 = call.send(client, v1_path)
    r2 = call.send(client, v2_path)
    body1, json1 = _decode(r1)
    body2, json2 = _decode(r2)

    diffs = []
    if r1.status_code != r2.status_code:
        diffs.append(Difference(("status",), r1.status_code, r2.status_code, "status"))
    for name in headers:
        h1 = r1.headers.get(name, ABSENT)
        h2 = r2.headers.get(name, ABSENT)
        if not _same(h1, h2):
            diffs.append(Difference(("header", name), h1, h2, "header"))
    if json1 and json2:
        diffs.extend(diff_json(body1, body2))
    elif json1 != json2:
        diffs.append(Difference(("body",), body1, body2,
                                "v1 is JSON, v2 is not" if json1 else "v2 is JSON, v1 is not"))
    elif body1 != body2:
        diffs.append(Difference(("body",), body1, body2, "bytes differ"))

    accepted = list(accepted)
    unaccepted, hits, used = [], [], set()
    for d in diffs:
        for i, acc in enumerate(accepted):
            if acc.matches(d):
                hits.append((d, acc))
                used.add(i)
                break
        else:
            unaccepted.append(d)
    stale = [acc for i, acc in enumerate(accepted) if i not in used and not acc.optional]

    return ParityResult(v1_path, v2_path, call, r1, r2, body1, body2,
                        json1 and json2, unaccepted, hits, stale)


def assert_parity(client, v1_path, v2_path, call=Call(), accepted=(),
                  headers=("Content-Type",)):
    """`compare()`, raising `AssertionError` with the full report on any
    unaccepted difference or stale acceptance. Returns the result otherwise,
    so a test can still look at the accepted hits."""
    result = compare(client, v1_path, v2_path, call, accepted, headers)
    if not result.ok:
        raise AssertionError("\n" + result.report())
    return result


__all__ = ["ABSENT", "ANY", "Accepted", "Call", "Difference", "ParityResult",
           "assert_parity", "compare", "diff_json", "parse_path", "render_path"]
