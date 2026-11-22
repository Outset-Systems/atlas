import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .labdata import dump_labdata, load_labdata, restamp, site_stamp
from .models import Base, Node, Site, Zone

DEFAULT_DB_URL = "sqlite:////data/atlas.db"

_engine = None
_engine_url = None
_session_factory = None


def db_url():
    return os.environ.get("ATLAS_DB_URL", DEFAULT_DB_URL)


def get_engine():
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
    Base.metadata.create_all(engine or get_engine())


def reset_engine_for_tests():
    global _engine, _engine_url, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = _engine_url = _session_factory = None
