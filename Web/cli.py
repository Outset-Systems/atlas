import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validation import validate


def _store():
    import store
    return store


def _site_lock(site):
    import contextlib
    from dataset import site_lock, site_lock_path
    folder = os.path.dirname(site_lock_path(site))
    if not os.path.isdir(folder):
        print(f"note: no revisions folder at {folder}, so no write lock is shared with a "
              "running Atlas; set ATLAS_REVISIONS to its folder, or run this inside it",
              file=sys.stderr)
        return contextlib.nullcontext()
    return site_lock(site)


def _locked(fn):
    def run(args, *more):
        from filelock import LockTimeout
        try:
            with _site_lock(args.site):
                return fn(args, *more)
        except LockTimeout as e:
            print(f"error: the map is being saved ({e}) — nothing imported; run it again",
                  file=sys.stderr)
            return 4
    run.__name__ = fn.__name__
    run.__doc__ = fn.__doc__
    return run


ACTOR = "cli"


def _print_problems(problems):
    for p in problems:
        print(f"  problem: {p}", file=sys.stderr)


def _stats_line(stats):
    return ", ".join(f"{k} {v}" for k, v in stats.items() if v)


def _read_token_file(path, label):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        print(f"error: cannot read {label}: {e}", file=sys.stderr)
        return None


@_locked
def cmd_import_json(args):
    try:
        with open(args.path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"error: cannot read dataset: {e}", file=sys.stderr)
        return 2
    problems = validate(data)
    _print_problems(problems)
    if problems and args.strict:
        print(f"error: {len(problems)} problem(s) and --strict set — nothing imported",
              file=sys.stderr)
        return 3
    st = _store()
    with st.session_scope() as s:
        import provenance
        provenance.stamp(st.dump_labdata(s, args.site) or {}, data, None, ACTOR,
                         "import-json", trust=args.keep_stamps)
        site = st.load_labdata(s, data, site_slug=args.site, site_name=args.name)
        print(f"imported {args.path} -> site {site.slug!r} v{site.data_version}: "
              f"{len(data.get('zones', []))} zones, {len(data.get('nodes', []))} nodes, "
              f"{len(data.get('routes', []))} routes"
              + (f", {len(problems)} problem(s) tolerated" if problems else ""))
    return 0


def cmd_import_netbox(args):
    from importers.netbox import (
        NetBoxClient, NetBoxError, fetch_snapshot, parse_role_map,
    )
    token = args.token
    if not token and args.token_file:
        token = _read_token_file(args.token_file, "token file")
        if token is None:
            return 2
    token = token or os.environ.get("NETBOX_TOKEN")
    if not token and os.environ.get("NETBOX_TOKEN_FILE"):
        token = _read_token_file(os.environ["NETBOX_TOKEN_FILE"], "NETBOX_TOKEN_FILE")
        if token is None:
            return 2
    if not token:
        print("error: no NetBox token (--token/--token-file or NETBOX_TOKEN[_FILE])",
              file=sys.stderr)
        return 2
    try:
        role_map = parse_role_map(args.role_map)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    client = NetBoxClient(args.url, token, verify=not args.insecure)
    try:
        snapshot = fetch_snapshot(client, netbox_site=args.netbox_site)
    except NetBoxError as e:
        print(f"error: {e} — nothing imported", file=sys.stderr)
        return 2

    return _write_netbox(args, snapshot, role_map)


@_locked
def _write_netbox(args, snapshot, role_map):
    from importers.netbox import sync
    st = _store()
    with st.session_scope() as s:
        before = st.dump_labdata(s, args.site)
        stats = sync(s, snapshot, site_slug=args.site, role_map=role_map)
        st.restamp(s, args.site, before, ACTOR, "netbox")
        problems = validate(st.dump_labdata(s, args.site))
    print(f"netbox -> site {args.site!r}: " + _stats_line(stats))
    _print_problems(problems)
    return 0


