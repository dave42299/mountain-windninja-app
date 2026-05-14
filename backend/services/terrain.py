"""Terrain data retrieval service -- public API for the mountain-windninja-app backend.

This module is the sole entry point for terrain operations. It owns:

- Cache lookup for both elevation and land cover tiles.
- Metadata extraction (WGS84 bounding box + CRS EPSG) from written raster files.
- ORM row creation, flush, and caller-facing commit contract.
- File cleanup on partial failures.
- Orchestration of the full terrain resolution pipeline via
  :func:`ensure_tiles_for_forecast`.

Source-specific download logic lives in sub-modules and is called from here:

- :mod:`services.terrain_dem` -- USGS 3DEP DEM via py3dep on the host.
- :mod:`services.terrain_lcp` -- LANDFIRE LCP via WindNinja ``fetch_dem`` in Docker.

CONUS validation and bbox geometry live in :mod:`services.terrain_geometry`.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import rasterio
from rasterio.warp import transform_bounds
from sqlalchemy.orm import Session

from config import settings
from models.orm import ElevationTile, LandCoverTile
from services.terrain_dem import (
    ELEVATION_SOURCE_USGS_3DEP,
    TerrainDemError,
    download_elevation_raster,
)
from services.terrain_geometry import (
    TerrainOutsideUsError,
    Wgs84BoundingBox,
    pad_bbox_fraction,
    square_bbox_wgs84,
    validate_conus_wgs84_bbox,
)
from services.terrain_lcp import (
    LAND_COVER_SOURCE_LANDFIRE,
    TerrainLcpError,
    download_land_cover_raster,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ForecastTerrainTiles",
    "TerrainDemError",
    "TerrainLcpError",
    "TerrainOutsideUsError",
    "Wgs84BoundingBox",
    "ensure_tiles_for_forecast",
]


@dataclass(frozen=True)
class ForecastTerrainTiles:
    """DEM + land cover tiles for one forecast location after cache lookup / download."""

    elevation_tile: ElevationTile
    land_cover_tile: LandCoverTile
    user_bbox: Wgs84BoundingBox
    padded_bbox: Wgs84BoundingBox


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _cleanup_files(*paths: Path) -> None:
    """Remove files if they exist, ignoring errors if the file is absent."""
    for path in paths:
        path.unlink(missing_ok=True)


def _read_raster_wgs84_metadata(path: Path) -> tuple[Wgs84BoundingBox, int]:
    """Read the WGS84 bounding box and EPSG code from a raster file on disk.

    Attempts ``crs.to_epsg()`` first, then ``crs.to_authority()`` as a fallback
    for files whose CRS authority is EPSG but whose EPSG code is not stored
    directly (common for LANDFIRE LCP files in CONUS Albers EPSG:5070).

    Raises:
        ValueError: CRS is absent or cannot be resolved to an EPSG integer.
    """
    with rasterio.open(path) as dataset:
        if dataset.crs is None:
            raise ValueError(f"Raster file has no CRS metadata: {path}")
        crs_epsg = dataset.crs.to_epsg()
        if crs_epsg is None:
            authority = dataset.crs.to_authority()
            if authority is not None and authority[0].upper() == "EPSG":
                crs_epsg = int(authority[1])
        if crs_epsg is None:
            raise ValueError(
                f"Cannot resolve EPSG code from CRS '{dataset.crs.to_wkt()[:200]}' "
                f"in {path}"
            )
        wgs84_bounds = transform_bounds(dataset.crs, "EPSG:4326", *dataset.bounds)

    west_4326, south_4326, east_4326, north_4326 = wgs84_bounds
    bbox = Wgs84BoundingBox(
        north=north_4326, east=east_4326, south=south_4326, west=west_4326
    )
    logger.debug(
        "Raster metadata: path=%s crs_epsg=%d wgs84=%s",
        path,
        crs_epsg,
        bbox,
    )
    return bbox, crs_epsg


# ---------------------------------------------------------------------------
# Per-layer ensure functions
# ---------------------------------------------------------------------------


def ensure_elevation_tile(
    session: Session,
    lookup: Wgs84BoundingBox,
    *,
    download: Wgs84BoundingBox,
    data_dir: Path,
) -> ElevationTile:
    """Return a cached or freshly downloaded USGS 3DEP DEM tile.

    **Lookup** is the user's true WGS84 bbox. A cache hit is any tile whose
    stored bbox fully contains ``lookup``.

    **Download** is the WGS84 extent passed to USGS (often padded beyond
    ``lookup``) so on-disk data covers nearby forecasts.

    Stored ``ElevationTile`` bbox columns are taken only from the written
    GeoTIFF so the index reflects actual file extent.

    Callers are responsible for CONUS validation before calling this function.
    :func:`ensure_tiles_for_forecast` handles this automatically.

    Args:
        session: Open ORM session. Caller commits after this returns.
        data_dir: Resolved application data root; files go under ``elevation/``.

    Raises:
        TerrainDemError: Download, reproject, write, or metadata read failure.
    """
    cached = ElevationTile.find_containing(
        session, lookup.north, lookup.south, lookup.east, lookup.west
    )
    if cached is not None:
        logger.info("DEM cache hit: tile_id=%s file=%s", cached.id, cached.file_path)
        return cached

    logger.info("DEM cache miss, downloading: bbox=%s", download)

    tile_id = uuid.uuid4()
    relative = Path("elevation") / f"{tile_id}.tif"
    absolute = data_dir / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    try:
        download_elevation_raster(download, absolute)
    except Exception:
        _cleanup_files(absolute)
        raise

    try:
        wgs84_bbox, crs_epsg = _read_raster_wgs84_metadata(absolute)
    except Exception as exc:
        _cleanup_files(absolute)
        raise TerrainDemError("Could not read metadata from written DEM") from exc

    elapsed = time.monotonic() - t0
    file_size = absolute.stat().st_size
    logger.info(
        "DEM downloaded: tile_id=%s crs_epsg=%d size_bytes=%d elapsed=%.1fs",
        tile_id,
        crs_epsg,
        file_size,
        elapsed,
    )

    tile = ElevationTile(
        id=tile_id,
        bbox_north=wgs84_bbox.north,
        bbox_south=wgs84_bbox.south,
        bbox_east=wgs84_bbox.east,
        bbox_west=wgs84_bbox.west,
        crs_epsg=crs_epsg,
        file_path=relative.as_posix(),
        source=ELEVATION_SOURCE_USGS_3DEP,
        file_size_bytes=file_size,
    )
    session.add(tile)
    session.flush()
    return tile


def ensure_land_cover_tile(
    session: Session,
    lookup: Wgs84BoundingBox,
    *,
    download: Wgs84BoundingBox,
    data_dir: Path,
    solver_image: str,
    subprocess_timeout_seconds: int,
) -> LandCoverTile:
    """Return a cached or freshly downloaded LANDFIRE LCP tile.

    **Lookup** is the user's true WGS84 bbox. **Download** is the extent for
    ``fetch_dem`` (often padded). Stored bbox columns come only from the LCP
    file.

    Callers are responsible for CONUS validation before calling this function.
    :func:`ensure_tiles_for_forecast` handles this automatically.

    Args:
        session: Open ORM session. Caller commits after this returns.
        data_dir: Resolved application data root; files go under ``land_cover/``.

    Raises:
        ValueError: Non-positive ``subprocess_timeout_seconds``.
        TerrainLcpError: Docker, ``fetch_dem``, ``gdalsrsinfo``, or metadata
            read failure.
    """
    if subprocess_timeout_seconds <= 0:
        raise ValueError("subprocess_timeout_seconds must be positive")

    cached = LandCoverTile.find_containing(
        session, lookup.north, lookup.south, lookup.east, lookup.west
    )
    if cached is not None:
        logger.info("LCP cache hit: tile_id=%s file=%s", cached.id, cached.file_path)
        return cached

    logger.info(
        "LCP cache miss, downloading: bbox=%s solver_image=%s timeout=%ds",
        download,
        solver_image,
        subprocess_timeout_seconds,
    )

    tile_id = uuid.uuid4()
    relative_lcp = Path("land_cover") / f"{tile_id}.lcp"
    absolute_lcp = data_dir / relative_lcp
    absolute_prj = absolute_lcp.with_suffix(".prj")
    absolute_lcp.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    try:
        download_land_cover_raster(
            download,
            host_data_dir=data_dir,
            relative_lcp=relative_lcp,
            solver_image=solver_image,
            timeout_seconds=subprocess_timeout_seconds,
        )
    except Exception:
        _cleanup_files(absolute_lcp, absolute_prj)
        raise

    try:
        wgs84_bbox, crs_epsg = _read_raster_wgs84_metadata(absolute_lcp)
    except Exception as exc:
        _cleanup_files(absolute_lcp, absolute_prj)
        raise TerrainLcpError("Could not read metadata from LCP") from exc

    elapsed = time.monotonic() - t0
    file_size = absolute_lcp.stat().st_size + absolute_prj.stat().st_size
    logger.info(
        "LCP downloaded: tile_id=%s crs_epsg=%d size_bytes=%d elapsed=%.1fs",
        tile_id,
        crs_epsg,
        file_size,
        elapsed,
    )

    tile = LandCoverTile(
        id=tile_id,
        bbox_north=wgs84_bbox.north,
        bbox_south=wgs84_bbox.south,
        bbox_east=wgs84_bbox.east,
        bbox_west=wgs84_bbox.west,
        crs_epsg=crs_epsg,
        file_path=relative_lcp.as_posix(),
        source=LAND_COVER_SOURCE_LANDFIRE,
        file_size_bytes=file_size,
    )
    session.add(tile)
    session.flush()
    return tile


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


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

    Builds the user's square WGS84 bbox from ``center_latitude``,
    ``center_longitude``, and ``size_km``, expands it by
    ``bbox_padding_fraction`` for **download only**, validates the padded
    extent is inside CONUS, then resolves tiles. **Cache lookup** uses the
    **user** (non-padded) box so similar clicks hit the same tile; padding
    only enlarges what is fetched on a cache miss.

    Commits after **elevation** resolves and again after **land cover** resolves
    so the two caches stay independent: if LCP fails, the DEM row (and file)
    from this request stay durable and the next call hits DEM only. Callers
    still insert ``Forecast`` only when both tiles exist; they should not roll
    back a transaction that would undo a layer already committed here.

    Concurrency: Near-simultaneous requests for overlapping areas may both miss
    the cache and each download independently, resulting in duplicate tile rows
    and files. This is harmless for correctness (each forecast references its
    own tile row) but wastes disk space. Phase 2 targets single-user local
    execution; a SELECT ... FOR UPDATE or database advisory lock can be added
    in Phase 4 if concurrent requests become common.

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

    root = (data_dir if data_dir is not None else settings.data_dir).resolve()
    image = solver_image if solver_image is not None else settings.solver_image
    timeout = (
        lcp_subprocess_timeout_seconds
        if lcp_subprocess_timeout_seconds is not None
        else settings.terrain_lcp_subprocess_timeout_seconds
    )

    user = square_bbox_wgs84(center_latitude, center_longitude, size_km)
    padded = pad_bbox_fraction(user, fraction=bbox_padding_fraction)
    validate_conus_wgs84_bbox(padded)

    logger.info(
        "Resolving terrain tiles: center=(%.4f, %.4f) size_km=%.1f padding=%.2f",
        center_latitude,
        center_longitude,
        size_km,
        bbox_padding_fraction,
    )
    logger.debug("User bbox: %s | Padded bbox: %s", user, padded)

    t_start = time.monotonic()

    elevation_tile = ensure_elevation_tile(
        session, user, download=padded, data_dir=root
    )
    session.commit()
    session.refresh(elevation_tile)

    land_cover_tile = ensure_land_cover_tile(
        session,
        user,
        download=padded,
        data_dir=root,
        solver_image=image,
        subprocess_timeout_seconds=timeout,
    )
    session.commit()
    session.refresh(land_cover_tile)

    elapsed = time.monotonic() - t_start
    logger.info(
        "Terrain tiles resolved: dem=%s lcp=%s elapsed=%.1fs",
        elevation_tile.id,
        land_cover_tile.id,
        elapsed,
    )

    return ForecastTerrainTiles(
        elevation_tile=elevation_tile,
        land_cover_tile=land_cover_tile,
        user_bbox=user,
        padded_bbox=padded,
    )
