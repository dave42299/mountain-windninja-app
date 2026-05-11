"""Tests for USGS 3DEP DEM helpers and cache (mocked network)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rioxarray  # noqa: F401 — registers ``.rio`` on xarray
import xarray as xr
from rasterio.transform import from_bounds
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from models.database import Base
from services import terrain_dem
from services.terrain import ensure_elevation_tile


def _memory_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _fake_dem_epsg5070() -> xr.DataArray:
    """Small synthetic DEM grid in EPSG:5070 for patching ``py3dep.get_dem``."""
    left, bottom, right, top = -1_085_912.0, 1_380_418.0, -1_085_412.0, 1_380_918.0
    width, height = 6, 5
    transform = from_bounds(left, bottom, right, top, width, height)
    data = np.ones((height, width), dtype=np.float32) * 2500.0
    res_x = (right - left) / width
    res_y = (top - bottom) / height
    x_coords = left + res_x * (np.arange(width) + 0.5)
    y_coords = top - res_y * (np.arange(height) + 0.5)
    data_array = xr.DataArray(
        data,
        dims=("y", "x"),
        coords={"y": ("y", y_coords), "x": ("x", x_coords)},
        name="elevation",
    )
    return (
        data_array.rio.set_spatial_dims(x_dim="x", y_dim="y")
        .rio.write_transform(transform)
        .rio.write_crs("EPSG:5070")
    )


def test_utm_epsg_from_wgs84_denver() -> None:
    assert terrain_dem.utm_epsg_from_wgs84(39.74, -104.99) == 32613


def test_utm_epsg_from_wgs84_southern_hemisphere() -> None:
    assert terrain_dem.utm_epsg_from_wgs84(-33.86, 151.2) == 32756


def test_validate_conus_accepts_berthoud_region() -> None:
    terrain_dem.validate_conus_wgs84_bbox(39.85, -105.65, 39.65, -105.85)


def test_validate_conus_rejects_europe() -> None:
    with pytest.raises(terrain_dem.TerrainOutsideUsError):
        terrain_dem.validate_conus_wgs84_bbox(55.0, 10.0, 54.0, 9.0)


def test_validate_conus_rejects_invalid_lat_order() -> None:
    with pytest.raises(ValueError, match="north"):
        terrain_dem.validate_conus_wgs84_bbox(39.0, -105.0, 40.0, -106.0)


# Bbox (north, east, south, west) that lies inside the WGS84 footprint of
# ``_fake_dem_epsg5070()`` after reproject/write (synthetic grid, not real terrain).
_SYNTHETIC_DEM_BBOX = (
    34.87023579240624,
    -108.00226586664824,
    34.86518365693566,
    -108.00839563663581,
)


@patch("services.terrain_dem.py3dep.get_dem", return_value=_fake_dem_epsg5070())
def test_ensure_elevation_tile_writes_file_and_row(mock_get_dem: object, tmp_path: Path) -> None:
    session = _memory_session()
    try:
        north, east, south, west = _SYNTHETIC_DEM_BBOX
        tile = terrain_dem.ensure_elevation_tile(
            session,
            north,
            east,
            south,
            west,
            data_dir=tmp_path,
        )
        session.commit()

        assert tile.source == terrain_dem.ELEVATION_SOURCE_USGS_3DEP
        center_lat = (north + south) / 2.0
        center_lon = (east + west) / 2.0
        assert tile.crs_epsg == terrain_dem.utm_epsg_from_wgs84(center_lat, center_lon)
        assert tile.file_path.startswith("elevation/")
        assert tile.file_path.endswith(".tif")
        assert (tmp_path / tile.file_path).is_file()
        assert tile.bbox_north > tile.bbox_south
        assert tile.bbox_east > tile.bbox_west
        assert mock_get_dem.call_count == 1
    finally:
        session.close()


@patch("services.terrain_dem.py3dep.get_dem", return_value=_fake_dem_epsg5070())
def test_ensure_elevation_tile_reuses_cache(mock_get_dem: object, tmp_path: Path) -> None:
    session = _memory_session()
    try:
        north, east, south, west = _SYNTHETIC_DEM_BBOX
        first = terrain_dem.ensure_elevation_tile(
            session,
            north,
            east,
            south,
            west,
            data_dir=tmp_path,
        )
        session.flush()

        second = terrain_dem.ensure_elevation_tile(
            session,
            north,
            east,
            south,
            west,
            data_dir=tmp_path,
        )
        session.commit()

        assert second.id == first.id
        assert mock_get_dem.call_count == 1
    finally:
        session.close()


def test_terrain_module_wraps_default_data_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    session = _memory_session()
    try:
        with patch("services.terrain_dem.py3dep.get_dem", return_value=_fake_dem_epsg5070()):
            north, east, south, west = _SYNTHETIC_DEM_BBOX
            tile = ensure_elevation_tile(session, north, east, south, west)
        session.commit()
        assert (tmp_path / tile.file_path).is_file()
    finally:
        session.close()