@_locked
def cmd_import_nmap(args):
    from importers.nmap import (
        NmapError, import_observations, parse_nmap_xml, undocumented,
    )
    try:
        with open(args.path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"error: cannot read scan: {e}", file=sys.stderr)
        return 2
    try:
        hosts = parse_nmap_xml(text)
    except NmapError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    st = _store()
    with st.session_scope() as s:
        before = st.dump_labdata(s, args.site)
        stats = import_observations(s, hosts, site_slug=args.site,
                                    source=args.source, promote=args.promote)
        st.restamp(s, args.site, before, ACTOR, args.source)
        drift = [
            f"{o.ip or o.mac} {('(' + o.hostname + ')') if o.hostname else ''}".strip()
            for o in undocumented(s, args.site)
        ]
    print(f"{args.source} -> site {args.site!r}: {len(hosts)} host(s) up, "
          + _stats_line(stats))
    if drift:
        print(f"  undocumented device(s) on the network ({len(drift)}):", file=sys.stderr)
        for d in drift:
            print(f"    {d}", file=sys.stderr)
    return 0


@_locked
def cmd_import_csv(args):
    from importers.csv_import import import_rows, parse_csv
    try:
        with open(args.path, encoding="utf-8-sig") as f:
            text = f.read()
    except OSError as e:
        print(f"error: cannot read csv: {e}", file=sys.stderr)
        return 2
    rows, errors = parse_csv(text)
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    if errors:
        print(f"error: {len(errors)} problem(s) — nothing imported", file=sys.stderr)
        return 3
    st = _store()
    with st.session_scope() as s:
        before = st.dump_labdata(s, args.site)
        stats = import_rows(s, rows, site_slug=args.site, retire_missing=args.retire_missing)
        st.restamp(s, args.site, before, ACTOR, "csv")
        problems = validate(st.dump_labdata(s, args.site))
    print(f"csv -> site {args.site!r}: {len(rows)} row(s), "
          + _stats_line(stats))
    _print_problems(problems)
    return 0


def cmd_export(args):
    st = _store()
    with st.session_scope() as s:
        data = st.dump_labdata(s, args.site)
    if data is None:
        print(f"error: no such site {args.site!r} (see: python cli.py sites)", file=sys.stderr)
        return 2
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if args.output and args.output != "-":
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"exported site {args.site!r} -> {args.output} "
              f"({len(data.get('nodes', []))} nodes)", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def cmd_sites(args):
    from sqlalchemy import func, select
    st = _store()
    with st.session_scope() as s:
        sites = s.scalars(select(st.Site).order_by(st.Site.slug)).all()
        if not sites:
            print("no sites (seed one: python cli.py import-json --site <slug> lab-data.json)")
            return 0
        for site in sites:
            nodes = s.scalar(select(func.count(st.Node.id)).where(st.Node.site_id == site.id))
            zones = s.scalar(select(func.count(st.Zone.id)).where(st.Zone.site_id == site.id))
            updated = site.updated_at.strftime("%Y-%m-%d %H:%M") if site.updated_at else "—"
            print(f"{site.slug:<20} v{site.data_version:<4} {zones:>3} zones {nodes:>4} nodes"
                  f"  updated {updated}  {site.name}")
    return 0


TOKEN_SCOPES = ("ingest", "tripwires")


def cmd_token_issue(args):
    from store.tokens import issue_token
    scopes = [x.strip() for x in (args.scopes or "").split(",") if x.strip()]
    bad = [x for x in scopes if x not in TOKEN_SCOPES]
    if not scopes or bad:
        print(f"error: --scopes must be a comma list of {', '.join(TOKEN_SCOPES)}"
              + (f" (not {bad[0]!r})" if bad else ""), file=sys.stderr)
        return 2
    args.scopes = ",".join(scopes)
    st = _store()
    with st.session_scope() as s:
        try:
            token, row = issue_token(s, args.site, label=args.label or "", scopes=args.scopes)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        tid = row.id
    print(f"token #{tid} for site {args.site!r} (scopes: {args.scopes})", file=sys.stderr)
    print("store it now — only its hash is kept, it cannot be shown again:", file=sys.stderr)
    print(token)
    return 0


