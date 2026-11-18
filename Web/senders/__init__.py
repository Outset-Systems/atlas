"""THE SENDERS: each kind of alert destination, declared once (2026-11-16).

A kind is one module here: `ntfy.py`, `gotify.py`, `webhook.py`, and
`discord.py` (2026-11-16, the first kind added after the split). Each says

  kind         its name, as a destination stores it
  label        the word the page shows for it (the theme's `alerts_kind_<kind>`
               comes first, when there is one)
  fields       what the destination form asks for after the name and the kind,
               in order (see `common.py`)
  secret_use   how the secret a destination names is sent
  build(message, secret)   `(headers, body_bytes)`, through the guard's own
               cleaning and cutting

and, when it has one, its rule for the address's path:

  check_path(path)   the problems with a path, in plain sentences
  check_address(scheme, host, port, path)   the same, for a kind that only
                     speaks to its own service's hosts; on top of the guard's
                     allowed hosts, never instead of them
  send_path(path)    the path that is posted to (the address's own, else)
  rewrites_url       True when the address is saved the way it is sent
  secret_path(path, secret)   for `secret_use {"in": "path"}` only, and then
                     required: the path with the secret in it, at send time,
                     or None when the secret cannot go there

The guard is not here. Off by default, the allowed hosts, resolving once and
pinning, the refused addresses, POST only, no redirects, the time limits, the
4 KB body, the 1 KB read, the outcomes, secrets bound to an origin and the
delivery log all stay in `alert_send.py`, one path every kind passes through.
How a message is cleaned and cut to fit is `shape.py`, beside the kinds, which
the guard imports. A kind only says what its request looks like.

The registry is ordered: the page offers the kinds in this order, the first
one picked. Only a kind whose entry is whole can send, so only it is offered
or accepted (`kinds`, `find`). Nothing here imports `alert_send`: a kind's
`build` takes the guard's cleaning and cutting from `shape.py`, which
`alert_send` imports in turn (2026-11-17).
"""

from . import common, discord, gotify, ntfy, webhook

#: The entries every kind has. The path rule is optional.
NEEDS = ("kind", "label", "fields", "secret_use", "build")

#: kind -> its entry, in the order the page offers them.
REGISTRY = {}


def can_send(entry):
    """True when `entry` declares everything a kind needs, so it may be offered
    and sent to: a name, a label, a form with an address, a way to use its
    secret, and a build."""
    if entry is None or not all(hasattr(entry, n) for n in NEEDS):
        return False
    if not (isinstance(entry.kind, str) and entry.kind and isinstance(entry.label, str)
            and entry.label and callable(entry.build)):
        return False
    use = entry.secret_use
    if not isinstance(use, dict) or use.get("in") not in common.SECRET_IN:
        return False
    if use["in"] == "header" and not (isinstance(use.get("header"), str) and use["header"]):
        return False
    # a secret that goes in the path needs the kind's own rule for putting it there
    if use["in"] == "path" and not callable(getattr(entry, "secret_path", None)):
        return False
    names = []
    for f in entry.fields if isinstance(entry.fields, (list, tuple)) else ():
        if not (isinstance(f, dict) and f.get("name") in common.STORED
                and f.get("type") in common.TYPES):
            return False
        names.append(f["name"])
    if "url" not in names or len(names) != len(set(names)):
        return False
    # a kind that sends no secret does not ask for one, and one that does, does
    return ("secret" in names) == (use["in"] != "none")


def register(entry):
    """Add a kind at the end of the list, or put it back in its place. Refused
    (ValueError) when it is not whole."""
    if not can_send(entry):
        raise ValueError(f"{getattr(entry, 'kind', entry)!r} is not a whole sender")
    REGISTRY[entry.kind] = entry
    return entry


for _entry in (ntfy, gotify, webhook, discord):
    register(_entry)


def kinds():
    """The kinds that can send, in order."""
    return tuple(k for k, e in REGISTRY.items() if can_send(e))


def find(kind):
    """The entry for `kind`, or None when there is none that can send."""
    entry = REGISTRY.get(kind) if isinstance(kind, str) else None
    return entry if can_send(entry) else None


def check_path(kind, path):
    """The kind's problems with an address's path; [] when it has no rule."""
    rule = getattr(find(kind), "check_path", None)
    return list(rule(path)) if callable(rule) else []


def check_address(kind, scheme, host, port, path):
    """The kind's problems with a whole address; [] when it has no rule."""
    rule = getattr(find(kind), "check_address", None)
    return list(rule(scheme, host, port, path)) if callable(rule) else []


def send_path(kind, path):
    """The path a kind posts to; the address's own when it has no rule."""
    rule = getattr(find(kind), "send_path", None)
    return rule(path) if callable(rule) else path


def secret_in_path(kind):
    """True when `kind` sends its secret in the path, so it cannot send without one."""
    entry = find(kind)
    return entry is not None and entry.secret_use.get("in") == "path"


def secret_path(kind, path, secret):
    """The path with the secret in it, for a kind that sends it there; the
    path as it is for any other kind. None when the secret cannot go there."""
    if not secret_in_path(kind):
        return path
    if not secret:
        return None
    return find(kind).secret_path(path, secret)


def rewrites_url(kind):
    return bool(getattr(find(kind), "rewrites_url", False))


def declarations():
    """What the page draws the destination form from: one entry per kind
    that can send, `{kind, label, fields}`, in order. No secret, no host."""
    out = []
    for k in kinds():
        e = REGISTRY[k]
        out.append({"kind": e.kind, "label": e.label,
                    "fields": [dict(f) for f in e.fields]})
    return out
