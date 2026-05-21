"""Wind-field data service -- parse WindNinja ASCII output for visualization.

Reads WindNinja's ESRI ASCII grid output (speed in mph + direction in
meteorological degrees), converts to U/V components in m/s, and computes
WGS84 bounding boxes from the UTM grid corners. This is the data pipeline
between the solver's on-disk output and the frontend's cesium-wind-layer.

Speed unit pipeline:
    HRRR (m/s) → WindNinja input (m/s) → WindNinja output (mph) → this service (m/s)
    → frontend cesium-wind-layer (m/s) → legend display (mph)
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pyproj import Transformer

logger = logging.getLogger(__name__)

MPH_TO_MPS = 0.44704

_PASTCAST_PREFIX = re.compile(r"^PASTCAST-", re.IGNORECASE)


class WindFieldError(Exception):
    """Base exception for wind-field parsing errors."""


class WindFieldMetadataError(WindFieldError):
    """metadata.json is missing or malformed."""


class WindFieldGridError(WindFieldError):
    """ASCII grid file is missing, corrupt, or unparseable."""


class WindFieldTimestepError(WindFieldError):
    """Requested timestep index is out of range."""


@dataclass(frozen=True)
class WindFieldBounds:
    """WGS84 bounding box (decimal degrees)."""

    west: float
    south: float
    east: float
    north: float


@dataclass(frozen=True)
class WindFieldData:
    """Parsed and converted wind-field data for one timestep."""

    u: list[float]
    v: list[float]
    width: int
    height: int
    bounds: WindFieldBounds
    valid_time: datetime
    speed_min: float
    speed_max: float
    timestep_index: int
    timestep_count: int


@dataclass(frozen=True)
class _AsciiGridHeader:
    """Parsed header from an ESRI ASCII grid file."""

    ncols: int
    nrows: int
    xllcorner: float
    yllcorner: float
    cellsize: float
    nodata_value: float


def load_wind_field(
    output_dir: Path,
    timestep_index: int,
) -> WindFieldData:
    """Load and convert one timestep of WindNinja output.

    Args:
        output_dir: Path to the forecast output directory (contains
            metadata.json and WindNinja ASCII grids).
        timestep_index: Zero-based index into the sorted output timesteps.

    Returns:
        WindFieldData with U/V arrays in m/s and WGS84 bounds.

    Raises:
        WindFieldMetadataError: metadata.json missing or malformed.
        WindFieldGridError: ASCII grid files missing or corrupt.
        WindFieldTimestepError: timestep_index out of range.
    """
    metadata = _read_metadata(output_dir)
    crs_epsg: int = metadata["elevation_crs_epsg"]
    timestep_count: int = metadata["timestep_count"]
    valid_times = [
        datetime.fromisoformat(ts["valid_time"])
        for ts in metadata["timesteps"]
    ]

    vel_files = _discover_output_grids(output_dir)

    if not vel_files:
        raise WindFieldGridError(
            f"No WindNinja velocity output (*_vel.asc) found in {output_dir}"
        )

    if timestep_index < 0 or timestep_index >= len(vel_files):
        raise WindFieldTimestepError(
            f"Timestep index {timestep_index} out of range "
            f"(0..{len(vel_files) - 1})"
        )

    vel_path = vel_files[timestep_index]
    ang_path = Path(str(vel_path).replace("_vel.asc", "_ang.asc"))

    if not ang_path.is_file():
        raise WindFieldGridError(
            f"Direction grid not found: {ang_path.name} "
            f"(expected alongside {vel_path.name})"
        )

    valid_time = valid_times[timestep_index] if timestep_index < len(valid_times) else valid_times[-1]

    speed_header, speed_data = _parse_ascii_grid(vel_path)
    _, direction_data = _parse_ascii_grid(ang_path)

    u, v, speed_min, speed_max = _convert_speed_direction_to_uv(
        speed_data, direction_data, speed_header.nodata_value,
    )

    bounds = _compute_wgs84_bounds(speed_header, crs_epsg)

    return WindFieldData(
        u=u,
        v=v,
        width=speed_header.ncols,
        height=speed_header.nrows,
        bounds=bounds,
        valid_time=valid_time,
        speed_min=speed_min,
        speed_max=speed_max,
        timestep_index=timestep_index,
        timestep_count=timestep_count,
    )


def _read_metadata(output_dir: Path) -> dict:
    """Read and validate metadata.json from the output directory."""
    metadata_path = output_dir / "metadata.json"
    if not metadata_path.is_file():
        raise WindFieldMetadataError(
            f"metadata.json not found in {output_dir}"
        )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WindFieldMetadataError(
            f"Failed to parse metadata.json: {exc}"
        ) from exc

    for required_key in ("elevation_crs_epsg", "timestep_count", "timesteps"):
        if required_key not in metadata:
            raise WindFieldMetadataError(
                f"metadata.json missing required key: {required_key}"
            )
    return metadata


def _discover_output_grids(output_dir: Path) -> list[Path]:
    """Find WindNinja velocity output grids, excluding parent-model rasters.

    Returns velocity grid paths sorted by filename (which sorts
    chronologically because WindNinja embeds timestamps in filenames).
    """
    vel_files = sorted(
        p for p in output_dir.glob("*_vel.asc")
        if not _PASTCAST_PREFIX.match(p.name)
    )
    return vel_files


def _parse_ascii_grid(path: Path) -> tuple[_AsciiGridHeader, list[float]]:
    """Parse an ESRI ASCII grid file into header + flat row-major data.

    The ESRI ASCII format has a 6-line header followed by space-separated
    numeric rows (first row = northernmost).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WindFieldGridError(f"Cannot read grid file {path}: {exc}") from exc

    lines = text.strip().split("\n")
    if len(lines) < 7:
        raise WindFieldGridError(
            f"Grid file {path.name} has only {len(lines)} lines "
            f"(expected at least 7: 6-line header + data)"
        )

    header_values: dict[str, str] = {}
    for i in range(6):
        parts = lines[i].split()
        if len(parts) < 2:
            raise WindFieldGridError(
                f"Grid file {path.name}: malformed header line {i + 1}: {lines[i]!r}"
            )
        header_values[parts[0].lower()] = parts[1]

    try:
        header = _AsciiGridHeader(
            ncols=int(header_values["ncols"]),
            nrows=int(header_values["nrows"]),
            xllcorner=float(header_values["xllcorner"]),
            yllcorner=float(header_values["yllcorner"]),
            cellsize=float(header_values["cellsize"]),
            nodata_value=float(header_values.get("nodata_value", "-9999")),
        )
    except (KeyError, ValueError) as exc:
        raise WindFieldGridError(
            f"Grid file {path.name}: invalid header: {exc}"
        ) from exc

    data: list[float] = []
    for row_idx, line in enumerate(lines[6:]):
        row_values = line.split()
        if len(row_values) != header.ncols:
            raise WindFieldGridError(
                f"Grid file {path.name}: row {row_idx} has {len(row_values)} "
                f"values, expected {header.ncols}"
            )
        data.extend(float(v) for v in row_values)

    expected_count = header.ncols * header.nrows
    if len(data) != expected_count:
        raise WindFieldGridError(
            f"Grid file {path.name}: expected {expected_count} data values "
            f"({header.nrows} rows x {header.ncols} cols), got {len(data)}"
        )

    return header, data


