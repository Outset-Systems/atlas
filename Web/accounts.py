"""The accounts store — real sign-in for ATLAS_AUTH_MODE=accounts and hybrid.

Only relevant in those two modes (see atlas_auth.py). Storage is a small SQLite
DB beside the dataset (`<data-dir>/accounts.db`), never inside it — the
lab-data golden round-trip contract stays untouched. Passwords are hashed
(werkzeug PBKDF2), never stored or logged in plaintext; TOTP secrets are
encrypted at rest via crypto_at_rest.py.

Two account sources share the table (the Feed's identity-sync doctrine):

  local   created by an admin (atlasctl user-add, /api/v2/auth/users, or the
          bootstrap envs). Carries a password_hash. No open signup, ever —
          this app maps infrastructure; strangers don't get accounts.
  ldap    mirrored from a successful directory bind (ldap_backend.py).
          password_hash is NULL — the directory is the credential authority;
          the row caches display name, email, groups and the admin flag so
          redaction and the audit trail have an offline record.

The session-epoch column is a sibling app's pattern: bumped on any credential
change, compared against the value stamped into the session at login, so a
stolen or stale cookie fails closed the moment credentials change.
"""

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

# `redaction.sees_everything` treats this group name as full-admin clearance
# (it is the Hub's admin group, and hub mode's whole authorisation model). In
# accounts mode, admin is the is_admin FLAG, not a clearance group — so this
# name must never be handed out as an ordinary `require_group` clearance, or it
# becomes a second, silent path to admin. Refused at every assignment point.
import envnames  # noqa: E402

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
    """The accounts store path — resolved in settings (the one env reader)."""
    return settings.accounts_db_path()


def _connect():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


#: Paths whose schema this process has already ensured. init_db runs at the
#: top of most accounts calls and get_user sits on the per-request auth path,
#: so the four CREATE TABLEs and the index must not be re-issued every time.
#: Keyed on the RESOLVED path, not a flag: the tests point each case at a
#: fresh temp DB, and a deployment can repoint ATLAS_ACCOUNTS_DB between
#: tests of its own.
_ensured_paths = set()


def init_db():
    path = os.path.abspath(db_path())
    if path in _ensured_paths and _migrated and os.path.exists(path):
        return                       # a reset `_migrated` re-runs the ALTERs
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
        # Last, so it can reach every table above — not just `users`.
        _migrate(conn)
        conn.commit()
    _ensured_paths.add(path)


_migrated = False


def _migrate(conn):
    """Columns added after a database was born. CREATE IF NOT EXISTS never
    revisits, so a fresh DB gets the full schema above and an old one gets
    ALTERed here — once per process: init_db runs at the top of most accounts
    calls, and get_user is on the per-request auth path, so this must not cost
    a PRAGMA every time."""
    global _migrated
    if _migrated:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "emblem" not in cols:   # 2026-08-16 — the mark beside the name
        conn.execute("ALTER TABLE users ADD COLUMN emblem TEXT NOT NULL DEFAULT ''")
    if "mfa_last_step" not in cols:   # 2026-10-15 — a TOTP code is good once
        conn.execute("ALTER TABLE users ADD COLUMN mfa_last_step INTEGER")
    _backfill_utc_stamps(conn)  # 2026-08-25 — the ledger's clock became UTC-Z
    _migrated = True


# Every stamp this store writes, so the backfill and the format test agree on
# one list. (table, column) — all four were written by the old naive `_now()`.
# ⚑ These names are interpolated into SQL below because sqlite cannot bind an
# identifier. They are module literals and must STAY literals: never build an
# entry here from anything that reaches the app from outside.
_STAMP_COLUMNS = (
    ("users", "created"),
    ("users", "last_login"),
    ("mfa_backup_codes", "created"),
    ("auth_audit", "ts"),
)


