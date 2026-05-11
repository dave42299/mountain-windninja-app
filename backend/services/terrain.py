"""Terrain data retrieval service.

Handles downloading DEM (elevation) and LCP (land cover) data
for a given lat/lon bounding box.
"""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import UnmappedInstanceError

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
from services.terrain_geometry import Wgs84BoundingBox, pad_bbox_fraction, square_bbox_wgs84
from services.terrain_lcp import (
    TerrainLcpError,
)
from services.terrain_lcp import (
    ensure_land_cover_tile as ensure_land_cover_tile_impl,
)


def _refresh_tile_after_commit(session: Session, tile: object) -> None:
    """Reload ORM attributes after ``commit`` (no-op for unmapped test doubles)."""
    try:
        session.refresh(tile)
    except UnmappedInstanceError:
        pass


__all__ = [
    "ForecastTerrainTiles",
    "TerrainDemError",
    "TerrainLcpError",
    "TerrainOutsideUsError",
    "Wgs84BoundingBox",
    "ensure_elevation_tile",
    "ensure_land_cover_tile",
    "ensure_tiles_for_forecast",
    "utm_epsg_from_wgs84",
    "validate_conus_wgs84_bbox",
]


@dataclass(frozen=True)
class ForecastTerrainTiles:
    """DEM + land cover tiles for one forecast location after cache lookup / download."""

    elevation_tile: ElevationTile
    land_cover_tile: LandCoverTile
    user_bbox_north: float
    user_bbox_east: float
    user_bbox_south: float
    user_bbox_west: float
    padded_bbox_north: float
    padded_bbox_east: float
    padded_bbox_south: float
    padded_bbox_west: float


def ensure_elevation_tile(
    session: Session,
    lookup: Wgs84BoundingBox,
    *,
    data_dir: Path | None = None,
    download: Wgs84BoundingBox | None = None,
) -> ElevationTile:
    """Return a cached or new USGS 3DEP DEM tile for WGS84 boxes (CONUS only).

    ``lookup`` is the user's true extent (used for cache containment). If
    ``download`` is omitted, download uses the same box as lookup.

    ``data_dir`` defaults to :attr:`config.settings.data_dir` (resolved).
    """
    root = (data_dir if data_dir is not None else settings.data_dir).resolve()
    download_bbox = lookup if download is None else download
    return ensure_elevation_tile_with_data_dir(
        session,
        lookup=lookup,
        download=download_bbox,
        data_dir=root,
    )


def ensure_land_cover_tile(
    session: Session,
    lookup: Wgs84BoundingBox,
    *,
    data_dir: Path | None = None,
    download: Wgs84BoundingBox | None = None,
    solver_image: str | None = None,
    subprocess_timeout_seconds: int | None = None,
) -> LandCoverTile:
    """Return a cached or new LANDFIRE LCP tile (CONUS only).

    ``lookup`` is the user's true extent for cache checks. ``download``, if
    given, is the box for ``fetch_dem``; otherwise it matches ``lookup``.

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
    download_bbox = lookup if download is None else download
    return ensure_land_cover_tile_impl(
        session,
        lookup=lookup,
        download=download_bbox,
        data_dir=root,
        solver_image=image,
        subprocess_timeout_seconds=timeout,
    )


def ensure_tiles_for_forecast(
    session: Session,
    *,
    center_latitude: float,
    center_longitude: float,
    size_km: float,
    data_dir: Path | None = None,
    bbox_padding_fraction: float = 0.25,
    solver_image: str | None = None,
    lcp_subprocess_timeout_seconds: int | None = None,
) -> ForecastTerrainTiles:
    """Resolve elevation and land cover tiles for a forecast area (CONUS Phase 2).

    Builds the user's square WGS84 bbox from ``center_latitude``, ``center_longitude``,
    and ``size_km``, expands it by ``bbox_padding_fraction`` for **download only**,
    validates the padded extent is inside CONUS, then resolves tiles. **Cache lookup**
    uses the **user** (non-padded) box so similar clicks hit the same tile; padding
    only enlarges what is fetched when a miss occurs.

    Commits after **elevation** resolves and again after **land cover** resolves so the
    two caches stay independent: if LCP fails, the DEM row (and file) from this request
    stay durable and the next call hits DEM only. Callers still insert ``Forecast`` only
    when both tiles exist; they should not roll back a transaction that would undo a
    layer already committed in an earlier step.

    Returns:
        Both tiles, the user bbox, and the padded bbox used for downloads.

    Raises:
        ValueError: Invalid ``bbox_padding_fraction`` or geometry inputs.
        TerrainOutsideUsError: Padded bbox not fully inside CONUS.
        TerrainDemError: DEM path failure.
        TerrainLcpError: LCP path failure.
    """
    if bbox_padding_fraction < 0:
        raise ValueError("bbox_padding_fraction must be non-negative")

    user = square_bbox_wgs84(
        center_latitude,
        center_longitude,
        size_km,
    )
    padded = pad_bbox_fraction(user, fraction=bbox_padding_fraction)
    validate_conus_wgs84_bbox(padded)

    elevation_tile = ensure_elevation_tile(
        session,
        user,
        data_dir=data_dir,
        download=padded,
    )
    session.commit()
    _refresh_tile_after_commit(session, elevation_tile)

    land_cover_tile = ensure_land_cover_tile(
        session,
        user,
        data_dir=data_dir,
        download=padded,
        solver_image=solver_image,
        subprocess_timeout_seconds=lcp_subprocess_timeout_seconds,
    )
    session.commit()
    _refresh_tile_after_commit(session, land_cover_tile)

    return ForecastTerrainTiles(
        elevation_tile=elevation_tile,
        land_cover_tile=land_cover_tile,
        user_bbox_north=user.north,
        user_bbox_east=user.east,
        user_bbox_south=user.south,
        user_bbox_west=user.west,
        padded_bbox_north=padded.north,
        padded_bbox_east=padded.east,
        padded_bbox_south=padded.south,
        padded_bbox_west=padded.west,
    )
