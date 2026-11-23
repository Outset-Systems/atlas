import ipaddress
import re
from urllib.parse import urlsplit

import certs

EXPOSURES = ("public", "internal", "vpn")
UNSET, OUTSIDE = "unset", "outside"

_NAME = re.compile(r"^(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{1,63}$")


def fold(value):
    return str(value).strip().lower().rstrip(".") if isinstance(value, str) else ""


def _is_address(text):
    try:
        ipaddress.ip_address(text.strip("[]"))
        return True
    except ValueError:
        return False


def shaped(value):
    name = fold(value)
    if not name or len(name) > 253 or _is_address(name) or not _NAME.match(name):
        return None
    if name.split(".")[-1].isdigit():
        return None
    return name


def host_of(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        host = urlsplit(text if "://" in text else "//" + text).hostname
    except ValueError:
        return None
    return shaped(host) if host else None


def is_rule(name):
    return isinstance(name, str) and name.startswith("*.")


def rule_covers(rule, name):
    if not is_rule(rule):
        return rule == name
    domain = rule[2:]
    return name == domain or name.endswith("." + domain) or name == rule


def cert_covers(cert_name, name):
    if not is_rule(cert_name):
        return cert_name == name
    if is_rule(name):
        return cert_name == name
    head, _, rest = name.partition(".")
    return bool(head) and rest == cert_name[2:]


def entries_of(data):
    out = []
    for entry in data.get("names") or [] if isinstance(data, dict) else []:
        if not isinstance(entry, dict):
            continue
        name = shaped(entry.get("name"))
        if not name:
            continue
        exposure = entry.get("exposure") or ""
        out.append((name, exposure if exposure in EXPOSURES else "", entry))
    return out


def intent(name, entries):
    best = None
    for rule, exposure, _ in entries:
        if not rule_covers(rule, name):
            continue
        rank = (0 if not is_rule(rule) else 1, -len(rule))
        if best is None or rank < best[0]:
            best = (rank, rule, exposure)
    if best is None:
        return OUTSIDE, None
    return (best[2] or UNSET), best[1]


def _place_name(node):
    return node.get("name") or node.get("id")


def derive(data):
    rows = {}

    def row(name):
        return rows.setdefault(name, {"name": name, "wildcard": is_rule(name),
                                      "found": set(), "uses": [], "certs": []})

    def use(name, how, node, service):
        r = row(name)
        r["found"].add(how)
        for mark in r["uses"]:
            if mark["place"] == node.get("id") and mark["service"] == service:
                if how not in mark["via"]:
                    mark["via"] = sorted([*mark["via"], how])
                return
        r["uses"].append({"place": node.get("id"), "place_name": _place_name(node),
                          "service": service, "via": [how]})

    if not isinstance(data, dict):
        return rows
    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        name = host_of(node.get("check_host"))
        if name:
            use(name, "check", node, None)
        for link in node.get("links") or []:
            if not isinstance(link, dict):
                continue
            label = link.get("label") if isinstance(link.get("label"), str) else None
            for how, key in (("url", "url"), ("check", "check_host")):
                name = host_of(link.get(key))
                if name:
                    use(name, how, node, label)
    named = []
    for cert in data.get("certs") or []:
        if not isinstance(cert, dict):
            continue
        name = shaped(cert.get("name"))
        if name:
            row(name)["found"].add("cert")
            named.append((name, cert))
    for name, r in rows.items():
        r["certs"] = [{"name": cn, "expires": c.get("expires")}
                      for cn, c in named if cert_covers(cn, name)]
    for r in rows.values():
        r["found"] = sorted(r["found"])
    return rows


def in_use(row):
    return "url" in row["found"] or "check" in row["found"]


def _nearest(row, today):
    best = None
    for c in row["certs"]:
        days = certs.days_left(c, today)
        if days is not None and (best is None or days < best["days"]):
            best = {"name": c["name"], "expires": c.get("expires"), "days": days}
    return best


def listing(data, today=None):
    entries = entries_of(data)
    out = []
    for name, r in derive(data).items():
        state, rule = intent(name, entries)
        out.append({
            "name": name, "intent": state, "rule": rule, "wildcard": r["wildcard"],
            "in_use": in_use(r), "found": r["found"], "uses": r["uses"],
            "cert": _nearest(r, today),
        })
    counts = {k: 0 for k in (*EXPOSURES, UNSET, OUTSIDE)}
    for r in out:
        counts[r["intent"]] += 1
    counts["total"] = len(out)
    def order(r):
        bare = r["name"][2:] if r["wildcard"] else r["name"]
        return (r["intent"] == OUTSIDE, ".".join(bare.split(".")[-2:]), bare.count("."), r["name"])

    out.sort(key=order)
    return out, counts


def visible_entries(entries, data):
    seen = list(derive(data))
    kept = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name = shaped(entry.get("name"))
        if name and any(rule_covers(name, n) for n in seen):
            kept.append(entry)
    return kept


def problems(data):
    out = []
    seen = {}
    for i, entry in enumerate(data.get("names") or [] if isinstance(data, dict) else []):
        if not isinstance(entry, dict):
            continue
        raw = entry.get("name")
        import validation
        label = validation.label_of("names", entry, i)
        name = shaped(raw)
        if raw is not None and not name:
            out.append(f"{label}: not a host name or a rule like *.example.com")
            continue
        if not name:
            continue
        if name in seen:
            out.append(f"{label}: the same name as {seen[name]!r}")
        seen.setdefault(name, raw)
        if not is_rule(name) and not entry.get("exposure"):
            out.append(f"{label}: an exact name needs public, internal or vpn")
    return out
