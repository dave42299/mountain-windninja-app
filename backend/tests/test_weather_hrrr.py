"""Tests for services.weather_hrrr -- HRRR download and GRIB-to-grid conversion."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds

from services.weather_hrrr import (
    FORCING_NODATA,
    DemGridSpec,
    WeatherDownloadError,
    _cleanup_forcing_files,
    padded_grid_spec,
    process_timestep,
    read_dem_grid_spec,
    uv_to_speed_direction,
    write_ascii_grid,
)
from services.weather_models import HrrrCycle


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_UTM13N = CRS.from_epsg(32613)


def _make_dem_spec(
    width: int = 100,
    height: int = 80,
    pixel_size: float = 10.0,
) -> DemGridSpec:
    """Build a synthetic DemGridSpec for testing."""
    left = 450_000.0
    bottom = 4_400_000.0
    right = left + width * pixel_size
    top = bottom + height * pixel_size
    transform = from_bounds(left, bottom, right, top, width, height)
    return DemGridSpec(
        width=width,
        height=height,
        transform=transform,
        crs=_UTM13N,
        bounds=rasterio.coords.BoundingBox(left, bottom, right, top),
    )


def _write_synthetic_dem(path: Path, spec: DemGridSpec) -> None:
    """Write a minimal GeoTIFF matching the given DemGridSpec."""
    data = np.ones((spec.height, spec.width), dtype=np.float32) * 3000.0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=spec.height,
        width=spec.width,
        count=1,
        dtype="float32",
        crs=spec.crs,
        transform=spec.transform,
    ) as ds:
        ds.write(data, 1)


# ---------------------------------------------------------------------------
# uv_to_speed_direction
# ---------------------------------------------------------------------------


class TestUvToSpeedDirection:
    def test_pure_east_wind(self) -> None:
        """U=5, V=0 → speed=5, direction=270° (wind from the west)."""
        u = np.array([[5.0]])
        v = np.array([[0.0]])
        speed, direction = uv_to_speed_direction(u, v)
        assert speed[0, 0] == pytest.approx(5.0)
        assert direction[0, 0] == pytest.approx(270.0)

    def test_pure_north_wind(self) -> None:
        """U=0, V=5 → speed=5, direction=180° (wind from the south)."""
        u = np.array([[0.0]])
        v = np.array([[5.0]])
        speed, direction = uv_to_speed_direction(u, v)
        assert speed[0, 0] == pytest.approx(5.0)
        assert direction[0, 0] == pytest.approx(180.0)

    def test_pure_south_wind(self) -> None:
        """U=0, V=-5 → speed=5, direction=0° (wind from the north)."""
        u = np.array([[0.0]])
        v = np.array([[-5.0]])
        speed, direction = uv_to_speed_direction(u, v)
        assert speed[0, 0] == pytest.approx(5.0)
        assert direction[0, 0] == pytest.approx(0.0, abs=1e-10)

    def test_pure_west_wind(self) -> None:
        """U=-5, V=0 → speed=5, direction=90° (wind from the east)."""
        u = np.array([[-5.0]])
        v = np.array([[0.0]])
        speed, direction = uv_to_speed_direction(u, v)
        assert speed[0, 0] == pytest.approx(5.0)
        assert direction[0, 0] == pytest.approx(90.0)

    def test_diagonal_wind(self) -> None:
        """U=3, V=4 → speed=5, direction between 180 and 270."""
        u = np.array([[3.0]])
        v = np.array([[4.0]])
        speed, direction = uv_to_speed_direction(u, v)
        assert speed[0, 0] == pytest.approx(5.0)
        expected_dir = (270.0 - math.degrees(math.atan2(4.0, 3.0))) % 360.0
        assert direction[0, 0] == pytest.approx(expected_dir)

    def test_nodata_propagation(self) -> None:
        """Nodata in either component produces nodata in both outputs."""
        u = np.array([[5.0, FORCING_NODATA]])
        v = np.array([[FORCING_NODATA, 3.0]])
        speed, direction = uv_to_speed_direction(u, v)
        assert speed[0, 0] == pytest.approx(FORCING_NODATA)
        assert speed[0, 1] == pytest.approx(FORCING_NODATA)
        assert direction[0, 0] == pytest.approx(FORCING_NODATA)
        assert direction[0, 1] == pytest.approx(FORCING_NODATA)

    def test_nan_propagation(self) -> None:
        """NaN in either component produces nodata in both outputs."""
        u = np.array([[float("nan"), 5.0]])
        v = np.array([[3.0, float("nan")]])
        speed, direction = uv_to_speed_direction(u, v)
        assert speed[0, 0] == pytest.approx(FORCING_NODATA)
        assert speed[0, 1] == pytest.approx(FORCING_NODATA)

    def test_batch_array(self) -> None:
        """Vectorized operation on a multi-element array."""
        u = np.array([[5.0, 0.0], [0.0, -5.0]])
        v = np.array([[0.0, 5.0], [-5.0, 0.0]])
        speed, direction = uv_to_speed_direction(u, v)
        assert speed.shape == (2, 2)
        np.testing.assert_allclose(speed, [[5.0, 5.0], [5.0, 5.0]])


# ---------------------------------------------------------------------------
# padded_grid_spec
# ---------------------------------------------------------------------------


class TestPaddedGridSpec:
    def test_dimensions_are_dem_plus_two(self) -> None:
        spec = _make_dem_spec(width=100, height=80, pixel_size=10.0)
        _, padded_width, padded_height, _ = padded_grid_spec(spec)
        assert padded_width == 102
        assert padded_height == 82

    def test_extent_expanded_by_one_pixel(self) -> None:
        spec = _make_dem_spec(width=100, height=80, pixel_size=10.0)
        _, _, _, (left, bottom, right, top) = padded_grid_spec(spec)
        assert left == pytest.approx(spec.bounds.left - 10.0)
        assert bottom == pytest.approx(spec.bounds.bottom - 10.0)
        assert right == pytest.approx(spec.bounds.right + 10.0)
        assert top == pytest.approx(spec.bounds.top + 10.0)


# ---------------------------------------------------------------------------
# write_ascii_grid
# ---------------------------------------------------------------------------


class TestWriteAsciiGrid:
    def test_header_format(self, tmp_path: Path) -> None:
        data = np.array([[1.0, 2.0], [3.0, 4.0]])
        transform = from_bounds(100.0, 200.0, 120.0, 220.0, 2, 2)
        output = tmp_path / "test.asc"

        write_ascii_grid(data, transform, _UTM13N, output)

        lines = output.read_text().splitlines()
        assert lines[0].startswith("ncols")
        assert "2" in lines[0]
        assert lines[1].startswith("nrows")
        assert "2" in lines[1]
        assert lines[2].startswith("xllcorner")
        assert lines[3].startswith("yllcorner")
        assert lines[4].startswith("cellsize")
        assert lines[5].startswith("NODATA_value")
        assert "-9999" in lines[5]

    def test_data_values_written_correctly(self, tmp_path: Path) -> None:
        data = np.array([[1.5, 2.5], [3.5, FORCING_NODATA]])
        transform = from_bounds(0.0, 0.0, 20.0, 20.0, 2, 2)
        output = tmp_path / "test.asc"

        write_ascii_grid(data, transform, _UTM13N, output)

        lines = output.read_text().splitlines()
        row1 = lines[6].split()
        assert float(row1[0]) == pytest.approx(1.5)
        assert float(row1[1]) == pytest.approx(2.5)
        row2 = lines[7].split()
        assert float(row2[0]) == pytest.approx(3.5)
        assert float(row2[1]) == pytest.approx(FORCING_NODATA)

    def test_prj_sidecar_created(self, tmp_path: Path) -> None:
        data = np.array([[1.0]])
        transform = from_bounds(0.0, 0.0, 10.0, 10.0, 1, 1)
        output = tmp_path / "test.asc"

        write_ascii_grid(data, transform, _UTM13N, output)

        prj_path = output.with_suffix(".prj")
        assert prj_path.exists()
        prj_content = prj_path.read_text()
        assert "UTM" in prj_content or "Transverse_Mercator" in prj_content

    def test_cellsize_from_transform(self, tmp_path: Path) -> None:
        data = np.array([[1.0, 2.0], [3.0, 4.0]])
        transform = from_bounds(0.0, 0.0, 200.0, 200.0, 2, 2)
        output = tmp_path / "test.asc"

        write_ascii_grid(data, transform, _UTM13N, output)

        lines = output.read_text().splitlines()
        cellsize_line = lines[4]
        cellsize_value = float(cellsize_line.split()[-1])
        assert cellsize_value == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# read_dem_grid_spec
# ---------------------------------------------------------------------------


class TestReadDemGridSpec:
    def test_reads_synthetic_dem(self, tmp_path: Path) -> None:
        spec = _make_dem_spec()
        dem_path = tmp_path / "test.tif"
        _write_synthetic_dem(dem_path, spec)

        result = read_dem_grid_spec(dem_path)

        assert result.width == spec.width
        assert result.height == spec.height
        assert result.crs == spec.crs

    def test_raises_for_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(WeatherDownloadError, match="Cannot open DEM"):
            read_dem_grid_spec(tmp_path / "nonexistent.tif")


# ---------------------------------------------------------------------------
# _cleanup_forcing_files
# ---------------------------------------------------------------------------


class TestCleanupForcingFiles:
    def test_removes_asc_and_prj(self, tmp_path: Path) -> None:
        asc = tmp_path / "speed.asc"
        prj = tmp_path / "speed.prj"
        asc.write_text("data")
        prj.write_text("projection")

        _cleanup_forcing_files(asc)

        assert not asc.exists()
        assert not prj.exists()

    def test_ignores_missing_files(self, tmp_path: Path) -> None:
        _cleanup_forcing_files(tmp_path / "nonexistent.asc")


# ---------------------------------------------------------------------------
# process_timestep (mocked Herbie + GRIB)
# ---------------------------------------------------------------------------


class TestProcessTimestep:
    @pytest.fixture
    def dem_spec(self) -> DemGridSpec:
        return _make_dem_spec(width=10, height=8, pixel_size=100.0)

    @pytest.fixture
    def output_dir(self, tmp_path: Path) -> Path:
        out = tmp_path / "weather"
        out.mkdir()
        return out

    @pytest.fixture
    def cycle(self) -> HrrrCycle:
        return HrrrCycle(
            analysis_time=datetime(2026, 5, 10, 12, tzinfo=timezone.utc),
            forecast_hour=2,
            valid_time=datetime(2026, 5, 10, 14, tzinfo=timezone.utc),
        )

    def _make_fake_grib(self, tmp_path: Path) -> Path:
        """Create a synthetic 2-band GeoTIFF pretending to be a GRIB2 file.

        Uses Lambert Conformal Conic (HRRR native) with GRIB_ELEMENT tags.
        """
        from rasterio.crs import CRS as RioCRS

        grib_path = tmp_path / "fake.grib2"
        hrrr_crs = RioCRS.from_proj4(
            "+proj=lcc +lat_1=25 +lat_2=25 +lat_0=25 +lon_0=-95 "
            "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        )
        grib_transform = from_bounds(-2_000_000, -1_000_000, 2_000_000, 1_000_000, 20, 20)

        u_data = np.full((20, 20), 5.0, dtype=np.float64)
        v_data = np.full((20, 20), 0.0, dtype=np.float64)

        with rasterio.open(
            grib_path,
            "w",
            driver="GTiff",
            height=20,
            width=20,
            count=2,
            dtype="float64",
            crs=hrrr_crs,
            transform=grib_transform,
        ) as ds:
            ds.write(u_data, 1)
            ds.write(v_data, 2)
            ds.update_tags(1, GRIB_ELEMENT="UGRD")
            ds.update_tags(2, GRIB_ELEMENT="VGRD")

        return grib_path

    @patch("services.weather_hrrr.download_hrrr_grib")
    def test_produces_speed_and_direction_grids(
        self, mock_download: MagicMock, cycle: HrrrCycle,
        dem_spec: DemGridSpec, output_dir: Path, tmp_path: Path,
    ) -> None:
        fake_grib = self._make_fake_grib(tmp_path)
        mock_download.return_value = fake_grib

        speed_path, direction_path = process_timestep(cycle, dem_spec, output_dir)

        assert speed_path.exists()
        assert direction_path.exists()
        assert speed_path.with_suffix(".prj").exists()
        assert direction_path.with_suffix(".prj").exists()
        assert "speed_20260510_1400" in speed_path.name
        assert "direction_20260510_1400" in direction_path.name

    @patch("services.weather_hrrr.download_hrrr_grib")
    def test_speed_values_are_reasonable(
        self, mock_download: MagicMock, cycle: HrrrCycle,
        dem_spec: DemGridSpec, output_dir: Path, tmp_path: Path,
    ) -> None:
        fake_grib = self._make_fake_grib(tmp_path)
        mock_download.return_value = fake_grib

        speed_path, _ = process_timestep(cycle, dem_spec, output_dir)

        lines = speed_path.read_text().splitlines()
        data_lines = lines[6:]
        for line in data_lines:
            for val_str in line.split():
                val = float(val_str)
                if val != FORCING_NODATA:
                    assert 0 <= val <= 100, f"Unreasonable speed: {val}"

    @patch("services.weather_hrrr.download_hrrr_grib")
    def test_cleanup_on_download_failure(
        self, mock_download: MagicMock, cycle: HrrrCycle,
        dem_spec: DemGridSpec, output_dir: Path,
    ) -> None:
        mock_download.side_effect = WeatherDownloadError("S3 timeout")

        with pytest.raises(WeatherDownloadError, match="S3 timeout"):
            process_timestep(cycle, dem_spec, output_dir)

        asc_files = list(output_dir.glob("*.asc"))
        prj_files = list(output_dir.glob("*.prj"))
        assert len(asc_files) == 0
        assert len(prj_files) == 0
