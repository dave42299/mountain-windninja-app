"""Tests for :func:`services.terrain.ensure_tiles_for_forecast`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from models.database import Base
from models.orm import ElevationTile, LandCoverTile
from services.terrain import ForecastTerrainTiles, ensure_tiles_for_forecast
from services.terrain_dem import TerrainOutsideUsError
from services.terrain_geometry import pad_bbox_fraction, square_bbox_wgs84


def _memory_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_forecast_terrain_tiles_is_frozen_named_tuple_like() -> None:
    elev = MagicMock(spec=ElevationTile)
    lcp = MagicMock(spec=LandCoverTile)
    result = ForecastTerrainTiles(
        elevation_tile=elev,
        land_cover_tile=lcp,
        user_bbox_north=40.0,
        user_bbox_east=-105.0,
        user_bbox_south=39.0,
        user_bbox_west=-106.0,
        padded_bbox_north=40.1,
        padded_bbox_east=-104.9,
        padded_bbox_south=38.9,
        padded_bbox_west=-106.1,
    )
    assert result.elevation_tile is elev
    assert result.user_bbox_north == 40.0
    assert result.padded_bbox_north == 40.1


@patch("services.terrain.ensure_land_cover_tile")
@patch("services.terrain.ensure_elevation_tile")
def test_ensure_tiles_lookup_uses_user_box_download_uses_padded(
    mock_elevation: MagicMock,
    mock_land_cover: MagicMock,
    tmp_path: Path,
) -> None:
    mock_elevation.return_value = MagicMock(spec=ElevationTile)
    mock_land_cover.return_value = MagicMock(spec=LandCoverTile)

    session = _memory_session()
    try:
        center_lat = 39.74
        center_lon = -105.38
        size_km = 10.0
        ensure_tiles_for_forecast(
            session,
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
    finally:
        session.close()


@patch("services.terrain.ensure_land_cover_tile")
@patch("services.terrain.ensure_elevation_tile")
def test_ensure_tiles_custom_padding(
    mock_elevation: MagicMock,
    mock_land_cover: MagicMock,
    tmp_path: Path,
) -> None:
    mock_elevation.return_value = MagicMock(spec=ElevationTile)
    mock_land_cover.return_value = MagicMock(spec=LandCoverTile)

    session = _memory_session()
    try:
        center_lat = 40.0
        center_lon = -105.1
        size_km = 8.0
        padding = 0.1
        ensure_tiles_for_forecast(
            session,
            center_latitude=center_lat,
            center_longitude=center_lon,
            size_km=size_km,
            data_dir=tmp_path,
            bbox_padding_fraction=padding,
        )
        core = square_bbox_wgs84(center_lat, center_lon, size_km)
        padded = pad_bbox_fraction(core, fraction=padding)
        mock_elevation.assert_called_once()
        assert mock_elevation.call_args[0][1] == core
        assert mock_elevation.call_args[1]["download"] == padded
    finally:
        session.close()


def test_ensure_tiles_negative_padding_raises() -> None:
    session = _memory_session()
    try:
        with pytest.raises(ValueError, match="non-negative"):
            ensure_tiles_for_forecast(
                session,
                center_latitude=39.74,
                center_longitude=-105.38,
                size_km=10.0,
                bbox_padding_fraction=-0.01,
            )
    finally:
        session.close()


def test_ensure_tiles_rejects_non_conus_after_pad() -> None:
    session = _memory_session()
    try:
        with pytest.raises(TerrainOutsideUsError):
            ensure_tiles_for_forecast(
                session,
                center_latitude=50.0,
                center_longitude=-105.0,
                size_km=500.0,
            )
    finally:
        session.close()


@patch("services.terrain.ensure_land_cover_tile")
@patch("services.terrain.ensure_elevation_tile")
def test_ensure_tiles_forwards_overrides(
    mock_elevation: MagicMock,
    mock_land_cover: MagicMock,
    tmp_path: Path,
) -> None:
    mock_elevation.return_value = MagicMock(spec=ElevationTile)
    mock_land_cover.return_value = MagicMock(spec=LandCoverTile)

    session = _memory_session()
    try:
        ensure_tiles_for_forecast(
            session,
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
    finally:
        session.close()


@patch("services.terrain.ensure_land_cover_tile")
@patch("services.terrain.ensure_elevation_tile")
def test_ensure_tiles_returns_user_and_padded_bboxes(
    mock_elevation: MagicMock,
    mock_land_cover: MagicMock,
    tmp_path: Path,
) -> None:
    elevation = MagicMock(spec=ElevationTile)
    land_cover = MagicMock(spec=LandCoverTile)
    mock_elevation.return_value = elevation
    mock_land_cover.return_value = land_cover

    session = _memory_session()
    try:
        lat, lon = 39.74, -105.38
        km = 10.0
        result = ensure_tiles_for_forecast(
            session,
            center_latitude=lat,
            center_longitude=lon,
            size_km=km,
            data_dir=tmp_path,
        )
        assert result.elevation_tile is elevation
        assert result.land_cover_tile is land_cover
        core = square_bbox_wgs84(lat, lon, km)
        padded = pad_bbox_fraction(core, fraction=0.25)
        assert (
            result.user_bbox_north,
            result.user_bbox_east,
            result.user_bbox_south,
            result.user_bbox_west,
        ) == core.as_tuple()
        assert (
            result.padded_bbox_north,
            result.padded_bbox_east,
            result.padded_bbox_south,
            result.padded_bbox_west,
        ) == padded.as_tuple()
    finally:
        session.close()