def _to_utc_z(raw):
    """One stored stamp → the app's UTC-Z spelling, or None to leave it alone.

    A value already ending in `Z` is done. A value carrying an offset is simply
    re-expressed. A NAIVE value is the pre-fix case: it was written by
    `datetime.now()`, so it means local time — on THIS machine's zone, which is
    the only reading available after the fact. On the UTC container that is an
    identity conversion and the row merely gains its missing `Z`; on a clone
    restored to a different zone the shift is a best effort, and better than a
    stamp that claims nothing at all.
    """
    raw = (raw or "").strip()
    if not raw or raw.endswith("Z"):
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None          # not a stamp we wrote; never guess at it
    if dt.tzinfo is None:
        dt = dt.astimezone()             # naive == local, by definition of the bug
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _backfill_utc_stamps(conn):
    """Rewrite pre-2026-08-25 naive-local stamps as UTC-Z, once.

    Idempotent by construction: every converted value ends in `Z`, and the
    query only selects values that do not — so the second run matches nothing.
    It costs one scan per table per PROCESS (`_migrated` guards the rest),
    which for a home-lab ledger is cheaper than carrying a migration-version
    table just to skip it.
    """
    for table, col in _STAMP_COLUMNS:
        try:
            rows = conn.execute(
                f"SELECT rowid, {col} FROM {table} "
                f"WHERE {col} IS NOT NULL AND {col} <> '' AND {col} NOT LIKE '%Z'"
            ).fetchall()
        except sqlite3.OperationalError:
            continue         # table not born yet (a partially-created DB)
        fixed = [(z, r[0]) for r in rows if (z := _to_utc_z(r[1])) is not None]
        if fixed:
            conn.executemany(
                f"UPDATE {table} SET {col} = ? WHERE rowid = ?", fixed)
            log.info("accounts: %s.%s — %d stamp(s) converted to UTC-Z",
                     table, col, len(fixed))


def _now():
    """The sign-in ledger's clock — `2026-08-25T11:40:00Z`, the same spelling
    every other stamp in the Atlas uses (`jsonio.iso_utc`).

    It was `datetime.now().isoformat()` — naive LOCAL time, and the only wrong
    clock in the app: a stamp with no offset that a reader (the SIGN-INS panel,
    a JS `new Date`, an operator reading `atlasctl user-list`) has no way to
    place. On a UTC container the numbers happened to be right and the *format*
    still lied; anywhere else both were wrong. Rows written before this fix are
    converted once, in `_backfill_utc_stamps`.
    """
    return jsonio.iso_utc()


def _norm(username):
    return (username or "").strip().lower()


def valid_username(username):
    return bool(_USERNAME_RE.match(_norm(username)))


def _check_password(password):
    """The one password rule. Raises ValueError with the sentence the user reads."""
    if len(password or "") < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")


# ── Users ────────────────────────────────────────────────────────────────────

def get_user(username):
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?",
                           (_norm(username),)).fetchone()
        return dict(row) if row else None


