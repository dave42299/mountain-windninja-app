"""Docker-based WindNinja solver execution.

Runs ``WindNinja_cli`` inside the solver Docker image via ``subprocess``.
Handles Docker startup, OpenFOAM environment sourcing, timeout, and error
reporting.  Also provides mesh cache cleanup for recovery after failed runs.

Volume mount convention (shared with :mod:`services.terrain_lcp`):
    Host ``data/`` is mounted read-write at ``/data`` in the container.

Reference implementation:
    ``mountain_windninja/scripts/windninja_runner.py``
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
import uuid as uuid_mod
from dataclasses import dataclass
from pathlib import Path

from config import CONTAINER_DATA_ROOT

logger = logging.getLogger(__name__)


class SolverExecutionError(RuntimeError):
    """WindNinja solver execution failed (Docker error, timeout, non-zero exit)."""


@dataclass(frozen=True)
class SolverTimestepResult:
    """Result of a single WindNinja invocation."""

    stdout: str
    stderr: str
    elapsed_seconds: float


def execute_windninja(
    *,
    container_config_path: str,
    solver_image: str,
    host_data_dir: Path,
    timeout_seconds: int,
) -> SolverTimestepResult:
    """Run WindNinja_cli inside the solver Docker container.

    Mounts ``host_data_dir`` read-write at ``/data``.  The config file and all
    paths it references must be under ``/data`` inside the container.

    OpenFOAM's bashrc is sourced with error suppression per AGENTS.md gotcha #4
    (unbound variables crash ``set -eu``).

    Args:
        container_config_path: Absolute path to the .cfg **inside** the
            container (e.g. ``/data/output/{fid}/windninja_*.cfg``).
        solver_image: Docker image name (e.g. ``mountain-windninja:local``).
        host_data_dir: Resolved host path to the application data root.
        timeout_seconds: Per-invocation timeout.

    Returns:
        :class:`SolverTimestepResult` with captured stdout/stderr.

    Raises:
        SolverExecutionError: Docker not found, timeout, or non-zero exit.
    """
    mount = f"{host_data_dir.resolve()}:{CONTAINER_DATA_ROOT}"
    container_name = f"windninja-{uuid_mod.uuid4().hex[:12]}"

    inner_script = (
        "source /opt/openfoam9/etc/bashrc 2>/dev/null || true && "
        f"WindNinja_cli {container_config_path}"
    )
    command = [
        "docker", "run", "--rm",
        "--name", container_name,
        "-v", mount,
        solver_image,
        "bash", "-lc", inner_script,
    ]

    logger.info(
        "Launching WindNinja: image=%s config=%s timeout=%ds container=%s",
        solver_image,
        container_config_path,
        timeout_seconds,
        container_name,
    )
    logger.debug("Docker command: %s", command)

    t_start = time.monotonic()

    try:
        result = subprocess.run(
            command,
            check=True,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SolverExecutionError(
            "Docker CLI not found; install Docker and ensure `docker` is on PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        _kill_container(container_name)
        raise SolverExecutionError(
            f"WindNinja solver timed out after {timeout_seconds} seconds. "
            f"Consider increasing solver_timeout_seconds or reducing domain size."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr_text = (exc.stderr or "").strip()
        stdout_text = (exc.stdout or "").strip()
        detail = stderr_text or stdout_text or f"exit code {exc.returncode}"
        raise SolverExecutionError(
            f"WindNinja solver failed: {detail}"
        ) from exc

    elapsed = time.monotonic() - t_start
    logger.info("WindNinja completed: elapsed=%.1fs", elapsed)

    return SolverTimestepResult(
        stdout=result.stdout,
        stderr=result.stderr,
        elapsed_seconds=elapsed,
    )


def cleanup_mesh_cache(
    host_elevation_dir: Path,
    elevation_filename_stem: str,
) -> int:
    """Remove NINJAFOAM mesh cache directories for a given elevation tile.

    WindNinja creates ``NINJAFOAM_{elevation_stem}_*`` directories next to the
    elevation file.  A corrupted mesh cache (from a failed run) causes all
    subsequent runs to fail with ``Can't open log.ninja`` (AGENTS.md gotcha #1).

    Args:
        host_elevation_dir: Directory containing the elevation file.
        elevation_filename_stem: Stem of the elevation filename (e.g. UUID).

    Returns:
        Number of directories removed.
    """
    pattern = f"NINJAFOAM_{elevation_filename_stem}*"
    removed = 0

    for entry in host_elevation_dir.glob(pattern):
        if entry.is_dir():
            logger.warning("Removing mesh cache: %s", entry)
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1

    if removed:
        logger.info(
            "Cleaned %d mesh cache director%s for %s",
            removed,
            "y" if removed == 1 else "ies",
            elevation_filename_stem,
        )

    return removed


def _kill_container(container_name: str) -> None:
    """Best-effort kill of a Docker container after a timeout.

    The ``--rm`` flag on ``docker run`` ensures the container is removed
    once killed.  Errors are logged but not raised because the primary
    error (timeout) is already being reported by the caller.
    """
    try:
        subprocess.run(
            ["docker", "kill", container_name],
            timeout=30,
            capture_output=True,
            text=True,
        )
        logger.info("Killed timed-out container: %s", container_name)
    except Exception:
        logger.warning(
            "Failed to kill container %s (may have already exited)",
            container_name,
        )