def cmd_token_list(args):
    from store.tokens import list_tokens
    st = _store()
    with st.session_scope() as s:
        rows = list_tokens(s, site_slug=args.site, include_revoked=args.all)
        if not rows:
            print("no tokens" + (" (use --all to include revoked)" if not args.all else ""))
            return 0
        for row, site in rows:
            used = row.last_used_at.strftime("%Y-%m-%d %H:%M") if row.last_used_at else "never"
            state = "REVOKED" if row.revoked_at else "live"
            print(f"#{row.id:<4} {site.slug:<20} {state:<8} scopes={row.scopes:<10} "
                  f"used {used}  {row.label}")
    return 0


def cmd_token_revoke(args):
    from store.tokens import revoke_token
    st = _store()
    with st.session_scope() as s:
        ok = revoke_token(s, args.id)
    if not ok:
        print(f"error: token #{args.id} is unknown or already revoked", file=sys.stderr)
        return 2
    print(f"token #{args.id} revoked")
    return 0


def cmd_tripwires_key(args):
    import secrets as _secrets
    if args.new_secret:
        print(_secrets.token_urlsafe(32))
        return 0
    import tripwires
    key = tripwires.webhook_key()
    if not key:
        print("error: no ATLAS_TRIPWIRES_SECRET (or _FILE) of at least "
              f"{tripwires.SECRET_MIN} characters — make one with "
              "`python cli.py tripwires-key --new-secret`", file=sys.stderr)
        return 2
    print("the TRIPWIRES webhook key (Bearer header or ?key=); it changes "
          "when the secret does:", file=sys.stderr)
    print(key)
    return 0


def cmd_initdb(args):
    st = _store()
    st.init_db()
    print(f"tables created at {st.db_url()} (deployments should use: alembic upgrade head)")
    return 0



