"""Tests for the wind-field data service and API endpoint.

Covers:
- ESRI ASCII grid parsing (synthetic small grids)
- Speed/direction → U/V conversion (meteorological convention)
- UTM → WGS84 bounds computation
- Output grid discovery and PASTCAST filtering
- Metadata validation
- API endpoint guards (404, 409, timestep out of range)
- Happy-path API integration
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from config import Settings
from models.enums import ForecastStatus
from services.wind_field import (
    WindFieldBounds,
    WindFieldGridError,
    WindFieldMetadataError,
    WindFieldTimestepError,
    _AsciiGridHeader,
    _compute_wgs84_bounds,
    _convert_speed_direction_to_uv,
    _discover_output_grids,
    _parse_ascii_grid,
    _read_metadata,
    load_wind_field,
    MPH_TO_MPS,
)
from tests.conftest import insert_forecast, insert_tiles


# ---------------------------------------------------------------------------
# Helpers for building synthetic test data
# ---------------------------------------------------------------------------


def _make_ascii_grid(
    ncols: int = 3,
    nrows: int = 2,
    xllcorner: float = 450000.0,
    yllcorner: float = 4400000.0,
    cellsize: float = 100.0,
    nodata_value: float = -9999.0,
    data: list[list[float]] | None = None,
) -> str:
    """Build an ESRI ASCII grid string for testing."""
    if data is None:
        data = [
            [1.0 * (r * ncols + c) for c in range(ncols)]
            for r in range(nrows)
        ]
    lines = [
        f"ncols         {ncols}",
        f"nrows         {nrows}",
        f"xllcorner     {xllcorner}",
        f"yllcorner     {yllcorner}",
        f"cellsize      {cellsize}",
        f"NODATA_value  {nodata_value}",
    ]
    for row in data:
        lines.append(" ".join(f"{v}" for v in row))
    return "\n".join(lines) + "\n"


def _make_metadata(
    output_dir: Path,
    *,
    crs_epsg: int = 32613,
    timestep_count: int = 2,
    valid_times: list[str] | None = None,
) -> Path:
    """Write a minimal metadata.json for testing."""
    if valid_times is None:
        valid_times = [
            "2026-05-15T06:00:00+00:00",
            "2026-05-15T07:00:00+00:00",
        ]
    metadata = {
        "forecast_id": str(uuid.uuid4()),
        "solver_type": "momentum",
        "initialization_method": "griddedInitialization",
        "elevation_tile_id": str(uuid.uuid4()),
        "elevation_file": "elevation/test.tif",
        "elevation_crs_epsg": crs_epsg,
        "output_wind_height_m": 10.0,
        "output_speed_units": "mph",
        "mesh_resolution_m": 100.0,
        "vegetation": "trees",
        "timestep_count": timestep_count,
        "timesteps": [
            {
                "valid_time": vt,
                "speed_grid": f"speed_{i}.asc",
                "direction_grid": f"direction_{i}.asc",
            }
            for i, vt in enumerate(valid_times)
        ],
    }
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata_path


def _write_test_grids(
    output_dir: Path,
    stem: str = "test_100_20260515T0600",
    ncols: int = 3,
    nrows: int = 2,
    speed_data: list[list[float]] | None = None,
    direction_data: list[list[float]] | None = None,
) -> tuple[Path, Path]:
    """Write a paired vel/ang ASCII grid for testing."""
    if speed_data is None:
        speed_data = [[10.0, 20.0, 30.0], [5.0, 15.0, 25.0]]
    if direction_data is None:
        direction_data = [[0.0, 90.0, 180.0], [270.0, 45.0, 315.0]]

    vel_path = output_dir / f"{stem}_vel.asc"
    ang_path = output_dir / f"{stem}_ang.asc"
    vel_path.write_text(
        _make_ascii_grid(ncols=ncols, nrows=nrows, data=speed_data),
        encoding="utf-8",
    )
    ang_path.write_text(
        _make_ascii_grid(ncols=ncols, nrows=nrows, data=direction_data),
        encoding="utf-8",
    )
    return vel_path, ang_path


# ---------------------------------------------------------------------------
# _parse_ascii_grid
# ---------------------------------------------------------------------------


class TestParseAsciiGrid:
    def test_parses_valid_grid(self, tmp_path: Path) -> None:
        data = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        grid_text = _make_ascii_grid(ncols=3, nrows=2, data=data)
        grid_path = tmp_path / "test.asc"
        grid_path.write_text(grid_text)

        header, values = _parse_ascii_grid(grid_path)
        assert header.ncols == 3
        assert header.nrows == 2
        assert header.xllcorner == 450000.0
        assert header.yllcorner == 4400000.0
        assert header.cellsize == 100.0
        assert values == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]

    def test_rejects_too_few_lines(self, tmp_path: Path) -> None:
        grid_path = tmp_path / "short.asc"
        grid_path.write_text("ncols 3\nnrows 2\n")

        with pytest.raises(WindFieldGridError, match="only 2 lines"):
            _parse_ascii_grid(grid_path)

    def test_rejects_wrong_column_count(self, tmp_path: Path) -> None:
        grid_text = _make_ascii_grid(ncols=3, nrows=1, data=[[1.0, 2.0]])
        grid_path = tmp_path / "bad_cols.asc"
        grid_path.write_text(grid_text)

        with pytest.raises(WindFieldGridError, match="row 0 has 2 values"):
            _parse_ascii_grid(grid_path)

    def test_rejects_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(WindFieldGridError, match="Cannot read"):
            _parse_ascii_grid(tmp_path / "nonexistent.asc")

    def test_handles_default_nodata(self, tmp_path: Path) -> None:
        lines = [
            "ncols         2",
            "nrows         1",
            "xllcorner     0",
            "yllcorner     0",
            "cellsize      1",
            "NODATA_value  -9999",
            "1.0 -9999",
        ]
        grid_path = tmp_path / "nodata.asc"
        grid_path.write_text("\n".join(lines))

        header, values = _parse_ascii_grid(grid_path)
        assert header.nodata_value == -9999.0
        assert values == [1.0, -9999.0]


# ---------------------------------------------------------------------------
# _convert_speed_direction_to_uv
# ---------------------------------------------------------------------------


class TestConvertSpeedDirectionToUV:
    def test_north_wind(self) -> None:
        """Wind from the north (0°): u=0, v=-speed."""
        u, v, s_min, s_max = _convert_speed_direction_to_uv(
            [10.0], [0.0], -9999.0,
        )
        speed_mps = 10.0 * MPH_TO_MPS
        assert len(u) == 1
        assert abs(u[0]) < 1e-10
        assert abs(v[0] - (-speed_mps)) < 1e-10
        assert abs(s_min - speed_mps) < 1e-10
        assert abs(s_max - speed_mps) < 1e-10

    def test_east_wind(self) -> None:
        """Wind from the east (90°): u=-speed, v=0."""
        u, v, _, _ = _convert_speed_direction_to_uv(
            [10.0], [90.0], -9999.0,
        )
        speed_mps = 10.0 * MPH_TO_MPS
        assert abs(u[0] - (-speed_mps)) < 1e-10
        assert abs(v[0]) < 1e-10

    def test_south_wind(self) -> None:
        """Wind from the south (180°): u=0, v=+speed."""
        u, v, _, _ = _convert_speed_direction_to_uv(
            [10.0], [180.0], -9999.0,
        )
        speed_mps = 10.0 * MPH_TO_MPS
        assert abs(u[0]) < 1e-10
        assert abs(v[0] - speed_mps) < 1e-10

    def test_west_wind(self) -> None:
        """Wind from the west (270°): u=+speed, v=0."""
        u, v, _, _ = _convert_speed_direction_to_uv(
            [10.0], [270.0], -9999.0,
        )
        speed_mps = 10.0 * MPH_TO_MPS
        assert abs(u[0] - speed_mps) < 1e-10
        assert abs(v[0]) < 1e-10

    def test_nodata_produces_zero(self) -> None:
        u, v, s_min, s_max = _convert_speed_direction_to_uv(
            [-9999.0], [-9999.0], -9999.0,
        )
        assert u == [0.0]
        assert v == [0.0]
        assert s_min == 0.0
        assert s_max == 0.0

    def test_mixed_values_track_min_max(self) -> None:
        speeds_mph = [5.0, 20.0, 10.0]
        directions = [0.0, 0.0, 0.0]
        _, _, s_min, s_max = _convert_speed_direction_to_uv(
            speeds_mph, directions, -9999.0,
        )
        assert abs(s_min - 5.0 * MPH_TO_MPS) < 1e-10
        assert abs(s_max - 20.0 * MPH_TO_MPS) < 1e-10

    def test_speed_unit_conversion(self) -> None:
        """Verify mph → m/s conversion factor."""
        u, v, _, _ = _convert_speed_direction_to_uv(
            [100.0], [0.0], -9999.0,
        )
        expected_mps = 100.0 * 0.44704
        assert abs(v[0] - (-expected_mps)) < 1e-6

    def test_45_degree_wind(self) -> None:
        """Wind from 45° (NE): both u and v should be negative."""
        u, v, _, _ = _convert_speed_direction_to_uv(
            [10.0], [45.0], -9999.0,
        )
        speed_mps = 10.0 * MPH_TO_MPS
        expected_component = speed_mps * math.sin(math.radians(45))
        assert abs(u[0] - (-expected_component)) < 1e-10
        assert abs(v[0] - (-expected_component)) < 1e-10


# ---------------------------------------------------------------------------
# _compute_wgs84_bounds
# ---------------------------------------------------------------------------


class TestComputeWgs84Bounds:
    def test_utm_13n_berthoud_area(self) -> None:
        """Berthoud Pass area in UTM Zone 13N should produce reasonable WGS84 bounds."""
        header = _AsciiGridHeader(
            ncols=100,
            nrows=100,
            xllcorner=438000.0,
            yllcorner=4405000.0,
            cellsize=100.0,
            nodata_value=-9999.0,
        )
        bounds = _compute_wgs84_bounds(header, crs_epsg=32613)

        assert -106.0 < bounds.west < -105.5
        assert -106.0 < bounds.east < -105.5
        assert bounds.west < bounds.east
        assert 39.5 < bounds.south < 40.0
        assert 39.5 < bounds.north < 40.0
        assert bounds.south < bounds.north

    def test_small_grid_has_nonzero_extent(self) -> None:
        header = _AsciiGridHeader(
            ncols=10,
            nrows=10,
            xllcorner=500000.0,
            yllcorner=4400000.0,
            cellsize=100.0,
            nodata_value=-9999.0,
        )
        bounds = _compute_wgs84_bounds(header, crs_epsg=32613)
        assert bounds.east > bounds.west
        assert bounds.north > bounds.south


# ---------------------------------------------------------------------------
# _discover_output_grids
# ---------------------------------------------------------------------------


class TestDiscoverOutputGrids:
    def test_finds_vel_files_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "test_20260515T0700_vel.asc").write_text("data")
        (tmp_path / "test_20260515T0600_vel.asc").write_text("data")
        (tmp_path / "test_20260515T0600_ang.asc").write_text("data")
        (tmp_path / "metadata.json").write_text("{}")

        result = _discover_output_grids(tmp_path)
        assert len(result) == 2
        assert result[0].name == "test_20260515T0600_vel.asc"
        assert result[1].name == "test_20260515T0700_vel.asc"

    def test_excludes_pastcast_files(self, tmp_path: Path) -> None:
        (tmp_path / "test_20260515T0600_vel.asc").write_text("data")
        (tmp_path / "PASTCAST-HRRR_20260515_vel.asc").write_text("data")

        result = _discover_output_grids(tmp_path)
        assert len(result) == 1
        assert result[0].name == "test_20260515T0600_vel.asc"

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = _discover_output_grids(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# _read_metadata
# ---------------------------------------------------------------------------


class TestReadMetadata:
    def test_reads_valid_metadata(self, tmp_path: Path) -> None:
        _make_metadata(tmp_path)
        metadata = _read_metadata(tmp_path)
        assert metadata["elevation_crs_epsg"] == 32613
        assert metadata["timestep_count"] == 2
        assert len(metadata["timesteps"]) == 2

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(WindFieldMetadataError, match="not found"):
            _read_metadata(tmp_path)

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        (tmp_path / "metadata.json").write_text("not json!!!")
        with pytest.raises(WindFieldMetadataError, match="Failed to parse"):
            _read_metadata(tmp_path)

    def test_missing_required_key_raises(self, tmp_path: Path) -> None:
        (tmp_path / "metadata.json").write_text('{"foo": "bar"}')
        with pytest.raises(WindFieldMetadataError, match="missing required key"):
            _read_metadata(tmp_path)


# ---------------------------------------------------------------------------
# load_wind_field (integration)
# ---------------------------------------------------------------------------


class TestLoadWindField:
    def test_happy_path(self, tmp_path: Path) -> None:
        _make_metadata(tmp_path, timestep_count=2)
        _write_test_grids(
            tmp_path,
            stem="test_100_20260515T0600",
            speed_data=[[10.0, 20.0, 30.0], [5.0, 15.0, 25.0]],
            direction_data=[[0.0, 90.0, 180.0], [270.0, 45.0, 315.0]],
        )
        _write_test_grids(
            tmp_path,
            stem="test_100_20260515T0700",
            speed_data=[[12.0, 22.0, 32.0], [7.0, 17.0, 27.0]],
            direction_data=[[0.0, 90.0, 180.0], [270.0, 45.0, 315.0]],
        )

        result = load_wind_field(tmp_path, timestep_index=0)
        assert result.width == 3
        assert result.height == 2
        assert result.timestep_index == 0
        assert result.timestep_count == 2
        assert len(result.u) == 6
        assert len(result.v) == 6
        assert result.speed_min >= 0
        assert result.speed_max > result.speed_min
        assert result.bounds.west < result.bounds.east
        assert result.bounds.south < result.bounds.north
        assert result.valid_time == datetime(2026, 5, 15, 6, 0, tzinfo=timezone.utc)

    def test_second_timestep(self, tmp_path: Path) -> None:
        _make_metadata(tmp_path, timestep_count=2)
        _write_test_grids(tmp_path, stem="test_100_20260515T0600")
        _write_test_grids(tmp_path, stem="test_100_20260515T0700")

        result = load_wind_field(tmp_path, timestep_index=1)
        assert result.timestep_index == 1
        assert result.valid_time == datetime(2026, 5, 15, 7, 0, tzinfo=timezone.utc)

    def test_timestep_out_of_range(self, tmp_path: Path) -> None:
        _make_metadata(tmp_path, timestep_count=1, valid_times=["2026-05-15T06:00:00+00:00"])
        _write_test_grids(tmp_path, stem="test_100_20260515T0600")

        with pytest.raises(WindFieldTimestepError, match="out of range"):
            load_wind_field(tmp_path, timestep_index=5)

    def test_negative_timestep_out_of_range(self, tmp_path: Path) -> None:
        _make_metadata(tmp_path, timestep_count=1, valid_times=["2026-05-15T06:00:00+00:00"])
        _write_test_grids(tmp_path, stem="test_100_20260515T0600")

        with pytest.raises(WindFieldTimestepError, match="out of range"):
            load_wind_field(tmp_path, timestep_index=-1)

    def test_no_output_grids(self, tmp_path: Path) -> None:
        _make_metadata(tmp_path, timestep_count=1, valid_times=["2026-05-15T06:00:00+00:00"])

        with pytest.raises(WindFieldGridError, match="No WindNinja velocity output"):
            load_wind_field(tmp_path, timestep_index=0)

    def test_missing_angle_grid(self, tmp_path: Path) -> None:
        _make_metadata(tmp_path, timestep_count=1, valid_times=["2026-05-15T06:00:00+00:00"])
        vel_path = tmp_path / "test_100_20260515T0600_vel.asc"
        vel_path.write_text(
            _make_ascii_grid(ncols=3, nrows=2),
            encoding="utf-8",
        )

        with pytest.raises(WindFieldGridError, match="Direction grid not found"):
            load_wind_field(tmp_path, timestep_index=0)


# ---------------------------------------------------------------------------
# API endpoint: get_wind_field
# ---------------------------------------------------------------------------


class TestGetWindFieldEndpoint:
    def _setup_completed_forecast_with_grids(
        self,
        db_session: Session,
        tmp_path: Path,
    ) -> uuid.UUID:
        """Insert a completed forecast and write synthetic output grids."""
        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()

        output_dir = tmp_path / "output" / str(forecast.id)
        output_dir.mkdir(parents=True)

        _make_metadata(output_dir, crs_epsg=32613, timestep_count=2)
        _write_test_grids(output_dir, stem="test_100_20260515T0600")
        _write_test_grids(output_dir, stem="test_100_20260515T0700")

        return forecast.id

    def test_happy_path(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import get_wind_field

        forecast_id = self._setup_completed_forecast_with_grids(db_session, tmp_path)
        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")

        response = get_wind_field(
            forecast_id=forecast_id,
            timestep_index=0,
            db=db_session,
            settings=test_settings,
        )
        assert response.forecast_id == forecast_id
        assert response.timestep_index == 0
        assert response.timestep_count == 2
        assert response.width == 3
        assert response.height == 2
        assert len(response.u) == 6
        assert len(response.v) == 6
        assert response.speed_min >= 0
        assert response.speed_max > 0
        assert response.bounds.west < response.bounds.east
        assert response.bounds.south < response.bounds.north

    def test_second_timestep(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import get_wind_field

        forecast_id = self._setup_completed_forecast_with_grids(db_session, tmp_path)
        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")

        response = get_wind_field(
            forecast_id=forecast_id,
            timestep_index=1,
            db=db_session,
            settings=test_settings,
        )
        assert response.timestep_index == 1

    def test_forecast_not_found(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import get_wind_field

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        with pytest.raises(HTTPException) as exc_info:
            get_wind_field(
                forecast_id=uuid.uuid4(),
                timestep_index=0,
                db=db_session,
                settings=test_settings,
            )
        assert exc_info.value.status_code == 404

    def test_forecast_not_completed(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import get_wind_field

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.running_solver,
        )
        db_session.commit()

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        with pytest.raises(HTTPException) as exc_info:
            get_wind_field(
                forecast_id=forecast.id,
                timestep_index=0,
                db=db_session,
                settings=test_settings,
            )
        assert exc_info.value.status_code == 409

    def test_timestep_out_of_range_returns_404(
        self, db_session: Session, tmp_path: Path,
    ) -> None:
        from api.routers.forecasts import get_wind_field

        forecast_id = self._setup_completed_forecast_with_grids(db_session, tmp_path)
        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")

        with pytest.raises(HTTPException) as exc_info:
            get_wind_field(
                forecast_id=forecast_id,
                timestep_index=99,
                db=db_session,
                settings=test_settings,
            )
        assert exc_info.value.status_code == 404

    def test_missing_output_dir_returns_404(
        self, db_session: Session, tmp_path: Path,
    ) -> None:
        from api.routers.forecasts import get_wind_field

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        with pytest.raises(HTTPException) as exc_info:
            get_wind_field(
                forecast_id=forecast.id,
                timestep_index=0,
                db=db_session,
                settings=test_settings,
            )
        assert exc_info.value.status_code == 404
