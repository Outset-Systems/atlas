"""Directory (AD/LDAP) sign-in for accounts mode — the configurable AD tie-in.

The hosted Atlas does not sit behind the Hub, so it cannot inherit the Hub's
AD identity headers; when a directory is wanted, this module binds to it
directly, the same way the Hub itself does. Everything is environment
configuration, nothing is hard-coded:

    ATLAS_AUTH_BACKENDS        CSV, order = try order. "local" (default),
                               "ldap", or "local,ldap". ldap is only live when
                               the two required vars below are also set.
    ATLAS_LDAP_URL             ldaps://dc.home.example:636  — ldaps:// ONLY.
                               Plain ldap:// is refused outright: this app's
                               suite doctrine is strict LDAP TLS, and a
                               credentials-carrying simple bind on a cleartext
                               channel is not a configuration, it's an incident.
    ATLAS_LDAP_BASE_DN         DC=corp,DC=example
    ATLAS_LDAP_UPN_DOMAIN      optional; derived from BASE_DN's DC= parts when
                               unset (corp.example above).
    ATLAS_LDAP_CA_FILE         optional CA bundle for a private CA (the lab's
                               The domain controller-CA). Validation is CERT_REQUIRED
                               with or without it; this only says *which* roots.
    ATLAS_LDAP_ACCESS_GROUPS   optional CSV. Set: a bound user must be in one
                               of these to get in. Unset: any user who can
                               bind is allowed (the directory is the policy).
    ATLAS_LDAP_ADMIN_GROUPS    CSV, default "atlas-admins" — membership grants
                               the Atlas admin flag (Desk writes, user mgmt).
                               Entries may be a bare CN or a full group DN;
                               a DN is the way to name one specific group when
                               several in the directory share a CN. Use ';' to
                               separate when the list contains DNs — they have
                               commas of their own.
    ATLAS_LDAP_GROUP_SCOPE     "base" (default) honours `memberOf` only from
                               under BASE_DN; "any" honours it forest-wide.
                               Default matters: on "any", a group named
                               atlas-admins created in any OU a user can write to
                               is Atlas admin.
    ATLAS_LDAP_TIMEOUT         seconds, default 5.

On success the identity is mirrored into the accounts store
(accounts.upsert_ldap_user) so redaction, audit and the admin panel have an
offline record; the directory stays the only credential authority.

`ldap3` is imported lazily — deployments that never enable the backend never
need it installed. Tests inject `_connect_fn` instead of a real server.
"""

import os
import re
import envnames


def _cfg(name, default="", overrides=None):
    """A directory setting, from THE SETTINGS first and the environment second.

    One seam, so every reader below became operator-configurable without a
    single call site changing. The persisted layer wins deliberately: a form
    field an operator edits and that then loses to a stale deployment value
    would be worse than no field at all. `auth_config` allowlists what may be
    written, so this cannot become a way to set unrelated environment keys.

    `overrides` is the SETTINGS-page "test these values without saving them"
    path, and when present it is the ONLY layer consulted — a proposal is
    judged exactly as typed, never blended with what is already in force.
    It is passed down the call chain rather than staged into `os.environ`,
    because this process serves other requests on other threads while a test
    bind is in flight: staging globally meant a concurrent login could be
    authorised against settings that nobody had approved yet, and persist the
    resulting admin flag long after the test returned.
    """
    if overrides is not None:
        return (str(overrides.get(name, "") or "").strip() or default)
    import auth_config
    return (auth_config.get(name) or os.environ.get(name) or default).strip()


def enabled():
    backends = [b.strip().lower() for b in
                _cfg("ATLAS_AUTH_BACKENDS", "local").split(",")]
    return ("ldap" in backends and bool(_cfg("ATLAS_LDAP_URL"))
            and bool(_cfg("ATLAS_LDAP_BASE_DN")))


def backends():
    """The configured try-order, filtered to what is actually usable."""
    order = [b.strip().lower() for b in
             _cfg("ATLAS_AUTH_BACKENDS", "local").split(",") if b.strip()]
    return [b for b in order if b == "local" or (b == "ldap" and enabled())]


def _esc(value: str) -> str:
    """RFC 4515 filter-value escaping."""
    return (value.replace("\\", "\\5c").replace("*", "\\2a")
            .replace("(", "\\28").replace(")", "\\29").replace("\x00", "\\00"))


def _upn_domain(base_dn: str) -> str:
    parts = re.findall(r"DC=([^,]+)", base_dn, re.IGNORECASE)
    return ".".join(parts)


def _cn(dn: str) -> str:
    m = re.match(r"CN=([^,]+)", dn, re.IGNORECASE)
    return m.group(1) if m else dn


def _norm_dn(dn: str) -> str:
    """A DN flattened for comparison — case and inter-component spacing only."""
    return ",".join(p.strip() for p in str(dn).split(",")).lower()


def _under(dn: str, base_dn: str) -> bool:
    """True when `dn` sits inside the configured base DN."""
    if not base_dn:
        return True
    dn, base = _norm_dn(dn), _norm_dn(base_dn)
    # the base itself, or a component boundary before it: a bare suffix
    # match would let `dc=notexample,dc=com` pass for `dc=example,dc=com`
    return dn == base or dn.endswith("," + base)


def _in_scope(raw_groups, base_dn, scope):
    """The group DNs whose membership this Atlas will honour.

    A `memberOf` DN is only meaningful together with where it lives. Reducing
    every DN to its CN and matching on that means a group named `atlas-admins`
    ANYWHERE the directory can reach — a delegated OU an ordinary user may
    create objects in, or a trusted domain — grants Atlas admin, and likewise
    hands out any `require_group` clearance by name. So membership is honoured
    only from under `ATLAS_LDAP_BASE_DN`, which is the scope the operator
    actually nominated.

    `ATLAS_LDAP_GROUP_SCOPE=any` restores the old forest-wide behaviour for a
    deployment whose groups genuinely live outside its base DN; it is opt-in
    because it cannot be made safe, only chosen.
    """
    if scope == "any":
        return list(raw_groups)
    return [dn for dn in raw_groups if _under(dn, base_dn)]