def _read_file(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        print(f"error: cannot read the {what} file {path!r}: {e.strerror or e}", file=sys.stderr)
        return None


def _read_password(args):
    if getattr(args, "password_file", None):
        return _read_file(args.password_file, "password")
    import getpass
    pw = getpass.getpass("Password: ")
    if getpass.getpass("Again: ") != pw:
        print("error: passwords do not match", file=sys.stderr)
        return None
    return pw


def cmd_user_add(args):
    import accounts
    pw = _read_password(args)
    if pw is None:
        return 2
    try:
        acc = accounts.create_local_user(
            args.username, pw, display_name=args.display_name or "",
            email=args.email or "",
            groups=[g.strip() for g in (args.groups or "").split(",") if g.strip()],
            is_admin=args.admin)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    accounts.audit("user_created", acc["username"], detail="atlasctl")
    print(f"created {acc['username']}" + (" (admin)" if args.admin else ""))
    return 0


def cmd_user_list(args):
    import accounts
    users = accounts.list_users()
    if not users:
        print("no accounts (create one: python cli.py user-add <name> --admin)")
        return 0
    for u in users:
        flags = "".join((
            "A" if u["is_admin"] else "-",
            "M" if u["mfa_enabled"] else "-",
            "x" if not u["active"] else "-"))
        print(f"{u['username']:<28} {u['source']:<6} {flags}  "
              f"last {u['last_login'] or 'never':<20} {u['groups_csv']}")
    return 0


def cmd_user_passwd(args):
    import accounts
    pw = _read_password(args)
    if pw is None:
        return 2
    try:
        accounts.set_password(args.username, pw)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    accounts.audit("password_changed", args.username, detail="atlasctl")
    print(f"password set for {args.username} (existing sessions invalidated)")
    return 0


def cmd_user_mod(args):
    import accounts
    acc = accounts.get_user(args.username)
    if not acc:
        print(f"error: no such account {args.username!r}", file=sys.stderr)
        return 2
    if args.set_admin is not None:
        if acc["source"] == "ldap":
            print("error: directory accounts get admin from ATLAS_LDAP_ADMIN_GROUPS",
                  file=sys.stderr)
            return 2
        if acc["source"] == "oidc":
            print("error: single sign-on accounts get admin from ATLAS_OIDC_ADMIN_GROUPS",
                  file=sys.stderr)
            return 2
        try:
            accounts.set_admin(args.username, args.set_admin)
        except accounts.LastAdminError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        accounts.audit("user_admin", args.username, detail="atlasctl")
    if args.set_active is not None:
        try:
            accounts.set_active(args.username, args.set_active)
        except accounts.LastAdminError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        accounts.audit("user_active", args.username, detail="atlasctl")
    if args.reset_mfa:
        accounts.disable_mfa(args.username)
        accounts.audit("mfa_reset", args.username, detail="atlasctl")
    u = accounts.get_user(args.username)
    print(f"{u['username']}: admin={bool(u['is_admin'])} active={bool(u['active'])} "
          f"mfa={bool(u['mfa_enabled'])}")
    return 0


def cmd_user_del(args):
    import accounts
    acc = accounts.get_user(args.username)
    if not acc:
        print(f"error: no such account {args.username!r}", file=sys.stderr)
        return 2
    if acc["is_admin"] and acc["active"] and accounts.count_active_admins() <= 1:
        print("error: that is the last active admin", file=sys.stderr)
        return 2
    try:
        accounts.delete_user(args.username)
    except accounts.LastAdminError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    accounts.audit("user_deleted", args.username, detail="atlasctl")
    print(f"deleted {args.username}")
    return 0


def cmd_mcp(args):
    token = os.environ.get("ATLAS_TOKEN", "").strip()
    if args.token_file:
        token = _read_file(args.token_file, "token")
        if token is None:
            return 2
    import mcp_stdio
    return mcp_stdio.main(token)


def _add_dataset_commands(sub):
    p = sub.add_parser("import-json", help="full-replace import of a canonical dataset")
    p.add_argument("path")
    p.add_argument("--site", default="default", help="site slug (default: default)")
    p.add_argument("--name", help="site display name (default: dataset meta.title)")
    p.add_argument("--strict", action="store_true", help="refuse import on validation problems")
    p.add_argument("--keep-stamps", action="store_true",
                   help="restoring or moving a map: keep the file's own record of who charted "
                        "and checked each place (otherwise every new place starts unchecked)")
    p.set_defaults(fn=cmd_import_json)

    p = sub.add_parser("import-netbox", help="read-only sync from a NetBox instance")
    p.add_argument("--site", default="default", help="Atlas site slug to sync into")
    p.add_argument("--url", required=True, help="NetBox base URL (e.g. https://netbox.home.example)")
    p.add_argument("--token", help="API token (prefer --token-file or NETBOX_TOKEN[_FILE])")
    p.add_argument("--token-file", help="file containing the API token")
    p.add_argument("--netbox-site", help="only objects from this NetBox site slug")
    p.add_argument("--role-map", default="",
                   help="extra role=kind pairs, e.g. 'nas=physical,edge=network'")
    p.add_argument("--insecure", action="store_true", help="skip TLS verification")
    p.set_defaults(fn=cmd_import_netbox)

    p = sub.add_parser("import-nmap", help="record an nmap -oX scan as observations (drift)")
    p.add_argument("path", help="nmap XML file (nmap -oX scan.xml <targets>)")
    p.add_argument("--site", default="default")
    p.add_argument("--source", default="nmap", choices=("nmap", "arp", "relay"))
    p.add_argument("--promote", action="store_true",
                   help="turn undocumented hosts into real nodes (kind=unknown)")
    p.set_defaults(fn=cmd_import_nmap)

    p = sub.add_parser("import-csv", help="import a device list (name,ip,kind,zone,role,url,notes)")
    p.add_argument("path")
    p.add_argument("--site", default="default")
    p.add_argument("--retire-missing", action="store_true",
                   help="treat the file as the whole inventory: retire csv nodes absent from it")
    p.set_defaults(fn=cmd_import_csv)

    p = sub.add_parser("export", help="write a site back out as lab-data.json")
    p.add_argument("--site", default="default")
    p.add_argument("-o", "--output", help="output path (default: stdout)")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("sites", help="list sites")
    p.set_defaults(fn=cmd_sites)


def _add_token_commands(sub):
    p = sub.add_parser("token-issue", help="mint a relay token for a site (shown once)")
    p.add_argument("--site", required=True)
    p.add_argument("--label", help="what this token is for, e.g. 'branch-office relay'")
    p.add_argument("--scopes", default="ingest",
                   help="comma list: ingest (relay), tripwires (the TRIPWIRES webhook)")
    p.set_defaults(fn=cmd_token_issue)

    p = sub.add_parser("token-list", help="list relay tokens")
    p.add_argument("--site")
    p.add_argument("--all", action="store_true", help="include revoked tokens")
    p.set_defaults(fn=cmd_token_list)

    p = sub.add_parser("token-revoke", help="revoke a relay token by id")
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_token_revoke)

    p = sub.add_parser("tripwires-key",
                       help="print the TRIPWIRES webhook key (from ATLAS_TRIPWIRES_SECRET)")
    p.add_argument("--new-secret", action="store_true",
                   help="print a fresh random secret to store instead")
    p.set_defaults(fn=cmd_tripwires_key)

    p = sub.add_parser("mcp", help="serve MCP over stdio, for a client that cannot send a "
                                   "header (needs an API token in ATLAS_TOKEN)")
    p.add_argument("--token-file", help="read the token from this file instead of ATLAS_TOKEN")
    p.set_defaults(fn=cmd_mcp)


