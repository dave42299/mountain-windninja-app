"""Tests for api.routers.forecasts -- endpoint handlers and background worker."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

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

    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_status_transitions_queued_to_completed(
        self,
        mock_weather: MagicMock,
        db_session: Session,
    ) -> None:
        from api.routers.forecasts import _run_forecast_pipeline

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_weather.return_value = MagicMock(timesteps=[MagicMock()] * 3)

        with patch("api.routers.forecasts.get_session_factory") as mock_factory:
            mock_factory.return_value = self._make_non_closing_factory(db_session)
            _run_forecast_pipeline(forecast_id)

        reloaded = db_session.get(Forecast, forecast_id)
        assert reloaded.status == ForecastStatus.completed
        assert reloaded.started_at is not None
        assert reloaded.completed_at is not None
        mock_weather.assert_called_once()

    @patch("api.routers.forecasts.prepare_weather_for_forecast")
    def test_passes_correct_args_to_weather_service(
        self,
        mock_weather: MagicMock,
        db_session: Session,
    ) -> None:
        from api.routers.forecasts import _run_forecast_pipeline

        elev, lcp = _insert_tiles(db_session)
        forecast = _insert_forecast(db_session, elev, lcp)
        db_session.commit()
        forecast_id = forecast.id

        mock_weather.return_value = MagicMock(timesteps=[])

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
