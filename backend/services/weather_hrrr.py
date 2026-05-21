"""HRRR GRIB2 download and forcing grid conversion for Phase 2.

Downloads HRRR forecast/analysis GRIB2 data from AWS S3 via the Herbie
library, extracts 10 m U/V wind components, reprojects to match the DEM's
CRS and extent (+1 pixel padding on each side), converts to speed/direction,
and writes ESRI ASCII Grid files with ``.prj`` sidecars suitable for
WindNinja ``griddedInitialization``.

Cache management, file path generation, and orchestration are handled by
the weather orchestrator in :mod:`services.weather`.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.enums import Resampling
from rasterio.transform import Affine, from_bounds
from rasterio.warp import reproject

from .weather_models import HrrrCycle

logger = logging.getLogger(__name__)


def _naive_utc(dt: datetime) -> datetime:
    """Strip tzinfo for Herbie which cannot compare tz-aware timestamps."""
    return dt.replace(tzinfo=None)

FORCING_NODATA = -9999.0

_HRRR_SEARCH_STRING = ":(?:UGRD|VGRD):10 m above ground:"


class WeatherDownloadError(RuntimeError):
    """HRRR download, GRIB extraction, or grid conversion failed."""


@dataclass(frozen=True, slots=True)
class DemGridSpec:
    """Spatial parameters of a DEM needed to align forcing grids."""

    width: int
    height: int
    transform: Affine
    crs: rasterio.crs.CRS
    bounds: rasterio.coords.BoundingBox


def read_dem_grid_spec(dem_path: Path) -> DemGridSpec:
    """Read spatial metadata from a DEM raster file.

    Raises:
        WeatherDownloadError: If the file cannot be opened or lacks CRS.
    """
    try:
        with rasterio.open(dem_path) as dataset:
            if dataset.crs is None:
                raise WeatherDownloadError(f"DEM has no CRS metadata: {dem_path}")
            return DemGridSpec(
                width=dataset.width,
                height=dataset.height,
                transform=dataset.transform,
                crs=dataset.crs,
                bounds=dataset.bounds,
            )
    except rasterio.errors.RasterioIOError as exc:
        raise WeatherDownloadError(f"Cannot open DEM: {dem_path}") from exc


def padded_grid_spec(spec: DemGridSpec) -> tuple[Affine, int, int, tuple[float, float, float, float]]:
    """Compute the DEM extent padded by one pixel on each side.

    WindNinja's griddedInitialization requires forcing grids to be
    ``DEM size + 2`` pixels in each dimension, with extent expanded by
    one DEM pixel width/height on each side.

    Returns:
        (transform, width, height, (left, bottom, right, top)) for the
        padded grid.
    """
    pixel_width = abs(spec.transform.a)
    pixel_height = abs(spec.transform.e)

    padded_left = spec.bounds.left - pixel_width
    padded_bottom = spec.bounds.bottom - pixel_height
    padded_right = spec.bounds.right + pixel_width
    padded_top = spec.bounds.top + pixel_height

    padded_width = spec.width + 2
    padded_height = spec.height + 2

    padded_transform = from_bounds(
        padded_left, padded_bottom, padded_right, padded_top,
        padded_width, padded_height,
    )

    return (
        padded_transform,
        padded_width,
        padded_height,
        (padded_left, padded_bottom, padded_right, padded_top),
    )


# ---------------------------------------------------------------------------
# Herbie interaction
# ---------------------------------------------------------------------------


def check_hrrr_availability(cycles: list[HrrrCycle]) -> None:
    """Verify that HRRR GRIB2 data exists on S3 for every requested cycle.

    Uses Herbie's inventory (reads the ``.idx`` sidecar file via HTTP HEAD)
    to confirm each cycle+forecast-hour combination is available without
    downloading the full GRIB.

    Raises:
        WeatherDownloadError: If any cycle is unavailable.
    """
    from herbie import Herbie

    for cycle in cycles:
        try:
            herbie_instance = Herbie(
                _naive_utc(cycle.analysis_time),
                model="hrrr",
                product="sfc",
                fxx=cycle.forecast_hour,
                verbose=False,
            )
            inventory = herbie_instance.inventory(searchString=_HRRR_SEARCH_STRING)
            if inventory.empty:
                raise WeatherDownloadError(
                    f"HRRR GRIB2 index has no UGRD/VGRD 10m entries for "
                    f"cycle={cycle.analysis_time.isoformat()} fxx={cycle.forecast_hour}"
                )
        except WeatherDownloadError:
            raise
        except Exception as exc:
            raise WeatherDownloadError(
                f"Cannot verify HRRR availability for "
                f"cycle={cycle.analysis_time.isoformat()} fxx={cycle.forecast_hour}: {exc}"
            ) from exc

    logger.info("HRRR availability confirmed for %d cycles", len(cycles))


def download_hrrr_grib(cycle: HrrrCycle) -> Path:
    """Download UGRD+VGRD 10 m above ground from HRRR via Herbie.

    Herbie manages its own file cache (``~/data/hrrr/...``), so repeated
    calls for the same cycle return the cached file without re-downloading.

    Returns:
        Path to the downloaded (or cached) GRIB2 file.

    Raises:
        WeatherDownloadError: Download failed.
    """
    from herbie import Herbie

    logger.info(
        "Downloading HRRR GRIB: cycle=%s fxx=%d",
        cycle.analysis_time.isoformat(),
        cycle.forecast_hour,
    )

    try:
        herbie_instance = Herbie(
            _naive_utc(cycle.analysis_time),
            model="hrrr",
            product="sfc",
            fxx=cycle.forecast_hour,
            verbose=False,
        )
        grib_path = herbie_instance.download(searchString=_HRRR_SEARCH_STRING)
    except Exception as exc:
        raise WeatherDownloadError(
            f"Failed to download HRRR GRIB for "
            f"cycle={cycle.analysis_time.isoformat()} fxx={cycle.forecast_hour}: {exc}"
        ) from exc

    if grib_path is None:
        raise WeatherDownloadError(
            f"Herbie returned no file for "
            f"cycle={cycle.analysis_time.isoformat()} fxx={cycle.forecast_hour}"
        )

    result_path = Path(grib_path)
    logger.info("HRRR GRIB downloaded: %s", result_path)
    return result_path


# ---------------------------------------------------------------------------
# GRIB extraction and reprojection
# ---------------------------------------------------------------------------


def _identify_uv_bands(grib_path: Path) -> tuple[int, int]:
    """Identify which rasterio bands contain UGRD and VGRD.

    GRIB2 files downloaded by Herbie with the 10m U/V search string
    contain exactly two bands. Band metadata ``GRIB_ELEMENT`` identifies
    the variable.

    Returns:
        (u_band, v_band) 1-based band numbers.

    Raises:
        WeatherDownloadError: Cannot identify U/V bands.
    """
    u_band: int | None = None
    v_band: int | None = None

    with rasterio.open(grib_path) as dataset:
        for band_idx in dataset.indexes:
            tags = dataset.tags(band_idx)
            element = tags.get("GRIB_ELEMENT", "")
            if element == "UGRD":
                u_band = band_idx
            elif element == "VGRD":
                v_band = band_idx

    if u_band is None or v_band is None:
        raise WeatherDownloadError(
            f"Could not identify UGRD/VGRD bands in {grib_path}. "
            f"Expected GRIB_ELEMENT tags."
        )

    return u_band, v_band


def extract_and_warp_wind(
    grib_path: Path,
    dem_spec: DemGridSpec,
) -> tuple[NDArray[np.float64], NDArray[np.float64], Affine]:
    """Read U/V from GRIB2 and reproject to the padded DEM grid.

    Returns:
        (u_array, v_array, padded_transform) where arrays have shape
        ``(padded_height, padded_width)`` in the DEM's CRS.

    Raises:
        WeatherDownloadError: GRIB read or reprojection failure.
    """
    padded_transform, padded_width, padded_height, _ = padded_grid_spec(dem_spec)

    u_band, v_band = _identify_uv_bands(grib_path)

    try:
        with rasterio.open(grib_path) as dataset:
            src_crs = dataset.crs
            src_transform = dataset.transform

            u_src = dataset.read(u_band).astype(np.float64)
            v_src = dataset.read(v_band).astype(np.float64)
            src_nodata = dataset.nodata
    except Exception as exc:
        raise WeatherDownloadError(f"Failed to read GRIB2: {grib_path}") from exc

    u_dst = np.full((padded_height, padded_width), FORCING_NODATA, dtype=np.float64)
    v_dst = np.full((padded_height, padded_width), FORCING_NODATA, dtype=np.float64)

    try:
        reproject(
            source=u_src,
            destination=u_dst,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=padded_transform,
            dst_crs=dem_spec.crs,
            resampling=Resampling.bilinear,
            src_nodata=src_nodata,
            dst_nodata=FORCING_NODATA,
        )
        reproject(
            source=v_src,
            destination=v_dst,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=padded_transform,
            dst_crs=dem_spec.crs,
            resampling=Resampling.bilinear,
            src_nodata=src_nodata,
            dst_nodata=FORCING_NODATA,
        )
    except Exception as exc:
        raise WeatherDownloadError("Failed to reproject HRRR wind to DEM CRS") from exc

    logger.debug(
        "Warped wind grids: shape=(%d, %d) crs=%s",
        padded_height,
        padded_width,
        dem_spec.crs,
    )
    return u_dst, v_dst, padded_transform


# ---------------------------------------------------------------------------
# U/V to speed/direction conversion
# ---------------------------------------------------------------------------


def uv_to_speed_direction(
    u: NDArray[np.float64],
    v: NDArray[np.float64],
    nodata: float = FORCING_NODATA,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Convert U/V wind components to speed (m/s) and meteorological direction.

    Meteorological direction is where the wind blows FROM, in degrees
    clockwise from north: ``(270 - atan2(v, u) * 180/pi) % 360``.

    Pixels where either U or V is ``nodata`` (or NaN) produce ``nodata``
    in both output grids.
    """
    is_nodata = (
        np.isclose(u, nodata) | np.isclose(v, nodata)
        | np.isnan(u) | np.isnan(v)
    )

    speed = np.hypot(u, v)
    direction = np.mod(270.0 - np.degrees(np.arctan2(v, u)), 360.0)

    speed[is_nodata] = nodata
    direction[is_nodata] = nodata

    return speed, direction


