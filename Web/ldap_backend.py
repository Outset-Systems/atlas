import logging
import os
import re
import envnames

log = logging.getLogger("atlas.auth.ldap")


def _cfg(name, default="", overrides=None):
    if overrides is not None:
        return (str(overrides.get(name, "") or "").strip() or default)
    import auth_config
    return (auth_config.get(name) or os.environ.get(name) or default).strip()


def _order(value):
    return [b.strip().lower() for b in value.split(",") if b.strip()]


def is_ldaps(url):
    return url.lower().startswith("ldaps://")


def enabled():
    backends = _order(_cfg("ATLAS_AUTH_BACKENDS", "local"))
    return ("ldap" in backends and bool(_cfg("ATLAS_LDAP_URL"))
            and bool(_cfg("ATLAS_LDAP_BASE_DN")))


def backends():
    order = _order(_cfg("ATLAS_AUTH_BACKENDS", "local"))
    return [b for b in order if b == "local" or (b == "ldap" and enabled())]


def _esc(value: str) -> str:
    return (value.replace("\\", "\\5c").replace("*", "\\2a")
            .replace("(", "\\28").replace(")", "\\29").replace("\x00", "\\00"))


def _upn_domain(base_dn: str) -> str:
    parts = re.findall(r"DC=([^,]+)", base_dn, re.IGNORECASE)
    return ".".join(parts)


def _cn(dn: str) -> str:
    m = re.match(r"CN=([^,]+)", dn, re.IGNORECASE)
    return m.group(1) if m else dn


def _norm_dn(dn: str) -> str:
    return ",".join(p.strip() for p in str(dn).split(",")).lower()


def _under(dn: str, base_dn: str) -> bool:
    if not base_dn:
        return True
    dn, base = _norm_dn(dn), _norm_dn(base_dn)
    return dn == base or dn.endswith("," + base)


def _in_scope(raw_groups, base_dn, scope):
    if scope == "any":
        return list(raw_groups)
    return [dn for dn in raw_groups if _under(dn, base_dn)]


def _group_list(value):
    value = value or ""
    sep = ";" if (";" in value or "=" in value) else ","
    return [p.strip() for p in value.split(sep) if p.strip()]


def _matches(group_dns, configured):
    if not configured:
        return False
    wanted_dns = {_norm_dn(c) for c in configured if "=" in c}
    wanted_cns = {c.lower() for c in configured if "=" not in c}
    for dn in group_dns:
        if _norm_dn(dn) in wanted_dns:
            return True
        if _cn(dn).lower() in wanted_cns:
            return True
    return False


_connect_fn = None


def _real_connect(url, upn, password, timeout, ca_file=None):
    import ssl
    from urllib.parse import urlparse

    from ldap3 import SIMPLE, Connection, Server, Tls

    parsed = urlparse(url)
    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=ca_file or None)
    server = Server(parsed.hostname, port=parsed.port or 636,
                    use_ssl=True, tls=tls, connect_timeout=timeout)
    return Connection(server, user=upn, password=password,
                      authentication=SIMPLE, auto_bind=True,
                      receive_timeout=timeout)


def _bind(url, upn, password, timeout, overrides=None):
    try:
        if _connect_fn:
            conn = _connect_fn(url, upn, password, timeout)
        else:
            conn = _real_connect(url, upn, password, timeout,
                                 _cfg("ATLAS_LDAP_CA_FILE", overrides=overrides))
    except ValueError:
        raise
    except Exception:
        return False, None
    return True, conn


def _lookup(conn, base_dn, username, upn):
    try:
        from ldap3 import SUBTREE
    except ImportError:
        SUBTREE = "SUBTREE"
    esc_user, esc_upn = _esc(username), _esc(upn)
    try:
        conn.search(search_base=base_dn,
                    search_filter=f"(|(userPrincipalName={esc_upn})"
                                  f"(&(sAMAccountName={esc_user})"
                                  f"(!(userPrincipalName=*))))",
                    search_scope=SUBTREE,
                    attributes=["memberOf", "mail", "displayName"])
        if not conn.entries or len(conn.entries) > 1:
            return None
        entry = conn.entries[0]
        raw_groups = list(entry.memberOf.values) if entry.memberOf else []
        display = str(entry.displayName) if entry.displayName else username
        email = str(entry.mail) if entry.mail else ""
    finally:
        try:
            conn.unbind()
        except Exception:
            pass
    return raw_groups, display, email


def authenticate(username, password, overrides=None):
    url = _cfg("ATLAS_LDAP_URL", overrides=overrides)
    base_dn = _cfg("ATLAS_LDAP_BASE_DN", overrides=overrides)
    if not is_ldaps(url):
        raise ValueError("ATLAS_LDAP_URL must be ldaps:// — plaintext LDAP "
                         "carries the user's password and is refused.")
    username = (username or "").strip()
    if not username or not (password or "").strip():
        return False, {}
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", username):
        return False, {}

    domain = _cfg("ATLAS_LDAP_UPN_DOMAIN", overrides=overrides) or _upn_domain(base_dn)
    timeout = int(_cfg("ATLAS_LDAP_TIMEOUT", "5", overrides=overrides) or 5)
    upn = f"{username}@{domain}"
    bound, conn = _bind(url, upn, password, timeout, overrides)
    if not bound:
        return False, {}
    try:
        found = _lookup(conn, base_dn, username, upn)
    except Exception as e:
        log.warning("ldap: the directory took the bind for %s and then failed the lookup: %s",
                    username, e)
        return False, {}
    if found is None:
        return False, {}
    raw_groups, display, email = found

    scope = (_cfg("ATLAS_LDAP_GROUP_SCOPE", "base", overrides=overrides) or "base").lower()
    group_dns = _in_scope(raw_groups, base_dn, scope)
    groups = [_cn(dn) for dn in group_dns]

    access = _group_list(_cfg("ATLAS_LDAP_ACCESS_GROUPS", overrides=overrides))
    if access and not _matches(group_dns, access):
        return False, {}
    admin_groups = _group_list(_cfg("ATLAS_LDAP_ADMIN_GROUPS", envnames.env("ATLAS_ADMIN_GROUP"),
                                    overrides=overrides))
    return True, {
        "username": username.lower(),
        "display_name": display,
        "email": email,
        "groups": groups,
        "is_admin": _matches(group_dns, admin_groups),
    }
