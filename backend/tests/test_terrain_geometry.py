"""Tests for services.terrain_geometry."""

import math

import pytest

from services.terrain_geometry import (
    TerrainOutsideUsError,
    Wgs84BoundingBox,
    pad_bbox_fraction,
    square_bbox_wgs84,
    validate_conus_wgs84_bbox,
)


def test_square_bbox_symmetric_at_equator() -> None:
    bbox = square_bbox_wgs84(0.0, 0.0, 10.0)
    lat_span = bbox.north - bbox.south
    lon_span = bbox.east - bbox.west
    assert lat_span == pytest.approx(lon_span)
    assert bbox.north == pytest.approx(-bbox.south)
    assert bbox.east == pytest.approx(-bbox.west)


def test_square_bbox_at_45n_longitude_span_wider_than_latitude() -> None:
    bbox = square_bbox_wgs84(45.0, 0.0, 10.0)
    lat_span = bbox.north - bbox.south
    lon_span = bbox.east - bbox.west
    assert lon_span > lat_span
    assert (bbox.north + bbox.south) / 2 == pytest.approx(45.0)
    assert (bbox.east + bbox.west) / 2 == pytest.approx(0.0)


def test_pad_bbox_fraction_scales_span() -> None:
    inner = Wgs84BoundingBox(north=1.0, east=2.0, south=-1.0, west=0.0)
    padded = pad_bbox_fraction(inner, fraction=0.25)
    assert (padded.north - padded.south) == pytest.approx((inner.north - inner.south) * 1.25)
    assert (padded.east - padded.west) == pytest.approx((inner.east - inner.west) * 1.25)


def test_pad_bbox_fraction_preserves_center() -> None:
    inner = Wgs84BoundingBox(north=40.0, east=-104.0, south=39.0, west=-106.0)
    padded = pad_bbox_fraction(inner, fraction=0.25)
    assert (padded.north + padded.south) / 2 == pytest.approx((inner.north + inner.south) / 2)
    assert (padded.east + padded.west) / 2 == pytest.approx((inner.east + inner.west) / 2)


def test_pad_bbox_fraction_zero_is_noop() -> None:
    bbox = Wgs84BoundingBox(north=10.0, east=5.0, south=8.0, west=3.0)
    assert pad_bbox_fraction(bbox, fraction=0.0) == bbox


def test_square_bbox_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError, match="size_km"):
        square_bbox_wgs84(0.0, 0.0, 0.0)


def test_square_bbox_rejects_oversized_domain() -> None:
    with pytest.raises(ValueError, match="exceeds maximum"):
        square_bbox_wgs84(39.0, -105.0, 51.0)


def test_square_bbox_rejects_pole_latitude() -> None:
    with pytest.raises(ValueError, match="pole"):
        square_bbox_wgs84(89.9999, 0.0, 10.0)


def test_bbox_rejects_north_le_south() -> None:
    with pytest.raises(ValueError, match="north"):
        Wgs84BoundingBox(north=0.0, east=1.0, south=1.0, west=0.0)


def test_bbox_rejects_east_le_west() -> None:
    with pytest.raises(ValueError, match="east"):
        Wgs84BoundingBox(north=1.0, east=0.0, south=0.0, west=1.0)


def test_pad_rejects_negative_fraction() -> None:
    with pytest.raises(ValueError, match="fraction"):
        pad_bbox_fraction(Wgs84BoundingBox(north=1.0, east=1.0, south=0.0, west=0.0), fraction=-0.1)


def test_square_then_pad_ordering_western_us() -> None:
    """Sanity: N>E>S>W ordering and positive spans for a Colorado-like point."""
    core = square_bbox_wgs84(39.8, -105.78, 12.0)
    assert core.north > core.south and core.east > core.west
    padded = pad_bbox_fraction(core, fraction=0.25)
    assert padded.north > core.north and padded.south < core.south
    assert padded.east > core.east and padded.west < core.west
    assert math.isfinite(padded.north + padded.east + padded.south + padded.west)


def test_square_bbox_known_center_size_matches_closed_form() -> None:
    """Regression: fixed center, 12 km square → corners match sphere approximation."""
    center_lat = 39.8
    center_lon = -105.78
    size_km = 12.0
    bbox = square_bbox_wgs84(center_lat, center_lon, size_km)
    cos_lat = math.cos(math.radians(center_lat))
    half_edge_m = (size_km * 1000.0) / 2.0
    delta_lat = half_edge_m / 111_320.0
    delta_lon = half_edge_m / (111_320.0 * cos_lat)
    assert bbox.north == pytest.approx(center_lat + delta_lat)
    assert bbox.south == pytest.approx(center_lat - delta_lat)
    assert bbox.east == pytest.approx(center_lon + delta_lon)
    assert bbox.west == pytest.approx(center_lon - delta_lon)


def test_pad_25_percent_expands_half_extent_by_quarter() -> None:
    """Padding 0.25 grows each half-axis by 25% (total span ×1.25)."""
    core = square_bbox_wgs84(40.0, -100.0, 20.0)
    half_lat_before = (core.north - core.south) / 2.0
    half_lon_before = (core.east - core.west) / 2.0
    padded = pad_bbox_fraction(core, fraction=0.25)
    assert (padded.north - padded.south) / 2.0 == pytest.approx(half_lat_before * 1.25)
    assert (padded.east - padded.west) / 2.0 == pytest.approx(half_lon_before * 1.25)


# ---------------------------------------------------------------------------
# CONUS validation
# ---------------------------------------------------------------------------


def test_validate_conus_accepts_berthoud_region() -> None:
    validate_conus_wgs84_bbox(
        Wgs84BoundingBox(north=39.85, east=-105.65, south=39.65, west=-105.85)
    )


def test_validate_conus_rejects_europe() -> None:
    with pytest.raises(TerrainOutsideUsError):
        validate_conus_wgs84_bbox(
            Wgs84BoundingBox(north=55.0, east=10.0, south=54.0, west=9.0)
        )


def test_validate_conus_rejects_canada() -> None:
    with pytest.raises(TerrainOutsideUsError):
        validate_conus_wgs84_bbox(
            Wgs84BoundingBox(north=52.0, east=-105.0, south=51.0, west=-106.0)
        )


def test_bbox_as_wsen_tuple_returns_standard_gis_order() -> None:
    bbox = Wgs84BoundingBox(north=40.0, east=-104.0, south=39.0, west=-106.0)
    assert bbox.as_wsen_tuple() == (-106.0, 39.0, -104.0, 40.0)