def _convert_speed_direction_to_uv(
    speed_mph: list[float],
    direction_deg: list[float],
    nodata_value: float,
) -> tuple[list[float], list[float], float, float]:
    """Convert speed (mph) + meteorological direction (degrees) to U/V (m/s).

    Meteorological "from" convention:
        u = -speed * sin(direction)
        v = -speed * cos(direction)

    Returns (u, v, speed_min_mps, speed_max_mps).
    """
    u: list[float] = []
    v: list[float] = []
    speed_min = float("inf")
    speed_max = float("-inf")

    for spd_mph, dir_deg in zip(speed_mph, direction_deg):
        if spd_mph == nodata_value or dir_deg == nodata_value:
            u.append(0.0)
            v.append(0.0)
            continue

        speed_mps = spd_mph * MPH_TO_MPS
        direction_rad = math.radians(dir_deg)

        u.append(-speed_mps * math.sin(direction_rad))
        v.append(-speed_mps * math.cos(direction_rad))

        if speed_mps < speed_min:
            speed_min = speed_mps
        if speed_mps > speed_max:
            speed_max = speed_mps

    if speed_min == float("inf"):
        speed_min = 0.0
        speed_max = 0.0

    return u, v, speed_min, speed_max


def _compute_wgs84_bounds(
    header: _AsciiGridHeader,
    crs_epsg: int,
) -> WindFieldBounds:
    """Compute WGS84 bounding box from UTM grid corners.

    The ASCII grid header gives xllcorner/yllcorner (SW corner in UTM).
    We compute the NE corner and transform both to EPSG:4326.
    """
    transformer = Transformer.from_crs(
        f"EPSG:{crs_epsg}", "EPSG:4326", always_xy=True,
    )

    x_min = header.xllcorner
    y_min = header.yllcorner
    x_max = header.xllcorner + header.ncols * header.cellsize
    y_max = header.yllcorner + header.nrows * header.cellsize

    lon_min, lat_min = transformer.transform(x_min, y_min)
    lon_max, lat_max = transformer.transform(x_max, y_max)

    return WindFieldBounds(
        west=min(lon_min, lon_max),
        south=min(lat_min, lat_max),
        east=max(lon_min, lon_max),
        north=max(lat_min, lat_max),
    )
