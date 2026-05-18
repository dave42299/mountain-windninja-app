"""Tests for services.weather -- public weather orchestrator."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from models.enums import WeatherModel
from tests.conftest import utc
from services.weather import (
    ForecastWeatherGrids,
    WeatherDownloadError,
    WeatherError,
    WeatherTimeRangeError,
    prepare_weather_for_forecast,
)
from services.weather_hrrr import DemGridSpec
from services.weather_models import HrrrCycle


def _make_fake_elevation_tile() -> MagicMock:
    """Create a mock ElevationTile with Berthoud-area defaults."""
    tile = MagicMock()
    tile.id = uuid.uuid4()
    tile.file_path = "elevation/test-dem.tif"
    tile.crs_epsg = 32613
    return tile


def _make_cycles(start: datetime, count: int) -> list[HrrrCycle]:
    from datetime import timedelta

    return [
        HrrrCycle(
            analysis_time=start + timedelta(hours=i),
            forecast_hour=0,
            valid_time=start + timedelta(hours=i),
        )
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestPrepareWeatherHappyPath:
    @patch("services.weather.process_timestep")
    @patch("services.weather.check_hrrr_availability")
    @patch("services.weather.resolve_hrrr_cycles")
    @patch("services.weather.validate_hrrr_time_range")
    @patch("services.weather.read_dem_grid_spec")
    def test_returns_forecast_weather_grids(
        self,
        mock_read_dem: MagicMock,
        mock_validate: MagicMock,
        mock_resolve: MagicMock,
        mock_check: MagicMock,
        mock_process: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        start = utc(2026, 5, 10, 12)
        cycles = _make_cycles(start, 3)
        mock_resolve.return_value = cycles
        mock_read_dem.return_value = MagicMock(spec=DemGridSpec)

        def fake_process(cycle: HrrrCycle, dem_spec: DemGridSpec, output_dir: Path):
            label = cycle.valid_time.strftime("%Y%m%d_%H%M")
            speed = output_dir / f"speed_{label}.asc"
            direction = output_dir / f"direction_{label}.asc"
            speed.write_text("fake speed")
            direction.write_text("fake direction")
            return speed, direction

        mock_process.side_effect = fake_process

        tile = _make_fake_elevation_tile()

        result = prepare_weather_for_forecast(
            forecast_id=forecast_id,
            forecast_start=start,
            duration_hours=3,
            weather_model=WeatherModel.hrrr,
            elevation_tile=tile,
            data_dir=tmp_path,
            now=utc(2026, 5, 10, 18),
        )

        assert isinstance(result, ForecastWeatherGrids)
        assert len(result.timesteps) == 3
        assert result.weather_dir == Path("weather") / forecast_id

        mock_read_dem.assert_called_once()
        mock_validate.assert_called_once()
        mock_resolve.assert_called_once()
        mock_check.assert_called_once_with(cycles)
        assert mock_process.call_count == 3

    @patch("services.weather.process_timestep")
    @patch("services.weather.check_hrrr_availability")
    @patch("services.weather.resolve_hrrr_cycles")
    @patch("services.weather.validate_hrrr_time_range")
    @patch("services.weather.read_dem_grid_spec")
    def test_writes_metadata_json(
        self,
        mock_read_dem: MagicMock,
        mock_validate: MagicMock,
        mock_resolve: MagicMock,
        mock_check: MagicMock,
        mock_process: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        start = utc(2026, 5, 10, 12)
        cycles = _make_cycles(start, 2)
        mock_resolve.return_value = cycles
        mock_read_dem.return_value = MagicMock(spec=DemGridSpec)

        def fake_process(cycle, dem_spec, output_dir):
            label = cycle.valid_time.strftime("%Y%m%d_%H%M")
            speed = output_dir / f"speed_{label}.asc"
            direction = output_dir / f"direction_{label}.asc"
            speed.write_text("speed data")
            direction.write_text("direction data")
            return speed, direction

        mock_process.side_effect = fake_process

        tile = _make_fake_elevation_tile()

        result = prepare_weather_for_forecast(
            forecast_id=forecast_id,
            forecast_start=start,
            duration_hours=2,
            weather_model=WeatherModel.hrrr,
            elevation_tile=tile,
            data_dir=tmp_path,
            now=utc(2026, 5, 10, 18),
        )

        metadata_path = tmp_path / result.weather_dir / "metadata.json"
        assert metadata_path.exists()

        metadata = json.loads(metadata_path.read_text())
        assert metadata["forecast_id"] == forecast_id
        assert metadata["weather_model"] == "hrrr"
        assert metadata["speed_units"] == "mps"
        assert len(metadata["timesteps"]) == 2
        assert metadata["timesteps"][0]["forecast_hour"] == 0

    @patch("services.weather.process_timestep")
    @patch("services.weather.check_hrrr_availability")
    @patch("services.weather.resolve_hrrr_cycles")
    @patch("services.weather.validate_hrrr_time_range")
    @patch("services.weather.read_dem_grid_spec")
    def test_timestep_paths_are_relative(
        self,
        mock_read_dem: MagicMock,
        mock_validate: MagicMock,
        mock_resolve: MagicMock,
        mock_check: MagicMock,
        mock_process: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        start = utc(2026, 5, 10, 12)
        cycles = _make_cycles(start, 1)
        mock_resolve.return_value = cycles
        mock_read_dem.return_value = MagicMock(spec=DemGridSpec)

        def fake_process(cycle, dem_spec, output_dir):
            label = cycle.valid_time.strftime("%Y%m%d_%H%M")
            speed = output_dir / f"speed_{label}.asc"
            direction = output_dir / f"direction_{label}.asc"
            speed.write_text("speed")
            direction.write_text("direction")
            return speed, direction

        mock_process.side_effect = fake_process

        tile = _make_fake_elevation_tile()

        result = prepare_weather_for_forecast(
            forecast_id=forecast_id,
            forecast_start=start,
            duration_hours=1,
            weather_model=WeatherModel.hrrr,
            elevation_tile=tile,
            data_dir=tmp_path,
            now=utc(2026, 5, 10, 18),
        )

        ts = result.timesteps[0]
        assert not ts.speed_grid_path.is_absolute()
        assert not ts.direction_grid_path.is_absolute()
        assert str(ts.speed_grid_path).startswith("weather/")


# ---------------------------------------------------------------------------
# NBM rejection
# ---------------------------------------------------------------------------


class TestNbmRejection:
    def test_nbm_raises_weather_error(self, tmp_path: Path) -> None:
        tile = _make_fake_elevation_tile()
        with pytest.raises(WeatherError, match="not yet supported"):
            prepare_weather_for_forecast(
                forecast_id=str(uuid.uuid4()),
                forecast_start=utc(2026, 5, 10, 12),
                duration_hours=6,
                weather_model=WeatherModel.nbm,
                elevation_tile=tile,
                data_dir=tmp_path,
            )

    def test_nbm_string_raises_weather_error(self, tmp_path: Path) -> None:
        tile = _make_fake_elevation_tile()
        with pytest.raises(WeatherError, match="not yet supported"):
            prepare_weather_for_forecast(
                forecast_id=str(uuid.uuid4()),
                forecast_start=utc(2026, 5, 10, 12),
                duration_hours=6,
                weather_model="nbm",
                elevation_tile=tile,
                data_dir=tmp_path,
            )


# ---------------------------------------------------------------------------
# Time validation passthrough
# ---------------------------------------------------------------------------


class TestTimeValidation:
    def test_validates_before_resolving_cycles(self, tmp_path: Path) -> None:
        tile = _make_fake_elevation_tile()
        with pytest.raises(WeatherTimeRangeError, match="archive start"):
            prepare_weather_for_forecast(
                forecast_id=str(uuid.uuid4()),
                forecast_start=utc(2013, 1, 1),
                duration_hours=6,
                weather_model=WeatherModel.hrrr,
                elevation_tile=tile,
                data_dir=tmp_path,
            )


# ---------------------------------------------------------------------------
# Failure cleanup
# ---------------------------------------------------------------------------


class TestFailureCleanup:
    @patch("services.weather.process_timestep")
    @patch("services.weather.check_hrrr_availability")
    @patch("services.weather.resolve_hrrr_cycles")
    @patch("services.weather.validate_hrrr_time_range")
    @patch("services.weather.read_dem_grid_spec")
    def test_cleans_up_weather_dir_on_process_failure(
        self,
        mock_read_dem: MagicMock,
        mock_validate: MagicMock,
        mock_resolve: MagicMock,
        mock_check: MagicMock,
        mock_process: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        start = utc(2026, 5, 10, 12)
        cycles = _make_cycles(start, 3)
        mock_resolve.return_value = cycles
        mock_read_dem.return_value = MagicMock(spec=DemGridSpec)

        call_count = 0

        def fake_process_with_failure(cycle, dem_spec, output_dir):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise WeatherDownloadError("S3 connection lost")
            label = cycle.valid_time.strftime("%Y%m%d_%H%M")
            speed = output_dir / f"speed_{label}.asc"
            direction = output_dir / f"direction_{label}.asc"
            speed.write_text("speed data")
            direction.write_text("direction data")
            return speed, direction

        mock_process.side_effect = fake_process_with_failure

        tile = _make_fake_elevation_tile()

        weather_dir = tmp_path / "weather" / forecast_id

        with pytest.raises(WeatherDownloadError, match="S3 connection lost"):
            prepare_weather_for_forecast(
                forecast_id=forecast_id,
                forecast_start=start,
                duration_hours=3,
                weather_model=WeatherModel.hrrr,
                elevation_tile=tile,
                data_dir=tmp_path,
                now=utc(2026, 5, 10, 18),
            )

        assert not weather_dir.exists()

    @patch("services.weather.check_hrrr_availability")
    @patch("services.weather.resolve_hrrr_cycles")
    @patch("services.weather.validate_hrrr_time_range")
    @patch("services.weather.read_dem_grid_spec")
    def test_cleans_up_on_availability_failure(
        self,
        mock_read_dem: MagicMock,
        mock_validate: MagicMock,
        mock_resolve: MagicMock,
        mock_check: MagicMock,
        tmp_path: Path,
    ) -> None:
        forecast_id = str(uuid.uuid4())
        start = utc(2026, 5, 10, 12)
        cycles = _make_cycles(start, 3)
        mock_resolve.return_value = cycles
        mock_check.side_effect = WeatherDownloadError("HRRR data not available")
        mock_read_dem.return_value = MagicMock(spec=DemGridSpec)

        tile = _make_fake_elevation_tile()

        weather_dir = tmp_path / "weather" / forecast_id

        with pytest.raises(WeatherDownloadError, match="not available"):
            prepare_weather_for_forecast(
                forecast_id=forecast_id,
                forecast_start=start,
                duration_hours=3,
                weather_model=WeatherModel.hrrr,
                elevation_tile=tile,
                data_dir=tmp_path,
                now=utc(2026, 5, 10, 18),
            )

        if weather_dir.exists():
            assert list(weather_dir.glob("*.asc")) == []


# ---------------------------------------------------------------------------
# Orchestration call order
# ---------------------------------------------------------------------------


class TestOrchestrationOrder:
    @patch("services.weather.process_timestep")
    @patch("services.weather.check_hrrr_availability")
    @patch("services.weather.resolve_hrrr_cycles")
    @patch("services.weather.validate_hrrr_time_range")
    @patch("services.weather.read_dem_grid_spec")
    def test_validate_then_resolve_then_check_then_process(
        self,
        mock_read_dem: MagicMock,
        mock_validate: MagicMock,
        mock_resolve: MagicMock,
        mock_check: MagicMock,
        mock_process: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Verify the pipeline executes in the correct order."""
        forecast_id = str(uuid.uuid4())
        start = utc(2026, 5, 10, 12)
        cycles = _make_cycles(start, 1)
        mock_resolve.return_value = cycles
        mock_read_dem.return_value = MagicMock(spec=DemGridSpec)

        call_order: list[str] = []
        mock_validate.side_effect = lambda *a, **k: call_order.append("validate")

        def track_resolve(*a, **k):
            call_order.append("resolve")
            return cycles

        mock_resolve.side_effect = track_resolve

        def track_check(*a, **k):
            call_order.append("check")

        mock_check.side_effect = track_check

        def track_process(cycle, dem_spec, output_dir):
            call_order.append("process")
            label = cycle.valid_time.strftime("%Y%m%d_%H%M")
            speed = output_dir / f"speed_{label}.asc"
            direction = output_dir / f"direction_{label}.asc"
            speed.write_text("speed")
            direction.write_text("direction")
            return speed, direction

        mock_process.side_effect = track_process

        tile = _make_fake_elevation_tile()

        prepare_weather_for_forecast(
            forecast_id=forecast_id,
            forecast_start=start,
            duration_hours=1,
            weather_model=WeatherModel.hrrr,
            elevation_tile=tile,
            data_dir=tmp_path,
            now=utc(2026, 5, 10, 18),
        )

        assert call_order == ["validate", "resolve", "check", "process"]
