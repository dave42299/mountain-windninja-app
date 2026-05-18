"""Tests for api.routers.forecasts -- endpoint handlers and background worker."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from config import Settings
from models.enums import ForecastStatus, SolverType, WeatherModel
from models.orm import Forecast
from models.schemas import ForecastCreate
from tests.conftest import (
    BERTHOUD_LAT,
    BERTHOUD_LON,
    BERTHOUD_SIZE_KM,
    insert_forecast,
    insert_forecast_area,
    insert_tiles,
    make_non_closing_factory,
    utc,
)


_NOW = utc(2026, 5, 15, 12)


# ---------------------------------------------------------------------------
# _resolve_location
# ---------------------------------------------------------------------------


class TestResolveLocation:
    def test_ad_hoc_coordinates(self, db_session: Session) -> None:
        from api.routers.forecasts import _resolve_location

        body = ForecastCreate(
            latitude=39.80,
            longitude=-105.77,
            size_km=10.0,
            forecast_start=_NOW,
            duration_hours=6,
        )
        lat, lon, size, area_id = _resolve_location(body, db_session)
        assert lat == 39.80
        assert lon == -105.77
        assert size == 10.0
        assert area_id is None

    def test_from_forecast_area(self, db_session: Session) -> None:
        from api.routers.forecasts import _resolve_location

        area = insert_forecast_area(db_session)
        body = ForecastCreate(
            forecast_area_id=area.id,
            forecast_start=_NOW,
            duration_hours=6,
        )
        lat, lon, size, area_id = _resolve_location(body, db_session)
        assert lat == area.center_latitude
        assert lon == area.center_longitude
        assert size == area.size_km
        assert area_id == area.id

    def test_missing_forecast_area_raises_404(self, db_session: Session) -> None:
        from api.routers.forecasts import _resolve_location

        body = ForecastCreate(
            forecast_area_id=uuid.uuid4(),
            forecast_start=_NOW,
            duration_hours=6,
        )
        with pytest.raises(HTTPException) as exc_info:
            _resolve_location(body, db_session)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _run_forecast_pipeline -- happy path
# ---------------------------------------------------------------------------


def _call_pipeline(
    db_session: Session,
    forecast_id: uuid.UUID,
    test_settings: Settings,
    *,
    weather_mock: MagicMock | None = None,
    solver_mock: MagicMock | None = None,
    terrain_mock: MagicMock | None = None,
) -> None:
    """Invoke the pipeline with the injected session factory and settings."""
    from api.routers.forecasts import _run_forecast_pipeline

    _run_forecast_pipeline(
        forecast_id,
        center_latitude=BERTHOUD_LAT,
        center_longitude=BERTHOUD_LON,
        size_km=BERTHOUD_SIZE_KM,
        settings=test_settings,
        session_factory=make_non_closing_factory(db_session),
    )


class TestRunForecastPipelineHappyPath:
    @patch("api.routers.forecasts.run_solver_for_forecast")
    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    @patch("api.routers.forecasts.ensure_tiles_for_forecast")
    def test_status_transitions_queued_to_completed(
        self,
        mock_terrain: MagicMock,
        mock_weather: MagicMock,
        mock_solver: MagicMock,
        db_session: Session,
        test_settings: Settings,
    ) -> None:
        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_terrain.return_value = MagicMock(
            elevation_tile=elev, land_cover_tile=lcp,
        )
        mock_weather.return_value = MagicMock(timesteps=[MagicMock()] * 3)
        mock_solver.return_value = MagicMock()

        _call_pipeline(db_session, forecast_id, test_settings)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.completed
        assert reloaded.started_at is not None
        assert reloaded.completed_at is not None
        assert reloaded.elevation_tile_id == elev.id
        assert reloaded.land_cover_tile_id == lcp.id
        mock_terrain.assert_called_once()
        mock_weather.assert_called_once()
        mock_solver.assert_called_once()

    @patch("api.routers.forecasts.run_solver_for_forecast")
    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    @patch("api.routers.forecasts.ensure_tiles_for_forecast")
    def test_passes_settings_to_services(
        self,
        mock_terrain: MagicMock,
        mock_weather: MagicMock,
        mock_solver: MagicMock,
        db_session: Session,
        test_settings: Settings,
    ) -> None:
        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_terrain.return_value = MagicMock(
            elevation_tile=elev, land_cover_tile=lcp,
        )
        mock_weather.return_value = MagicMock(timesteps=[])
        mock_solver.return_value = MagicMock()

        _call_pipeline(db_session, forecast_id, test_settings)

        terrain_kwargs = mock_terrain.call_args.kwargs
        assert terrain_kwargs["data_dir"] == test_settings.data_dir

        weather_kwargs = mock_weather.call_args.kwargs
        assert weather_kwargs["forecast_id"] == str(forecast_id)
        assert weather_kwargs["data_dir"] == test_settings.data_dir

        solver_kwargs = mock_solver.call_args.kwargs
        assert solver_kwargs["data_dir"] == test_settings.data_dir
        assert solver_kwargs["solver_image"] == test_settings.solver_image


# ---------------------------------------------------------------------------
# _run_forecast_pipeline -- failure paths
# ---------------------------------------------------------------------------


class TestRunForecastPipelineFailure:
    @patch("api.routers.forecasts.ensure_tiles_for_forecast")
    def test_terrain_dem_error_sets_failed_status(
        self,
        mock_terrain: MagicMock,
        db_session: Session,
        test_settings: Settings,
    ) -> None:
        from services.terrain import TerrainDemError

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_terrain.side_effect = TerrainDemError("DEM download failed")

        _call_pipeline(db_session, forecast_id, test_settings)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "DEM download failed" in reloaded.error_message

    @patch("api.routers.forecasts.ensure_tiles_for_forecast")
    def test_terrain_lcp_error_sets_failed_status(
        self,
        mock_terrain: MagicMock,
        db_session: Session,
        test_settings: Settings,
    ) -> None:
        from services.terrain import TerrainLcpError

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_terrain.side_effect = TerrainLcpError("LCP fetch timed out")

        _call_pipeline(db_session, forecast_id, test_settings)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "LCP fetch timed out" in reloaded.error_message

    @patch("api.routers.forecasts.ensure_tiles_for_forecast")
    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_weather_time_range_error_sets_failed_status(
        self,
        mock_weather: MagicMock,
        mock_terrain: MagicMock,
        db_session: Session,
        test_settings: Settings,
    ) -> None:
        from services.weather import WeatherTimeRangeError

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_terrain.return_value = MagicMock(
            elevation_tile=elev, land_cover_tile=lcp,
        )
        mock_weather.side_effect = WeatherTimeRangeError("before archive start")

        _call_pipeline(db_session, forecast_id, test_settings)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "before archive start" in reloaded.error_message
        assert reloaded.completed_at is not None

    @patch("api.routers.forecasts.ensure_tiles_for_forecast")
    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_weather_download_error_sets_failed_status(
        self,
        mock_weather: MagicMock,
        mock_terrain: MagicMock,
        db_session: Session,
        test_settings: Settings,
    ) -> None:
        from services.weather import WeatherDownloadError

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_terrain.return_value = MagicMock(
            elevation_tile=elev, land_cover_tile=lcp,
        )
        mock_weather.side_effect = WeatherDownloadError("S3 timeout")

        _call_pipeline(db_session, forecast_id, test_settings)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "S3 timeout" in reloaded.error_message

    @patch("api.routers.forecasts.ensure_tiles_for_forecast")
    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    @patch("api.routers.forecasts.run_solver_for_forecast")
    def test_solver_config_error_sets_failed_status(
        self,
        mock_solver: MagicMock,
        mock_weather: MagicMock,
        mock_terrain: MagicMock,
        db_session: Session,
        test_settings: Settings,
    ) -> None:
        from services.solver import SolverConfigError

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_terrain.return_value = MagicMock(
            elevation_tile=elev, land_cover_tile=lcp,
        )
        mock_weather.return_value = MagicMock(timesteps=[MagicMock()])
        mock_solver.side_effect = SolverConfigError("bad config spec")

        _call_pipeline(db_session, forecast_id, test_settings)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "bad config spec" in reloaded.error_message

    @patch("api.routers.forecasts.ensure_tiles_for_forecast")
    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    @patch("api.routers.forecasts.run_solver_for_forecast")
    def test_solver_execution_error_sets_failed_status(
        self,
        mock_solver: MagicMock,
        mock_weather: MagicMock,
        mock_terrain: MagicMock,
        db_session: Session,
        test_settings: Settings,
    ) -> None:
        from services.solver import SolverExecutionError

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_terrain.return_value = MagicMock(
            elevation_tile=elev, land_cover_tile=lcp,
        )
        mock_weather.return_value = MagicMock(timesteps=[MagicMock()])
        mock_solver.side_effect = SolverExecutionError("Docker crash after retries")

        _call_pipeline(db_session, forecast_id, test_settings)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "Docker crash after retries" in reloaded.error_message

    @patch("api.routers.forecasts.ensure_tiles_for_forecast")
    def test_unexpected_error_sets_failed_with_internal_error(
        self,
        mock_terrain: MagicMock,
        db_session: Session,
        test_settings: Settings,
    ) -> None:
        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_terrain.side_effect = RuntimeError("something unexpected")

        _call_pipeline(db_session, forecast_id, test_settings)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "Internal error" in reloaded.error_message

    def test_missing_forecast_id_does_not_crash(
        self,
        db_session: Session,
        test_settings: Settings,
    ) -> None:
        _call_pipeline(db_session, uuid.uuid4(), test_settings)


# ---------------------------------------------------------------------------
# _update_status and _fail_forecast
# ---------------------------------------------------------------------------


class TestStatusHelpers:
    def test_update_status_sets_started_at_on_fetching_terrain(
        self, db_session: Session,
    ) -> None:
        from api.routers.forecasts import _update_status

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()

        assert forecast.started_at is None
        _update_status(db_session, forecast, ForecastStatus.fetching_terrain)
        assert forecast.started_at is not None
        assert forecast.status == ForecastStatus.fetching_terrain

    def test_update_status_sets_completed_at_on_completed(
        self, db_session: Session,
    ) -> None:
        from api.routers.forecasts import _update_status

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()

        _update_status(db_session, forecast, ForecastStatus.completed)
        assert forecast.completed_at is not None
        assert forecast.status == ForecastStatus.completed

    def test_fail_forecast_records_error_message(
        self, db_session: Session,
    ) -> None:
        from api.routers.forecasts import _fail_forecast

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()

        _fail_forecast(db_session, forecast, "download failed")
        assert forecast.status == ForecastStatus.failed
        assert forecast.error_message == "download failed"
        assert forecast.completed_at is not None


# ---------------------------------------------------------------------------
# Shared helpers: _get_forecast, _require_completed_forecast,
#                 _resolve_output_dir
# ---------------------------------------------------------------------------


class TestGetForecast:
    def test_returns_forecast(self, db_session: Session) -> None:
        from api.routers.forecasts import _get_forecast

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(db_session, elev, lcp)
        db_session.commit()

        result = _get_forecast(forecast.id, db_session)
        assert result.id == forecast.id

    def test_raises_404_for_missing(self, db_session: Session) -> None:
        from api.routers.forecasts import _get_forecast

        with pytest.raises(HTTPException) as exc_info:
            _get_forecast(uuid.uuid4(), db_session)
        assert exc_info.value.status_code == 404


class TestRequireCompletedForecast:
    def test_passes_for_completed(self, db_session: Session) -> None:
        from api.routers.forecasts import _require_completed_forecast

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()
        _require_completed_forecast(forecast)

    def test_raises_409_for_running(self, db_session: Session) -> None:
        from api.routers.forecasts import _require_completed_forecast

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.running_solver,
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            _require_completed_forecast(forecast)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["status"] == ForecastStatus.running_solver.value
        assert exc_info.value.detail["retry_after_seconds"] == 60

    def test_raises_409_for_failed_with_no_retry(self, db_session: Session) -> None:
        from api.routers.forecasts import _require_completed_forecast

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.failed,
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            _require_completed_forecast(forecast)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["status"] == ForecastStatus.failed.value
        assert exc_info.value.detail["retry_after_seconds"] is None

    def test_raises_409_for_queued_with_retry(self, db_session: Session) -> None:
        from api.routers.forecasts import _require_completed_forecast

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.queued,
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            _require_completed_forecast(forecast)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["retry_after_seconds"] == 5


class TestResolveOutputDir:
    def test_returns_existing_dir(self, tmp_path: Path) -> None:
        from api.routers.forecasts import _resolve_output_dir

        forecast_id = uuid.uuid4()
        output_dir = tmp_path / "output" / str(forecast_id)
        output_dir.mkdir(parents=True)

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        result = _resolve_output_dir(forecast_id, test_settings)
        assert result == output_dir

    def test_raises_404_for_missing_dir(self, tmp_path: Path) -> None:
        from api.routers.forecasts import _resolve_output_dir

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        with pytest.raises(HTTPException) as exc_info:
            _resolve_output_dir(uuid.uuid4(), test_settings)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# list_forecast_output
# ---------------------------------------------------------------------------


class TestListForecastOutput:
    def test_happy_path(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import list_forecast_output

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()

        output_dir = tmp_path / "output" / str(forecast.id)
        output_dir.mkdir(parents=True)
        (output_dir / "speed.asc").write_text("test speed data")
        (output_dir / "direction.asc").write_text("test direction data")

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        response = list_forecast_output(
            forecast_id=forecast.id, db=db_session, settings=test_settings,
        )
        assert response.forecast_id == forecast.id
        assert len(response.files) == 2
        filenames = {f.filename for f in response.files}
        assert filenames == {"speed.asc", "direction.asc"}
        for file_info in response.files:
            assert file_info.size_bytes > 0

    def test_forecast_not_found(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import list_forecast_output

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        with pytest.raises(HTTPException) as exc_info:
            list_forecast_output(
                forecast_id=uuid.uuid4(), db=db_session, settings=test_settings,
            )
        assert exc_info.value.status_code == 404

    def test_forecast_not_completed(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import list_forecast_output

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.queued,
        )
        db_session.commit()

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        with pytest.raises(HTTPException) as exc_info:
            list_forecast_output(
                forecast_id=forecast.id, db=db_session, settings=test_settings,
            )
        assert exc_info.value.status_code == 409

    def test_missing_directory(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import list_forecast_output

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        with pytest.raises(HTTPException) as exc_info:
            list_forecast_output(
                forecast_id=forecast.id, db=db_session, settings=test_settings,
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# download_forecast_output
# ---------------------------------------------------------------------------


class TestDownloadForecastOutput:
    def test_happy_path(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import download_forecast_output

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()

        output_dir = tmp_path / "output" / str(forecast.id)
        output_dir.mkdir(parents=True)
        (output_dir / "speed.asc").write_text("test speed data")

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        response = download_forecast_output(
            forecast_id=forecast.id,
            filename="speed.asc",
            db=db_session,
            settings=test_settings,
        )
        assert Path(response.path) == output_dir / "speed.asc"
        assert response.media_type == "text/plain"

    def test_path_traversal_rejected(
        self, db_session: Session, tmp_path: Path,
    ) -> None:
        from api.routers.forecasts import download_forecast_output

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        with pytest.raises(HTTPException) as exc_info:
            download_forecast_output(
                forecast_id=forecast.id,
                filename="../../../etc/passwd",
                db=db_session,
                settings=test_settings,
            )
        assert exc_info.value.status_code == 400

    def test_slash_in_filename_rejected(
        self, db_session: Session, tmp_path: Path,
    ) -> None:
        from api.routers.forecasts import download_forecast_output

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        with pytest.raises(HTTPException) as exc_info:
            download_forecast_output(
                forecast_id=forecast.id,
                filename="sub/file.asc",
                db=db_session,
                settings=test_settings,
            )
        assert exc_info.value.status_code == 400

    def test_file_not_found(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import download_forecast_output

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()

        output_dir = tmp_path / "output" / str(forecast.id)
        output_dir.mkdir(parents=True)

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        with pytest.raises(HTTPException) as exc_info:
            download_forecast_output(
                forecast_id=forecast.id,
                filename="nonexistent.asc",
                db=db_session,
                settings=test_settings,
            )
        assert exc_info.value.status_code == 404

    def test_json_media_type(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import download_forecast_output

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()

        output_dir = tmp_path / "output" / str(forecast.id)
        output_dir.mkdir(parents=True)
        (output_dir / "metadata.json").write_text('{"key": "value"}')

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        response = download_forecast_output(
            forecast_id=forecast.id,
            filename="metadata.json",
            db=db_session,
            settings=test_settings,
        )
        assert response.media_type == "application/json"

    def test_tif_media_type(self, db_session: Session, tmp_path: Path) -> None:
        from api.routers.forecasts import download_forecast_output

        elev, lcp = insert_tiles(db_session)
        forecast = insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()

        output_dir = tmp_path / "output" / str(forecast.id)
        output_dir.mkdir(parents=True)
        (output_dir / "dem.tif").write_bytes(b"fake geotiff")

        test_settings = Settings(data_dir=tmp_path, database_url="sqlite:///:memory:")
        response = download_forecast_output(
            forecast_id=forecast.id,
            filename="dem.tif",
            db=db_session,
            settings=test_settings,
        )
        assert response.media_type == "image/tiff"


# ---------------------------------------------------------------------------
# list_forecasts -- filter and pagination tests
# ---------------------------------------------------------------------------


class TestListForecasts:
    def test_returns_paginated_response(self, db_session: Session) -> None:
        from api.routers.forecasts import list_forecasts

        elev, lcp = insert_tiles(db_session)
        for _ in range(5):
            insert_forecast(db_session, elev, lcp, status=ForecastStatus.completed)
        db_session.commit()

        response = list_forecasts(limit=50, offset=0, db=db_session)
        assert response.total == 5
        assert len(response.items) == 5
        assert response.limit == 50
        assert response.offset == 0

    def test_limit_and_offset(self, db_session: Session) -> None:
        from api.routers.forecasts import list_forecasts

        elev, lcp = insert_tiles(db_session)
        for _ in range(5):
            insert_forecast(db_session, elev, lcp, status=ForecastStatus.completed)
        db_session.commit()

        response = list_forecasts(limit=2, offset=1, db=db_session)
        assert response.total == 5
        assert len(response.items) == 2
        assert response.limit == 2
        assert response.offset == 1

    def test_filter_by_status(self, db_session: Session) -> None:
        from api.routers.forecasts import list_forecasts

        elev, lcp = insert_tiles(db_session)
        insert_forecast(db_session, elev, lcp, status=ForecastStatus.completed)
        insert_forecast(db_session, elev, lcp, status=ForecastStatus.completed)
        insert_forecast(db_session, elev, lcp, status=ForecastStatus.failed)
        insert_forecast(db_session, elev, lcp, status=ForecastStatus.queued)
        db_session.commit()

        completed = list_forecasts(
            status=ForecastStatus.completed, limit=50, offset=0, db=db_session,
        )
        assert completed.total == 2
        assert all(f.status == ForecastStatus.completed for f in completed.items)

        failed = list_forecasts(
            status=ForecastStatus.failed, limit=50, offset=0, db=db_session,
        )
        assert failed.total == 1
        assert failed.items[0].status == ForecastStatus.failed

    def test_filter_by_forecast_area_id(self, db_session: Session) -> None:
        from api.routers.forecasts import list_forecasts

        elev, lcp = insert_tiles(db_session)
        area = insert_forecast_area(db_session)
        insert_forecast(
            db_session, elev, lcp, forecast_area_id=area.id,
            status=ForecastStatus.completed,
        )
        insert_forecast(
            db_session, elev, lcp, forecast_area_id=area.id,
            status=ForecastStatus.queued,
        )
        insert_forecast(db_session, elev, lcp, status=ForecastStatus.completed)
        db_session.commit()

        filtered = list_forecasts(
            forecast_area_id=area.id, limit=50, offset=0, db=db_session,
        )
        assert filtered.total == 2
        for f in filtered.items:
            assert f.forecast_area_id == area.id

    def test_combined_filters(self, db_session: Session) -> None:
        from api.routers.forecasts import list_forecasts

        elev, lcp = insert_tiles(db_session)
        area = insert_forecast_area(db_session)
        insert_forecast(
            db_session, elev, lcp, forecast_area_id=area.id,
            status=ForecastStatus.completed,
        )
        insert_forecast(
            db_session, elev, lcp, forecast_area_id=area.id,
            status=ForecastStatus.failed,
        )
        insert_forecast(db_session, elev, lcp, status=ForecastStatus.completed)
        db_session.commit()

        filtered = list_forecasts(
            status=ForecastStatus.completed, forecast_area_id=area.id,
            limit=50, offset=0, db=db_session,
        )
        assert filtered.total == 1
        assert filtered.items[0].forecast_area_id == area.id
        assert filtered.items[0].status == ForecastStatus.completed

    def test_empty_result(self, db_session: Session) -> None:
        from api.routers.forecasts import list_forecasts

        response = list_forecasts(limit=50, offset=0, db=db_session)
        assert response.total == 0
        assert response.items == []
