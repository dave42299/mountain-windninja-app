"""USGS 3DEP DEM download and cache for Phase 2 (continental US only).

Uses py3dep on the host (no Docker), writes a UTM GeoTIFF under ``data_dir/elevation/``,
and records an ``ElevationTile`` row with bbox in WGS84 read from the written file.
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
from services.terrain_geometry import Wgs84BoundingBox

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


def validate_conus_wgs84_bbox(bbox: Wgs84BoundingBox) -> None:
    """Raise ``TerrainOutsideUsError`` if the bbox is not fully inside the CONUS envelope."""
    if bbox.north <= bbox.south:
        raise ValueError("north must be greater than south")
    if bbox.east <= bbox.west:
        raise ValueError("east must be greater than west")
    if (
        bbox.north > _CONUS_NORTH
        or bbox.south < _CONUS_SOUTH
        or bbox.east > _CONUS_EAST
        or bbox.west < _CONUS_WEST
    ):
        raise TerrainOutsideUsError(
            "Forecast extent must lie fully inside the continental United States "
            f"(WGS84 envelope south={_CONUS_SOUTH}..north={_CONUS_NORTH}, "
            f"west={_CONUS_WEST}..east={_CONUS_EAST})."
        )


def ensure_elevation_tile(
    session: Session,
    *,
    lookup: Wgs84BoundingBox,
    download: Wgs84BoundingBox,
    data_dir: Path,
) -> ElevationTile:
    """Return a cached or freshly downloaded DEM tile.

    **Lookup** is the user's true WGS84 bbox (north/east are maxima). A cache hit is
    any tile whose stored bbox fully contains that box.

    **Download** is the WGS84 extent passed to py3dep (often larger than the lookup
    box, e.g. after padding) so on-disk data covers nearby forecasts.

    Stored ``ElevationTile`` bbox columns are taken **only** from the written GeoTIFF
    (axis-aligned hull in WGS84), so the index reflects actual file extent.

    Args:
        session: Open ORM session (caller commits).
        data_dir: Application data root; files go under ``elevation/`` relative to this.

    Raises:
        TerrainOutsideUsError: Download bbox not fully inside CONUS.
        TerrainDemError: py3dep or raster I/O failure.
    """
    validate_conus_wgs84_bbox(download)

    cached = ElevationTile.find_containing(
        session, lookup.north, lookup.south, lookup.east, lookup.west
    )
    if cached is not None:
        return cached

    root = data_dir.resolve()
    elevation_dir = root / "elevation"
    elevation_dir.mkdir(parents=True, exist_ok=True)

    center_lat = (download.north + download.south) / 2.0
    center_lon = (download.east + download.west) / 2.0
    utm_epsg = utm_epsg_from_wgs84(center_lat, center_lon)

    west_south_east_north = (download.west, download.south, download.east, download.north)
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

    tile = ElevationTile(
        id=tile_id,
        bbox_north=north_4326,
        bbox_south=south_4326,
        bbox_east=east_4326,
        bbox_west=west_4326,
        crs_epsg=crs_epsg,
        file_path=relative_path.as_posix(),
        source=ELEVATION_SOURCE_USGS_3DEP,
        file_size_bytes=file_size_bytes,
    )
    session.add(tile)
    session.flush()
    return tile