def list_users():
    """For the admin panel / atlasctl. Excludes every credential column — an
    admin manages accounts, never reads their secrets."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT username, display_name, email, source, groups_csv, is_admin, "
            "active, mfa_enabled, emblem, created, last_login "
            # `created` is TEXT, so this is a LEXICOGRAPHIC sort — which is a
            # chronological one only because every stamp is the same
            # fixed-width UTC-Z spelling (`_now`). Converting the old naive
            # rows made this MORE correct, not less: two rows written either
            # side of a DST change used to sort by wall clock.
            "FROM users ORDER BY created ASC").fetchall()
        return [dict(r) for r in rows]


def count_active_admins():
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE is_admin = 1 AND active = 1").fetchone()
        return row["n"] if row else 0


def is_last_active_admin(acc):
    """True when `acc` is an active admin and there is no other. Demoting,
    deactivating or deleting it would leave nobody able to manage accounts."""
    return bool(acc.get("is_admin") and acc.get("active")
                and count_active_admins() <= 1)


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
            "groups_csv, is_admin, created) VALUES (?, ?, ?, 'local', ?, ?, ?, ?)",
            (username, display_name or username, email,
             generate_password_hash(password),
             groups_csv, 1 if is_admin else 0, _now()))
        conn.commit()
    return get_user(username)


class SourceConflict(ValueError):
    """A directory identity and a local account claim the same username.

    Deliberately a ValueError so the login route's existing "misconfigured"
    arm catches it: the right outcome is a refused sign-in and a loud log line,
    never a silent swap of one account for the other.
    """


def upsert_ldap_user(username, *, display_name="", email="", groups=(), is_admin=False):
    """Mirror a directory identity after a successful bind. The directory is
    authoritative: groups and the admin flag are overwritten every login, so a
    revoked AD group revokes here on the next sign-in (and immediately for new
    sessions; existing sessions live until epoch/expiry).

    ⚠ Authoritative over LDAP rows ONLY. This used to `DO UPDATE` whatever row
    held the username, which quietly converted a LOCAL account into a directory
    one the first time an AD user of the same name signed in. Both directions
    were bad: the local admin `link` lost `is_admin` to the directory's verdict
    AND its password (verify_password requires source='local'), which if it was
    the only admin locked user management for good; and in the other direction
    an AD user landing on an existing local name inherited that identity. A
    name collision across two authorities is for an operator to resolve, not
    for a login to decide silently.
    """
    username = _norm(username)
    init_db()
    # The directory's raw list may carry the reserved admin group (that is
    # how is_admin was decided); it is dropped here rather than refused, since
    # a login is not the place to raise. The flag is the only admin path.
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
            "groups_csv, is_admin, created, last_login) "
            "VALUES (?, ?, ?, 'ldap', NULL, ?, ?, ?, ?) "
            "ON CONFLICT(username) DO UPDATE SET "
            "display_name=excluded.display_name, email=excluded.email, "
            "source='ldap', groups_csv=excluded.groups_csv, "
            "is_admin=excluded.is_admin, last_login=excluded.last_login "
            # The same guard again, where it is atomic: the check above races
            # a concurrent create_local_user between its read and this write.
            "WHERE users.source = 'ldap'",
            (username, display_name or username, email, groups_csv,
             1 if is_admin else 0, _now(), _now()))
        conn.commit()
    fresh = get_user(username)
    if not fresh or (fresh.get("source") or "") != "ldap":
        raise SourceConflict(
            f"{username!r} could not be mirrored: a non-directory account of "
            f"that name exists.")
    return fresh


_DECOY = {}


def _decoy_hash():
    """A hash no password was ever meant to match, made once per process."""
    if "hash" not in _DECOY:
        _DECOY["hash"] = generate_password_hash(secrets.token_urlsafe(32))
    return _DECOY["hash"]


def verify_password(username, password):
    """Local-source accounts only; returns the account dict or None. An ldap
    row has no hash and can never pass here — its credential lives in the
    directory, and accepting a local password for it would be a second door."""
    acc = get_user(username)
    usable = bool(acc and acc["source"] == "local" and acc["password_hash"])
    # the hash runs either way: skipping it told a stranger which names exist
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


def set_admin(username, on):
    with _connect() as conn:
        conn.execute("UPDATE users SET is_admin = ? WHERE username = ?",
                     (1 if on else 0, _norm(username)))
        conn.commit()


def set_active(username, on):
    """Deactivation bumps the epoch so live sessions die with the account."""
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET active = ?, session_epoch = session_epoch + 1 "
            "WHERE username = ?", (1 if on else 0, _norm(username)))
        conn.commit()


def set_groups(username, groups):
    """Assign groups on a LOCAL account (feeds require_group redaction). An
    ldap account's groups mirror the directory and are refused here."""
    acc = get_user(username)
    if not acc or acc["source"] != "local":
        raise ValueError("Groups can only be assigned on local accounts.")
    groups_csv = ",".join(_clean_groups(groups))
    with _connect() as conn:
        conn.execute("UPDATE users SET groups_csv = ? WHERE username = ?",
                     (groups_csv, _norm(username)))
        conn.commit()


def set_emblem(username, emblem):
    """The mark an account wears beside its name — short, cosmetic, its own.
    Length/shape are the route's to enforce; this stores what it is handed."""
    init_db()
    with _connect() as conn:
        conn.execute("UPDATE users SET emblem = ? WHERE username = ?",
                     (emblem or "", _norm(username)))
        conn.commit()


def delete_user(username):
    username = _norm(username)
    with _connect() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute("DELETE FROM mfa_backup_codes WHERE username = ?", (username,))
        conn.commit()


def groups_of(acc):
    return [g.strip() for g in (acc.get("groups_csv") or "").split(",") if g.strip()]


# ── Session epochs ───────────────────────────────────────────────────────────

def session_epoch(username):
    acc = get_user(username)
    return int(acc["session_epoch"]) if acc else 0


def bump_session_epoch(username):
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET session_epoch = session_epoch + 1 WHERE username = ?",
            (_norm(username),))
        conn.commit()


# ── MFA (TOTP + one-time backup codes) ───────────────────────────────────────

BACKUP_CODE_COUNT = 10


