"""Opt-in Docker integration test for the solver pipeline.

Set ``RUN_SOLVER_INTEGRATION=1`` to run. Requires the WindNinja Docker image
(``mountain-windninja:local``) to be built and available locally.

This test:
  1. Uses a real DEM tile (downloaded via py3dep if not cached).
  2. Uses synthetic weather forcing grids (ASCII files written by the test).
  3. Runs the actual WindNinja solver inside Docker via ``run_solver_for_forecast``.
  4. Verifies WindNinja produces expected output files.
  5. Cleans up output and mesh cache after the test.

Typical runtime: 30-120s depending on domain size and solver type.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds

from models.enums import SolverType
from tests.conftest import utc
from models.orm import ElevationTile
from services.solver import SolverResult, run_solver_for_forecast
from services.weather import ForcingTimestep, ForecastWeatherGrids
from services.weather_models import HrrrCycle

pytestmark = pytest.mark.integration

_SKIP_REASON = (
    "Set RUN_SOLVER_INTEGRATION=1 to run Docker-based solver tests. "
    "Requires mountain-windninja:local Docker image."
)


def _write_synthetic_dem(path: Path, *, rows: int = 50, cols: int = 50) -> None:
    """Write a minimal but valid GeoTIFF DEM for WindNinja.

    Creates a small UTM Zone 13N tile with gentle terrain (sloped plane).
    """
    west, south = 446000.0, 4408000.0
    cell_size = 30.0
    east = west + cols * cell_size
    north = south + rows * cell_size
    transform = from_bounds(west, south, east, north, cols, rows)

    elevation = np.linspace(3000, 3500, rows * cols).reshape(rows, cols).astype(np.float32)

    with rasterio.open(
        path, "w",
        driver="GTiff", width=cols, height=rows, count=1,
        dtype="float32", crs=CRS.from_epsg(32613),
        transform=transform,
    ) as dst:
        dst.write(elevation, 1)


def _write_ascii_grid(
    path: Path, *, rows: int, cols: int, xllcorner: float, yllcorner: float,
    cellsize: float, value: float, crs_wkt: str,
) -> None:
    """Write an ESRI ASCII Grid with a .prj sidecar."""
    header = (
        f"ncols         {cols}\n"
        f"nrows         {rows}\n"
        f"xllcorner     {xllcorner}\n"
        f"yllcorner     {yllcorner}\n"
        f"cellsize      {cellsize}\n"
        f"NODATA_value  -9999\n"
    )
    data_rows = "\n".join(" ".join(f"{value:.6f}" for _ in range(cols)) for _ in range(rows))
    path.write_text(header + data_rows + "\n", encoding="utf-8")
    path.with_suffix(".prj").write_text(crs_wkt, encoding="utf-8")


def _make_forcing_grids(
    data_dir: Path, forecast_id: str,
) -> ForecastWeatherGrids:
    """Create one timestep of synthetic forcing grids aligned to the DEM.

    Forcing grids are DEM size + 2 pixels per the alignment contract.
    """
    dem_rows, dem_cols = 50, 50
    cell_size = 30.0
    west, south = 446000.0, 4408000.0

    forcing_rows = dem_rows + 2
    forcing_cols = dem_cols + 2
    forcing_west = west - cell_size
    forcing_south = south - cell_size

    crs_wkt = CRS.from_epsg(32613).to_wkt()

    weather_dir = data_dir / "weather" / forecast_id
    weather_dir.mkdir(parents=True, exist_ok=True)
    relative_weather_dir = Path("weather") / forecast_id

    valid_time = utc(2026, 5, 15, 12)
    label = valid_time.strftime("%Y%m%d_%H%M")

    speed_path = weather_dir / f"speed_{label}.asc"
    direction_path = weather_dir / f"direction_{label}.asc"

    _write_ascii_grid(
        speed_path,
        rows=forcing_rows, cols=forcing_cols,
        xllcorner=forcing_west, yllcorner=forcing_south,
        cellsize=cell_size, value=5.0,
        crs_wkt=crs_wkt,
    )
    _write_ascii_grid(
        direction_path,
        rows=forcing_rows, cols=forcing_cols,
        xllcorner=forcing_west, yllcorner=forcing_south,
        cellsize=cell_size, value=270.0,
        crs_wkt=crs_wkt,
    )

    timestep = ForcingTimestep(
        valid_time=valid_time,
        speed_grid_path=relative_weather_dir / speed_path.name,
        direction_grid_path=relative_weather_dir / direction_path.name,
        cycle=HrrrCycle(
            analysis_time=valid_time,
            forecast_hour=0,
            valid_time=valid_time,
        ),
    )

    return ForecastWeatherGrids(
        timesteps=[timestep],
        weather_dir=relative_weather_dir,
    )


@pytest.mark.skipif(
    os.environ.get("RUN_SOLVER_INTEGRATION") != "1",
    reason=_SKIP_REASON,
)
def test_solver_runs_mass_conservation(tmp_path: Path) -> None:
    """Run mass_conservation solver on a tiny synthetic domain.

    Mass conservation is faster than momentum (~5-10s vs 30-120s) so it is
    a better choice for integration testing.
    """
    data_dir = tmp_path / "data"
    for subdir in ("elevation", "land_cover", "output", "weather"):
        (data_dir / subdir).mkdir(parents=True)

    dem_relative = Path("elevation/test_dem.tif")
    dem_absolute = data_dir / dem_relative
    _write_synthetic_dem(dem_absolute)

    tile = ElevationTile(
        id=uuid.uuid4(),
        bbox_north=39.82, bbox_south=39.60,
        bbox_east=-105.50, bbox_west=-105.80,
        crs_epsg=32613,
        file_path=dem_relative.as_posix(),
        source="usgs_3dep",
        file_size_bytes=dem_absolute.stat().st_size,
    )

    forecast_id = str(uuid.uuid4())
    weather_grids = _make_forcing_grids(data_dir, forecast_id)

    try:
        result = run_solver_for_forecast(
            forecast_id=forecast_id,
            weather_grids=weather_grids,
            elevation_tile=tile,
            solver_type=SolverType.mass_conservation,
            output_wind_height=10.0,
            data_dir=data_dir,
            solver_threads=1,
            solver_timeout_seconds=120,
            solver_max_retries=1,
            solver_mesh_resolution=100.0,
            solver_vegetation="grass",
        )

        assert isinstance(result, SolverResult)
        assert result.output_dir.parts[0] == "output"
        assert result.elapsed_seconds > 0

        output_absolute = data_dir / result.output_dir
        assert output_absolute.is_dir()

        output_files = list(output_absolute.iterdir())
        output_names = {f.name for f in output_files}
        assert any(name.endswith(".asc") for name in output_names), (
            f"Expected .asc output files, got: {output_names}"
        )
        assert "metadata.json" in output_names

    finally:
        output_dir = data_dir / "output" / forecast_id
        if output_dir.exists():
            shutil.rmtree(output_dir)
        for entry in (data_dir / "elevation").glob("NINJAFOAM_*"):
            if entry.is_dir():
                shutil.rmtree(entry)
