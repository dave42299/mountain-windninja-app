"""Tests for services.solver_runner -- Docker execution and mesh cache cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.solver_runner import (
    SolverExecutionError,
    SolverTimestepResult,
    cleanup_mesh_cache,
    execute_windninja,
)


# ---------------------------------------------------------------------------
# execute_windninja -- happy path
# ---------------------------------------------------------------------------


class TestExecuteWindNinjaSuccess:
    @patch("services.solver_runner.subprocess.run")
    def test_returns_timestep_result(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(
            stdout="WindNinja complete", stderr="", returncode=0,
        )

        result = execute_windninja(
            container_config_path="/data/output/fid/windninja_20260510_1200.cfg",
            solver_image="mountain-windninja:local",
            host_data_dir=tmp_path,
            timeout_seconds=300,
        )

        assert isinstance(result, SolverTimestepResult)
        assert result.stdout == "WindNinja complete"
        assert result.stderr == ""
        assert result.elapsed_seconds > 0

    @patch("services.solver_runner.subprocess.run")
    def test_docker_command_structure(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)

        execute_windninja(
            container_config_path="/data/output/fid/config.cfg",
            solver_image="my-solver:v1",
            host_data_dir=tmp_path,
            timeout_seconds=600,
        )

        mock_run.assert_called_once()
        args = mock_run.call_args
        command = args[0][0]

        assert command[0] == "docker"
        assert command[1] == "run"
        assert "--rm" in command
        assert "my-solver:v1" in command
        assert "bash" in command
        assert args.kwargs["check"] is True
        assert args.kwargs["timeout"] == 600
        assert args.kwargs["capture_output"] is True

    @patch("services.solver_runner.subprocess.run")
    def test_volume_mount(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)

        execute_windninja(
            container_config_path="/data/output/fid/config.cfg",
            solver_image="test:latest",
            host_data_dir=tmp_path,
            timeout_seconds=300,
        )

        command = mock_run.call_args[0][0]
        mount_idx = command.index("-v")
        mount_arg = command[mount_idx + 1]
        assert mount_arg.startswith(str(tmp_path.resolve()))
        assert mount_arg.endswith(":/data")

    @patch("services.solver_runner.subprocess.run")
    def test_container_has_unique_name(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)

        execute_windninja(
            container_config_path="/data/output/fid/config.cfg",
            solver_image="test:latest",
            host_data_dir=tmp_path,
            timeout_seconds=300,
        )

        command = mock_run.call_args[0][0]
        name_idx = command.index("--name")
        container_name = command[name_idx + 1]
        assert container_name.startswith("windninja-")
        assert len(container_name) > len("windninja-")

    @patch("services.solver_runner.subprocess.run")
    def test_openfoam_bashrc_sourced(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """OpenFOAM bashrc must be sourced with error suppression (AGENTS.md gotcha #4)."""
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)

        execute_windninja(
            container_config_path="/data/output/fid/config.cfg",
            solver_image="test:latest",
            host_data_dir=tmp_path,
            timeout_seconds=300,
        )

        command = mock_run.call_args[0][0]
        inner_script = command[-1]
        assert "source /opt/openfoam9/etc/bashrc 2>/dev/null || true" in inner_script
        assert "WindNinja_cli /data/output/fid/config.cfg" in inner_script


# ---------------------------------------------------------------------------
# execute_windninja -- error handling
# ---------------------------------------------------------------------------


