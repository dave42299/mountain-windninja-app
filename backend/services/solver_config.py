"""WindNinja .cfg file generation for griddedInitialization.

Pure logic module -- generates config file contents from typed inputs and writes
them to disk.  No Docker, no database, no network.  The only I/O is writing
the final .cfg text file.

Config files use **container paths** (``/data/...``) because WindNinja runs
inside a Docker container with the host ``data/`` directory mounted at
``/data``.

Reference implementation:
    ``mountain_windninja/scripts/windninja_config.py`` --
    ``generate_gridded_config()``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from config import CONTAINER_DATA_ROOT
from models.enums import SolverType

logger = logging.getLogger(__name__)

_MOMENTUM_ITERATIONS = 300

# HRRR forcing grids are at 10 m AGL; WindNinja needs to know the input height
# to interpolate correctly.  Hardcoded for now because all supported weather
# models (HRRR, NBM) provide 10 m winds.
# TODO: Make configurable if we add models with different reference heights.
INPUT_WIND_HEIGHT_M = 10.0


class SolverConfigError(RuntimeError):
    """WindNinja config generation failed (bad paths, invalid parameters)."""


@dataclass(frozen=True)
class WindNinjaConfigSpec:
    """All inputs needed to generate one timestep's .cfg file."""

    container_elevation_path: str
    container_speed_grid_path: str
    container_direction_grid_path: str
    container_output_dir: str
    valid_time: datetime
    solver_type: SolverType
    output_wind_height: float
    mesh_resolution: float
    num_threads: int
    vegetation: str


def generate_windninja_config(
    spec: WindNinjaConfigSpec,
    *,
    host_output_dir: Path,
    config_filename: str | None = None,
) -> Path:
    """Write a single-timestep WindNinja .cfg for griddedInitialization.

    Args:
        spec: Typed config inputs (all paths are container paths).
        host_output_dir: Host filesystem directory to write the .cfg into.
        config_filename: Override the default filename (for testing).

    Returns:
        Absolute host path to the written .cfg file.

    Raises:
        SolverConfigError: Invalid spec values.
    """
    _validate_spec(spec)

    is_momentum = spec.solver_type == SolverType.momentum
    timestamp_label = spec.valid_time.strftime("%Y%m%d_%H%M")

    lines = [
        f"num_threads = {spec.num_threads}",
        f"elevation_file = {spec.container_elevation_path}",
        "",
        "initialization_method = griddedInitialization",
        f"input_speed_grid = {spec.container_speed_grid_path}",
        f"input_dir_grid = {spec.container_direction_grid_path}",
        "input_speed_units = mps",
        f"input_wind_height = {INPUT_WIND_HEIGHT_M}",
        "units_input_wind_height = m",
        "",
        f"vegetation = {spec.vegetation}",
        "",
        "diurnal_winds = false",
        "",
        f"year  = {spec.valid_time.year}",
        f"month = {spec.valid_time.month}",
        f"day   = {spec.valid_time.day}",
        f"hour  = {spec.valid_time.hour}",
        f"minute = {spec.valid_time.minute}",
        "time_zone = UTC",
        "",
        f"mesh_resolution = {spec.mesh_resolution}",
        "units_mesh_resolution = m",
        "",
        f"momentum_flag = {'true' if is_momentum else 'false'}",
    ]

    if is_momentum:
        lines.append(f"number_of_iterations = {_MOMENTUM_ITERATIONS}")

    lines += [
        "",
        f"output_wind_height = {spec.output_wind_height}",
        "units_output_wind_height = m",
        "output_speed_units = mph",
        "",
        "write_goog_output = false",
        "",
        "write_ascii_output = true",
        "ascii_out_resolution = -1",
        "units_ascii_out_resolution = m",
        "",
        "write_shapefile_output = false",
        "",
        f"output_path = {spec.container_output_dir}",
    ]

    filename = config_filename or f"windninja_{timestamp_label}.cfg"
    host_config_path = host_output_dir / filename
    host_config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    logger.debug("WindNinja config written: %s", host_config_path)
    return host_config_path


def _validate_spec(spec: WindNinjaConfigSpec) -> None:
    """Raise SolverConfigError for obviously invalid spec values."""
    if spec.num_threads < 1:
        raise SolverConfigError(
            f"num_threads must be >= 1, got {spec.num_threads}"
        )
    if spec.mesh_resolution <= 0:
        raise SolverConfigError(
            f"mesh_resolution must be positive, got {spec.mesh_resolution}"
        )
    if spec.output_wind_height <= 0:
        raise SolverConfigError(
            f"output_wind_height must be positive, got {spec.output_wind_height}"
        )
    if not spec.container_elevation_path:
        raise SolverConfigError("container_elevation_path is required")
    if not spec.container_speed_grid_path:
        raise SolverConfigError("container_speed_grid_path is required")
    if not spec.container_direction_grid_path:
        raise SolverConfigError("container_direction_grid_path is required")
