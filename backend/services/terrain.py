"""Terrain data retrieval service.

Handles downloading DEM (elevation) and LCP (land cover) data
for a given lat/lon bounding box.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from config import settings
from models.orm import ElevationTile
from services.terrain_dem import (
    TerrainDemError,
    TerrainOutsideUsError,
    utm_epsg_from_wgs84,
    validate_conus_wgs84_bbox,
)
from services.terrain_dem import (
    ensure_elevation_tile as ensure_elevation_tile_with_data_dir,
)

__all__ = [
    "TerrainDemError",
    "TerrainOutsideUsError",
    "ensure_elevation_tile",
    "utm_epsg_from_wgs84",
    "validate_conus_wgs84_bbox",
]


def ensure_elevation_tile(
    session: Session,
    north: float,
    east: float,
    south: float,
    west: float,
    *,
    data_dir: Path | None = None,
) -> ElevationTile:
    """Return a cached or new USGS 3DEP DEM tile for a WGS84 bbox (CONUS only).

    ``data_dir`` defaults to :attr:`config.settings.data_dir` (resolved).
    """
    root = (data_dir if data_dir is not None else settings.data_dir).resolve()
    return ensure_elevation_tile_with_data_dir(
        session,
        north,
        east,
        south,
        west,
        data_dir=root,
    )