# ---------------------------------------------------------------------------
# ASCII Grid writing
# ---------------------------------------------------------------------------


def write_ascii_grid(
    data: NDArray[np.float64],
    transform: Affine,
    crs: rasterio.crs.CRS,
    output_path: Path,
    nodata: float = FORCING_NODATA,
) -> None:
    """Write a 2D array as an ESRI ASCII Grid (.asc) with ``.prj`` sidecar.

    The header uses ``xllcorner`` / ``yllcorner`` (lower-left) convention.
    Data values are written with 6 decimal places; nodata as integer ``-9999``.
    """
    nrows, ncols = data.shape
    # ESRI ASCII Grid only supports square pixels. USGS 3DEP DEMs reprojected
    # to UTM always have equal x/y cell size, so this is safe.
    cellsize = abs(transform.a)

    xllcorner = transform.c
    yllcorner = transform.f + transform.e * nrows  # transform.f is top-left y

    header_lines = [
        f"ncols         {ncols}",
        f"nrows         {nrows}",
        f"xllcorner     {xllcorner:.10f}",
        f"yllcorner     {yllcorner:.10f}",
        f"cellsize      {cellsize:.10f}",
        f"NODATA_value  {nodata:g}",
    ]

    with output_path.open("w", encoding="utf-8") as out_file:
        out_file.write("\n".join(header_lines) + "\n")
        for row_idx in range(nrows):
            values = []
            for value in data[row_idx]:
                if math.isfinite(value) and not np.isclose(value, nodata):
                    values.append(f"{value:.6f}")
                else:
                    values.append(f"{nodata:g}")
            out_file.write(" ".join(values) + "\n")

    _write_prj_sidecar(output_path, crs)

    logger.debug("ASCII grid written: %s (%d x %d)", output_path, ncols, nrows)


