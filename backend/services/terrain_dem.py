"""USGS 3DEP DEM download and cache for Phase 2 (continental US only).

Uses py3dep on the host (no Docker), writes a UTM GeoTIFF under ``data_dir/elevation/``,
and records an ``ElevationTile`` row with bbox in WGS84 (from the written file).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import py3dep
import rasterio
import rioxarray  # noqa: F401 — registers ``.rio`` on xarray objects returned by py3dep
from py3dep.exceptions import ServiceUnavailableError
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from sqlalchemy.orm import Session

from models.orm import ElevationTile

ELEVATION_SOURCE_USGS_3DEP = "usgs_3dep"

# Approximate CONUS envelope in WGS84. Phase 2 excludes Alaska, Hawaii, and non-US.
_CONUS_NORTH = 49.6
_CONUS_SOUTH = 24.0
_CONUS_EAST = -66.0
_CONUS_WEST = -125.05


class TerrainOutsideUsError(ValueError):
    """The requested extent is outside the Phase 2 continental US service area."""


class TerrainDemError(RuntimeError):
    """DEM fetch, reproject, or write failed."""


def utm_epsg_from_wgs84(latitude: float, longitude: float) -> int:
    """Return WGS84 UTM zone EPSG (326xx north of equator, 327xx south).

    Matches the common ``floor((lon + 180) / 6) + 1`` zone rule with EPSG prefixes.
    """
    if not -80.0 <= latitude <= 84.0:
        raise ValueError("latitude outside UTM latitude limits for this helper")
    zone = int((longitude + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    if latitude >= 0:
        return 32_600 + zone
    return 32_700 + zone


def validate_conus_wgs84_bbox(north: float, east: float, south: float, west: float) -> None:
    """Raise ``TerrainOutsideUsError`` if the bbox is not fully inside the CONUS envelope."""
    if north <= south:
        raise ValueError("north must be greater than south")
    if east <= west:
        raise ValueError("east must be greater than west")
    if (
        north > _CONUS_NORTH
        or south < _CONUS_SOUTH
        or east > _CONUS_EAST
        or west < _CONUS_WEST
    ):
        raise TerrainOutsideUsError(
            "Forecast extent must lie fully inside the continental United States "
            f"(WGS84 envelope south={_CONUS_SOUTH}..north={_CONUS_NORTH}, "
            f"west={_CONUS_WEST}..east={_CONUS_EAST})."
        )


def ensure_elevation_tile(
    session: Session,
    north: float,
    east: float,
    south: float,
    west: float,
    *,
    data_dir: Path,
) -> ElevationTile:
    """Return a cached or freshly downloaded DEM tile whose bbox contains the request.

    Args:
        session: Open ORM session (caller commits).
        north, east, south, west: Requested WGS84 bbox (degrees), same convention as
            :mod:`services.terrain_geometry` (north/east are maxima).
        data_dir: Application data root; files go under ``elevation/`` relative to this.

    Returns:
        ``ElevationTile`` with ``file_path`` relative to ``data_dir``.

    Raises:
        TerrainOutsideUsError: Bbox not fully inside CONUS.
        TerrainDemError: py3dep or raster I/O failure.
    """
    validate_conus_wgs84_bbox(north, east, south, west)

    cached = ElevationTile.find_containing(session, north, south, east, west)
    if cached is not None:
        return cached

    root = data_dir.resolve()
    elevation_dir = root / "elevation"
    elevation_dir.mkdir(parents=True, exist_ok=True)

    center_lat = (north + south) / 2.0
    center_lon = (east + west) / 2.0
    utm_epsg = utm_epsg_from_wgs84(center_lat, center_lon)

    west_south_east_north = (west, south, east, north)
    try:
        dem = py3dep.get_dem(west_south_east_north, resolution=10, crs=4326)
        dem_utm = dem.rio.reproject(f"EPSG:{utm_epsg}", resampling=Resampling.bilinear)
    except ServiceUnavailableError as exc:
        raise TerrainDemError("USGS 3DEP service unavailable") from exc
    except Exception as exc:
        raise TerrainDemError("Failed to download or reproject DEM") from exc

    tile_id = uuid.uuid4()
    relative_path = Path("elevation") / f"{tile_id}.tif"
    absolute_path = root / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        dem_utm.rio.to_raster(absolute_path, driver="GTiff")
    except Exception as exc:
        if absolute_path.exists():
            absolute_path.unlink(missing_ok=True)
        raise TerrainDemError("Failed to write DEM GeoTIFF") from exc

    file_size_bytes = absolute_path.stat().st_size

    with rasterio.open(absolute_path) as dataset:
        if dataset.crs is None:
            raise TerrainDemError("Written DEM has no CRS metadata")
        crs_epsg = dataset.crs.to_epsg()
        if crs_epsg is None:
            raise TerrainDemError("Written DEM CRS is not EPSG-encoded")
        wgs84_bounds = transform_bounds(
            dataset.crs,
            "EPSG:4326",
            *dataset.bounds,
        )

    west_4326, south_4326, east_4326, north_4326 = wgs84_bounds

    # The axis-aligned WGS84 hull of a UTM footprint can be slightly tighter than
    # the original request in lon/lat. Union with the requested bbox so
    # ``find_containing`` remains correct for the same request on cache hits.
    north_stored = max(north_4326, north)
    south_stored = min(south_4326, south)
    east_stored = max(east_4326, east)
    west_stored = min(west_4326, west)

    tile = ElevationTile(
        id=tile_id,
        bbox_north=north_stored,
        bbox_south=south_stored,
        bbox_east=east_stored,
        bbox_west=west_stored,
        crs_epsg=crs_epsg,
        file_path=relative_path.as_posix(),
        source=ELEVATION_SOURCE_USGS_3DEP,
        file_size_bytes=file_size_bytes,
    )
    session.add(tile)
    session.flush()
    return tile