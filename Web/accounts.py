import hmac
import logging
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone

import jsonio
import settings

from werkzeug.security import check_password_hash, generate_password_hash

log = logging.getLogger("atlas.auth.accounts")

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._@-]{0,127}$")

MIN_PASSWORD_LEN = 12

import envnames

RESERVED_ADMIN_GROUP = envnames.env("ATLAS_ADMIN_GROUP")


def _clean_groups(groups):
    out = []
    for g in groups:
        g = (g or "").strip()
        if not g:
            continue
        if g == RESERVED_ADMIN_GROUP:
            raise ValueError(
                f"{RESERVED_ADMIN_GROUP!r} is the admin group — grant admin with "
                "the is_admin flag, not as a clearance group.")
        out.append(g)
    return out


def db_path():
    return settings.accounts_db_path()


def _connect():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


_ensured_paths = set()


def init_db():
    path = os.path.abspath(db_path())
    if path in _ensured_paths and _migrated and os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE,
                display_name  TEXT NOT NULL DEFAULT '',
                email         TEXT NOT NULL DEFAULT '',
                source        TEXT NOT NULL DEFAULT 'local',
                password_hash TEXT,
                groups_csv    TEXT NOT NULL DEFAULT '',
                is_admin      INTEGER NOT NULL DEFAULT 0,
                active        INTEGER NOT NULL DEFAULT 1,
                mfa_enabled   INTEGER NOT NULL DEFAULT 0,
                mfa_secret    TEXT,
                mfa_pending_secret TEXT,
                mfa_last_step INTEGER,
                session_epoch INTEGER NOT NULL DEFAULT 0,
                emblem        TEXT NOT NULL DEFAULT '',
                created       TEXT NOT NULL,
                last_login    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mfa_backup_codes (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                username  TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                used      INTEGER NOT NULL DEFAULT 0,
                created   TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS login_throttle (
                key TEXT NOT NULL,
                ts  REAL NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_throttle_key ON login_throttle (key, ts)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_audit (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       TEXT NOT NULL,
                event    TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                ip       TEXT NOT NULL DEFAULT '',
                detail   TEXT NOT NULL DEFAULT ''
            )
        """)
        _migrate(conn)
        conn.commit()
    _ensured_paths.add(path)


_migrated = False


def _migrate(conn):
    global _migrated
    if _migrated:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "emblem" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN emblem TEXT NOT NULL DEFAULT ''")
    if "mfa_last_step" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN mfa_last_step INTEGER")
    _backfill_utc_stamps(conn)
    _migrated = True


_STAMP_COLUMNS = (
    ("users", "created"),
    ("users", "last_login"),
    ("mfa_backup_codes", "created"),
    ("auth_audit", "ts"),
)


def _to_utc_z(raw):
    raw = (raw or "").strip()
    if not raw or raw.endswith("Z"):
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _backfill_utc_stamps(conn):
    for table, col in _STAMP_COLUMNS:
        try:
            rows = conn.execute(
                f"SELECT rowid, {col} FROM {table} "
                f"WHERE {col} IS NOT NULL AND {col} <> '' AND {col} NOT LIKE '%Z'"
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        fixed = [(z, r[0]) for r in rows if (z := _to_utc_z(r[1])) is not None]
        if fixed:
            conn.executemany(
                f"UPDATE {table} SET {col} = ? WHERE rowid = ?", fixed)
            log.info("accounts: %s.%s — %d stamp(s) converted to UTC-Z",
                     table, col, len(fixed))


def _now():
    return jsonio.iso_utc()


def _norm(username):
    return (username or "").strip().lower()


def valid_username(username):
    return bool(_USERNAME_RE.match(_norm(username)))


def _check_password(password):
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")



def get_user(username):
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?",
                           (_norm(username),)).fetchone()
        return dict(row) if row else None


def list_users():
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT username, display_name, email, source, groups_csv, is_admin, "
            "active, mfa_enabled, emblem, created, last_login "
            "FROM users ORDER BY created ASC").fetchall()
        return [dict(r) for r in rows]


def count_active_admins():
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE is_admin = 1 AND active = 1").fetchone()
        return row["n"] if row else 0


def is_last_active_admin(acc):
    return bool(acc.get("is_admin") and acc.get("active")
                and count_active_admins() <= 1)


class LastAdminError(ValueError):
    pass


_NOT_THE_LAST_ADMIN = ("NOT (is_admin = 1 AND active = 1 AND "
                       "(SELECT COUNT(*) FROM users WHERE is_admin = 1 AND active = 1) <= 1)")


def _first_epoch():
    return secrets.randbelow(2 ** 31 - 1) + 1


def create_local_user(username, password, *, display_name="", email="",
                      groups=(), is_admin=False):
    username = _norm(username)
    if not valid_username(username):
        raise ValueError("Usernames are lowercase letters, digits, . _ @ -")
    _check_password(password)
    groups_csv = ",".join(_clean_groups(groups))
    init_db()
    if get_user(username):
        raise ValueError("That username already exists.")
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (username, display_name, email, source, password_hash, "
            "groups_csv, is_admin, created, session_epoch) "
            "VALUES (?, ?, ?, 'local', ?, ?, ?, ?, ?)",
            (username, display_name or username, email,
             generate_password_hash(password),
             groups_csv, 1 if is_admin else 0, _now(), _first_epoch()))
        conn.commit()
    return get_user(username)


class SourceConflict(ValueError):
    pass


def upsert_ldap_user(username, *, display_name="", email="", groups=(), is_admin=False):
    username = _norm(username)
    init_db()
    groups_csv = ",".join(
        g for g in (g.strip() for g in groups) if g and g != RESERVED_ADMIN_GROUP)
    existing = get_user(username)
    if existing and (existing.get("source") or "") != "ldap":
        raise SourceConflict(
            f"{username!r} already exists as a {existing.get('source') or 'local'} "
            f"account; the directory identity of the same name was refused. "
            f"Rename or remove one of them.")
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (username, display_name, email, source, password_hash, "
            "groups_csv, is_admin, created, last_login, session_epoch) "
            "VALUES (?, ?, ?, 'ldap', NULL, ?, ?, ?, ?, ?) "
            "ON CONFLICT(username) DO UPDATE SET "
            "display_name=excluded.display_name, email=excluded.email, "
            "source='ldap', groups_csv=excluded.groups_csv, "
            "is_admin=excluded.is_admin, last_login=excluded.last_login "
            "WHERE users.source = 'ldap'",
            (username, display_name or username, email, groups_csv,
             1 if is_admin else 0, _now(), _now(), _first_epoch()))
        conn.commit()
    fresh = get_user(username)
    if not fresh or (fresh.get("source") or "") != "ldap":
        raise SourceConflict(
            f"{username!r} could not be mirrored: a non-directory account of "
            f"that name exists.")
    return fresh


_DECOY = {}


def _decoy_hash():
    if "hash" not in _DECOY:
        _DECOY["hash"] = generate_password_hash(secrets.token_urlsafe(32))
    return _DECOY["hash"]


def verify_password(username, password):
    acc = get_user(username)
    usable = bool(acc and acc["source"] == "local" and acc["password_hash"])
    matches = check_password_hash(acc["password_hash"] if usable else _decoy_hash(), password or "")
    return acc if usable and matches else None


def set_password(username, new_password):
    _check_password(new_password)
    acc = get_user(username)
    if not acc or acc["source"] != "local":
        raise ValueError("No such local account.")
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1 "
            "WHERE username = ?",
            (generate_password_hash(new_password), _norm(username)))
        conn.commit()


def touch_login(username):
    with _connect() as conn:
        conn.execute("UPDATE users SET last_login = ? WHERE username = ?",
                     (_now(), _norm(username)))
        conn.commit()


def _guarded(conn, sql, args, username):
    cur = conn.execute(sql + " AND " + _NOT_THE_LAST_ADMIN, args)
    if cur.rowcount == 0 and conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (_norm(username),)).fetchone():
        raise LastAdminError("That is the last active admin.")
    return cur


def set_admin(username, on):
    with _connect() as conn:
        if on:
            conn.execute("UPDATE users SET is_admin = 1 WHERE username = ?", (_norm(username),))
        else:
            _guarded(conn, "UPDATE users SET is_admin = 0 WHERE username = ?",
                     (_norm(username),), username)
        conn.commit()


def set_active(username, on):
    with _connect() as conn:
        sql = ("UPDATE users SET active = ?, session_epoch = session_epoch + 1 "
               "WHERE username = ?")
        if on:
            conn.execute(sql, (1, _norm(username)))
        else:
            _guarded(conn, sql, (0, _norm(username)), username)
        conn.commit()


def set_groups(username, groups):
    acc = get_user(username)
    if not acc or acc["source"] != "local":
        raise ValueError("Groups can only be assigned on local accounts.")
    groups_csv = ",".join(_clean_groups(groups))
    with _connect() as conn:
        conn.execute("UPDATE users SET groups_csv = ? WHERE username = ?",
                     (groups_csv, _norm(username)))
        conn.commit()


def set_emblem(username, emblem):
    init_db()
    with _connect() as conn:
        conn.execute("UPDATE users SET emblem = ? WHERE username = ?",
                     (emblem or "", _norm(username)))
        conn.commit()


def delete_user(username):
    username = _norm(username)
    with _connect() as conn:
        _guarded(conn, "DELETE FROM users WHERE username = ?", (username,), username)
        conn.execute("DELETE FROM mfa_backup_codes WHERE username = ?", (username,))
        conn.commit()


def groups_of(acc):
    return [g.strip() for g in (acc.get("groups_csv") or "").split(",") if g.strip()]



def session_epoch(username):
    acc = get_user(username)
    return int(acc["session_epoch"]) if acc else 0


def bump_session_epoch(username):
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET session_epoch = session_epoch + 1 WHERE username = ?",
            (_norm(username),))
        conn.commit()



BACKUP_CODE_COUNT = 10


def start_mfa_enrollment(username, *, reauthenticated=False):
    import io

    import pyotp
    import qrcode
    import qrcode.image.svg

    import crypto_at_rest
    acc = get_user(username)
    if acc and acc.get("mfa_enabled") and not reauthenticated:
        raise ValueError("MFA is already enabled — confirm the current password "
                         "and a fresh code to replace it.")
    secret = pyotp.random_base32()
    with _connect() as conn:
        conn.execute("UPDATE users SET mfa_pending_secret = ? WHERE username = ?",
                     (crypto_at_rest.encrypt_text(secret), _norm(username)))
        conn.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=_norm(username), issuer_name=settings.APP_BRAND)
    buf = io.BytesIO()
    qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).save(buf)
    return secret, uri, buf.getvalue().decode("utf-8")


def _matching_step(secret, code, now=None):
    import pyotp
    code = (code or "").strip()
    if not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    current = int((now if now is not None else time.time()) // totp.interval)
    return next((s for s in (current - 1, current, current + 1)
                 if hmac.compare_digest(totp.at(s * totp.interval), code)), None)


def confirm_mfa(username, code):
    import crypto_at_rest
    acc = get_user(username)
    if not acc or not acc.get("mfa_pending_secret"):
        raise ValueError("No pending MFA enrollment for this account.")
    secret = crypto_at_rest.decrypt_text(acc["mfa_pending_secret"])
    step = _matching_step(secret, code)
    if step is None:
        raise ValueError("Incorrect code.")
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET mfa_enabled = 1, mfa_secret = ?, mfa_pending_secret = NULL, "
            "mfa_last_step = ? WHERE username = ?",
            (crypto_at_rest.encrypt_text(secret), step, _norm(username)))
        conn.commit()
    return generate_backup_codes(username)


def disable_mfa(username):
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET mfa_enabled = 0, mfa_secret = NULL, "
            "mfa_pending_secret = NULL, mfa_last_step = NULL, "
            "session_epoch = session_epoch + 1 "
            "WHERE username = ?", (_norm(username),))
        conn.execute("DELETE FROM mfa_backup_codes WHERE username = ?",
                     (_norm(username),))
        conn.commit()


def verify_mfa_code(username, code, now=None):
    import crypto_at_rest
    acc = get_user(username)
    if not acc or not acc.get("mfa_enabled") or not acc.get("mfa_secret"):
        return False
    step = _matching_step(crypto_at_rest.decrypt_text(acc["mfa_secret"]), code, now)
    if step is None:
        return False
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET mfa_last_step = ? WHERE username = ? "
            "AND (mfa_last_step IS NULL OR mfa_last_step < ?)",
            (step, _norm(username), step))
        conn.commit()
    return cur.rowcount == 1


def generate_backup_codes(username):
    username = _norm(username)
    codes = []
    now = _now()
    with _connect() as conn:
        conn.execute("DELETE FROM mfa_backup_codes WHERE username = ?", (username,))
        for _ in range(BACKUP_CODE_COUNT):
            raw = secrets.token_hex(4)
            code = f"{raw[:4]}-{raw[4:]}"
            codes.append(code)
            conn.execute(
                "INSERT INTO mfa_backup_codes (username, code_hash, used, created) "
                "VALUES (?, ?, 0, ?)", (username, generate_password_hash(code), now))
        conn.commit()
    return codes


def consume_backup_code(username, code):
    username = _norm(username)
    code = (code or "").strip()
    if not code:
        return False
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, code_hash FROM mfa_backup_codes WHERE username = ? AND used = 0",
            (username,)).fetchall()
        for row in rows:
            if check_password_hash(row["code_hash"], code):
                cur = conn.execute(
                    "UPDATE mfa_backup_codes SET used = 1 WHERE id = ? AND used = 0",
                    (row["id"],))
                conn.commit()
                return cur.rowcount == 1
    return False


def verify_mfa_or_backup(username, code):
    return verify_mfa_code(username, code) or consume_backup_code(username, code)



THROTTLE_USER_MAX = settings.LOGIN_MAX_USER
THROTTLE_IP_MAX = settings.LOGIN_MAX_IP
THROTTLE_WINDOW_S = settings.LOGIN_WINDOW_S


def _user_key(username):
    return "u:" + _norm(username)


def _ip_key(ip):
    return "ip:" + (ip or "?")


def throttled(username, ip):
    init_db()
    now = time.time()
    cutoff = now - THROTTLE_WINDOW_S
    with _connect() as conn:
        conn.execute("DELETE FROM login_throttle WHERE ts < ?", (cutoff - 3600,))
        n_user = conn.execute(
            "SELECT COUNT(*) AS n FROM login_throttle WHERE key = ? AND ts > ?",
            (_user_key(username), cutoff)).fetchone()["n"]
        n_ip = conn.execute(
            "SELECT COUNT(*) AS n FROM login_throttle WHERE key = ? AND ts > ?",
            (_ip_key(ip), cutoff)).fetchone()["n"]
        conn.commit()
    return n_user >= THROTTLE_USER_MAX or n_ip >= THROTTLE_IP_MAX


def record_failure(username, ip):
    init_db()
    now = time.time()
    with _connect() as conn:
        conn.execute("INSERT INTO login_throttle (key, ts) VALUES (?, ?)",
                     (_user_key(username), now))
        conn.execute("INSERT INTO login_throttle (key, ts) VALUES (?, ?)",
                     (_ip_key(ip), now))
        conn.commit()


def clear_failures(username):
    with _connect() as conn:
        conn.execute("DELETE FROM login_throttle WHERE key = ?",
                     (_user_key(username),))
        conn.commit()



AUDIT_KEEP = 20000


def audit(event, username="", ip="", detail=""):
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO auth_audit (ts, event, username, ip, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (_now(), event, _norm(username), ip or "", (detail or "")[:500]))
        conn.execute("DELETE FROM auth_audit WHERE id <= ?", (cur.lastrowid - AUDIT_KEEP,))
        conn.commit()


def audit_tail(limit=200):
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ts, event, username, ip, detail FROM auth_audit "
            "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]
