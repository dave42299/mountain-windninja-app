"""Tests for api.routers.forecasts -- endpoint handlers and background worker."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import Settings
from models.database import Base
from models.enums import ForecastStatus, SolverType, WeatherModel
from models.orm import ElevationTile, Forecast, ForecastArea, LandCoverTile
from models.schemas import ForecastCreate


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


_NOW = _utc(2026, 5, 15, 12)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session() -> Session:  # type: ignore[override]
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _insert_tiles(session: Session) -> tuple[ElevationTile, LandCoverTile]:
    elev = ElevationTile(
        id=uuid.uuid4(),
        bbox_north=39.85,
        bbox_south=39.65,
        bbox_east=-105.65,
        bbox_west=-105.85,
        crs_epsg=32613,
        file_path="elevation/test.tif",
        source="usgs_3dep",
        file_size_bytes=10000,
    )
    lcp = LandCoverTile(
        id=uuid.uuid4(),
        bbox_north=39.85,
        bbox_south=39.65,
        bbox_east=-105.65,
        bbox_west=-105.85,
        crs_epsg=5070,
        file_path="land_cover/test.lcp",
        source="landfire",
        file_size_bytes=20000,
    )
    session.add_all([elev, lcp])
    session.flush()
    return elev, lcp


def _insert_forecast_area(session: Session) -> ForecastArea:
    area = ForecastArea(
        id=uuid.uuid4(),
        label="Berthoud Pass",
        center_latitude=39.80,
        center_longitude=-105.77,
        size_km=10.0,
    )
    session.add(area)
    session.flush()
    return area


def _insert_forecast(
    session: Session,
    elev: ElevationTile,
    lcp: LandCoverTile,
    *,
    status: ForecastStatus = ForecastStatus.queued,
    forecast_area_id: uuid.UUID | None = None,
) -> Forecast:
    forecast = Forecast(
        id=uuid.uuid4(),
        forecast_area_id=forecast_area_id,
        center_latitude=39.80,
        center_longitude=-105.77,
        size_km=10.0,
        elevation_tile_id=elev.id,
        land_cover_tile_id=lcp.id,
        status=status,
        weather_model=WeatherModel.hrrr,
        solver_type=SolverType.momentum,
        output_wind_height=10.0,
        forecast_start=_utc(2026, 5, 15, 6),
        duration_hours=6,
    )
    session.add(forecast)
    session.flush()
    return forecast


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

        area = _insert_forecast_area(db_session)
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
        from fastapi import HTTPException

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


class TestRunForecastPipelineHappyPath:
    @staticmethod
    def _make_non_closing_factory(session: Session):
        """Build a factory whose sessions skip close() so assertions can
        inspect the same session afterward.  _run_forecast_pipeline calls
        ``session.close()`` in its ``finally`` block; patching it out lets
        us keep the session alive for post-run assertions.
        """
        def factory():
            session.close = lambda: None  # type: ignore[assignment]
            return session
        return factory

    @patch("api.routers.forecasts.run_solver_for_forecast")
    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_status_transitions_queued_to_completed(
        self,
        mock_weather: MagicMock,
        mock_solver: MagicMock,
        db_session: Session,
    ) -> None:
        from api.routers.forecasts import _run_forecast_pipeline

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_weather.return_value = MagicMock(timesteps=[MagicMock()] * 3)
        mock_solver.return_value = MagicMock()

        with patch("api.routers.forecasts.get_session_factory") as mock_factory:
            mock_factory.return_value = self._make_non_closing_factory(db_session)
            _run_forecast_pipeline(forecast_id)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.completed
        assert reloaded.started_at is not None
        assert reloaded.completed_at is not None
        mock_weather.assert_called_once()
        mock_solver.assert_called_once()

    @patch("api.routers.forecasts.run_solver_for_forecast")
    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_passes_correct_args_to_weather_service(
        self,
        mock_weather: MagicMock,
        mock_solver: MagicMock,
        db_session: Session,
    ) -> None:
        from api.routers.forecasts import _run_forecast_pipeline

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_weather.return_value = MagicMock(timesteps=[])
        mock_solver.return_value = MagicMock()

        with patch("api.routers.forecasts.get_session_factory") as mock_factory:
            mock_factory.return_value = self._make_non_closing_factory(db_session)
            _run_forecast_pipeline(forecast_id)

        call_kwargs = mock_weather.call_args.kwargs
        assert call_kwargs["forecast_id"] == str(forecast_id)
        assert call_kwargs["forecast_start"] == forecast.forecast_start
        assert call_kwargs["duration_hours"] == forecast.duration_hours
        assert call_kwargs["weather_model"] == forecast.weather_model


# ---------------------------------------------------------------------------
# _run_forecast_pipeline -- failure paths
# ---------------------------------------------------------------------------


class TestRunForecastPipelineFailure:
    @staticmethod
    def _make_non_closing_factory(session: Session):
        def factory():
            session.close = lambda: None  # type: ignore[assignment]
            return session
        return factory

    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_weather_time_range_error_sets_failed_status(
        self,
        mock_weather: MagicMock,
        db_session: Session,
    ) -> None:
        from services.weather import WeatherTimeRangeError

        from api.routers.forecasts import _run_forecast_pipeline

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_weather.side_effect = WeatherTimeRangeError("before archive start")

        with patch("api.routers.forecasts.get_session_factory") as mock_factory:
            mock_factory.return_value = self._make_non_closing_factory(db_session)
            _run_forecast_pipeline(forecast_id)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "before archive start" in reloaded.error_message
        assert reloaded.completed_at is not None

    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_weather_download_error_sets_failed_status(
        self,
        mock_weather: MagicMock,
        db_session: Session,
    ) -> None:
        from services.weather import WeatherDownloadError

        from api.routers.forecasts import _run_forecast_pipeline

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_weather.side_effect = WeatherDownloadError("S3 timeout")

        with patch("api.routers.forecasts.get_session_factory") as mock_factory:
            mock_factory.return_value = self._make_non_closing_factory(db_session)
            _run_forecast_pipeline(forecast_id)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "S3 timeout" in reloaded.error_message

    @patch("api.routers.forecasts.run_solver_for_forecast")
    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_solver_config_error_sets_failed_status(
        self,
        mock_weather: MagicMock,
        mock_solver: MagicMock,
        db_session: Session,
    ) -> None:
        from services.solver import SolverConfigError

        from api.routers.forecasts import _run_forecast_pipeline

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_weather.return_value = MagicMock(timesteps=[MagicMock()])
        mock_solver.side_effect = SolverConfigError("bad config spec")

        with patch("api.routers.forecasts.get_session_factory") as mock_factory:
            mock_factory.return_value = self._make_non_closing_factory(db_session)
            _run_forecast_pipeline(forecast_id)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "bad config spec" in reloaded.error_message

    @patch("api.routers.forecasts.run_solver_for_forecast")
    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_solver_execution_error_sets_failed_status(
        self,
        mock_weather: MagicMock,
        mock_solver: MagicMock,
        db_session: Session,
    ) -> None:
        from services.solver import SolverExecutionError

        from api.routers.forecasts import _run_forecast_pipeline

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_weather.return_value = MagicMock(timesteps=[MagicMock()])
        mock_solver.side_effect = SolverExecutionError("Docker crash after retries")

        with patch("api.routers.forecasts.get_session_factory") as mock_factory:
            mock_factory.return_value = self._make_non_closing_factory(db_session)
            _run_forecast_pipeline(forecast_id)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "Docker crash after retries" in reloaded.error_message

    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_unexpected_error_sets_failed_with_internal_error(
        self,
        mock_weather: MagicMock,
        db_session: Session,
    ) -> None:
        from api.routers.forecasts import _run_forecast_pipeline

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_weather.side_effect = RuntimeError("something unexpected")

        with patch("api.routers.forecasts.get_session_factory") as mock_factory:
            mock_factory.return_value = self._make_non_closing_factory(db_session)
            _run_forecast_pipeline(forecast_id)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.failed
        assert "Internal error" in reloaded.error_message

    def test_missing_forecast_id_does_not_crash(
        self,
        db_session: Session,
    ) -> None:
        from api.routers.forecasts import _run_forecast_pipeline

        def factory():
            db_session.close = lambda: None  # type: ignore[assignment]
            return db_session

        with patch("api.routers.forecasts.get_session_factory") as mock_factory:
            mock_factory.return_value = factory
            _run_forecast_pipeline(uuid.uuid4())


# ---------------------------------------------------------------------------
# _update_status and _fail_forecast
# ---------------------------------------------------------------------------


class TestStatusHelpers:
    def test_update_status_sets_started_at_on_fetching_weather(
        self, db_session: Session,
    ) -> None:
        from api.routers.forecasts import _update_status

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()

        assert forecast.started_at is None
        _update_status(db_session, forecast, ForecastStatus.fetching_weather)
        assert forecast.started_at is not None
        assert forecast.status == ForecastStatus.fetching_weather

    def test_update_status_sets_completed_at_on_completed(
        self, db_session: Session,
    ) -> None:
        from api.routers.forecasts import _update_status

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()

        _update_status(db_session, forecast, ForecastStatus.completed)
        assert forecast.completed_at is not None
        assert forecast.status == ForecastStatus.completed

    def test_fail_forecast_records_error_message(
        self, db_session: Session,
    ) -> None:
        from api.routers.forecasts import _fail_forecast

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()

        _fail_forecast(db_session, forecast, "download failed")
        assert forecast.status == ForecastStatus.failed
        assert forecast.error_message == "download failed"
        assert forecast.completed_at is not None


# ---------------------------------------------------------------------------
# Shared helpers: _get_forecast_or_404, _require_completed_forecast,
#                 _resolve_output_dir
# ---------------------------------------------------------------------------


class TestGetForecastOr404:
    def test_returns_forecast(self, db_session: Session) -> None:
        from api.routers.forecasts import _get_forecast_or_404

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()

        result = _get_forecast_or_404(forecast.id, db_session)
        assert result.id == forecast.id

    def test_raises_404_for_missing(self, db_session: Session) -> None:
        from api.routers.forecasts import _get_forecast_or_404

        with pytest.raises(HTTPException) as exc_info:
            _get_forecast_or_404(uuid.uuid4(), db_session)
        assert exc_info.value.status_code == 404


class TestRequireCompletedForecast:
    def test_passes_for_completed(self, db_session: Session) -> None:
        from api.routers.forecasts import _require_completed_forecast

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.completed,
        )
        db_session.commit()
        _require_completed_forecast(forecast)

    def test_raises_409_for_running(self, db_session: Session) -> None:
        from api.routers.forecasts import _require_completed_forecast

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.running_solver,
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            _require_completed_forecast(forecast)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["status"] == ForecastStatus.running_solver

    def test_raises_409_for_failed(self, db_session: Session) -> None:
        from api.routers.forecasts import _require_completed_forecast

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
            db_session, elev, lcp, status=ForecastStatus.failed,
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            _require_completed_forecast(forecast)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["status"] == ForecastStatus.failed


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

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
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

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
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

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
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

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
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

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
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

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
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

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
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

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(
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
