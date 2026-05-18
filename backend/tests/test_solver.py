"""Tests for services.solver -- public solver orchestrator."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from models.enums import SolverType
from tests.conftest import utc
from services.solver import (
    SolverConfigError,
    SolverExecutionError,
    SolverResult,
    run_solver_for_forecast,
)
from services.solver_config import WindNinjaConfigSpec
from services.solver_runner import SolverTimestepResult
from services.weather import ForcingTimestep, ForecastWeatherGrids
from services.weather_models import HrrrCycle


def _make_fake_elevation_tile(
    file_path: str = "elevation/test-dem.tif",
    *,
    data_dir: Path | None = None,
) -> MagicMock:
    """Create a mock ElevationTile, optionally writing a stub file on disk.

    When ``data_dir`` is provided, the parent directory is created and a
    small placeholder file is written so the solver's pre-flight check passes.
    """
    tile = MagicMock()
    tile.id = uuid.uuid4()
    tile.file_path = file_path
    tile.crs_epsg = 32613

    if data_dir is not None:
        abs_path = data_dir / file_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text("stub DEM")

    return tile


def _make_weather_grids(
    forecast_id: str,
    start: datetime,
    count: int,
) -> ForecastWeatherGrids:
    timesteps = []
    for i in range(count):
        valid_time = start + timedelta(hours=i)
        label = valid_time.strftime("%Y%m%d_%H%M")
        timesteps.append(
            ForcingTimestep(
                valid_time=valid_time,
                speed_grid_path=Path(f"weather/{forecast_id}/speed_{label}.asc"),
                direction_grid_path=Path(f"weather/{forecast_id}/direction_{label}.asc"),
                cycle=HrrrCycle(
                    analysis_time=valid_time,
                    forecast_hour=0,
                    valid_time=valid_time,
                ),
            )
        )
    return ForecastWeatherGrids(
        timesteps=timesteps,
        weather_dir=Path(f"weather/{forecast_id}"),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestRunSolverHappyPath:
    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_returns_solver_result(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        start = utc(2026, 5, 10, 12)
        tile = _make_fake_elevation_tile(data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, start, 3)

        def fake_gen_config(spec, *, host_output_dir):
            filename = f"windninja_{spec.valid_time.strftime('%Y%m%d_%H%M')}.cfg"
            path = host_output_dir / filename
            path.write_text("fake config")
            return path

        mock_gen_config.side_effect = fake_gen_config
        mock_execute.return_value = SolverTimestepResult(
            stdout="ok", stderr="", elapsed_seconds=30.0,
        )

        result = run_solver_for_forecast(
            forecast_id=forecast_id,
            weather_grids=weather,
            elevation_tile=tile,
            solver_type=SolverType.momentum,
            data_dir=tmp_path,
            solver_image="test:latest",
            solver_timeout_seconds=300,
            solver_max_retries=0,
        )

        assert isinstance(result, SolverResult)
        assert len(result.timestep_outputs) == 3
        assert result.output_dir == Path("output") / forecast_id
        assert result.elapsed_seconds > 0

    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_creates_output_directory(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 1)

        mock_gen_config.side_effect = lambda spec, **kw: _fake_config(spec, **kw)
        mock_execute.return_value = SolverTimestepResult(
            stdout="", stderr="", elapsed_seconds=1.0,
        )

        run_solver_for_forecast(
            forecast_id=forecast_id,
            weather_grids=weather,
            elevation_tile=tile,
            solver_type=SolverType.momentum,
            data_dir=tmp_path,
            solver_image="test:latest",
            solver_timeout_seconds=300,
            solver_max_retries=0,
        )

        assert (tmp_path / "output" / forecast_id).is_dir()

    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_writes_metadata_json(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 2)

        mock_gen_config.side_effect = lambda spec, **kw: _fake_config(spec, **kw)
        mock_execute.return_value = SolverTimestepResult(
            stdout="", stderr="", elapsed_seconds=1.0,
        )

        run_solver_for_forecast(
            forecast_id=forecast_id,
            weather_grids=weather,
            elevation_tile=tile,
            solver_type=SolverType.momentum,
            data_dir=tmp_path,
            solver_image="test:latest",
            solver_timeout_seconds=300,
            solver_max_retries=0,
        )

        metadata_path = tmp_path / "output" / forecast_id / "metadata.json"
        assert metadata_path.exists()

        metadata = json.loads(metadata_path.read_text())
        assert metadata["forecast_id"] == forecast_id
        assert metadata["solver_type"] == "momentum"
        assert metadata["initialization_method"] == "griddedInitialization"
        assert metadata["timestep_count"] == 2
        assert len(metadata["timesteps"]) == 2

    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_calls_execute_for_each_timestep(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 4)

        mock_gen_config.side_effect = lambda spec, **kw: _fake_config(spec, **kw)
        mock_execute.return_value = SolverTimestepResult(
            stdout="", stderr="", elapsed_seconds=1.0,
        )

        run_solver_for_forecast(
            forecast_id=forecast_id,
            weather_grids=weather,
            elevation_tile=tile,
            solver_type=SolverType.momentum,
            data_dir=tmp_path,
            solver_image="test:latest",
            solver_timeout_seconds=300,
            solver_max_retries=0,
        )

        assert mock_gen_config.call_count == 4
        assert mock_execute.call_count == 4

    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_config_spec_uses_container_paths(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(file_path="elevation/dem123.tif", data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 1)

        captured_specs: list[WindNinjaConfigSpec] = []

        def capture_config(spec, **kw):
            captured_specs.append(spec)
            return _fake_config(spec, **kw)

        mock_gen_config.side_effect = capture_config
        mock_execute.return_value = SolverTimestepResult(
            stdout="", stderr="", elapsed_seconds=1.0,
        )

        run_solver_for_forecast(
            forecast_id=forecast_id,
            weather_grids=weather,
            elevation_tile=tile,
            solver_type=SolverType.momentum,
            data_dir=tmp_path,
            solver_image="test:latest",
            solver_timeout_seconds=300,
            solver_max_retries=0,
        )

        spec = captured_specs[0]
        assert spec.container_elevation_path == "/data/elevation/dem123.tif"
        assert spec.container_output_dir == f"/data/output/{forecast_id}"
        assert spec.container_speed_grid_path.startswith("/data/weather/")
        assert spec.container_direction_grid_path.startswith("/data/weather/")

    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_mass_conservation_solver_type(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 1)

        captured_specs: list[WindNinjaConfigSpec] = []

        def capture_config(spec, **kw):
            captured_specs.append(spec)
            return _fake_config(spec, **kw)

        mock_gen_config.side_effect = capture_config
        mock_execute.return_value = SolverTimestepResult(
            stdout="", stderr="", elapsed_seconds=1.0,
        )

        run_solver_for_forecast(
            forecast_id=forecast_id,
            weather_grids=weather,
            elevation_tile=tile,
            solver_type=SolverType.mass_conservation,
            data_dir=tmp_path,
            solver_image="test:latest",
            solver_timeout_seconds=300,
            solver_max_retries=0,
        )

        assert captured_specs[0].solver_type == SolverType.mass_conservation


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    @patch("services.solver.cleanup_mesh_cache")
    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_retry_succeeds_on_second_attempt(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        mock_cleanup: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 1)

        mock_gen_config.side_effect = lambda spec, **kw: _fake_config(spec, **kw)

        call_count = 0

        def fail_then_succeed(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SolverExecutionError("mesh corruption")
            return SolverTimestepResult(
                stdout="ok", stderr="", elapsed_seconds=30.0,
            )

        mock_execute.side_effect = fail_then_succeed

        result = run_solver_for_forecast(
            forecast_id=forecast_id,
            weather_grids=weather,
            elevation_tile=tile,
            solver_type=SolverType.momentum,
            data_dir=tmp_path,
            solver_image="test:latest",
            solver_timeout_seconds=300,
            solver_max_retries=2,
        )

        assert isinstance(result, SolverResult)
        assert mock_execute.call_count == 2
        mock_cleanup.assert_called_once()

    @patch("services.solver.cleanup_mesh_cache")
    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_retries_exhausted_raises(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        mock_cleanup: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 1)

        mock_gen_config.side_effect = lambda spec, **kw: _fake_config(spec, **kw)
        mock_execute.side_effect = SolverExecutionError("persistent failure")

        with pytest.raises(SolverExecutionError, match="persistent failure"):
            run_solver_for_forecast(
                forecast_id=forecast_id,
                weather_grids=weather,
                elevation_tile=tile,
                solver_type=SolverType.momentum,
                data_dir=tmp_path,
                solver_image="test:latest",
                solver_timeout_seconds=300,
                solver_max_retries=2,
            )

        # 1 initial + 2 retries = 3 attempts
        assert mock_execute.call_count == 3
        # Mesh cleaned between retries (2 times) + final cleanup in outer handler
        assert mock_cleanup.call_count >= 2


# ---------------------------------------------------------------------------
# Failure cleanup
# ---------------------------------------------------------------------------


class TestFailureCleanup:
    @patch("services.solver.cleanup_mesh_cache")
    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_cleans_output_dir_on_failure(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        mock_cleanup: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 1)

        mock_gen_config.side_effect = lambda spec, **kw: _fake_config(spec, **kw)
        mock_execute.side_effect = SolverExecutionError("Docker crash")

        output_dir = tmp_path / "output" / forecast_id

        with pytest.raises(SolverExecutionError):
            run_solver_for_forecast(
                forecast_id=forecast_id,
                weather_grids=weather,
                elevation_tile=tile,
                solver_type=SolverType.momentum,
                data_dir=tmp_path,
                solver_image="test:latest",
                solver_timeout_seconds=300,
                solver_max_retries=0,
            )

        assert not output_dir.exists()

    @patch("services.solver.cleanup_mesh_cache")
    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_cleans_mesh_cache_on_failure(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        mock_cleanup: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(file_path="elevation/tile99.tif", data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 1)

        mock_gen_config.side_effect = lambda spec, **kw: _fake_config(spec, **kw)
        mock_execute.side_effect = SolverExecutionError("OOM")

        with pytest.raises(SolverExecutionError):
            run_solver_for_forecast(
                forecast_id=forecast_id,
                weather_grids=weather,
                elevation_tile=tile,
                solver_type=SolverType.momentum,
                data_dir=tmp_path,
                solver_image="test:latest",
                solver_timeout_seconds=300,
                solver_max_retries=0,
            )

        mock_cleanup.assert_called()
        cleanup_call = mock_cleanup.call_args
        assert "tile99" in str(cleanup_call)

    @patch("services.solver.cleanup_mesh_cache")
    @patch("services.solver.generate_windninja_config")
    def test_cleans_up_on_config_error(
        self,
        mock_gen_config: MagicMock,
        mock_cleanup: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 1)

        mock_gen_config.side_effect = SolverConfigError("bad config")

        output_dir = tmp_path / "output" / forecast_id

        with pytest.raises(SolverConfigError, match="bad config"):
            run_solver_for_forecast(
                forecast_id=forecast_id,
                weather_grids=weather,
                elevation_tile=tile,
                solver_type=SolverType.momentum,
                data_dir=tmp_path,
                solver_image="test:latest",
                solver_timeout_seconds=300,
                solver_max_retries=0,
            )

        assert not output_dir.exists()


# ---------------------------------------------------------------------------
# Orchestration order
# ---------------------------------------------------------------------------


class TestPreflightChecks:
    def test_missing_elevation_file_raises_config_error(
        self, tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(file_path="elevation/nonexistent.tif")
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 1)

        with pytest.raises(SolverConfigError, match="Elevation file not found"):
            run_solver_for_forecast(
                forecast_id=forecast_id,
                weather_grids=weather,
                elevation_tile=tile,
                solver_type=SolverType.momentum,
                data_dir=tmp_path,
                solver_image="test:latest",
                solver_timeout_seconds=300,
                solver_max_retries=0,
            )


class TestOrchestrationOrder:
    @patch("services.solver.execute_windninja")
    @patch("services.solver.generate_windninja_config")
    def test_config_then_execute_per_timestep(
        self,
        mock_gen_config: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        tile = _make_fake_elevation_tile(data_dir=tmp_path)
        weather = _make_weather_grids(forecast_id, utc(2026, 5, 10, 12), 2)

        call_order: list[str] = []

        def track_config(spec, **kw):
            call_order.append(f"config_{spec.valid_time.hour}")
            return _fake_config(spec, **kw)

        def track_execute(**kw):
            call_order.append("execute")
            return SolverTimestepResult(
                stdout="", stderr="", elapsed_seconds=1.0,
            )

        mock_gen_config.side_effect = track_config
        mock_execute.side_effect = track_execute

        run_solver_for_forecast(
            forecast_id=forecast_id,
            weather_grids=weather,
            elevation_tile=tile,
            solver_type=SolverType.momentum,
            data_dir=tmp_path,
            solver_image="test:latest",
            solver_timeout_seconds=300,
            solver_max_retries=0,
        )

        assert call_order == ["config_12", "execute", "config_13", "execute"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_config(spec: WindNinjaConfigSpec, *, host_output_dir: Path) -> Path:
    filename = f"windninja_{spec.valid_time.strftime('%Y%m%d_%H%M')}.cfg"
    path = host_output_dir / filename
    path.write_text("fake config")
    return path
