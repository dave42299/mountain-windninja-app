"""Pydantic request/response schemas for the API."""

from datetime import datetime

from pydantic import BaseModel, Field


class DomainCreate(BaseModel):
    """Request to create a new forecast domain."""

    latitude: float = Field(ge=-90, le=90, description="Center latitude")
    longitude: float = Field(ge=-180, le=180, description="Center longitude")
    size_km: float = Field(default=12, gt=0, le=50, description="Domain size in km")
    label: str = Field(max_length=100, description="Human-readable name for this domain")


class DomainResponse(BaseModel):
    """A registered forecast domain."""

    id: str
    latitude: float
    longitude: float
    size_km: float
    label: str
    has_dem: bool
    has_lcp: bool
    created_at: datetime


class RunCreate(BaseModel):
    """Request to start a new WindNinja forecast run."""

    domain_id: str
    forecast_start: datetime
    duration_hours: int = Field(gt=0, le=48)
    weather_model: str = Field(default="hrrr", pattern="^(hrrr|nbm)$")


class RunResponse(BaseModel):
    """Status and metadata for a forecast run."""

    id: str
    domain_id: str
    status: str
    forecast_start: datetime
    duration_hours: int
    weather_model: str
    created_at: datetime
    completed_at: datetime | None = None
    output_url: str | None = None
