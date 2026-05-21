"""Forecast HTTP routes.

``POST /forecasts`` validates the location synchronously (CONUS geometry
check, no I/O), inserts a ``queued`` Forecast row, and launches a background
task that resolves terrain, fetches weather, and runs the WindNinja solver.

The background worker uses its own fresh session (from the injected session
factory) so status updates are committed independently of the request
session lifecycle.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from api.deps import get_db, get_session_factory, get_settings
from config import Settings
from models.enums import ForecastStatus
from models.orm import Forecast, ForecastArea
from models.schemas import (
    ForecastCreate,
    ForecastOutputResponse,
    ForecastResponse,
    OutputFileInfo,
    PaginatedForecastResponse,
    WindFieldResponse,
)
from services.terrain import (
    TerrainDemError,
    TerrainLcpError,
    TerrainOutsideUsError,
    ensure_tiles_for_forecast,
)
from services.terrain_geometry import (
    pad_bbox_fraction,
    square_bbox_wgs84,
    validate_conus_wgs84_bbox,
)
from services.solver import (
    SolverConfigError,
    SolverExecutionError,
    run_solver_for_forecast,
)
from services.wind_field import (
    WindFieldError,
    WindFieldTimestepError,
    load_wind_field,
)
from services.weather import (
    WeatherDownloadError,
    WeatherError,
    WeatherTimeRangeError,
    prepare_weather_for_forecast,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])

_MEDIA_TYPES: dict[str, str] = {
    ".asc": "text/plain",
    ".cfg": "text/plain",
    ".prj": "text/plain",
    ".json": "application/json",
    ".tif": "image/tiff",
    ".kmz": "application/vnd.google-earth.kmz",
}

_RETRY_AFTER_SECONDS: dict[ForecastStatus, int | None] = {
    ForecastStatus.queued: 5,
    ForecastStatus.fetching_terrain: 30,
    ForecastStatus.fetching_weather: 30,
    ForecastStatus.running_solver: 60,
    ForecastStatus.failed: None,
    ForecastStatus.cancelled: None,
}


def _get_forecast(forecast_id: uuid.UUID, db: Session) -> Forecast:
    """Look up a forecast by ID. Raises HTTP 404 if not found."""
    forecast = db.get(Forecast, forecast_id)
    if forecast is None:
        raise HTTPException(status_code=404, detail="Forecast not found")
    return forecast


def _require_completed_forecast(forecast: Forecast) -> None:
    """Raise HTTP 409 if the forecast has not reached ``completed`` status.

    The response body includes the current status and estimated retry time
    so the frontend can decide whether to keep polling or show an error.
    """
    if forecast.status != ForecastStatus.completed:
        retry_after = _RETRY_AFTER_SECONDS.get(forecast.status)
        detail: dict = {
            "message": "Forecast output is not available",
            "forecast_id": str(forecast.id),
            "status": forecast.status.value,
            "retry_after_seconds": retry_after,
        }
        raise HTTPException(status_code=409, detail=detail)


def _resolve_output_dir(forecast_id: uuid.UUID, settings: Settings) -> Path:
    """Derive and validate the output directory for a forecast.

    Raises HTTP 404 if the directory does not exist on disk (e.g. stale DB row).
    """
    output_dir = settings.data_dir / "output" / str(forecast_id)
    if not output_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail="Output directory not found on disk",
        )
    return output_dir


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=ForecastResponse, status_code=201)
def create_forecast(
    body: ForecastCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Forecast:
    """Submit a new wind forecast.

    Validates the location synchronously (fast geometry check, no I/O),
    then hands terrain resolution, weather fetching, and solver execution
    to a background task.  Returns 201 immediately with ``status=queued``.
    """
    center_latitude, center_longitude, size_km, forecast_area_id = (
        _resolve_location(body, db)
    )

    _validate_conus_location(center_latitude, center_longitude, size_km)

    forecast = Forecast(
        forecast_area_id=forecast_area_id,
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        size_km=size_km,
        status=ForecastStatus.queued,
        weather_model=body.weather_model,
        solver_type=body.solver_type,
        output_wind_height=body.output_wind_height,
        forecast_start=body.forecast_start,
        duration_hours=body.duration_hours,
    )
    db.add(forecast)
    db.commit()
    db.refresh(forecast)

    background_tasks.add_task(
        _run_forecast_pipeline,
        forecast_id=forecast.id,
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        size_km=size_km,
        settings=settings,
        session_factory=get_session_factory(),
    )

    return forecast


@router.get("/", response_model=PaginatedForecastResponse)
def list_forecasts(
    status: ForecastStatus | None = None,
    forecast_area_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedForecastResponse:
    base_statement = select(Forecast)
    if status is not None:
        base_statement = base_statement.where(Forecast.status == status)
    if forecast_area_id is not None:
        base_statement = base_statement.where(
            Forecast.forecast_area_id == forecast_area_id
        )

    total = db.scalar(
        select(func.count()).select_from(base_statement.subquery())
    ) or 0

    items = list(
        db.scalars(
            base_statement
            .order_by(Forecast.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )

    return PaginatedForecastResponse(
        items=items, total=total, limit=limit, offset=offset,
    )


@router.get("/{forecast_id}", response_model=ForecastResponse)
def get_forecast(
    forecast_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Forecast:
    return _get_forecast(forecast_id, db)


@router.get(
    "/{forecast_id}/output",
    response_model=ForecastOutputResponse,
)
def list_forecast_output(
    forecast_id: uuid.UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ForecastOutputResponse:
    """List output files for a completed forecast."""
    forecast = _get_forecast(forecast_id, db)
    _require_completed_forecast(forecast)
    output_dir = _resolve_output_dir(forecast_id, settings)

    files = [
        OutputFileInfo(filename=entry.name, size_bytes=entry.stat().st_size)
        for entry in sorted(output_dir.iterdir())
        if entry.is_file()
    ]
    return ForecastOutputResponse(forecast_id=forecast_id, files=files)


@router.get("/{forecast_id}/output/{filename:path}")
def download_forecast_output(
    forecast_id: uuid.UUID,
    filename: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Download a single output file from a completed forecast."""
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    forecast = _get_forecast(forecast_id, db)
    _require_completed_forecast(forecast)
    output_dir = _resolve_output_dir(forecast_id, settings)

    file_path = output_dir / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Output file not found")

    media_type = _MEDIA_TYPES.get(file_path.suffix, "application/octet-stream")
    return FileResponse(path=file_path, filename=filename, media_type=media_type)


