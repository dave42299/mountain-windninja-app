"""Shared pytest fixtures and test factories for the terrain test suite."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from models.database import Base
from models.orm import ElevationTile, LandCoverTile


@pytest.fixture
def db_session() -> Session:  # type: ignore[override]
    """In-memory SQLite session, cleaned up automatically after each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_elevation_tile(session: Session, **overrides: Any) -> ElevationTile:
    """Insert and flush a real ``ElevationTile`` with Berthoud-area defaults.

    Pass keyword arguments to override any field (e.g. ``bbox_north=40.0``).
    The returned tile has a valid ORM identity and can survive ``session.refresh()``.
    """
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "bbox_north": 39.85,
        "bbox_south": 39.65,
        "bbox_east": -105.65,
        "bbox_west": -105.85,
        "crs_epsg": 32613,
        "file_path": f"elevation/{uuid.uuid4()}.tif",
        "source": "usgs_3dep",
        "file_size_bytes": 12345,
    }
    defaults.update(overrides)
    tile = ElevationTile(**defaults)
    session.add(tile)
    session.flush()
    return tile


def make_land_cover_tile(session: Session, **overrides: Any) -> LandCoverTile:
    """Insert and flush a real ``LandCoverTile`` with Berthoud-area defaults.

    Pass keyword arguments to override any field (e.g. ``crs_epsg=5070``).
    The returned tile has a valid ORM identity and can survive ``session.refresh()``.
    """
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "bbox_north": 39.85,
        "bbox_south": 39.65,
        "bbox_east": -105.65,
        "bbox_west": -105.85,
        "crs_epsg": 5070,
        "file_path": f"land_cover/{uuid.uuid4()}.lcp",
        "source": "landfire",
        "file_size_bytes": 54321,
    }
    defaults.update(overrides)
    tile = LandCoverTile(**defaults)
    session.add(tile)
    session.flush()
    return tile