def _add_account_commands(sub):
    p = sub.add_parser("user-add", help="create a local account (accounts mode)")
    p.add_argument("username")
    p.add_argument("--admin", action="store_true")
    p.add_argument("--display-name")
    p.add_argument("--email")
    p.add_argument("--groups", help="CSV clearance groups (require_group redaction)")
    p.add_argument("--password-file", help="read the password from a file instead of prompting")
    p.set_defaults(fn=cmd_user_add)

    p = sub.add_parser("user-list", help="list accounts (flags: Admin/Mfa/inactive-x)")
    p.set_defaults(fn=cmd_user_list)

    p = sub.add_parser("user-passwd", help="set a local account's password")
    p.add_argument("username")
    p.add_argument("--password-file")
    p.set_defaults(fn=cmd_user_passwd)

    p = sub.add_parser("user-mod", help="promote/demote, activate/deactivate, reset MFA")
    p.add_argument("username")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--admin", dest="set_admin", action="store_true", default=None)
    grp.add_argument("--no-admin", dest="set_admin", action="store_false")
    grp2 = p.add_mutually_exclusive_group()
    grp2.add_argument("--activate", dest="set_active", action="store_true", default=None)
    grp2.add_argument("--deactivate", dest="set_active", action="store_false")
    p.add_argument("--reset-mfa", action="store_true")
    p.set_defaults(fn=cmd_user_mod)

    p = sub.add_parser("user-del", help="delete an account")
    p.add_argument("username")
    p.set_defaults(fn=cmd_user_del)


def _build_parser():
    ap = argparse.ArgumentParser(prog="python cli.py", description="atlasctl: dataset and account operations for the Atlas")
    ap.add_argument("--db", help="database URL (overrides ATLAS_DB_URL)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    _add_dataset_commands(sub)
    _add_token_commands(sub)

    p = sub.add_parser("initdb", help="create tables (dev; deployments use alembic)")
    p.set_defaults(fn=cmd_initdb)

    _add_account_commands(sub)
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    args = _build_parser().parse_args(argv)
    if args.db:
        os.environ["ATLAS_DB_URL"] = args.db
    try:
        return args.fn(args)
    except Exception as e:
        if type(e).__name__ != "OperationalError" or "no such table" not in str(e):
            raise
        print("error: this database has no tables yet. On the db backend, run `alembic "
              "upgrade head` first. A default install uses the file backend, where this "
              "command does not apply: fill the map from the editor instead. See "
              "ATLAS_DATA_BACKEND in docs/configuration.md.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