def start_mfa_enrollment(username, *, reauthenticated=False):
    """Pending secret, not active until confirmed. Returns
    (secret, provisioning_uri, qr_svg) — QR rendered in-process so the secret
    never leaves this process.

    An account that already holds a factor is not re-enrolled on a bare
    session (2026-11-01): a stolen cookie could otherwise swap the owner's
    authenticator for its own and mint fresh backup codes. The route proves
    the caller first (current password, and a fresh code from the live
    factor) and says so with `reauthenticated=True`."""
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
        # the instance's brand, not a lab name: this label sits in the user's
        # authenticator app forever (a demo realm login read "Atlas")
        name=_norm(username), issuer_name=settings.APP_BRAND)
    buf = io.BytesIO()
    qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).save(buf)
    return secret, uri, buf.getvalue().decode("utf-8")


def _matching_step(secret, code, now=None):
    """The TOTP step `code` is good for, within ±1 of the current one, or
    None. Constant-time per candidate; the caller decides what the step
    means (recorded on confirm, must be LATER than the last on verify)."""
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
        # The confirming step is recorded, not cleared (2026-11-01): with NULL
        # here the very code just typed was still good at the login that
        # followed, for the rest of its ±1 window.
        conn.execute(
            "UPDATE users SET mfa_enabled = 1, mfa_secret = ?, mfa_pending_secret = NULL, "
            "mfa_last_step = ? WHERE username = ?",
            (crypto_at_rest.encrypt_text(secret), step, _norm(username)))
        conn.commit()
    return generate_backup_codes(username)


def disable_mfa(username):
    with _connect() as conn:
        # Security downgrade: kill every OTHER live session too.
        conn.execute(
            "UPDATE users SET mfa_enabled = 0, mfa_secret = NULL, "
            "mfa_pending_secret = NULL, mfa_last_step = NULL, "
            "session_epoch = session_epoch + 1 "
            "WHERE username = ?", (_norm(username),))
        conn.execute("DELETE FROM mfa_backup_codes WHERE username = ?",
                     (_norm(username),))
        conn.commit()


def verify_mfa_code(username, code, now=None):
    """A TOTP code is good ONCE (2026-10-15). `valid_window=1` accepts the
    previous, current and next 30 s step, and nothing recorded which step had
    been used — so a code read over a shoulder or out of a proxy log could be
    replayed for ~90 s after the real sign-in. Now the matching step must be
    LATER than the last one accepted, and the check-and-record is a single
    conditional UPDATE so two gunicorn workers cannot both accept it."""
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
    """Replaces the whole set; plaintext returned exactly once."""
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
                # Burn it in the same statement that checks it is unburnt: two
                # workers that both matched this row race here, and only the
                # one whose UPDATE changed the row may sign in on it.
                cur = conn.execute(
                    "UPDATE mfa_backup_codes SET used = 1 WHERE id = ? AND used = 0",
                    (row["id"],))
                conn.commit()
                return cur.rowcount == 1
    return False


def verify_mfa_or_backup(username, code):
    return verify_mfa_code(username, code) or consume_backup_code(username, code)


# ── Login throttle (per-account AND per-IP, the Feed's phase-5 shape) ────────
# A distributed source mints a fresh per-IP bucket each request, so the per-IP
# cap alone can't bound online brute force against one account; the per-account
# cap alone would let one IP spray the whole user table. Both, always.

THROTTLE_USER_MAX = settings.LOGIN_MAX_USER
THROTTLE_IP_MAX = settings.LOGIN_MAX_IP
THROTTLE_WINDOW_S = settings.LOGIN_WINDOW_S


def _user_key(username):
    return "u:" + _norm(username)


def _ip_key(ip):
    return "ip:" + (ip or "?")


def throttled(username, ip):
    """True when either bucket is over its cap. Callers answer a generic 429 —
    the response must not reveal which bucket tripped or whether the account
    exists."""
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
    """On success, forgive the account bucket (not the IP bucket — an attacker
    who also guessed someone else's password shouldn't get their spray quota
    refreshed by one hit)."""
    with _connect() as conn:
        conn.execute("DELETE FROM login_throttle WHERE key = ?",
                     (_user_key(username),))
        conn.commit()


# ── Audit (append-only) ──────────────────────────────────────────────────────

def audit(event, username="", ip="", detail=""):
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO auth_audit (ts, event, username, ip, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (_now(), event, _norm(username), ip or "", detail or ""))
        conn.commit()


def audit_tail(limit=200):
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ts, event, username, ip, detail FROM auth_audit "
            "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]
