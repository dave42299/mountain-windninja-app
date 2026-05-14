"""Opt-in terrain tests that use the network (USGS 3DEP) and/or Docker (LCP).

Set ``RUN_TERRAIN_INTEGRATION=1`` to run. Default CI / local pytest skips these.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from services.terrain import Wgs84BoundingBox, ensure_elevation_tile

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.environ.get("RUN_TERRAIN_INTEGRATION") != "1",
    reason="Set RUN_TERRAIN_INTEGRATION=1 to run network-backed terrain tests.",
)
def test_live_usgs_dem_download_smoke(db_session: object, tmp_path: Path) -> None:
    """Downloads a small CONUS DEM via py3dep (writes under tmp_path, inserts one row)."""
    extent = Wgs84BoundingBox(north=39.82, east=-105.60, south=39.80, west=-105.62)
    tile = ensure_elevation_tile(
        db_session,  # type: ignore[arg-type]
        extent,
        download=extent,
        data_dir=tmp_path,
    )
    db_session.commit()  # type: ignore[union-attr]
    assert tile.file_path.endswith(".tif")
    assert (tmp_path / tile.file_path).is_file()
