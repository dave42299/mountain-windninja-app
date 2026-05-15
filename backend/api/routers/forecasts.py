"""Forecast HTTP routes.

``POST /forecasts`` resolves terrain, inserts the Forecast row, then launches
a background task that fetches weather and (eventually) runs the solver.

**Transaction boundary contract:** ``ensure_tiles_for_forecast`` owns its own
commits internally (one per terrain layer). The endpoint inserts and commits
the Forecast row separately. This ensures that already-committed tiles survive
if the Forecast insert fails.

The background worker uses its own fresh session (from the session factory)
so status updates are independent of the request session lifecycle.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db, get_session_factory, get_settings
from config import Settings
from models.enums import ForecastStatus
from models.orm import Forecast, ForecastArea
from models.schemas import ForecastCreate, ForecastResponse
from services.terrain import (
    TerrainDemError,
    TerrainLcpError,
    TerrainOutsideUsError,
    ensure_tiles_for_forecast,
)
from services.weather import (
    WeatherDownloadError,
    WeatherError,
    WeatherTimeRangeError,
    prepare_weather_for_forecast,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


@router.post("/", response_model=ForecastResponse, status_code=201)
def create_forecast(
    body: ForecastCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Forecast:
    """Submit a new wind forecast.

    Resolves terrain synchronously (tiles may be cached), inserts the
    Forecast row, then hands off weather fetching + solver execution to
    a background task.
    """
    center_latitude, center_longitude, size_km, forecast_area_id = (
        _resolve_location(body, db)
    )

    try:
        tiles = ensure_tiles_for_forecast(
            db,
            center_latitude=center_latitude,
            center_longitude=center_longitude,
            size_km=size_km,
        )
    except TerrainOutsideUsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (TerrainDemError, TerrainLcpError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    forecast = Forecast(
        forecast_area_id=forecast_area_id,
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        size_km=size_km,
        elevation_tile_id=tiles.elevation_tile.id,
        land_cover_tile_id=tiles.land_cover_tile.id,
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
    )

    return forecast


@router.get("/", response_model=list[ForecastResponse])
def list_forecasts(
    status: ForecastStatus | None = None,
    forecast_area_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> list[Forecast]:
    statement = select(Forecast)
    if status is not None:
        statement = statement.where(Forecast.status == status)
    if forecast_area_id is not None:
        statement = statement.where(Forecast.forecast_area_id == forecast_area_id)
    statement = statement.order_by(Forecast.created_at.desc())
    return list(db.scalars(statement).all())


@router.get("/{forecast_id}", response_model=ForecastResponse)
def get_forecast(
    forecast_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Forecast:
    forecast = db.get(Forecast, forecast_id)
    if forecast is None:
        raise HTTPException(status_code=404, detail="Forecast not found")
    return forecast


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

    assert body.latitude is not None
    assert body.longitude is not None
    assert body.size_km is not None
    return body.latitude, body.longitude, body.size_km, None


def _run_forecast_pipeline(forecast_id: uuid.UUID) -> None:
    """Background task: fetch weather, then run solver (Phase 2 stub).

    Uses its own DB session so status updates are committed independently
    of the request lifecycle.
    """
    session = get_session_factory()()
    try:
        forecast = session.get(Forecast, forecast_id)
        if forecast is None:
            logger.error("Background task: forecast %s not found", forecast_id)
            return

        _update_status(session, forecast, ForecastStatus.fetching_weather)

        try:
            weather_grids = prepare_weather_for_forecast(
                forecast_id=str(forecast_id),
                forecast_start=forecast.forecast_start,
                duration_hours=forecast.duration_hours,
                weather_model=forecast.weather_model,
                elevation_tile=forecast.elevation_tile,
            )
        except (WeatherTimeRangeError, WeatherError) as exc:
            _fail_forecast(session, forecast, str(exc))
            return
        except WeatherDownloadError as exc:
            _fail_forecast(session, forecast, str(exc))
            return

        _update_status(session, forecast, ForecastStatus.running_solver)

        # TODO(Phase 2 Step 5): Call solver service with weather_grids.
        # For now, mark as completed to close the weather pipeline loop.
        logger.info(
            "Weather grids ready for forecast %s (%d timesteps). "
            "Solver execution not yet implemented.",
            forecast_id,
            len(weather_grids.timesteps),
        )
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
    if status == ForecastStatus.fetching_weather and forecast.started_at is None:
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
