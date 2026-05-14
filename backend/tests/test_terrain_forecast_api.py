"""Tests for :func:`services.terrain.ensure_tiles_for_forecast`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from models.orm import ElevationTile
from services.terrain import (
    ForecastTerrainTiles,
    TerrainDemError,
    TerrainLcpError,
    TerrainOutsideUsError,
    Wgs84BoundingBox,
    ensure_tiles_for_forecast,
)
from services.terrain_geometry import pad_bbox_fraction, square_bbox_wgs84
from tests.conftest import make_elevation_tile, make_land_cover_tile


# ---------------------------------------------------------------------------
# ForecastTerrainTiles dataclass
# ---------------------------------------------------------------------------


def test_forecast_terrain_tiles_holds_bbox_objects(db_session: object) -> None:
    elev = make_elevation_tile(db_session)  # type: ignore[arg-type]
    lcp = make_land_cover_tile(db_session)  # type: ignore[arg-type]
    user = Wgs84BoundingBox(north=40.0, east=-105.0, south=39.0, west=-106.0)
    padded = Wgs84BoundingBox(north=40.1, east=-104.9, south=38.9, west=-106.1)

    result = ForecastTerrainTiles(
        elevation_tile=elev,
        land_cover_tile=lcp,
        user_bbox=user,
        padded_bbox=padded,
    )

    assert result.elevation_tile is elev
    assert result.user_bbox is user
    assert result.padded_bbox is padded
    assert result.user_bbox.north == 40.0
    assert result.padded_bbox.north == 40.1


# ---------------------------------------------------------------------------
# Padding / bbox semantics
# ---------------------------------------------------------------------------


def _make_tile_factories(db_session: object) -> tuple[MagicMock, MagicMock]:
    """Return mocks for ensure_elevation_tile and ensure_land_cover_tile that
    insert real ORM rows so session.refresh() works after commit."""

    def _elev_side_effect(session: object, lookup: object, **kwargs: object) -> ElevationTile:
        return make_elevation_tile(session)  # type: ignore[arg-type]

    def _lcp_side_effect(session: object, lookup: object, **kwargs: object) -> object:
        return make_land_cover_tile(session)  # type: ignore[arg-type]

    mock_elev = MagicMock(side_effect=_elev_side_effect)
    mock_lcp = MagicMock(side_effect=_lcp_side_effect)
    return mock_elev, mock_lcp


@patch("services.terrain.ensure_land_cover_tile")
@patch("services.terrain.ensure_elevation_tile")
def test_ensure_tiles_lookup_uses_user_box_download_uses_padded(
    mock_elevation: MagicMock,
    mock_land_cover: MagicMock,
    db_session: object,
    tmp_path: Path,
) -> None:
    mock_elev_tile, mock_lcp_tile = _make_tile_factories(db_session)
    mock_elevation.side_effect = mock_elev_tile.side_effect
    mock_land_cover.side_effect = mock_lcp_tile.side_effect

    center_lat, center_lon, size_km = 39.74, -105.38, 10.0
    ensure_tiles_for_forecast(
        db_session,  # type: ignore[arg-type]
        center_latitude=center_lat,
        center_longitude=center_lon,
        size_km=size_km,
        data_dir=tmp_path,
        bbox_padding_fraction=0.25,
    )

    core = square_bbox_wgs84(center_lat, center_lon, size_km)
    padded = pad_bbox_fraction(core, fraction=0.25)

    mock_elevation.assert_called_once()
    mock_land_cover.assert_called_once()
    assert mock_elevation.call_args[0][1] == core
    assert mock_elevation.call_args[1]["download"] == padded
    assert mock_land_cover.call_args[0][1] == core
    assert mock_land_cover.call_args[1]["download"] == padded


@patch("services.terrain.ensure_land_cover_tile")
@patch("services.terrain.ensure_elevation_tile")
def test_ensure_tiles_custom_padding(
    mock_elevation: MagicMock,
    mock_land_cover: MagicMock,
    db_session: object,
    tmp_path: Path,
) -> None:
    mock_elev_tile, mock_lcp_tile = _make_tile_factories(db_session)
    mock_elevation.side_effect = mock_elev_tile.side_effect
    mock_land_cover.side_effect = mock_lcp_tile.side_effect

    center_lat, center_lon, size_km, padding = 40.0, -105.1, 8.0, 0.10
    ensure_tiles_for_forecast(
        db_session,  # type: ignore[arg-type]
        center_latitude=center_lat,
        center_longitude=center_lon,
        size_km=size_km,
        data_dir=tmp_path,
        bbox_padding_fraction=padding,
    )
    core = square_bbox_wgs84(center_lat, center_lon, size_km)
    padded = pad_bbox_fraction(core, fraction=padding)
    assert mock_elevation.call_args[0][1] == core
    assert mock_elevation.call_args[1]["download"] == padded


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_ensure_tiles_negative_padding_raises(db_session: object) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ensure_tiles_for_forecast(
            db_session,  # type: ignore[arg-type]
            center_latitude=39.74,
            center_longitude=-105.38,
            size_km=10.0,
            bbox_padding_fraction=-0.01,
        )


def test_ensure_tiles_rejects_non_conus_after_pad(db_session: object) -> None:
    with pytest.raises(TerrainOutsideUsError):
        ensure_tiles_for_forecast(
            db_session,  # type: ignore[arg-type]
            center_latitude=50.0,
            center_longitude=-105.0,
            size_km=10.0,
        )


# ---------------------------------------------------------------------------
# Return value
# ---------------------------------------------------------------------------


@patch("services.terrain.ensure_land_cover_tile")
@patch("services.terrain.ensure_elevation_tile")
def test_ensure_tiles_returns_bbox_objects(
    mock_elevation: MagicMock,
    mock_land_cover: MagicMock,
    db_session: object,
    tmp_path: Path,
) -> None:
    mock_elev_tile, mock_lcp_tile = _make_tile_factories(db_session)
    mock_elevation.side_effect = mock_elev_tile.side_effect
    mock_land_cover.side_effect = mock_lcp_tile.side_effect

    lat, lon, km = 39.74, -105.38, 10.0
    result = ensure_tiles_for_forecast(
        db_session,  # type: ignore[arg-type]
        center_latitude=lat,
        center_longitude=lon,
        size_km=km,
        data_dir=tmp_path,
    )

    core = square_bbox_wgs84(lat, lon, km)
    padded = pad_bbox_fraction(core, fraction=0.25)

    assert isinstance(result.user_bbox, Wgs84BoundingBox)
    assert isinstance(result.padded_bbox, Wgs84BoundingBox)
    assert result.user_bbox == core
    assert result.padded_bbox == padded


# ---------------------------------------------------------------------------
# Solver image / timeout forwarding
# ---------------------------------------------------------------------------


@patch("services.terrain.ensure_land_cover_tile")
@patch("services.terrain.ensure_elevation_tile")
def test_ensure_tiles_forwards_overrides(
    mock_elevation: MagicMock,
    mock_land_cover: MagicMock,
    db_session: object,
    tmp_path: Path,
) -> None:
    mock_elev_tile, mock_lcp_tile = _make_tile_factories(db_session)
    mock_elevation.side_effect = mock_elev_tile.side_effect
    mock_land_cover.side_effect = mock_lcp_tile.side_effect

    ensure_tiles_for_forecast(
        db_session,  # type: ignore[arg-type]
        center_latitude=39.74,
        center_longitude=-105.38,
        size_km=10.0,
        data_dir=tmp_path,
        solver_image="my:image",
        lcp_subprocess_timeout_seconds=123,
    )
    kwargs = mock_land_cover.call_args[1]
    assert kwargs["solver_image"] == "my:image"
    assert kwargs["subprocess_timeout_seconds"] == 123


def test_ensure_tiles_uses_settings_defaults(
    db_session: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ensure_tiles_for_forecast picks up solver_image and timeout from settings."""
    from config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "solver_image", "settings-image:v1")
    monkeypatch.setattr(settings, "terrain_lcp_subprocess_timeout_seconds", 777)

    mock_elev_tile, mock_lcp_tile = _make_tile_factories(db_session)

    with (
        patch("services.terrain.ensure_elevation_tile") as mock_elevation,
        patch("services.terrain.ensure_land_cover_tile") as mock_land_cover,
    ):
        mock_elevation.side_effect = mock_elev_tile.side_effect
        mock_land_cover.side_effect = mock_lcp_tile.side_effect

        ensure_tiles_for_forecast(
            db_session,  # type: ignore[arg-type]
            center_latitude=39.74,
            center_longitude=-105.38,
            size_km=10.0,
        )

        kwargs = mock_land_cover.call_args[1]
        assert kwargs["solver_image"] == "settings-image:v1"
        assert kwargs["subprocess_timeout_seconds"] == 777


