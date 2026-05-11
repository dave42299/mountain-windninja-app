"""Terrain data retrieval service.

Handles downloading DEM (elevation) and LCP (land cover) data
for a given lat/lon bounding box.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from config import settings
from models.orm import ElevationTile, LandCoverTile
from services.terrain_dem import (
    TerrainDemError,
    TerrainOutsideUsError,
    utm_epsg_from_wgs84,
    validate_conus_wgs84_bbox,
)
from services.terrain_dem import (
    ensure_elevation_tile as ensure_elevation_tile_with_data_dir,
)
from services.terrain_lcp import (
    TerrainLcpError,
)
from services.terrain_lcp import (
    ensure_land_cover_tile as ensure_land_cover_tile_impl,
)

__all__ = [
    "TerrainDemError",
    "TerrainLcpError",
    "TerrainOutsideUsError",
    "ensure_elevation_tile",
    "ensure_land_cover_tile",
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


def ensure_land_cover_tile(
    session: Session,
    north: float,
    east: float,
    south: float,
    west: float,
    *,
    data_dir: Path | None = None,
    solver_image: str | None = None,
    subprocess_timeout_seconds: int | None = None,
) -> LandCoverTile:
    """Return a cached or new LANDFIRE LCP tile for a WGS84 bbox (CONUS only).

    Runs WindNinja ``fetch_dem --src lcp`` in Docker (see ``mwn.sh fetch-lcp``).

    ``data_dir`` defaults to :attr:`config.settings.data_dir` (resolved).
    ``solver_image`` defaults to :attr:`config.settings.solver_image`.
    Timeout defaults to :attr:`config.settings.terrain_lcp_subprocess_timeout_seconds`.
    """
    root = (data_dir if data_dir is not None else settings.data_dir).resolve()
    image = solver_image if solver_image is not None else settings.solver_image
    timeout = (
        subprocess_timeout_seconds
        if subprocess_timeout_seconds is not None
        else settings.terrain_lcp_subprocess_timeout_seconds
    )
    return ensure_land_cover_tile_impl(
        session,
        north,
        east,
        south,
        west,
        data_dir=root,
        solver_image=image,
        subprocess_timeout_seconds=timeout,
    )
