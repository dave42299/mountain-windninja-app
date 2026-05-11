"""Pure geometry helpers for terrain bounding boxes in WGS84.

All coordinates are decimal degrees. North and east are the maximum latitude
and longitude of the box; south and west are the minimum. This matches the
order used elsewhere (north, east, south, west) and typical GIS conventions
for a simple rectangular extent in geographic coordinates.

Latitude/longitude lengths are approximated with a sphere: one degree of
latitude is treated as a constant meter length; one degree of longitude
shrinks with cos(latitude). Good enough for Phase 2 domain sizes (tens of km)
in the continental US. Not for polar regions or cross-dateline boxes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Mean meters per degree of latitude (WGS84 sphere approximation, widely used).
_METERS_PER_DEGREE_LATITUDE = 111_320.0


@dataclass(frozen=True, slots=True)
class Wgs84BoundingBox:
    """Axis-aligned extent in WGS84 decimal degrees.

    ``north`` and ``east`` are maxima; ``south`` and ``west`` are minima.
    This matches :func:`square_bbox_wgs84` and terrain tile stored extents.
    """

    north: float
    east: float
    south: float
    west: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        """``(north, east, south, west)`` for interop with tuple-oriented callers."""
        return (self.north, self.east, self.south, self.west)


def square_bbox_wgs84(
    center_latitude: float,
    center_longitude: float,
    size_km: float,
) -> Wgs84BoundingBox:
    """Return the axis-aligned square bbox in WGS84 enclosing a center point.

    The square is aligned with parallels and meridians: ``size_km`` is the
    edge length of the square measured along the local north-south and
    east-west directions at the center (each half-edge is ``size_km / 2``
    km converted to degrees separately for lat and lon).

    Args:
        center_latitude: Degrees north, (-90, 90).
        center_longitude: Degrees east, [-180, 180].
        size_km: Full edge length of the square in kilometers, must be > 0.

    Returns:
        A :class:`Wgs84BoundingBox` in decimal degrees.

    Raises:
        ValueError: Invalid inputs or latitude too close to a pole for a
            stable longitude degree length.
    """
    if size_km <= 0:
        raise ValueError("size_km must be positive")
    if not -90.0 < center_latitude < 90.0:
        raise ValueError("center_latitude must be strictly between -90 and 90")
    if not -180.0 <= center_longitude <= 180.0:
        raise ValueError("center_longitude must be between -180 and 180 inclusive")

    cos_lat = math.cos(math.radians(center_latitude))
    if abs(cos_lat) < 1e-3:
        raise ValueError("center_latitude is too close to a pole for this approximation")

    half_edge_m = (size_km * 1000.0) / 2.0
    delta_lat = half_edge_m / _METERS_PER_DEGREE_LATITUDE
    meters_per_degree_lon = _METERS_PER_DEGREE_LATITUDE * cos_lat
    delta_lon = half_edge_m / meters_per_degree_lon

    north = center_latitude + delta_lat
    south = center_latitude - delta_lat
    east = center_longitude + delta_lon
    west = center_longitude - delta_lon

    return Wgs84BoundingBox(north=north, east=east, south=south, west=west)


def pad_bbox_fraction(bbox: Wgs84BoundingBox, fraction: float = 0.25) -> Wgs84BoundingBox:
    """Expand a WGS84 bbox by a fraction of its half-extent on each side.

    The center of the box is preserved. Each axis is scaled so the total
    north-south span becomes ``(1 + fraction)`` times the original span, and
    the same for east-west. With ``fraction=0.25``, each dimension grows by
    25% (Phase 2 padding convention).

    Args:
        bbox: Decimal degrees, must satisfy ``north > south`` and ``east > west``.
        fraction: Non-negative expansion factor (default 0.25).

    Returns:
        The expanded :class:`Wgs84BoundingBox`.

    Raises:
        ValueError: Invalid bbox or negative fraction.
    """
    if fraction < 0:
        raise ValueError("fraction must be non-negative")
    north, east, south, west = bbox.north, bbox.east, bbox.south, bbox.west
    if north <= south:
        raise ValueError("north must be greater than south")
    if east <= west:
        raise ValueError("east must be greater than west")

    center_lat = (north + south) / 2.0
    half_lat = (north - south) / 2.0
    center_lon = (east + west) / 2.0
    half_lon = (east - west) / 2.0

    new_half_lat = half_lat * (1.0 + fraction)
    new_half_lon = half_lon * (1.0 + fraction)

    new_north = center_lat + new_half_lat
    new_south = center_lat - new_half_lat
    new_east = center_lon + new_half_lon
    new_west = center_lon - new_half_lon

    return Wgs84BoundingBox(north=new_north, east=new_east, south=new_south, west=new_west)
