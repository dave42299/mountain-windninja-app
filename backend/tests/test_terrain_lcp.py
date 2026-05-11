"""Tests for LANDFIRE LCP terrain path (Docker mocked)."""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from models.database import Base
from services import terrain_lcp
from services.terrain import Wgs84BoundingBox, ensure_land_cover_tile
from services.terrain_dem import TerrainOutsideUsError


def _memory_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _touch_lcp_outputs(host_data_dir: Path, relative_lcp: Path) -> None:
    absolute_lcp = host_data_dir / relative_lcp
    absolute_lcp.parent.mkdir(parents=True, exist_ok=True)
    absolute_lcp.write_bytes(b"\x00")
    absolute_lcp.with_suffix(".prj").write_text('GEOGCS["WGS 84"]\n', encoding="utf-8")


def test_validate_conus_rejects_non_us_for_lcp() -> None:
    session = _memory_session()
    try:
        with pytest.raises(TerrainOutsideUsError):
            terrain_lcp.ensure_land_cover_tile(
                session,
                lookup=Wgs84BoundingBox(north=55.0, east=10.0, south=54.0, west=9.0),
                download=Wgs84BoundingBox(north=55.0, east=10.0, south=54.0, west=9.0),
                data_dir=Path("/tmp"),
                solver_image="img",
                subprocess_timeout_seconds=60,
            )
    finally:
        session.close()


def test_run_lcp_docker_pipeline_builds_expected_command(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    relative = Path("land_cover") / "abc.lcp"
    with patch.object(terrain_lcp.subprocess, "run") as mock_run:
        mock_run.return_value = CompletedProcess(args=[], returncode=0)
        terrain_lcp._run_lcp_docker_pipeline(
            solver_image="testimg",
            host_data_dir=root,
            relative_lcp=relative,
            download=Wgs84BoundingBox(north=40.0, east=-105.0, south=39.5, west=-105.6),
            subprocess_timeout_seconds=90,
        )
    mock_run.assert_called_once()
    argv = mock_run.call_args[0][0]
    assert argv[:4] == ["docker", "run", "--rm", "-v"]
    assert argv[4] == f"{root.resolve()}:/data"
    assert argv[5] == "testimg"
    assert argv[6:8] == ["bash", "-lc"]
    inner = argv[8]
    assert "fetch_dem --bbox 40.0 -105.0 39.5 -105.6 --src lcp" in inner
    assert "gdalsrsinfo -o wkt" in inner


@patch.object(terrain_lcp, "_read_land_cover_spatial_metadata")
@patch.object(terrain_lcp, "_run_lcp_docker_pipeline")
def test_ensure_land_cover_tile_writes_row(
    mock_run: MagicMock,
    mock_read: MagicMock,
    tmp_path: Path,
) -> None:
    mock_read.return_value = (40.0, -105.0, 39.0, -106.0, 5070)

    def _side_effect(**kwargs: object) -> None:
        _touch_lcp_outputs(
            Path(kwargs["host_data_dir"]),
            Path(kwargs["relative_lcp"]),
        )

    mock_run.side_effect = _side_effect

    session = _memory_session()
    try:
        lookup = Wgs84BoundingBox(
            north=39.82, east=-105.60, south=39.68, west=-105.80
        )
        tile = terrain_lcp.ensure_land_cover_tile(
            session,
            lookup=lookup,
            download=lookup,
            data_dir=tmp_path,
            solver_image="mountain-windninja:local",
            subprocess_timeout_seconds=120,
        )
        session.commit()

        assert tile.source == terrain_lcp.LAND_COVER_SOURCE_LANDFIRE
        assert tile.crs_epsg == 5070
        assert tile.file_path.startswith("land_cover/")
        assert tile.file_path.endswith(".lcp")
        assert (tmp_path / tile.file_path).is_file()
        assert (tmp_path / tile.file_path).with_suffix(".prj").is_file()
        mock_run.assert_called_once()
    finally:
        session.close()


@patch.object(terrain_lcp, "_read_land_cover_spatial_metadata")
@patch.object(terrain_lcp, "_run_lcp_docker_pipeline")
def test_ensure_land_cover_tile_reuses_cache(
    mock_run: MagicMock,
    mock_read: MagicMock,
    tmp_path: Path,
) -> None:
    mock_read.return_value = (40.0, -105.0, 39.0, -106.0, 5070)

    def _side_effect(**kwargs: object) -> None:
        _touch_lcp_outputs(
            Path(kwargs["host_data_dir"]),
            Path(kwargs["relative_lcp"]),
        )

    mock_run.side_effect = _side_effect

    session = _memory_session()
    try:
        lookup = Wgs84BoundingBox(north=39.82, east=-105.60, south=39.68, west=-105.80)
        first = terrain_lcp.ensure_land_cover_tile(
            session,
            lookup=lookup,
            download=lookup,
            data_dir=tmp_path,
            solver_image="img",
            subprocess_timeout_seconds=120,
        )
        session.flush()
        second = terrain_lcp.ensure_land_cover_tile(
            session,
            lookup=lookup,
            download=lookup,
            data_dir=tmp_path,
            solver_image="img",
            subprocess_timeout_seconds=120,
        )
        session.commit()
        assert second.id == first.id
        mock_run.assert_called_once()
    finally:
        session.close()


def test_terrain_module_wraps_land_cover_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "solver_image", "test-solver:latest")
    monkeypatch.setattr(settings, "terrain_lcp_subprocess_timeout_seconds", 999)

    session = _memory_session()
    try:
        with (
            patch.object(terrain_lcp, "_run_lcp_docker_pipeline") as mock_run,
            patch.object(
                terrain_lcp,
                "_read_land_cover_spatial_metadata",
                return_value=(40.0, -105.0, 39.0, -106.0, 5070),
            ),
        ):

            def _side_effect(**kwargs: object) -> None:
                assert kwargs["solver_image"] == "test-solver:latest"
                assert kwargs["subprocess_timeout_seconds"] == 999
                _touch_lcp_outputs(
                    Path(kwargs["host_data_dir"]),
                    Path(kwargs["relative_lcp"]),
                )

            mock_run.side_effect = _side_effect
            ensure_land_cover_tile(
                session,
                Wgs84BoundingBox(north=39.82, east=-105.60, south=39.68, west=-105.80),
            )
        session.commit()
    finally:
        session.close()


def test_non_positive_timeout_raises() -> None:
    session = _memory_session()
    try:
        with pytest.raises(ValueError, match="positive"):
            terrain_lcp.ensure_land_cover_tile(
                session,
                lookup=Wgs84BoundingBox(north=39.82, east=-105.60, south=39.68, west=-105.80),
                download=Wgs84BoundingBox(north=39.82, east=-105.60, south=39.68, west=-105.80),
                data_dir=Path("/tmp"),
                solver_image="img",
                subprocess_timeout_seconds=0,
            )
    finally:
        session.close()
