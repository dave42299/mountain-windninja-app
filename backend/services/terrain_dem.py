"""USGS 3DEP DEM download for Phase 2 (continental US only).

Uses py3dep on the host (no Docker) to fetch a DEM and write a UTM GeoTIFF.
Cache management, metadata extraction, and database interaction are handled by
the terrain orchestrator in :mod:`services.terrain`.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import py3dep
import rioxarray  # noqa: F401 — registers ``.rio`` on xarray objects returned by py3dep
from py3dep.exceptions import ServiceUnavailableError
from rasterio.enums import Resampling

from services.terrain_geometry import Wgs84BoundingBox

logger = logging.getLogger(__name__)

ELEVATION_SOURCE_USGS_3DEP = "usgs_3dep"


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


def download_elevation_raster(
    download_bbox: Wgs84BoundingBox,
    output_path: Path,
) -> None:
    """Download a USGS 3DEP DEM for ``download_bbox`` and write a UTM GeoTIFF.

    Reprojects to the UTM zone covering the bbox center so downstream work has
    one predictable projected CRS.

    The parent directory of ``output_path`` must already exist. Does not create
    directories, generate IDs, or interact with the database -- those are the
    caller's responsibilities.

    Raises:
        TerrainDemError: py3dep service error, download failure, reproject failure,
            or write failure.
    """
    center_lat = (download_bbox.north + download_bbox.south) / 2.0
    center_lon = (download_bbox.east + download_bbox.west) / 2.0
    utm_epsg = utm_epsg_from_wgs84(center_lat, center_lon)

    logger.info(
        "Downloading DEM from USGS 3DEP: bbox=%s utm_epsg=%d",
        download_bbox,
        utm_epsg,
    )
    logger.debug(
        "py3dep request bbox (W, S, E, N): (%s, %s, %s, %s)",
        download_bbox.west,
        download_bbox.south,
        download_bbox.east,
        download_bbox.north,
    )

    west_south_east_north = (
        download_bbox.west,
        download_bbox.south,
        download_bbox.east,
        download_bbox.north,
    )
    try:
        dem = py3dep.get_dem(west_south_east_north, resolution=10, crs=4326)
        dem_utm = dem.rio.reproject(f"EPSG:{utm_epsg}", resampling=Resampling.bilinear)
    except ServiceUnavailableError as exc:
        raise TerrainDemError("USGS 3DEP service unavailable") from exc
    except Exception as exc:
        raise TerrainDemError("Failed to download or reproject DEM") from exc

    try:
        dem_utm.rio.to_raster(output_path, driver="GTiff")
    except Exception as exc:
        raise TerrainDemError("Failed to write DEM GeoTIFF") from exc

    logger.info("DEM written: path=%s", output_path)
