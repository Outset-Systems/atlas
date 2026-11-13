"""Atlas DB backbone (Atlas for Teams, Phase 1 — the design notes).

Only queried when ATLAS_DATA_BACKEND=db. Importing `connections` loads this
package whatever the backend, though, so SQLAlchemy has to be installed in
file mode too.

Schema management: Alembic migrations (Web/migrations) are the deployment
path; `init_db()` (create_all) is for tests and throwaway dev databases.
"""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .labdata import dump_labdata, load_labdata, restamp, site_stamp  # noqa: F401
from .models import Base, Node, Site, Zone  # noqa: F401

DEFAULT_DB_URL = "sqlite:////data/atlas.db"

_engine = None
_engine_url = None
_session_factory = None


def db_url():
    return os.environ.get("ATLAS_DB_URL", DEFAULT_DB_URL)


def get_engine():
    """Process-wide engine, created lazily from ATLAS_DB_URL. Rebuilt if the
    URL changes (atlasctl --db, tests) — a stale cached engine silently
    pointing at the wrong database is worse than the rebuild cost."""
    global _engine, _engine_url, _session_factory
    url = db_url()
    if _engine is None or url != _engine_url:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine(url, future=True)
        _engine_url = url
        _session_factory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


@contextmanager
def session_scope():
    """Short-lived session: commit on success, rollback on error."""
    get_engine()
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine=None):
    """Create all tables (tests/dev). Deployments use `alembic upgrade head`."""
    Base.metadata.create_all(engine or get_engine())


def reset_engine_for_tests():
    """Drop the cached engine so tests can repoint ATLAS_DB_URL."""
    global _engine, _engine_url, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = _engine_url = _session_factory = None
