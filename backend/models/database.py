"""SQLAlchemy declarative base and factory functions for engine/session.

This module has zero side effects at import time. The engine and session
factory are created lazily by callers (FastAPI deps, Alembic env, tests)
so that importing models or schemas never requires a live database.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str, **kwargs) -> Engine:
    """Create a SQLAlchemy engine. Caller controls when this is invoked."""
    return create_engine(database_url, **kwargs)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to the given engine."""
    return sessionmaker(bind=engine)
