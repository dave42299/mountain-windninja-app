"""Tests for services.terrain_geometry."""

import math

import pytest

from services.terrain_geometry import pad_bbox_fraction, square_bbox_wgs84


def test_square_bbox_symmetric_at_equator() -> None:
    north, east, south, west = square_bbox_wgs84(0.0, 0.0, 111.32)
    assert north == pytest.approx(0.5)
    assert south == pytest.approx(-0.5)
    assert east == pytest.approx(0.5)
    assert west == pytest.approx(-0.5)


def test_square_bbox_at_45n_longitude_span_wider_than_latitude() -> None:
    north, east, south, west = square_bbox_wgs84(45.0, 0.0, 10.0)
    lat_span = north - south
    lon_span = east - west
    assert lon_span > lat_span
    assert (north + south) / 2 == pytest.approx(45.0)
    assert (east + west) / 2 == pytest.approx(0.0)


def test_pad_bbox_fraction_scales_span() -> None:
    north, east, south, west = 1.0, 2.0, -1.0, 0.0
    pn, pe, ps, pw = pad_bbox_fraction(north, east, south, west, fraction=0.25)
    assert (pn - ps) == pytest.approx((north - south) * 1.25)
    assert (pe - pw) == pytest.approx((east - west) * 1.25)


def test_pad_bbox_fraction_preserves_center() -> None:
    north, east, south, west = 40.0, -104.0, 39.0, -106.0
    pn, pe, ps, pw = pad_bbox_fraction(north, east, south, west, fraction=0.25)
    assert (pn + ps) / 2 == pytest.approx((north + south) / 2)
    assert (pe + pw) / 2 == pytest.approx((east + west) / 2)


def test_pad_bbox_fraction_zero_is_noop() -> None:
    bbox = (10.0, 5.0, 8.0, 3.0)
    assert pad_bbox_fraction(*bbox, fraction=0.0) == bbox


def test_square_bbox_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError, match="size_km"):
        square_bbox_wgs84(0.0, 0.0, 0.0)


def test_square_bbox_rejects_pole_latitude() -> None:
    with pytest.raises(ValueError, match="pole"):
        square_bbox_wgs84(89.9999, 0.0, 10.0)


def test_pad_rejects_invalid_extent() -> None:
    with pytest.raises(ValueError, match="north"):
        pad_bbox_fraction(0.0, 1.0, 1.0, 0.0)
    with pytest.raises(ValueError, match="east"):
        pad_bbox_fraction(1.0, 0.0, 0.0, 1.0)


def test_pad_rejects_negative_fraction() -> None:
    with pytest.raises(ValueError, match="fraction"):
        pad_bbox_fraction(1.0, 1.0, 0.0, 0.0, fraction=-0.1)


def test_square_then_pad_ordering_western_us() -> None:
    """Sanity: N>E>S>W ordering and positive spans for a Colorado-like point."""
    n, e, s, w = square_bbox_wgs84(39.8, -105.78, 12.0)
    assert n > s and e > w
    pn, pe, ps, pw = pad_bbox_fraction(n, e, s, w, fraction=0.25)
    assert pn > n and ps < s
    assert pe > e and pw < w
    assert math.isfinite(pn + pe + ps + pw)