def _write_prj_sidecar(asc_path: Path, crs: rasterio.crs.CRS) -> None:
    """Write ESRI WKT projection sidecar alongside an .asc file."""
    prj_path = asc_path.with_suffix(".prj")
    from rasterio.enums import WktVersion
    wkt = crs.to_wkt(version=WktVersion.WKT1_ESRI)
    prj_path.write_text(wkt.rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Single-timestep orchestration
# ---------------------------------------------------------------------------


def process_timestep(
    cycle: HrrrCycle,
    dem_spec: DemGridSpec,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Download, extract, convert, and write forcing grids for one timestep.

    Creates two files in ``output_dir``:
    - ``speed_YYYYMMDD_HHMM.asc`` (+ ``.prj``)
    - ``direction_YYYYMMDD_HHMM.asc`` (+ ``.prj``)

    Args:
        cycle: The HRRR cycle to download.
        dem_spec: Pre-read DEM spatial metadata (avoids re-opening the file
            on every timestep).
        output_dir: Directory for output ASCII grids.

    Returns:
        ``(speed_asc_path, direction_asc_path)``

    Raises:
        WeatherDownloadError: Any step in the pipeline failed. Partial files
            are cleaned up before re-raising.
    """
    timestamp_label = cycle.valid_time.strftime("%Y%m%d_%H%M")
    speed_path = output_dir / f"speed_{timestamp_label}.asc"
    direction_path = output_dir / f"direction_{timestamp_label}.asc"

    try:
        grib_path = download_hrrr_grib(cycle)
        u_array, v_array, padded_transform = extract_and_warp_wind(grib_path, dem_spec)
        speed_array, direction_array = uv_to_speed_direction(u_array, v_array)

        write_ascii_grid(speed_array, padded_transform, dem_spec.crs, speed_path)
        write_ascii_grid(direction_array, padded_transform, dem_spec.crs, direction_path)

    except Exception:
        _cleanup_forcing_files(speed_path, direction_path)
        raise

    logger.info(
        "Forcing grids written: valid_time=%s speed=%s direction=%s",
        cycle.valid_time.isoformat(),
        speed_path.name,
        direction_path.name,
    )
    return speed_path, direction_path


def _cleanup_forcing_files(*paths: Path) -> None:
    """Remove .asc and .prj files, ignoring missing files."""
    for path in paths:
        path.unlink(missing_ok=True)
        path.with_suffix(".prj").unlink(missing_ok=True)
