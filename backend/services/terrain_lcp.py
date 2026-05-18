"""LANDFIRE LCP download for Phase 2 (continental US only).

Runs WindNinja ``fetch_dem --src lcp`` inside the solver Docker image to fetch
an LCP file and generate a ``.prj`` sidecar (WindNinja requires it). Cache
management, metadata extraction, and database interaction are handled by the
terrain orchestrator in :mod:`services.terrain`.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path

from config import CONTAINER_DATA_ROOT
from services.terrain_geometry import Wgs84BoundingBox

logger = logging.getLogger(__name__)

LAND_COVER_SOURCE_LANDFIRE = "landfire"


class TerrainLcpError(RuntimeError):
    """LCP fetch via Docker / fetch_dem or post-processing failed."""


def _run_lcp_docker_pipeline(
    *,
    solver_image: str,
    host_data_dir: Path,
    relative_lcp: Path,
    download: Wgs84BoundingBox,
    subprocess_timeout_seconds: int,
) -> None:
    """Run ``fetch_dem`` and ``gdalsrsinfo`` in Docker (``solver_image``).

    Mounts ``host_data_dir`` read-write at ``/data`` in the container.
    """
    root = host_data_dir.resolve()
    mount = f"{root}:{CONTAINER_DATA_ROOT}"
    container_lcp = (CONTAINER_DATA_ROOT / relative_lcp).as_posix()
    container_prj = (CONTAINER_DATA_ROOT / relative_lcp).with_suffix(".prj").as_posix()

    inner_script = (
        f"fetch_dem --bbox {download.north} {download.east} {download.south} {download.west} "
        f"--src lcp {shlex.quote(container_lcp)}"
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
    logger.debug("LCP Docker command: %s", command)
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


def download_land_cover_raster(
    download_bbox: Wgs84BoundingBox,
    *,
    host_data_dir: Path,
    relative_lcp: Path,
    solver_image: str,
    timeout_seconds: int,
) -> None:
    """Run the Docker pipeline to fetch an LCP file and ``.prj`` sidecar.

    ``host_data_dir`` is mounted read-write at ``/data`` in the container.
    ``relative_lcp`` is the path of the output ``.lcp`` relative to
    ``host_data_dir`` (e.g. ``Path("land_cover/uuid.lcp")``). The parent
    directory must already exist.

    Does not create directories, generate IDs, or interact with the database.

    Raises:
        TerrainLcpError: Docker not found, timeout, non-zero exit, or output
            files missing after a successful run.
    """
    absolute_lcp = host_data_dir.resolve() / relative_lcp
    absolute_prj = absolute_lcp.with_suffix(".prj")

    logger.info(
        "Downloading LCP via Docker: bbox=%s solver_image=%s timeout=%ds",
        download_bbox,
        solver_image,
        timeout_seconds,
    )

    _run_lcp_docker_pipeline(
        solver_image=solver_image,
        host_data_dir=host_data_dir,
        relative_lcp=relative_lcp,
        download=download_bbox,
        subprocess_timeout_seconds=timeout_seconds,
    )

    if not absolute_lcp.is_file():
        raise TerrainLcpError(f"Expected LCP file was not created: {absolute_lcp}")
    if not absolute_prj.is_file():
        raise TerrainLcpError(f"Expected .prj sidecar was not created: {absolute_prj}")

    logger.info("LCP written: path=%s (with .prj sidecar)", absolute_lcp)
