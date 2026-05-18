"""Mocked end-to-end integration test.

Exercises the full API surface with mocked external I/O:
  POST /forecasts -> run pipeline -> GET /forecasts/{id}
  -> GET /forecasts/{id}/output -> GET /forecasts/{id}/output/{filename}

External boundaries mocked:
  - terrain downloads (USGS, LANDFIRE, Docker) via ensure_tiles_for_forecast
  - CONUS validation via _validate_conus_location
  - weather downloads (Herbie / S3) via prepare_weather_for_forecast
  - solver execution (Docker) via run_solver_for_forecast
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.deps import get_db, get_settings
from api.main import app
from config import Settings
from models.enums import ForecastStatus
from models.orm import ElevationTile, LandCoverTile
from services.terrain import ForecastTerrainTiles
from services.terrain_geometry import Wgs84BoundingBox
from services.weather import ForcingTimestep, ForecastWeatherGrids
from services.weather_models import HrrrCycle
from tests.conftest import BERTHOUD_LAT, BERTHOUD_LON, BERTHOUD_SIZE_KM, utc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _seed_tiles(db_session: Session, test_settings: Settings):
    """Insert elevation and land cover tile rows with real files on disk."""
    elev_relative = Path("elevation/test_dem.tif")
    lcp_relative = Path("land_cover/test_lcp.lcp")

    elev_absolute = test_settings.data_dir / elev_relative
    lcp_absolute = test_settings.data_dir / lcp_relative
    elev_absolute.write_bytes(b"fake DEM data")
    lcp_absolute.write_bytes(b"fake LCP data")

    elev = ElevationTile(
        id=uuid.uuid4(),
        bbox_north=39.85, bbox_south=39.65,
        bbox_east=-105.65, bbox_west=-105.85,
        crs_epsg=32613,
        file_path=elev_relative.as_posix(),
        source="usgs_3dep",
        file_size_bytes=elev_absolute.stat().st_size,
    )
    lcp = LandCoverTile(
        id=uuid.uuid4(),
        bbox_north=39.85, bbox_south=39.65,
        bbox_east=-105.65, bbox_west=-105.85,
        crs_epsg=5070,
        file_path=lcp_relative.as_posix(),
        source="landfire",
        file_size_bytes=lcp_absolute.stat().st_size,
    )
    db_session.add_all([elev, lcp])
    db_session.commit()
    return elev, lcp


@pytest.fixture
def client(session_factory, test_settings: Settings):
    def _override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_settings] = lambda: test_settings

    with (
        patch("api.routers.forecasts.get_session_factory", return_value=session_factory),
        TestClient(app) as test_client,
    ):
        yield test_client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers for mocking
# ---------------------------------------------------------------------------


def _make_terrain_mock(elev: ElevationTile, lcp: LandCoverTile):
    bbox = Wgs84BoundingBox(north=39.85, east=-105.65, south=39.65, west=-105.85)
    return ForecastTerrainTiles(
        elevation_tile=elev,
        land_cover_tile=lcp,
        user_bbox=bbox,
        padded_bbox=bbox,
    )


def _make_weather_grids(
    test_settings: Settings, forecast_id: str, num_timesteps: int = 3,
) -> ForecastWeatherGrids:
    """Create real weather grid files on disk and return the dataclass."""
    weather_dir = test_settings.data_dir / "weather" / forecast_id
    weather_dir.mkdir(parents=True, exist_ok=True)
    relative_weather_dir = Path("weather") / forecast_id

    timesteps: list[ForcingTimestep] = []
    for i in range(num_timesteps):
        valid_time = utc(2026, 5, 15, 6 + i)
        label = valid_time.strftime("%Y%m%d_%H%M")

        speed_file = weather_dir / f"speed_{label}.asc"
        direction_file = weather_dir / f"direction_{label}.asc"
        speed_file.write_text(f"speed data for hour {i}")
        direction_file.write_text(f"direction data for hour {i}")

        timesteps.append(ForcingTimestep(
            valid_time=valid_time,
            speed_grid_path=relative_weather_dir / speed_file.name,
            direction_grid_path=relative_weather_dir / direction_file.name,
            cycle=HrrrCycle(
                analysis_time=valid_time,
                forecast_hour=0,
                valid_time=valid_time,
            ),
        ))

    metadata = {"forecast_id": forecast_id, "timesteps": num_timesteps}
    (weather_dir / "metadata.json").write_text(json.dumps(metadata))

    return ForecastWeatherGrids(
        timesteps=timesteps,
        weather_dir=relative_weather_dir,
    )


def _solver_side_effect(test_settings: Settings):
    """Return a side_effect callable that writes dummy output files."""
    def _write_output(**kwargs):
        forecast_id = kwargs["forecast_id"]
        output_dir = test_settings.data_dir / "output" / forecast_id
        output_dir.mkdir(parents=True, exist_ok=True)

        (output_dir / "speed_20260515_0600.asc").write_text("solved speed 0600")
        (output_dir / "direction_20260515_0600.asc").write_text("solved dir 0600")
        (output_dir / "metadata.json").write_text(
            json.dumps({"forecast_id": forecast_id, "solver": "mock"})
        )

        return MagicMock(
            output_dir=Path("output") / forecast_id,
            timestep_outputs=[],
            elapsed_seconds=1.5,
        )
    return _write_output


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEndToEndHappyPath:
    """POST forecast -> run pipeline -> GET status -> GET output -> download."""

    def test_full_lifecycle(
        self,
        client: TestClient,
        db_session: Session,
        test_settings: Settings,
        _seed_tiles,
    ) -> None:
        elev, lcp = _seed_tiles

        terrain_result = _make_terrain_mock(elev, lcp)

        with (
            patch(
                "api.routers.forecasts._validate_conus_location",
            ),
            patch(
                "api.routers.forecasts.ensure_tiles_for_forecast",
                return_value=terrain_result,
            ),
            patch(
                "api.routers.forecasts.prepare_weather_for_forecast",
            ) as mock_weather,
            patch(
                "api.routers.forecasts.run_solver_for_forecast",
                side_effect=_solver_side_effect(test_settings),
            ),
        ):

            def weather_side_effect(**kwargs):
                return _make_weather_grids(
                    test_settings, kwargs["forecast_id"],
                )
            mock_weather.side_effect = weather_side_effect

            # 1. Submit forecast
            create_response = client.post("/forecasts/", json={
                "latitude": BERTHOUD_LAT,
                "longitude": BERTHOUD_LON,
                "size_km": BERTHOUD_SIZE_KM,
                "forecast_start": "2026-05-15T06:00:00Z",
                "duration_hours": 3,
            })
            assert create_response.status_code == 201
            forecast_data = create_response.json()
            forecast_id = forecast_data["id"]
            assert forecast_data["status"] == "queued" or forecast_data["status"] == "completed"

        # 2. Check status
        status_response = client.get(f"/forecasts/{forecast_id}")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["status"] == "completed"
        assert status_data["started_at"] is not None
        assert status_data["completed_at"] is not None

        # 3. List output files
        output_response = client.get(f"/forecasts/{forecast_id}/output")
        assert output_response.status_code == 200
        output_data = output_response.json()
        assert output_data["forecast_id"] == forecast_id
        filenames = {f["filename"] for f in output_data["files"]}
        assert "speed_20260515_0600.asc" in filenames
        assert "direction_20260515_0600.asc" in filenames
        assert "metadata.json" in filenames

        # 4. Download a specific output file
        download_response = client.get(
            f"/forecasts/{forecast_id}/output/speed_20260515_0600.asc"
        )
        assert download_response.status_code == 200
        assert download_response.text == "solved speed 0600"
        assert download_response.headers["content-type"] == "text/plain; charset=utf-8"


class TestEndToEndWeatherFailure:
    """Submit forecast -> weather fails -> status=failed -> output returns 409."""

    def test_weather_failure_propagates(
        self,
        client: TestClient,
        db_session: Session,
        test_settings: Settings,
        _seed_tiles,
    ) -> None:
        elev, lcp = _seed_tiles
        terrain_result = _make_terrain_mock(elev, lcp)

        from services.weather import WeatherDownloadError

        with (
            patch(
                "api.routers.forecasts._validate_conus_location",
            ),
            patch(
                "api.routers.forecasts.ensure_tiles_for_forecast",
                return_value=terrain_result,
            ),
            patch(
                "api.routers.forecasts.prepare_weather_for_forecast",
                side_effect=WeatherDownloadError("S3 bucket unreachable"),
            ),
        ):
            create_response = client.post("/forecasts/", json={
                "latitude": BERTHOUD_LAT,
                "longitude": BERTHOUD_LON,
                "size_km": BERTHOUD_SIZE_KM,
                "forecast_start": "2026-05-15T06:00:00Z",
                "duration_hours": 3,
            })
            assert create_response.status_code == 201
            forecast_id = create_response.json()["id"]

        # Status should be failed
        status_response = client.get(f"/forecasts/{forecast_id}")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["status"] == "failed"
        assert "S3 bucket unreachable" in status_data["error_message"]

        # Output should return 409 with retry_after_seconds=None (failed)
        output_response = client.get(f"/forecasts/{forecast_id}/output")
        assert output_response.status_code == 409
        detail = output_response.json()["detail"]
        assert detail["status"] == "failed"
        assert detail["retry_after_seconds"] is None


class TestEndToEndPagination:
    """Verify paginated list_forecasts via HTTP."""

    def test_paginated_list(
        self,
        client: TestClient,
        db_session: Session,
        test_settings: Settings,
        _seed_tiles,
    ) -> None:
        elev, lcp = _seed_tiles
        terrain_result = _make_terrain_mock(elev, lcp)

        with (
            patch("api.routers.forecasts._validate_conus_location"),
            patch(
                "api.routers.forecasts.ensure_tiles_for_forecast",
                return_value=terrain_result,
            ),
            patch("api.routers.forecasts.prepare_weather_for_forecast") as mock_weather,
            patch(
                "api.routers.forecasts.run_solver_for_forecast",
                side_effect=_solver_side_effect(test_settings),
            ),
        ):
            mock_weather.side_effect = lambda **kw: _make_weather_grids(
                test_settings, kw["forecast_id"],
            )

            for _ in range(3):
                resp = client.post("/forecasts/", json={
                    "latitude": BERTHOUD_LAT,
                    "longitude": BERTHOUD_LON,
                    "size_km": BERTHOUD_SIZE_KM,
                    "forecast_start": "2026-05-15T06:00:00Z",
                    "duration_hours": 1,
                })
                assert resp.status_code == 201

        response = client.get("/forecasts/?limit=2&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

        response_page2 = client.get("/forecasts/?limit=2&offset=2")
        data_page2 = response_page2.json()
        assert len(data_page2["items"]) == 1
