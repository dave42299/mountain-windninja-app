"""WindNinja solver execution service -- public API for the mountain-windninja-app backend.

This module is the sole entry point for solver operations.  It owns:

- Output directory creation and cleanup on failure.
- Per-timestep config generation and solver invocation with retry.
- Mesh cache cleanup between retries and on final failure.
- Metadata recording for reproducibility.

Source-specific logic lives in sub-modules:

- :mod:`services.solver_config` -- WindNinja ``.cfg`` file generation
  (pure logic, no Docker).
- :mod:`services.solver_runner` -- Docker subprocess execution and
  mesh cache cleanup.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from config import CONTAINER_DATA_ROOT, settings
from models.enums import SolverType
from models.orm import ElevationTile
from services.weather import ForecastWeatherGrids

from .solver_config import (
    SolverConfigError,
    WindNinjaConfigSpec,
    generate_windninja_config,
)
from .solver_runner import (
    SolverExecutionError,
    cleanup_mesh_cache,
    execute_windninja,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SolverConfigError",
    "SolverExecutionError",
    "SolverResult",
    "SolverTimestepOutput",
    "run_solver_for_forecast",
]


@dataclass(frozen=True)
class SolverTimestepOutput:
    """Output metadata for one solved timestep."""

    valid_time: datetime
    config_path: Path


@dataclass(frozen=True)
class SolverResult:
    """Complete solver output for a forecast."""

    output_dir: Path
    timestep_outputs: list[SolverTimestepOutput]
    elapsed_seconds: float


def run_solver_for_forecast(
    *,
    forecast_id: str,
    weather_grids: ForecastWeatherGrids,
    elevation_tile: ElevationTile,
    solver_type: SolverType | str,
    output_wind_height: float = 10.0,
    data_dir: Path | None = None,
    solver_image: str | None = None,
    solver_threads: int | None = None,
    solver_timeout_seconds: int | None = None,
    solver_max_retries: int | None = None,
    solver_mesh_resolution: float | None = None,
    solver_vegetation: str | None = None,
) -> SolverResult:
    """Run WindNinja for each timestep in a forecast's weather grids.

    For each hourly timestep:
      1. Generate a WindNinja ``.cfg`` (griddedInitialization).
      2. Execute ``WindNinja_cli`` in Docker.
      3. On failure: clean mesh cache and retry (up to ``max_retries``).

    On any unrecoverable failure the output directory is removed so no
    partial state is left behind.  The mesh cache is also cleaned to
    prevent corruption from blocking future runs (AGENTS.md gotcha #1).

    Args:
        forecast_id: UUID string identifying the parent forecast.
        weather_grids: Per-timestep forcing grids from the weather service.
        elevation_tile: DEM tile (UTM GeoTIFF) used as WindNinja elevation.
        solver_type: ``momentum`` or ``mass_conservation``.
        output_wind_height: Output wind height in meters above ground.
        data_dir: Override for ``settings.data_dir`` (for testing).
        solver_image: Override for ``settings.solver_image`` (for testing).
        solver_threads: Override for ``settings.solver_threads`` (for testing).
        solver_timeout_seconds: Per-timestep Docker timeout override.
        solver_max_retries: Retry count override.
        solver_mesh_resolution: Mesh resolution override (meters).
        solver_vegetation: Vegetation parameter override.

    Returns:
        :class:`SolverResult` with output directory and per-timestep metadata.

    Raises:
        SolverConfigError: Config generation failure.
        SolverExecutionError: Docker / WindNinja failure after retries exhausted.
    """
    root = (data_dir if data_dir is not None else settings.data_dir).resolve()
    image = solver_image if solver_image is not None else settings.solver_image
    threads = solver_threads if solver_threads is not None else settings.solver_threads
    timeout = solver_timeout_seconds if solver_timeout_seconds is not None else settings.solver_timeout_seconds
    max_retries = solver_max_retries if solver_max_retries is not None else settings.solver_max_retries
    mesh_resolution = solver_mesh_resolution if solver_mesh_resolution is not None else settings.solver_mesh_resolution
    vegetation = solver_vegetation if solver_vegetation is not None else settings.solver_vegetation

    solver_type_enum = (
        solver_type if isinstance(solver_type, SolverType)
        else SolverType(str(solver_type))
    )

    relative_output_dir = Path("output") / forecast_id
    host_output_dir = root / relative_output_dir
    host_output_dir.mkdir(parents=True, exist_ok=True)

    container_elevation = (
        PurePosixPath(CONTAINER_DATA_ROOT) / elevation_tile.file_path
    ).as_posix()
    container_output = (
        PurePosixPath(CONTAINER_DATA_ROOT) / relative_output_dir.as_posix()
    ).as_posix()

    elevation_stem = Path(elevation_tile.file_path).stem
    host_elevation_path = root / elevation_tile.file_path
    host_elevation_dir = host_elevation_path.parent

    if not host_elevation_path.is_file():
        raise SolverConfigError(
            f"Elevation file not found on disk: {host_elevation_path}. "
            f"The tile record exists in the database but the file is missing."
        )

    logger.info(
        "Starting solver: forecast_id=%s timesteps=%d solver_type=%s "
        "image=%s threads=%d timeout=%ds retries=%d",
        forecast_id,
        len(weather_grids.timesteps),
        solver_type_enum.value,
        image,
        threads,
        timeout,
        max_retries,
    )

    t_start = time.monotonic()
    timestep_outputs: list[SolverTimestepOutput] = []

    try:
        for i, timestep in enumerate(weather_grids.timesteps):
            logger.info(
                "Solving timestep %d/%d: valid_time=%s forecast_id=%s",
                i + 1,
                len(weather_grids.timesteps),
                timestep.valid_time.isoformat(),
                forecast_id,
            )

            container_speed = (
                PurePosixPath(CONTAINER_DATA_ROOT)
                / timestep.speed_grid_path.as_posix()
            ).as_posix()
            container_direction = (
                PurePosixPath(CONTAINER_DATA_ROOT)
                / timestep.direction_grid_path.as_posix()
            ).as_posix()

            spec = WindNinjaConfigSpec(
                container_elevation_path=container_elevation,
                container_speed_grid_path=container_speed,
                container_direction_grid_path=container_direction,
                container_output_dir=container_output,
                valid_time=timestep.valid_time,
                solver_type=solver_type_enum,
                output_wind_height=output_wind_height,
                mesh_resolution=mesh_resolution,
                num_threads=threads,
                vegetation=vegetation,
            )

            host_config_path = generate_windninja_config(
                spec, host_output_dir=host_output_dir,
            )

            container_config = (
                PurePosixPath(CONTAINER_DATA_ROOT)
                / relative_output_dir.as_posix()
                / host_config_path.name
            ).as_posix()

            _execute_with_retry(
                container_config_path=container_config,
                solver_image=image,
                host_data_dir=root,
                timeout_seconds=timeout,
                max_retries=max_retries,
                host_elevation_dir=host_elevation_dir,
                elevation_stem=elevation_stem,
            )

            timestep_outputs.append(
                SolverTimestepOutput(
                    valid_time=timestep.valid_time,
                    config_path=Path(
                        relative_output_dir / host_config_path.name
                    ),
                )
            )

    except Exception:
        logger.warning(
            "Solver failed for forecast_id=%s; cleaning up %s and mesh cache",
            forecast_id,
            host_output_dir,
        )
        shutil.rmtree(host_output_dir, ignore_errors=True)
        cleanup_mesh_cache(host_elevation_dir, elevation_stem)
        raise

    try:
        _write_metadata(
            host_output_dir,
            forecast_id,
            weather_grids,
            elevation_tile,
            solver_type_enum,
            output_wind_height,
            mesh_resolution,
            vegetation,
        )
    except Exception:
        logger.warning(
            "Failed to write metadata for forecast_id=%s; solver output preserved",
            forecast_id,
        )

    elapsed = time.monotonic() - t_start
    logger.info(
        "Solver completed: forecast_id=%s timesteps=%d elapsed=%.1fs",
        forecast_id,
        len(timestep_outputs),
        elapsed,
    )

    return SolverResult(
        output_dir=relative_output_dir,
        timestep_outputs=timestep_outputs,
        elapsed_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _execute_with_retry(
    *,
    container_config_path: str,
    solver_image: str,
    host_data_dir: Path,
    timeout_seconds: int,
    max_retries: int,
    host_elevation_dir: Path,
    elevation_stem: str,
) -> None:
    """Execute WindNinja with retry on failure, cleaning mesh cache between attempts."""
    last_error: SolverExecutionError | None = None

    for attempt in range(max_retries + 1):
        try:
            execute_windninja(
                container_config_path=container_config_path,
                solver_image=solver_image,
                host_data_dir=host_data_dir,
                timeout_seconds=timeout_seconds,
            )
            return
        except SolverExecutionError as exc:
            last_error = exc
            if attempt < max_retries:
                logger.warning(
                    "Solver attempt %d/%d failed: %s. "
                    "Cleaning mesh cache and retrying.",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                cleanup_mesh_cache(host_elevation_dir, elevation_stem)
            else:
                logger.error(
                    "Solver failed after %d attempt(s): %s",
                    max_retries + 1,
                    exc,
                )

    assert last_error is not None
    raise last_error


def _write_metadata(
    host_output_dir: Path,
    forecast_id: str,
    weather_grids: ForecastWeatherGrids,
    elevation_tile: ElevationTile,
    solver_type: SolverType,
    output_wind_height: float,
    mesh_resolution: float,
    vegetation: str,
) -> None:
    """Write solver metadata.json for reproducibility."""
    metadata = {
        "forecast_id": forecast_id,
        "solver_type": solver_type.value,
        "initialization_method": "griddedInitialization",
        "elevation_tile_id": str(elevation_tile.id),
        "elevation_file": elevation_tile.file_path,
        "elevation_crs_epsg": elevation_tile.crs_epsg,
        "output_wind_height_m": output_wind_height,
        "output_speed_units": "mph",
        "mesh_resolution_m": mesh_resolution,
        "vegetation": vegetation,
        "timestep_count": len(weather_grids.timesteps),
        "timesteps": [
            {
                "valid_time": ts.valid_time.isoformat(),
                "speed_grid": ts.speed_grid_path.name,
                "direction_grid": ts.direction_grid_path.name,
            }
            for ts in weather_grids.timesteps
        ],
    }
    metadata_path = host_output_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    logger.debug("Solver metadata written: %s", metadata_path)
