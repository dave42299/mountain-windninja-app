"""SQLAlchemy ORM models for ForecastArea, ElevationTile, LandCoverTile, and Forecast.

Design decisions documented here:

- ForecastArea is an optional "saved location" bookmark. Users can run
  forecasts at arbitrary points without saving them; ForecastArea exists for
  users who want to name, revisit, or schedule recurring forecasts for a
  specific area.

- Every Forecast stores its own center_latitude/center_longitude/size_km so
  the location is always known, regardless of whether a ForecastArea exists.
  This supports both ephemeral "click and run" and persistent "saved location"
  workflows.

- ElevationTile and LandCoverTile are separate tables because the underlying
  data has different CRS, resolution, format, update frequency, and source API.
  Keeping them independent allows re-downloading land cover (e.g. after a
  wildfire) without touching elevation data.

- bbox columns are always stored in WGS84 decimal degrees regardless of the
  file's native CRS. This ensures spatial containment queries compare
  consistently across tiles.

- Forecast records which specific elevation and land cover tiles were used,
  providing full traceability for reproducibility and validation.

- file_path on tile tables is stored relative to the application's data_dir
  setting (e.g. "elevation/abc123.tif", not an absolute path). The service
  layer resolves it against settings.data_dir at read time. This keeps paths
  portable across development, Docker, and cloud environments.

- Output directory is not stored; it is derived by convention from the
  forecast ID (data/output/{forecast_id}/) to avoid path bookkeeping.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ForecastStatus(str, enum.Enum):
    queued = "queued"
    fetching_weather = "fetching_weather"
    running_solver = "running_solver"
    completed = "completed"
    failed = "failed"


class WeatherModel(str, enum.Enum):
    hrrr = "hrrr"
    nbm = "nbm"


class SolverType(str, enum.Enum):
    mass_conservation = "mass_conservation"
    momentum = "momentum"


# ---------------------------------------------------------------------------
# ForecastArea -- a user's saved forecast location (optional)
# ---------------------------------------------------------------------------


class ForecastArea(Base):
    __tablename__ = "forecast_areas"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_new_uuid)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    center_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    center_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    size_km: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    forecasts: Mapped[list["Forecast"]] = relationship(back_populates="forecast_area")


# ---------------------------------------------------------------------------
# ElevationTile -- cached DEM raster (USGS 3DEP GeoTIFF)
# ---------------------------------------------------------------------------


class ElevationTile(Base):
    __tablename__ = "elevation_tiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_new_uuid)

    # Bounding box in WGS84 decimal degrees for consistent spatial lookups,
    # even though the file itself is in UTM. Populated by reading the
    # downloaded file's extent and reprojecting corners to EPSG:4326.
    bbox_north: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_south: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_east: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_west: Mapped[float] = mapped_column(Float, nullable=False)

    # Native CRS of the file on disk (e.g. 32613 for UTM Zone 13N).
    # We choose this at download time for DEM; the weather service needs it
    # to reproject HRRR forcing grids to the same coordinate system.
    crs_epsg: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relative to settings.data_dir (e.g. "elevation/abc123.tif").
    # Resolution is not stored because it's fixed by the data source
    # (10m for USGS 3DEP) and WindNinja reads it from the file directly.
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)

    # Which upstream data source provided this tile.
    # Current values: "usgs_3dep". Future: "srtm", "gmted".
    source: Mapped[str] = mapped_column(String(30), nullable=False)

    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    forecasts: Mapped[list["Forecast"]] = relationship(back_populates="elevation_tile")


# ---------------------------------------------------------------------------
# LandCoverTile -- cached LANDFIRE LCP raster
# ---------------------------------------------------------------------------


class LandCoverTile(Base):
    __tablename__ = "land_cover_tiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_new_uuid)

    # Bounding box in WGS84, same convention as ElevationTile.
    # The LCP file itself is in LANDFIRE's native CRS (typically CONUS
    # Albers EPSG:5070), so these are reprojected from the file extent.
    bbox_north: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_south: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_east: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_west: Mapped[float] = mapped_column(Float, nullable=False)

    # Native CRS of the file on disk. We don't control this -- LANDFIRE
    # returns data in its own projection (~30m CONUS Albers).
    crs_epsg: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relative to settings.data_dir (e.g. "land_cover/abc123.lcp").
    # Resolution is not stored because it's fixed by LANDFIRE (~30m)
    # and WindNinja reads it from the file directly.
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)

    # Current value: "landfire". Kept as a column for consistency with
    # ElevationTile and to support future land cover sources.
    source: Mapped[str] = mapped_column(String(30), nullable=False)

    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    forecasts: Mapped[list["Forecast"]] = relationship(back_populates="land_cover_tile")


# ---------------------------------------------------------------------------
# Forecast -- a single WindNinja forecast job
# ---------------------------------------------------------------------------


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_new_uuid)

    # Nullable: set when forecast is initiated from a saved ForecastArea,
    # null for ephemeral "click and run" forecasts. SET NULL on area deletion
    # so forecasts survive when a user removes a saved location.
    forecast_area_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("forecast_areas.id", ondelete="SET NULL"), nullable=True
    )

    # Location parameters are always stored directly on the forecast so we
    # know where it was, regardless of whether a ForecastArea exists.
    center_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    center_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    size_km: Mapped[float] = mapped_column(Float, nullable=False)

    # Each forecast records the exact tiles it used so results are reproducible.
    # RESTRICT prevents deleting tiles that are referenced by forecasts.
    elevation_tile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("elevation_tiles.id", ondelete="RESTRICT"), nullable=False
    )
    land_cover_tile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("land_cover_tiles.id", ondelete="RESTRICT"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ForecastStatus.queued
    )
    weather_model: Mapped[str] = mapped_column(String(10), nullable=False)

    solver_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=SolverType.momentum
    )
    output_wind_height: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0
    )

    forecast_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_hours: Mapped[int] = mapped_column(Integer, nullable=False)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    forecast_area: Mapped["ForecastArea | None"] = relationship(back_populates="forecasts")
    elevation_tile: Mapped["ElevationTile"] = relationship(back_populates="forecasts")
    land_cover_tile: Mapped["LandCoverTile | None"] = relationship(back_populates="forecasts")
