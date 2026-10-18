"""Per-site relay tokens.

Only the SHA-256 of a token is ever stored: an operator who reads the database
cannot replay a relay's credential. Plain SHA-256 (no KDF) is deliberate and
sufficient here — these are 256-bit random strings, not human passwords, so
there is no dictionary to attack and the lookup stays a single indexed query.

The token *is* the tenancy boundary: it names exactly one site, and the ingest
layer refuses any request that tries to write somewhere else.
"""

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from .models import Site, SiteToken

TOKEN_PREFIX = "atlas_"  # greppable by secret scanners
DEFAULT_SCOPES = "ingest"


def hash_token(token):
    return hashlib.sha256(str(token or "").strip().encode("utf-8")).hexdigest()


def issue_token(session, site_slug, label="", scopes=DEFAULT_SCOPES):
    """Mint a token for an existing site. Returns (token, row) — the plaintext
    is returned exactly once and never recoverable afterwards."""
    site = session.scalar(select(Site).where(Site.slug == site_slug))
    if site is None:
        raise ValueError(f"no such site {site_slug!r}")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = SiteToken(site_id=site.id, token_hash=hash_token(token),
                    label=label or "", scopes=scopes)
    session.add(row)
    session.flush()
    return token, row


def verify_token(session, token, scope="ingest"):
    """Resolve a bearer token. Returns (site, row, error) where error is one of
    None | 'unknown' | 'revoked' | 'scope'. Stamps last_used_at on success."""
    if not token:
        return None, None, "unknown"
    row = session.scalar(select(SiteToken).where(SiteToken.token_hash == hash_token(token)))
    if row is None:
        return None, None, "unknown"
    if row.revoked_at is not None:
        return None, row, "revoked"
    if scope and scope not in {s.strip() for s in (row.scopes or "").split(",") if s.strip()}:
        return None, row, "scope"
    row.last_used_at = datetime.now(timezone.utc)
    return session.get(Site, row.site_id), row, None


def revoke_token(session, token_id):
    """Revoke by row id. Returns True if it was live, False if unknown/already revoked."""
    row = session.get(SiteToken, token_id)
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(timezone.utc)
    return True


def list_tokens(session, site_slug=None, include_revoked=False):
    q = select(SiteToken, Site).join(Site, Site.id == SiteToken.site_id)
    if site_slug:
        q = q.where(Site.slug == site_slug)
    if not include_revoked:
        q = q.where(SiteToken.revoked_at.is_(None))
    return list(session.execute(q.order_by(Site.slug, SiteToken.id)).all())
