"""LANDFIRE LCP download and cache for Phase 2 (continental US only).

Runs WindNinja ``fetch_dem --src lcp`` inside the solver Docker image (same approach as
``mwn.sh fetch-lcp``), writes ``{uuid}.lcp`` plus a ``.prj`` sidecar (WindNinja requires it),
and records a ``LandCoverTile`` row with bbox in WGS84.
"""

from __future__ import annotations

import shlex
import subprocess
import uuid
from pathlib import Path

import rasterio
from rasterio.warp import transform_bounds
from sqlalchemy.orm import Session

from models.orm import LandCoverTile
from services.terrain_dem import validate_conus_wgs84_bbox

LAND_COVER_SOURCE_LANDFIRE = "landfire"

_CONTAINER_DATA_ROOT = Path("/data")


class TerrainLcpError(RuntimeError):
    """LCP fetch via Docker / fetch_dem or post-processing failed."""


def _read_land_cover_spatial_metadata(
    lcp_path: Path,
) -> tuple[float, float, float, float, int]:
    """Return WGS84 bbox (north, east, south, west) and native EPSG for an LCP on disk."""
    with rasterio.open(lcp_path) as dataset:
        if dataset.crs is None:
            raise TerrainLcpError("Land cover file has no CRS metadata")
        crs_epsg = dataset.crs.to_epsg()
        if crs_epsg is None:
            authority = dataset.crs.to_authority()
            if authority is not None and authority[0].upper() == "EPSG":
                crs_epsg = int(authority[1])
            else:
                crs_epsg = 5070
        wgs84_bounds = transform_bounds(
            dataset.crs,
            "EPSG:4326",
            *dataset.bounds,
        )
    west_4326, south_4326, east_4326, north_4326 = wgs84_bounds
    return north_4326, east_4326, south_4326, west_4326, crs_epsg


def _run_lcp_docker_pipeline(
    *,
    solver_image: str,
    host_data_dir: Path,
    relative_lcp: Path,
    north: float,
    east: float,
    south: float,
    west: float,
    subprocess_timeout_seconds: int,
) -> None:
    """Run ``fetch_dem`` and ``gdalsrsinfo`` in Docker (``solver_image``).

    Mounts ``host_data_dir`` read-write at ``/data`` in the container.
    """
    root = host_data_dir.resolve()
    mount = f"{root}:{_CONTAINER_DATA_ROOT.as_posix()}"
    container_lcp = (_CONTAINER_DATA_ROOT / relative_lcp).as_posix()
    container_prj = (_CONTAINER_DATA_ROOT / relative_lcp).with_suffix(".prj").as_posix()

    inner_script = (
        f"fetch_dem --bbox {north} {east} {south} {west} --src lcp {shlex.quote(container_lcp)}"
        f" && gdalsrsinfo -o wkt {shlex.quote(container_lcp)} > {shlex.quote(container_prj)}"
    )
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        mount,
        solver_image,
        "bash",
        "-lc",
        inner_script,
    ]
    try:
        subprocess.run(
            command,
            check=True,
            timeout=subprocess_timeout_seconds,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise TerrainLcpError(
            "Docker CLI not found; install Docker and ensure `docker` is on PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TerrainLcpError(
            f"Land cover download timed out after {subprocess_timeout_seconds} seconds."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or f"exit code {exc.returncode}"
        raise TerrainLcpError(f"fetch_dem / gdalsrsinfo failed: {detail}") from exc


def ensure_land_cover_tile(
    session: Session,
    north: float,
    east: float,
    south: float,
    west: float,
    *,
    data_dir: Path,
    solver_image: str,
    subprocess_timeout_seconds: int = 3600,
) -> LandCoverTile:
    """Return a cached or freshly downloaded LCP tile whose bbox contains the request.

    Args:
        session: Open ORM session (caller commits).
        north, east, south, west: Requested WGS84 bbox (degrees).
        data_dir: Application data root; files go under ``land_cover/`` relative to this.
        solver_image: Docker image with ``fetch_dem`` and GDAL (e.g. ``mountain-windninja:local``).
        subprocess_timeout_seconds: Wall-clock limit for the combined Docker invocation.

    Returns:
        ``LandCoverTile`` with ``file_path`` pointing at the ``.lcp`` relative to ``data_dir``.

    Raises:
        ValueError: Invalid timeout.
        TerrainOutsideUsError: Bbox not fully inside CONUS (from :func:`validate_conus_wgs84_bbox`).
        TerrainLcpError: Docker, ``fetch_dem``, ``gdalsrsinfo``, or metadata read failure.
    """
    if subprocess_timeout_seconds <= 0:
        raise ValueError("subprocess_timeout_seconds must be positive")

    validate_conus_wgs84_bbox(north, east, south, west)

    cached = LandCoverTile.find_containing(session, north, south, east, west)
    if cached is not None:
        return cached

    root = data_dir.resolve()
    land_cover_dir = root / "land_cover"
    land_cover_dir.mkdir(parents=True, exist_ok=True)

    tile_id = uuid.uuid4()
    relative_lcp = Path("land_cover") / f"{tile_id}.lcp"
    absolute_lcp = root / relative_lcp
    absolute_prj = absolute_lcp.with_suffix(".prj")

    try:
        _run_lcp_docker_pipeline(
            solver_image=solver_image,
            host_data_dir=root,
            relative_lcp=relative_lcp,
            north=north,
            east=east,
            south=south,
            west=west,
            subprocess_timeout_seconds=subprocess_timeout_seconds,
        )
    except TerrainLcpError:
        absolute_lcp.unlink(missing_ok=True)
        absolute_prj.unlink(missing_ok=True)
        raise

    if not absolute_lcp.is_file():
        raise TerrainLcpError(f"Expected LCP file was not created: {absolute_lcp}")
    if not absolute_prj.is_file():
        raise TerrainLcpError(f"Expected .prj sidecar was not created: {absolute_prj}")

    try:
        file_north, file_east, file_south, file_west, crs_epsg = _read_land_cover_spatial_metadata(
            absolute_lcp
        )
    except Exception as exc:
        absolute_lcp.unlink(missing_ok=True)
        absolute_prj.unlink(missing_ok=True)
        raise TerrainLcpError("Could not read spatial metadata from LCP") from exc

    north_stored = max(file_north, north)
    south_stored = min(file_south, south)
    east_stored = max(file_east, east)
    west_stored = min(file_west, west)

    file_size_bytes = absolute_lcp.stat().st_size + absolute_prj.stat().st_size

    tile = LandCoverTile(
        id=tile_id,
        bbox_north=north_stored,
        bbox_south=south_stored,
        bbox_east=east_stored,
        bbox_west=west_stored,
        crs_epsg=crs_epsg,
        file_path=relative_lcp.as_posix(),
        source=LAND_COVER_SOURCE_LANDFIRE,
        file_size_bytes=file_size_bytes,
    )
    session.add(tile)
    session.flush()
    return tile
