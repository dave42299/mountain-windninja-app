"""Weather data retrieval service -- public API for the mountain-windninja-app backend.

This module is the sole entry point for weather operations. It owns:

- Time-range validation (heuristic checks, then S3 availability probes).
- HRRR cycle resolution for each hourly timestep.
- Orchestration of the GRIB download + grid conversion pipeline.
- Output directory creation and cleanup on failure.
- Metadata recording for reproducibility.

Source-specific download and conversion logic lives in sub-modules:

- :mod:`services.weather_models` -- HRRR cycle resolution, time validation
  heuristics, constants (pure datetime logic, no I/O).
- :mod:`services.weather_hrrr` -- Herbie-based GRIB2 download, rasterio
  extraction, U/V-to-speed/direction conversion, ASCII Grid writing.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config import settings
from models.enums import WeatherModel
from models.orm import ElevationTile

from .weather_hrrr import (
    DemGridSpec,
    WeatherDownloadError,
    check_hrrr_availability,
    process_timestep,
    read_dem_grid_spec,
)
from .weather_models import (
    HrrrCycle,
    WeatherTimeRangeError,
    resolve_hrrr_cycles,
    validate_hrrr_time_range,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ForcingTimestep",
    "ForecastWeatherGrids",
    "HrrrCycle",
    "WeatherDownloadError",
    "WeatherError",
    "WeatherTimeRangeError",
    "prepare_weather_for_forecast",
]


class WeatherError(RuntimeError):
    """Base error for weather service failures."""


@dataclass(frozen=True)
class ForcingTimestep:
    """One timestep's forcing grids after download + conversion."""

    valid_time: datetime
    speed_grid_path: Path
    direction_grid_path: Path
    cycle: HrrrCycle


@dataclass(frozen=True)
class ForecastWeatherGrids:
    """All forcing grids for a forecast, ready to be consumed by the solver."""

    timesteps: list[ForcingTimestep]
    weather_dir: Path


def prepare_weather_for_forecast(
    *,
    forecast_id: str,
    forecast_start: datetime,
    duration_hours: int,
    weather_model: WeatherModel | str,
    elevation_tile: ElevationTile,
    data_dir: Path | None = None,
    now: datetime | None = None,
) -> ForecastWeatherGrids:
    """Download and prepare forcing grids for a forecast.

    1. Validate the weather model is HRRR (NBM is not yet supported).
    2. Validate the time range with heuristic checks.
    3. Resolve which HRRR cycle + forecast hour covers each hourly timestep.
    4. Probe S3 to confirm all cycles are available.
    5. Download GRIB2 data and convert to speed/direction ASCII grids
       aligned to the DEM.
    6. Write metadata.json for reproducibility.

    Output goes to ``data/weather/{forecast_id}/``. On any failure the
    directory is removed so no partial state is left behind.

    Args:
        forecast_id: UUID string identifying the parent forecast.
        forecast_start: Timezone-aware start of the forecast window (UTC).
        duration_hours: Number of hourly timesteps.
        weather_model: Must be ``hrrr``; ``nbm`` raises ``WeatherError``.
        elevation_tile: DEM tile whose CRS and extent define the target grid.
        data_dir: Override for ``settings.data_dir`` (for testing).
        now: Override for current time (for testing).

    Returns:
        :class:`ForecastWeatherGrids` with per-timestep forcing paths.

    Raises:
        WeatherError: NBM requested (not yet supported).
        WeatherTimeRangeError: Time range outside HRRR coverage.
        WeatherDownloadError: S3 availability check or download/conversion
            failure.
    """
    model_str = weather_model.value if isinstance(weather_model, WeatherModel) else str(weather_model)
    if model_str != WeatherModel.hrrr.value:
        raise WeatherError(
            f"Weather model '{model_str}' is not yet supported. "
            f"Only HRRR is available in Phase 2."
        )

    validate_hrrr_time_range(forecast_start, duration_hours, now=now)

    cycles = resolve_hrrr_cycles(forecast_start, duration_hours, now=now)

    logger.info(
        "Checking HRRR availability: %d cycles for forecast_id=%s",
        len(cycles),
        forecast_id,
    )
    check_hrrr_availability(cycles)

    root = (data_dir if data_dir is not None else settings.data_dir).resolve()
    dem_absolute = root / elevation_tile.file_path
    dem_spec = read_dem_grid_spec(dem_absolute)

    relative_weather_dir = Path("weather") / forecast_id
    weather_dir = root / relative_weather_dir
    weather_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Preparing %d forcing timesteps: forecast_id=%s weather_dir=%s",
        len(cycles),
        forecast_id,
        weather_dir,
    )

    t_start = time.monotonic()
    timesteps: list[ForcingTimestep] = []

    try:
        for cycle in cycles:
            speed_path, direction_path = process_timestep(
                cycle, dem_spec, weather_dir,
            )
            timesteps.append(
                ForcingTimestep(
                    valid_time=cycle.valid_time,
                    speed_grid_path=Path(relative_weather_dir / speed_path.name),
                    direction_grid_path=Path(relative_weather_dir / direction_path.name),
                    cycle=cycle,
                )
            )

        _write_metadata(weather_dir, forecast_id, cycles, timesteps, elevation_tile)

    except Exception:
        logger.warning(
            "Weather preparation failed for forecast_id=%s; cleaning up %s",
            forecast_id,
            weather_dir,
        )
        shutil.rmtree(weather_dir, ignore_errors=True)
        raise

    elapsed = time.monotonic() - t_start
    logger.info(
        "Weather grids prepared: forecast_id=%s timesteps=%d elapsed=%.1fs",
        forecast_id,
        len(timesteps),
        elapsed,
    )

    return ForecastWeatherGrids(
        timesteps=timesteps,
        weather_dir=relative_weather_dir,
    )


def _write_metadata(
    weather_dir: Path,
    forecast_id: str,
    cycles: list[HrrrCycle],
    timesteps: list[ForcingTimestep],
    elevation_tile: ElevationTile,
) -> None:
    """Write metadata.json documenting the weather data provenance."""
    metadata = {
        "forecast_id": forecast_id,
        "weather_model": "hrrr",
        "source": "aws_s3_noaa_hrrr_bdp_pds",
        "elevation_tile_id": str(elevation_tile.id),
        "elevation_crs_epsg": elevation_tile.crs_epsg,
        "speed_units": "mps",
        "direction_convention": "meteorological_from_degrees",
        "nodata_value": -9999,
        "timesteps": [
            {
                "valid_time": ts.valid_time.isoformat(),
                "analysis_time": ts.cycle.analysis_time.isoformat(),
                "forecast_hour": ts.cycle.forecast_hour,
                "speed_grid": ts.speed_grid_path.name,
                "direction_grid": ts.direction_grid_path.name,
            }
            for ts in timesteps
        ],
    }
    metadata_path = weather_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    logger.debug("Metadata written: %s", metadata_path)