def _group_list(value):
    """Split a configured group list.

    Comma-separated by default, which is what every CN list has always been.
    But a full group DN *contains* commas, so any value carrying one is split
    on semicolons instead — otherwise `CN=atlas-admins,OU=Real,DC=home,DC=example`
    silently becomes four group names, one of which is `CN=atlas-admins` and
    matches nothing.
    """
    value = value or ""
    sep = ";" if (";" in value or "=" in value) else ","
    return [p.strip() for p in value.split(sep) if p.strip()]


def _matches(group_dns, configured, base_dn):
    """True if any honoured group DN matches a configured name or full DN.

    Accepts either form in the config: a bare CN (`atlas-admins`, matched against
    in-scope DNs only) or a full DN, which is matched exactly and is the way to
    name one specific group when several share a CN.
    """
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


# Test seam: replaced with a fake in the suite. Returns an object with
# .search(...), .entries and .unbind(), or raises on a failed bind.
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


def authenticate(username, password, overrides=None):
    """Bind as the user. Returns (ok, info) where info carries
    username/display_name/email/groups/is_admin. Never raises on a wrong
    password — (False, {}) — but DOES raise on misconfiguration (bad URL
    scheme), because that must fail loudly at the first login attempt, not
    read as one more wrong password forever.

    `overrides` binds against proposed settings without applying them (the
    SETTINGS page's "test"); see `_cfg`.
    """
    url = _cfg("ATLAS_LDAP_URL", overrides=overrides)
    base_dn = _cfg("ATLAS_LDAP_BASE_DN", overrides=overrides)
    if not url.lower().startswith("ldaps://"):
        raise ValueError("ATLAS_LDAP_URL must be ldaps:// — plaintext LDAP "
                         "carries the user's password and is refused.")
    username = (username or "").strip()
    # An empty password to an AD simple bind is an ANONYMOUS bind, and it
    # SUCCEEDS. Without this check, a blank password would log in as anyone.
    if not username or not (password or "").strip():
        return False, {}
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", username):
        return False, {}

    domain = _cfg("ATLAS_LDAP_UPN_DOMAIN", overrides=overrides) or _upn_domain(base_dn)
    timeout = int(_cfg("ATLAS_LDAP_TIMEOUT", "5", overrides=overrides) or 5)
    upn = f"{username}@{domain}"
    try:
        if _connect_fn:                      # test seam: unchanged 4-arg shape
            conn = _connect_fn(url, upn, password, timeout)
        else:
            conn = _real_connect(url, upn, password, timeout,
                                 _cfg("ATLAS_LDAP_CA_FILE", overrides=overrides))
    except ValueError:
        raise
    except Exception:
        # Wrong password, unreachable DC, expired account — all one answer.
        # The audit row (written by the caller) records that it was ldap.
        return False, {}

    try:
        from ldap3 import SUBTREE
    except ImportError:  # test seam in play; real ldap3 absent
        SUBTREE = "SUBTREE"
    # The bind proved control of a UPN, so the UPN is what the lookup must
    # resolve. Searching `(sAMAccountName=<username>)` asked a DIFFERENT
    # question: in AD the UPN prefix and sAMAccountName are independent
    # attributes, so a user whose UPN is `bob@…` while their sAMAccountName is
    # `alice` bound as bob and was then handed the groups, mail, display name
    # and admin verdict of whichever *other* account owned sAMAccountName=bob.
    # Authenticate as one account, receive another's clearance.
    #
    # The sAMAccountName arm is kept only for accounts that carry NO UPN at all
    # (AD then synthesises one from sAMAccountName at bind time, and there is no
    # other account whose real UPN could collide with it).
    esc_user, esc_upn = _esc(username), _esc(upn)
    try:
        conn.search(search_base=base_dn,
                    search_filter=f"(|(userPrincipalName={esc_upn})"
                                  f"(&(sAMAccountName={esc_user})"
                                  f"(!(userPrincipalName=*))))",
                    search_scope=SUBTREE,
                    attributes=["memberOf", "mail", "displayName"])
        if not conn.entries or len(conn.entries) > 1:
            # More than one match means the directory cannot tell us who bound;
            # guessing is exactly the confusion this filter exists to end.
            return False, {}
        entry = conn.entries[0]
        raw_groups = list(entry.memberOf.values) if entry.memberOf else []
        display = str(entry.displayName) if entry.displayName else username
        email = str(entry.mail) if entry.mail else ""
    finally:
        try:
            conn.unbind()
        except Exception:
            pass

    scope = (_cfg("ATLAS_LDAP_GROUP_SCOPE", "base", overrides=overrides) or "base").lower()
    group_dns = _in_scope(raw_groups, base_dn, scope)
    groups = [_cn(dn) for dn in group_dns]

    access = _group_list(_cfg("ATLAS_LDAP_ACCESS_GROUPS", overrides=overrides))
    if access and not _matches(group_dns, access, base_dn):
        return False, {}
    admin_groups = _group_list(_cfg("ATLAS_LDAP_ADMIN_GROUPS", envnames.env("ATLAS_ADMIN_GROUP"),
                                    overrides=overrides))
    return True, {
        "username": username.lower(),
        "display_name": display,
        "email": email,
        "groups": groups,
        "is_admin": _matches(group_dns, admin_groups, base_dn),
    }