# ---------------------------------------------------------------------------
# Partial-failure durability: DEM commit survives LCP failure
# ---------------------------------------------------------------------------


def test_dem_commit_survives_lcp_failure(db_session: object, tmp_path: Path) -> None:
    """DEM row must stay committed when LCP download fails.

    This validates the independent-commit strategy: if LCP fails, the DEM row
    (committed earlier) is preserved so the next request gets a DEM cache hit.
    """
    import numpy as np
    import rioxarray  # noqa: F401
    import xarray as xr
    from rasterio.transform import from_bounds

    # Minimal synthetic DEM for py3dep mock (same as in test_terrain_dem.py).
    left, bottom, right, top = -1_085_912.0, 1_380_418.0, -1_085_412.0, 1_380_918.0
    width, height = 6, 5
    transform = from_bounds(left, bottom, right, top, width, height)
    data = np.ones((height, width), dtype=np.float32) * 2500.0
    res_x = (right - left) / width
    res_y = (top - bottom) / height
    x_coords = left + res_x * (np.arange(width) + 0.5)
    y_coords = top - res_y * (np.arange(height) + 0.5)
    fake_dem = (
        xr.DataArray(
            data,
            dims=("y", "x"),
            coords={"y": ("y", top - res_y * (np.arange(height) + 0.5)),
                    "x": ("x", left + res_x * (np.arange(width) + 0.5))},
            name="elevation",
        )
        .rio.set_spatial_dims(x_dim="x", y_dim="y")
        .rio.write_transform(transform)
        .rio.write_crs("EPSG:5070")
    )

    with (
        patch("services.terrain_dem.py3dep.get_dem", return_value=fake_dem),
        patch(
            "services.terrain_lcp.download_land_cover_raster",
            side_effect=TerrainLcpError("LANDFIRE down"),
        ),
    ):
        with pytest.raises(TerrainLcpError):
            ensure_tiles_for_forecast(
                db_session,  # type: ignore[arg-type]
                center_latitude=34.866,
                center_longitude=-108.004,
                size_km=0.5,
                data_dir=tmp_path,
            )

    # DEM row must have survived in the database.
    dem_tiles = db_session.scalars(select(ElevationTile)).all()  # type: ignore[union-attr]
    assert len(dem_tiles) == 1, "DEM row was rolled back — independent commit failed"
