"""Tests for LANDFIRE LCP terrain path (Docker mocked)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from services import terrain_lcp
from services.terrain import TerrainLcpError, Wgs84BoundingBox, ensure_land_cover_tile


def _touch_lcp_outputs(host_data_dir: Path, relative_lcp: Path) -> None:
    """Write minimal stub .lcp and .prj files so existence checks pass."""
    absolute_lcp = host_data_dir / relative_lcp
    absolute_lcp.parent.mkdir(parents=True, exist_ok=True)
    absolute_lcp.write_bytes(b"\x00")
    absolute_lcp.with_suffix(".prj").write_text('GEOGCS["WGS 84"]\n', encoding="utf-8")


# ---------------------------------------------------------------------------
# _run_lcp_docker_pipeline
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# download_land_cover_raster
# ---------------------------------------------------------------------------


def test_download_land_cover_raster_success(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    relative = Path("land_cover") / "test.lcp"
    (root / "land_cover").mkdir()

    def _side_effect(**kwargs: object) -> None:
        _touch_lcp_outputs(Path(str(kwargs["host_data_dir"])), Path(str(kwargs["relative_lcp"])))

    with patch.object(terrain_lcp, "_run_lcp_docker_pipeline", side_effect=_side_effect):
        terrain_lcp.download_land_cover_raster(
            Wgs84BoundingBox(north=39.82, east=-105.60, south=39.68, west=-105.80),
            host_data_dir=root,
            relative_lcp=relative,
            solver_image="img",
            timeout_seconds=60,
        )

    assert (root / relative).is_file()
    assert (root / relative).with_suffix(".prj").is_file()


def test_download_land_cover_raster_missing_lcp_raises(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    (root / "land_cover").mkdir()
    relative = Path("land_cover") / "test.lcp"

    with patch.object(terrain_lcp, "_run_lcp_docker_pipeline"):  # no side-effect = no files
        with pytest.raises(terrain_lcp.TerrainLcpError, match="Expected LCP"):
            terrain_lcp.download_land_cover_raster(
                Wgs84BoundingBox(north=39.82, east=-105.60, south=39.68, west=-105.80),
                host_data_dir=root,
                relative_lcp=relative,
                solver_image="img",
                timeout_seconds=60,
            )


def test_download_land_cover_raster_docker_not_found_raises(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    (root / "land_cover").mkdir()
    relative = Path("land_cover") / "test.lcp"

    with patch.object(
        terrain_lcp,
        "_run_lcp_docker_pipeline",
        side_effect=terrain_lcp.TerrainLcpError("Docker CLI not found"),
    ):
        with pytest.raises(terrain_lcp.TerrainLcpError, match="Docker"):
            terrain_lcp.download_land_cover_raster(
                Wgs84BoundingBox(north=39.82, east=-105.60, south=39.68, west=-105.80),
                host_data_dir=root,
                relative_lcp=relative,
                solver_image="img",
                timeout_seconds=60,
            )


def test_download_land_cover_raster_timeout_raises(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    (root / "land_cover").mkdir()
    relative = Path("land_cover") / "test.lcp"

    with patch.object(
        terrain_lcp,
        "_run_lcp_docker_pipeline",
        side_effect=terrain_lcp.TerrainLcpError("timed out after 60 seconds"),
    ):
        with pytest.raises(terrain_lcp.TerrainLcpError, match="timed out"):
            terrain_lcp.download_land_cover_raster(
                Wgs84BoundingBox(north=39.82, east=-105.60, south=39.68, west=-105.80),
                host_data_dir=root,
                relative_lcp=relative,
                solver_image="img",
                timeout_seconds=60,
            )


# ---------------------------------------------------------------------------
# ensure_land_cover_tile (orchestration: cache, download, metadata, ORM row)
# ---------------------------------------------------------------------------

_LOOKUP = Wgs84BoundingBox(north=39.82, east=-105.60, south=39.68, west=-105.80)
_MOCK_WGS84_BBOX = Wgs84BoundingBox(north=40.0, east=-105.0, south=39.0, west=-106.0)
_MOCK_CRS_EPSG = 5070


def _mock_download_side_effect(download_bbox: object, **kwargs: object) -> None:
    _touch_lcp_outputs(
        Path(str(kwargs["host_data_dir"])),
        Path(str(kwargs["relative_lcp"])),
    )


@patch("services.terrain._read_raster_wgs84_metadata")
@patch("services.terrain.download_land_cover_raster")
def test_ensure_land_cover_tile_writes_row(
    mock_download: MagicMock,
    mock_read: MagicMock,
    db_session: object,
    tmp_path: Path,
) -> None:
    mock_read.return_value = (_MOCK_WGS84_BBOX, _MOCK_CRS_EPSG)
    mock_download.side_effect = _mock_download_side_effect

    tile = ensure_land_cover_tile(
        db_session,  # type: ignore[arg-type]
        _LOOKUP,
        download=_LOOKUP,
        data_dir=tmp_path,
        solver_image="mountain-windninja:local",
        subprocess_timeout_seconds=120,
    )
    db_session.commit()  # type: ignore[union-attr]

    assert tile.source == terrain_lcp.LAND_COVER_SOURCE_LANDFIRE
    assert tile.crs_epsg == _MOCK_CRS_EPSG
    assert tile.file_path.startswith("land_cover/")
    assert tile.file_path.endswith(".lcp")
    assert (tmp_path / tile.file_path).is_file()
    assert (tmp_path / tile.file_path).with_suffix(".prj").is_file()
    mock_download.assert_called_once()


@patch("services.terrain._read_raster_wgs84_metadata")
@patch("services.terrain.download_land_cover_raster")
def test_ensure_land_cover_tile_reuses_cache(
    mock_download: MagicMock,
    mock_read: MagicMock,
    db_session: object,
    tmp_path: Path,
) -> None:
    mock_read.return_value = (_MOCK_WGS84_BBOX, _MOCK_CRS_EPSG)
    mock_download.side_effect = _mock_download_side_effect

    first = ensure_land_cover_tile(
        db_session,  # type: ignore[arg-type]
        _LOOKUP,
        download=_LOOKUP,
        data_dir=tmp_path,
        solver_image="img",
        subprocess_timeout_seconds=120,
    )
    db_session.flush()  # type: ignore[union-attr]

    second = ensure_land_cover_tile(
        db_session,  # type: ignore[arg-type]
        _LOOKUP,
        download=_LOOKUP,
        data_dir=tmp_path,
        solver_image="img",
        subprocess_timeout_seconds=120,
    )
    db_session.commit()  # type: ignore[union-attr]

    assert second.id == first.id
    mock_download.assert_called_once()


def test_non_positive_timeout_raises(db_session: object) -> None:
    with pytest.raises(ValueError, match="positive"):
        ensure_land_cover_tile(
            db_session,  # type: ignore[arg-type]
            _LOOKUP,
            download=_LOOKUP,
            data_dir=Path("/tmp"),
            solver_image="img",
            subprocess_timeout_seconds=0,
        )


def test_ensure_land_cover_tile_cleanup_on_metadata_failure(
    db_session: object, tmp_path: Path
) -> None:
    """If metadata extraction fails after the LCP is written, both files are removed."""
    with (
        patch(
            "services.terrain.download_land_cover_raster",
            side_effect=_mock_download_side_effect,
        ),
        patch(
            "services.terrain._read_raster_wgs84_metadata",
            side_effect=ValueError("bad CRS"),
        ),
    ):
        with pytest.raises(TerrainLcpError):
            ensure_land_cover_tile(
                db_session,  # type: ignore[arg-type]
                _LOOKUP,
                download=_LOOKUP,
                data_dir=tmp_path,
                solver_image="img",
                subprocess_timeout_seconds=60,
            )

    land_cover_dir = tmp_path / "land_cover"
    remaining = list(land_cover_dir.glob("*")) if land_cover_dir.exists() else []
    assert remaining == [], f"Orphan files left behind: {remaining}"