class TestExecuteWindNinjaErrors:
    @patch("services.solver_runner.subprocess.run")
    def test_docker_not_found(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.side_effect = FileNotFoundError("docker not found")

        with pytest.raises(SolverExecutionError, match="Docker CLI not found"):
            execute_windninja(
                container_config_path="/data/output/fid/config.cfg",
                solver_image="test:latest",
                host_data_dir=tmp_path,
                timeout_seconds=300,
            )

    @patch("services.solver_runner._kill_container")
    @patch("services.solver_runner.subprocess.run")
    def test_timeout_kills_container(
        self, mock_run: MagicMock, mock_kill: MagicMock, tmp_path: Path,
    ) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=300)

        with pytest.raises(SolverExecutionError, match="timed out"):
            execute_windninja(
                container_config_path="/data/output/fid/config.cfg",
                solver_image="test:latest",
                host_data_dir=tmp_path,
                timeout_seconds=300,
            )

        mock_kill.assert_called_once()
        container_name = mock_kill.call_args[0][0]
        assert container_name.startswith("windninja-")

    @patch("services.solver_runner.subprocess.run")
    def test_nonzero_exit_with_stderr(self, mock_run: MagicMock, tmp_path: Path) -> None:
        err = subprocess.CalledProcessError(returncode=1, cmd="docker")
        err.stderr = "Can't open log.ninja"
        err.stdout = ""
        mock_run.side_effect = err

        with pytest.raises(SolverExecutionError, match="Can't open log.ninja"):
            execute_windninja(
                container_config_path="/data/output/fid/config.cfg",
                solver_image="test:latest",
                host_data_dir=tmp_path,
                timeout_seconds=300,
            )

    @patch("services.solver_runner.subprocess.run")
    def test_nonzero_exit_with_stdout_fallback(
        self, mock_run: MagicMock, tmp_path: Path,
    ) -> None:
        err = subprocess.CalledProcessError(returncode=1, cmd="docker")
        err.stderr = ""
        err.stdout = "Segmentation fault"
        mock_run.side_effect = err

        with pytest.raises(SolverExecutionError, match="Segmentation fault"):
            execute_windninja(
                container_config_path="/data/output/fid/config.cfg",
                solver_image="test:latest",
                host_data_dir=tmp_path,
                timeout_seconds=300,
            )

    @patch("services.solver_runner.subprocess.run")
    def test_nonzero_exit_code_fallback(
        self, mock_run: MagicMock, tmp_path: Path,
    ) -> None:
        err = subprocess.CalledProcessError(returncode=137, cmd="docker")
        err.stderr = ""
        err.stdout = ""
        mock_run.side_effect = err

        with pytest.raises(SolverExecutionError, match="exit code 137"):
            execute_windninja(
                container_config_path="/data/output/fid/config.cfg",
                solver_image="test:latest",
                host_data_dir=tmp_path,
                timeout_seconds=300,
            )


# ---------------------------------------------------------------------------
# cleanup_mesh_cache
# ---------------------------------------------------------------------------


class TestCleanupMeshCache:
    def test_removes_matching_directories(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "NINJAFOAM_abc123_4"
        cache_dir.mkdir()
        (cache_dir / "system").mkdir()
        (cache_dir / "system" / "controlDict").write_text("dummy")

        removed = cleanup_mesh_cache(tmp_path, "abc123")

        assert removed == 1
        assert not cache_dir.exists()

    def test_removes_multiple_matching_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "NINJAFOAM_abc123_4").mkdir()
        (tmp_path / "NINJAFOAM_abc123_8").mkdir()

        removed = cleanup_mesh_cache(tmp_path, "abc123")

        assert removed == 2

    def test_ignores_non_matching_directories(self, tmp_path: Path) -> None:
        (tmp_path / "NINJAFOAM_abc123_4").mkdir()
        (tmp_path / "NINJAFOAM_other_tile_4").mkdir()

        removed = cleanup_mesh_cache(tmp_path, "abc123")

        assert removed == 1
        assert (tmp_path / "NINJAFOAM_other_tile_4").exists()

    def test_ignores_files_with_matching_names(self, tmp_path: Path) -> None:
        (tmp_path / "NINJAFOAM_abc123_info.txt").write_text("not a dir")

        removed = cleanup_mesh_cache(tmp_path, "abc123")

        assert removed == 0
        assert (tmp_path / "NINJAFOAM_abc123_info.txt").exists()

    def test_no_op_when_no_cache_exists(self, tmp_path: Path) -> None:
        removed = cleanup_mesh_cache(tmp_path, "nonexistent")

        assert removed == 0
