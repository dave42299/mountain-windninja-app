"""Shared pytest fixtures and test helpers for the backend test suite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import Settings
from models.database import Base
from models.enums import ForecastStatus, SolverType, WeatherModel
from models.orm import ElevationTile, Forecast, ForecastArea, LandCoverTile

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

BERTHOUD_LAT = 39.80
BERTHOUD_LON = -105.77
BERTHOUD_SIZE_KM = 10.0


# ---------------------------------------------------------------------------
# Shared helpers (must be imported explicitly by test modules)
# ---------------------------------------------------------------------------


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Build a timezone-aware UTC datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


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


def insert_tiles(session: Session) -> tuple[ElevationTile, LandCoverTile]:
    """Insert a paired elevation + land-cover tile with fixed test paths."""
    elev = ElevationTile(
        id=uuid.uuid4(),
        bbox_north=39.85,
        bbox_south=39.65,
        bbox_east=-105.65,
        bbox_west=-105.85,
        crs_epsg=32613,
        file_path="elevation/test.tif",
        source="usgs_3dep",
        file_size_bytes=10000,
    )
    lcp = LandCoverTile(
        id=uuid.uuid4(),
        bbox_north=39.85,
        bbox_south=39.65,
        bbox_east=-105.65,
        bbox_west=-105.85,
        crs_epsg=5070,
        file_path="land_cover/test.lcp",
        source="landfire",
        file_size_bytes=20000,
    )
    session.add_all([elev, lcp])
    session.flush()
    return elev, lcp


def insert_forecast_area(session: Session) -> ForecastArea:
    """Insert and flush a ForecastArea centred on Berthoud Pass."""
    area = ForecastArea(
        id=uuid.uuid4(),
        label="Berthoud Pass",
        center_latitude=BERTHOUD_LAT,
        center_longitude=BERTHOUD_LON,
        size_km=BERTHOUD_SIZE_KM,
    )
    session.add(area)
    session.flush()
    return area


def insert_forecast(
    session: Session,
    elev: ElevationTile,
    lcp: LandCoverTile,
    *,
    status: ForecastStatus = ForecastStatus.queued,
    forecast_area_id: uuid.UUID | None = None,
) -> Forecast:
    """Insert and flush a Forecast row wired to the given tile pair."""
    forecast = Forecast(
        id=uuid.uuid4(),
        forecast_area_id=forecast_area_id,
        center_latitude=BERTHOUD_LAT,
        center_longitude=BERTHOUD_LON,
        size_km=BERTHOUD_SIZE_KM,
        elevation_tile_id=elev.id,
        land_cover_tile_id=lcp.id,
        status=status,
        weather_model=WeatherModel.hrrr,
        solver_type=SolverType.momentum,
        output_wind_height=10.0,
        forecast_start=utc(2026, 5, 15, 6),
        duration_hours=6,
    )
    session.add(forecast)
    session.flush()
    return forecast


def make_non_closing_factory(session: Session):
    """Build a session factory whose sessions skip ``close()``.

    ``_run_forecast_pipeline`` calls ``session.close()`` in its ``finally``
    block; disabling it lets the calling test keep the session alive for
    post-run assertions.
    """
    def factory():
        session.close = lambda: None  # type: ignore[assignment]
        return session
    return factory


# ---------------------------------------------------------------------------
# Shared fixtures (auto-discovered by pytest, no import needed)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_engine():
    """Thread-safe in-memory SQLite engine.

    Uses StaticPool + check_same_thread=False so the same connection works
    across threads (required by FastAPI TestClient).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """SQLAlchemy session bound to the shared in-memory engine."""
    session = sessionmaker(bind=db_engine)()
    yield session
    session.close()


@pytest.fixture
def session_factory(db_engine):
    """``sessionmaker`` bound to the shared engine, for tests that need a factory."""
    return sessionmaker(bind=db_engine)


@pytest.fixture
def test_settings(tmp_path: Path):
    """Application ``Settings`` pointing at an isolated tmp_path data directory."""
    for subdir in ("elevation", "land_cover", "output", "weather"):
        (tmp_path / subdir).mkdir()
    return Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
