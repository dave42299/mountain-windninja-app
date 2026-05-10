"""FastAPI dependencies for database sessions and app settings.

Engine and session factory are created lazily on first use via @lru_cache,
so importing this module has no side effects and the database connection is
only established when the first HTTP request arrives.
"""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from config import Settings, settings as app_settings
from models.database import build_engine, build_session_factory


@lru_cache
def _get_engine() -> Engine:
    return build_engine(app_settings.database_url)


@lru_cache
def _get_session_factory() -> sessionmaker[Session]:
    return build_session_factory(_get_engine())


def get_db() -> Generator[Session, None, None]:
    db = _get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def get_settings() -> Settings:
    return app_settings
