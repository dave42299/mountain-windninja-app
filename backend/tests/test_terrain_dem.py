"""Tests for USGS 3DEP DEM helpers and cache (network mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rioxarray  # noqa: F401 — registers ``.rio`` on xarray
import xarray as xr
from py3dep.exceptions import ServiceUnavailableError
from rasterio.transform import from_bounds

from services import terrain_dem
from services.terrain import TerrainDemError, Wgs84BoundingBox, ensure_elevation_tile


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


# Bbox that lies inside the WGS84 footprint of ``_fake_dem_epsg5070()`` after
# reproject/write (synthetic grid in CONUS Albers, not real terrain).
_SYNTHETIC_DEM_BBOX = Wgs84BoundingBox(
    north=34.87023579240624,
    east=-108.00226586664824,
    south=34.86518365693566,
    west=-108.00839563663581,
)


# ---------------------------------------------------------------------------
# utm_epsg_from_wgs84
# ---------------------------------------------------------------------------


def test_utm_epsg_from_wgs84_denver() -> None:
    assert terrain_dem.utm_epsg_from_wgs84(39.74, -104.99) == 32613


def test_utm_epsg_from_wgs84_southern_hemisphere() -> None:
    assert terrain_dem.utm_epsg_from_wgs84(-33.86, 151.2) == 32756


# ---------------------------------------------------------------------------
# download_elevation_raster
# ---------------------------------------------------------------------------


def test_download_elevation_raster_writes_file(tmp_path: Path) -> None:
    with patch("services.terrain_dem.py3dep.get_dem", return_value=_fake_dem_epsg5070()):
        terrain_dem.download_elevation_raster(_SYNTHETIC_DEM_BBOX, tmp_path / "out.tif")
    assert (tmp_path / "out.tif").is_file()


def test_download_elevation_raster_service_unavailable_raises(tmp_path: Path) -> None:
    with patch(
        "services.terrain_dem.py3dep.get_dem",
        side_effect=ServiceUnavailableError("down"),
    ):
        with pytest.raises(terrain_dem.TerrainDemError, match="unavailable"):
            terrain_dem.download_elevation_raster(
                _SYNTHETIC_DEM_BBOX, tmp_path / "out.tif"
            )


def test_download_elevation_raster_generic_exception_raises(tmp_path: Path) -> None:
    with patch(
        "services.terrain_dem.py3dep.get_dem",
        side_effect=RuntimeError("network error"),
    ):
        with pytest.raises(terrain_dem.TerrainDemError, match="Failed to download"):
            terrain_dem.download_elevation_raster(
                _SYNTHETIC_DEM_BBOX, tmp_path / "out.tif"
            )


# ---------------------------------------------------------------------------
# ensure_elevation_tile (orchestration: cache, download, metadata, ORM row)
# ---------------------------------------------------------------------------


@patch("services.terrain_dem.py3dep.get_dem", return_value=_fake_dem_epsg5070())
def test_ensure_elevation_tile_writes_file_and_row(
    mock_get_dem: object, db_session: object, tmp_path: Path
) -> None:
    tile = ensure_elevation_tile(
        db_session,  # type: ignore[arg-type]
        _SYNTHETIC_DEM_BBOX,
        download=_SYNTHETIC_DEM_BBOX,
        data_dir=tmp_path,
    )
    db_session.commit()  # type: ignore[union-attr]

    assert tile.source == terrain_dem.ELEVATION_SOURCE_USGS_3DEP
    center_lat = (_SYNTHETIC_DEM_BBOX.north + _SYNTHETIC_DEM_BBOX.south) / 2.0
    center_lon = (_SYNTHETIC_DEM_BBOX.east + _SYNTHETIC_DEM_BBOX.west) / 2.0
    assert tile.crs_epsg == terrain_dem.utm_epsg_from_wgs84(center_lat, center_lon)
    assert tile.file_path.startswith("elevation/")
    assert tile.file_path.endswith(".tif")
    assert (tmp_path / tile.file_path).is_file()
    assert tile.bbox_north > tile.bbox_south
    assert tile.bbox_east > tile.bbox_west
    assert mock_get_dem.call_count == 1  # type: ignore[union-attr]


@patch("services.terrain_dem.py3dep.get_dem", return_value=_fake_dem_epsg5070())
def test_ensure_elevation_tile_reuses_cache(
    mock_get_dem: object, db_session: object, tmp_path: Path
) -> None:
    first = ensure_elevation_tile(
        db_session,  # type: ignore[arg-type]
        _SYNTHETIC_DEM_BBOX,
        download=_SYNTHETIC_DEM_BBOX,
        data_dir=tmp_path,
    )
    db_session.flush()  # type: ignore[union-attr]

    # Lookup slightly inside the file-derived stored bbox so find_containing matches.
    second = ensure_elevation_tile(
        db_session,  # type: ignore[arg-type]
        Wgs84BoundingBox(
            north=first.bbox_north - 1e-4,
            east=first.bbox_east - 1e-4,
            south=first.bbox_south + 1e-4,
            west=first.bbox_west + 1e-4,
        ),
        download=_SYNTHETIC_DEM_BBOX,
        data_dir=tmp_path,
    )
    db_session.commit()  # type: ignore[union-attr]

    assert second.id == first.id
    assert mock_get_dem.call_count == 1  # type: ignore[union-attr]


def test_ensure_elevation_tile_cleanup_on_metadata_failure(
    db_session: object, tmp_path: Path
) -> None:
    """If metadata extraction fails after the file is written, the file is removed."""
    with (
        patch("services.terrain_dem.py3dep.get_dem", return_value=_fake_dem_epsg5070()),
        patch(
            "services.terrain._read_raster_wgs84_metadata",
            side_effect=ValueError("bad CRS"),
        ),
    ):
        with pytest.raises(TerrainDemError):
            ensure_elevation_tile(
                db_session,  # type: ignore[arg-type]
                _SYNTHETIC_DEM_BBOX,
                download=_SYNTHETIC_DEM_BBOX,
                data_dir=tmp_path,
            )

    elevation_dir = tmp_path / "elevation"
    tif_files = list(elevation_dir.glob("*.tif")) if elevation_dir.exists() else []
    assert tif_files == [], "Orphan .tif file left behind after metadata failure"
