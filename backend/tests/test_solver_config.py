"""Tests for services.solver_config -- WindNinja .cfg generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from models.enums import SolverType
from services.solver_config import (
    INPUT_WIND_HEIGHT_M,
    SolverConfigError,
    WindNinjaConfigSpec,
    generate_windninja_config,
)


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _make_spec(**overrides) -> WindNinjaConfigSpec:
    defaults = {
        "container_elevation_path": "/data/elevation/abc123.tif",
        "container_speed_grid_path": "/data/weather/fid/speed_20260510_1200.asc",
        "container_direction_grid_path": "/data/weather/fid/direction_20260510_1200.asc",
        "container_output_dir": "/data/output/fid",
        "valid_time": _utc(2026, 5, 10, 12),
        "solver_type": SolverType.momentum,
        "output_wind_height": 10.0,
        "mesh_resolution": 100.0,
        "num_threads": 4,
        "vegetation": "trees",
    }
    defaults.update(overrides)
    return WindNinjaConfigSpec(**defaults)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestGenerateConfig:
    def test_writes_cfg_file(self, tmp_path: Path) -> None:
        spec = _make_spec()
        result = generate_windninja_config(spec, host_output_dir=tmp_path)

        assert result.exists()
        assert result.suffix == ".cfg"
        assert result.parent == tmp_path

    def test_default_filename_contains_timestamp(self, tmp_path: Path) -> None:
        spec = _make_spec(valid_time=_utc(2026, 5, 10, 14, 30))
        result = generate_windninja_config(spec, host_output_dir=tmp_path)

        assert result.name == "windninja_20260510_1430.cfg"

    def test_custom_filename(self, tmp_path: Path) -> None:
        spec = _make_spec()
        result = generate_windninja_config(
            spec, host_output_dir=tmp_path, config_filename="custom.cfg",
        )

        assert result.name == "custom.cfg"

    def test_gridded_initialization(self, tmp_path: Path) -> None:
        spec = _make_spec()
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "initialization_method = griddedInitialization" in content
        assert "input_speed_grid = /data/weather/fid/speed_20260510_1200.asc" in content
        assert "input_dir_grid = /data/weather/fid/direction_20260510_1200.asc" in content
        assert "input_speed_units = mps" in content

    def test_elevation_file_is_container_path(self, tmp_path: Path) -> None:
        spec = _make_spec(container_elevation_path="/data/elevation/tile99.tif")
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "elevation_file = /data/elevation/tile99.tif" in content

    def test_output_path_is_container_path(self, tmp_path: Path) -> None:
        spec = _make_spec(container_output_dir="/data/output/my-forecast")
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "output_path = /data/output/my-forecast" in content

    def test_vegetation_parameter(self, tmp_path: Path) -> None:
        spec = _make_spec(vegetation="grass")
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "vegetation = grass" in content

    def test_input_wind_height_uses_constant(self, tmp_path: Path) -> None:
        spec = _make_spec()
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert f"input_wind_height = {INPUT_WIND_HEIGHT_M}" in content

    def test_diurnal_winds_always_false(self, tmp_path: Path) -> None:
        spec = _make_spec()
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "diurnal_winds = false" in content

    def test_datetime_fields(self, tmp_path: Path) -> None:
        spec = _make_spec(valid_time=_utc(2026, 1, 3, 18, 0))
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "year  = 2026" in content
        assert "month = 1" in content
        assert "day   = 3" in content
        assert "hour  = 18" in content
        assert "minute = 0" in content
        assert "time_zone = UTC" in content


# ---------------------------------------------------------------------------
# Momentum vs mass conservation
# ---------------------------------------------------------------------------


class TestSolverType:
    def test_momentum_flag_true(self, tmp_path: Path) -> None:
        spec = _make_spec(solver_type=SolverType.momentum)
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "momentum_flag = true" in content
        assert "number_of_iterations = 300" in content

    def test_mass_conservation_flag_false(self, tmp_path: Path) -> None:
        spec = _make_spec(solver_type=SolverType.mass_conservation)
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "momentum_flag = false" in content
        assert "number_of_iterations" not in content

    def test_num_threads(self, tmp_path: Path) -> None:
        spec = _make_spec(num_threads=6)
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "num_threads = 6" in content

    def test_mesh_resolution(self, tmp_path: Path) -> None:
        spec = _make_spec(mesh_resolution=50.0)
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "mesh_resolution = 50.0" in content

    def test_output_wind_height(self, tmp_path: Path) -> None:
        spec = _make_spec(output_wind_height=5.0)
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "output_wind_height = 5.0" in content


# ---------------------------------------------------------------------------
# Output format flags
# ---------------------------------------------------------------------------


class TestOutputFormats:
    def test_ascii_output_enabled(self, tmp_path: Path) -> None:
        spec = _make_spec()
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "write_ascii_output = true" in content
        assert "ascii_out_resolution = -1" in content

    def test_kml_output_disabled(self, tmp_path: Path) -> None:
        spec = _make_spec()
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "write_goog_output = false" in content

    def test_shapefile_disabled(self, tmp_path: Path) -> None:
        spec = _make_spec()
        result = generate_windninja_config(spec, host_output_dir=tmp_path)
        content = result.read_text()

        assert "write_shapefile_output = false" in content


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_zero_threads_raises(self, tmp_path: Path) -> None:
        spec = _make_spec(num_threads=0)
        with pytest.raises(SolverConfigError, match="num_threads"):
            generate_windninja_config(spec, host_output_dir=tmp_path)

    def test_negative_mesh_resolution_raises(self, tmp_path: Path) -> None:
        spec = _make_spec(mesh_resolution=-10.0)
        with pytest.raises(SolverConfigError, match="mesh_resolution"):
            generate_windninja_config(spec, host_output_dir=tmp_path)

    def test_zero_output_wind_height_raises(self, tmp_path: Path) -> None:
        spec = _make_spec(output_wind_height=0)
        with pytest.raises(SolverConfigError, match="output_wind_height"):
            generate_windninja_config(spec, host_output_dir=tmp_path)

    def test_empty_elevation_path_raises(self, tmp_path: Path) -> None:
        spec = _make_spec(container_elevation_path="")
        with pytest.raises(SolverConfigError, match="elevation_path"):
            generate_windninja_config(spec, host_output_dir=tmp_path)

    def test_empty_speed_grid_path_raises(self, tmp_path: Path) -> None:
        spec = _make_spec(container_speed_grid_path="")
        with pytest.raises(SolverConfigError, match="speed_grid_path"):
            generate_windninja_config(spec, host_output_dir=tmp_path)

    def test_empty_direction_grid_path_raises(self, tmp_path: Path) -> None:
        spec = _make_spec(container_direction_grid_path="")
        with pytest.raises(SolverConfigError, match="direction_grid_path"):
            generate_windninja_config(spec, host_output_dir=tmp_path)