@router.get(
    "/{forecast_id}/wind-field/{timestep_index}",
    response_model=WindFieldResponse,
)
def get_wind_field(
    forecast_id: uuid.UUID,
    timestep_index: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WindFieldResponse:
    """Return parsed wind-field data (U/V in m/s) for one timestep."""
    forecast = _get_forecast(forecast_id, db)
    _require_completed_forecast(forecast)
    output_dir = _resolve_output_dir(forecast_id, settings)

    try:
        wind_data = load_wind_field(output_dir, timestep_index)
    except WindFieldTimestepError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WindFieldError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return WindFieldResponse(
        forecast_id=forecast_id,
        timestep_index=wind_data.timestep_index,
        timestep_count=wind_data.timestep_count,
        valid_time=wind_data.valid_time,
        width=wind_data.width,
        height=wind_data.height,
        bounds=wind_data.bounds,
        u=wind_data.u,
        v=wind_data.v,
        speed_min=wind_data.speed_min,
        speed_max=wind_data.speed_max,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_location(
    body: ForecastCreate,
    db: Session,
) -> tuple[float, float, float, uuid.UUID | None]:
    """Extract (lat, lon, size_km, forecast_area_id) from the request.

    If ``forecast_area_id`` is provided, fetches the saved area's location.
    Otherwise uses the ad-hoc coordinates from the request body.
    """
    if body.forecast_area_id is not None:
        area = db.get(ForecastArea, body.forecast_area_id)
        if area is None:
            raise HTTPException(
                status_code=404, detail="Forecast area not found"
            )
        return (
            area.center_latitude,
            area.center_longitude,
            area.size_km,
            area.id,
        )

    if body.latitude is None or body.longitude is None or body.size_km is None:
        raise HTTPException(
            status_code=422,
            detail="latitude, longitude, and size_km are required for ad-hoc forecasts",
        )
    return body.latitude, body.longitude, body.size_km, None


def _validate_conus_location(
    center_latitude: float, center_longitude: float, size_km: float,
) -> None:
    """Pre-flight CONUS check (pure geometry, no I/O).

    Raises HTTP 422 if the padded forecast extent falls outside CONUS.
    """
    user_bbox = square_bbox_wgs84(center_latitude, center_longitude, size_km)
    padded_bbox = pad_bbox_fraction(user_bbox, fraction=0.25)
    try:
        validate_conus_wgs84_bbox(padded_bbox)
    except TerrainOutsideUsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _run_forecast_pipeline(
    forecast_id: uuid.UUID,
    *,
    center_latitude: float,
    center_longitude: float,
    size_km: float,
    settings: Settings,
    session_factory: sessionmaker,
) -> None:
    """Background task: resolve terrain, fetch weather, run solver.

    Uses an injected session factory so status updates are committed
    independently of the request lifecycle. Settings are captured at
    dispatch time rather than re-reading the global singleton.
    """
    session: Session = session_factory()
    try:
        forecast = session.get(Forecast, forecast_id)
        if forecast is None:
            logger.error("Background task: forecast %s not found", forecast_id)
            return

        # --- Terrain ---
        _update_status(session, forecast, ForecastStatus.fetching_terrain)

        try:
            tiles = ensure_tiles_for_forecast(
                session,
                center_latitude=center_latitude,
                center_longitude=center_longitude,
                size_km=size_km,
                data_dir=settings.data_dir,
                solver_image=settings.solver_image,
                lcp_subprocess_timeout_seconds=settings.terrain_lcp_subprocess_timeout_seconds,
            )
        except TerrainOutsideUsError as exc:
            _fail_forecast(session, forecast, str(exc))
            return
        except (TerrainDemError, TerrainLcpError) as exc:
            _fail_forecast(session, forecast, str(exc))
            return

        forecast.elevation_tile_id = tiles.elevation_tile.id
        forecast.land_cover_tile_id = tiles.land_cover_tile.id
        session.commit()

        # --- Weather ---
        _update_status(session, forecast, ForecastStatus.fetching_weather)

        try:
            weather_grids = prepare_weather_for_forecast(
                forecast_id=str(forecast_id),
                forecast_start=forecast.forecast_start,
                duration_hours=forecast.duration_hours,
                weather_model=forecast.weather_model,
                elevation_tile=tiles.elevation_tile,
                data_dir=settings.data_dir,
            )
        except (WeatherTimeRangeError, WeatherError) as exc:
            _fail_forecast(session, forecast, str(exc))
            return
        except WeatherDownloadError as exc:
            _fail_forecast(session, forecast, str(exc))
            return

        # --- Solver ---
        _update_status(session, forecast, ForecastStatus.running_solver)

        try:
            run_solver_for_forecast(
                forecast_id=str(forecast_id),
                weather_grids=weather_grids,
                elevation_tile=tiles.elevation_tile,
                solver_type=forecast.solver_type,
                output_wind_height=forecast.output_wind_height,
                data_dir=settings.data_dir,
                solver_image=settings.solver_image,
                solver_threads=settings.solver_threads,
                solver_timeout_seconds=settings.solver_timeout_seconds,
                solver_max_retries=settings.solver_max_retries,
                solver_mesh_resolution=settings.solver_mesh_resolution,
                solver_vegetation=settings.solver_vegetation,
            )
        except (SolverConfigError, SolverExecutionError) as exc:
            _fail_forecast(session, forecast, str(exc))
            return

        _update_status(session, forecast, ForecastStatus.completed)

    except Exception as exc:
        logger.exception("Unhandled error in forecast pipeline: %s", forecast_id)
        try:
            forecast = session.get(Forecast, forecast_id)
            if forecast is not None:
                _fail_forecast(session, forecast, f"Internal error: {exc}")
        except Exception:
            logger.exception("Failed to record error for forecast %s", forecast_id)
    finally:
        session.close()


def _update_status(
    session: Session,
    forecast: Forecast,
    status: ForecastStatus,
) -> None:
    forecast.status = status
    if status == ForecastStatus.fetching_terrain and forecast.started_at is None:
        forecast.started_at = datetime.now(timezone.utc)
    if status == ForecastStatus.completed:
        forecast.completed_at = datetime.now(timezone.utc)
    session.commit()
    logger.info("Forecast %s -> %s", forecast.id, status.value)


def _fail_forecast(
    session: Session,
    forecast: Forecast,
    error_message: str,
) -> None:
    forecast.status = ForecastStatus.failed
    forecast.error_message = error_message
    forecast.completed_at = datetime.now(timezone.utc)
    session.commit()
    logger.warning("Forecast %s failed: %s", forecast.id, error_message)
