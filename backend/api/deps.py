from collections.abc import Generator

from sqlalchemy.orm import Session

from config import settings as app_settings
from models.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_settings():
    return app_settings
