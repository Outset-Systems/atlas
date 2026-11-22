from . import common, discord, gotify, ntfy, webhook

NEEDS = ("kind", "label", "fields", "secret_use", "build")

REGISTRY = {}


def can_send(entry):
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
    return ("secret" in names) == (use["in"] != "none")


def register(entry):
    if not can_send(entry):
        raise ValueError(f"{getattr(entry, 'kind', entry)!r} is not a whole sender")
    REGISTRY[entry.kind] = entry
    return entry


for _entry in (ntfy, gotify, webhook, discord):
    register(_entry)


def kinds():
    return tuple(k for k, e in REGISTRY.items() if can_send(e))


def find(kind):
    entry = REGISTRY.get(kind) if isinstance(kind, str) else None
    return entry if can_send(entry) else None


def check_path(kind, path):
    rule = getattr(find(kind), "check_path", None)
    return list(rule(path)) if callable(rule) else []


def check_address(kind, scheme, host, port, path):
    rule = getattr(find(kind), "check_address", None)
    return list(rule(scheme, host, port, path)) if callable(rule) else []


def send_path(kind, path):
    rule = getattr(find(kind), "send_path", None)
    return rule(path) if callable(rule) else path


def secret_in_path(kind):
    entry = find(kind)
    return entry is not None and entry.secret_use.get("in") == "path"


def secret_path(kind, path, secret):
    if not secret_in_path(kind):
        return path
    if not secret:
        return None
    return find(kind).secret_path(path, secret)


def rewrites_url(kind):
    return bool(getattr(find(kind), "rewrites_url", False))


def declarations():
    out = []
    for k in kinds():
        e = REGISTRY[k]
        out.append({"kind": e.kind, "label": e.label,
                    "fields": [dict(f) for f in e.fields]})
    return out
