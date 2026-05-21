"""Pydantic request/response schemas for the API."""

import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .enums import ForecastStatus, SolverType, WeatherModel


# ---------------------------------------------------------------------------
# ForecastArea schemas
# ---------------------------------------------------------------------------


class ForecastAreaCreate(BaseModel):
    """Request to save a forecast area."""

    center_latitude: float = Field(ge=-90, le=90, description="Center latitude")
    center_longitude: float = Field(ge=-180, le=180, description="Center longitude")
    size_km: float = Field(default=12, gt=0, le=50, description="Area size in km")
    label: str | None = Field(default=None, max_length=100)


class ForecastAreaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str | None
    center_latitude: float
    center_longitude: float
    size_km: float
    created_at: datetime


# ---------------------------------------------------------------------------
# Tile schemas (elevation + land cover)
# ---------------------------------------------------------------------------


class TileResponse(BaseModel):
    """Shared response shape for both elevation and land cover tiles."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bbox_north: float
    bbox_south: float
    bbox_east: float
    bbox_west: float
    crs_epsg: int
    source: str
    downloaded_at: datetime
    file_size_bytes: int | None = None


# ---------------------------------------------------------------------------
# Forecast schemas
# ---------------------------------------------------------------------------


class ForecastCreate(BaseModel):
    """Request to start a new WindNinja forecast.

    Either provide forecast_area_id to run from a saved area, or provide
    latitude/longitude/size_km directly for an ephemeral "click and run."
    """

    forecast_area_id: uuid.UUID | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    size_km: float | None = Field(default=None, gt=0, le=50)
    forecast_start: AwareDatetime
    duration_hours: int = Field(gt=0, le=48)
    weather_model: WeatherModel = WeatherModel.hrrr
    solver_type: SolverType = SolverType.momentum
    output_wind_height: float = Field(default=10.0, gt=0, le=100)

    @model_validator(mode="after")
    def check_location_source(self):
        has_forecast_area = self.forecast_area_id is not None
        has_coordinates = self.latitude is not None

        if has_forecast_area and has_coordinates:
            raise ValueError(
                "Provide forecast_area_id or latitude/longitude, not both"
            )
        if not has_forecast_area and not has_coordinates:
            raise ValueError(
                "Provide either forecast_area_id or latitude/longitude/size_km"
            )
        if has_coordinates and (self.longitude is None or self.size_km is None):
            raise ValueError(
                "latitude, longitude, and size_km are all required for ad-hoc forecasts"
            )
        return self


class ForecastResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    forecast_area_id: uuid.UUID | None = None
    center_latitude: float
    center_longitude: float
    size_km: float
    elevation_tile_id: uuid.UUID | None = None
    land_cover_tile_id: uuid.UUID | None = None
    status: ForecastStatus
    weather_model: WeatherModel
    solver_type: SolverType
    output_wind_height: float
    forecast_start: datetime
    duration_hours: int
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class PaginatedForecastResponse(BaseModel):
    items: list[ForecastResponse]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Forecast output schemas
# ---------------------------------------------------------------------------


class OutputFileInfo(BaseModel):
    filename: str
    size_bytes: int


class ForecastOutputResponse(BaseModel):
    forecast_id: uuid.UUID
    files: list[OutputFileInfo]


# ---------------------------------------------------------------------------
# Wind-field schemas
# ---------------------------------------------------------------------------


class WindFieldBounds(BaseModel):
    west: float
    south: float
    east: float
    north: float


class WindFieldResponse(BaseModel):
    forecast_id: uuid.UUID
    timestep_index: int
    timestep_count: int
    valid_time: datetime
    width: int
    height: int
    bounds: WindFieldBounds
    u: list[float]
    v: list[float]
    speed_min: float
    speed_max: float
