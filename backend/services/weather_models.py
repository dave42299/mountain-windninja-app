"""HRRR cycle resolution and time-range validation for weather data retrieval.

Pure datetime logic with no I/O or external dependencies. Analogous to
:mod:`services.terrain_geometry` for the terrain pipeline.

HRRR (High-Resolution Rapid Refresh) runs every hour and publishes forecast
data to AWS S3 (``noaa-hrrr-bdp-pds``). Each cycle produces forecasts for up
to 18 hours ahead (standard cycles) or 48 hours ahead (extended cycles at
00/06/12/18 UTC). There is a lag of roughly 1-2 hours between the cycle
analysis time and when data appears on S3.

This module resolves which HRRR cycle and forecast hour to use for each
timestep in a user's requested forecast window, and validates that the window
falls within HRRR's temporal coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


HRRR_ARCHIVE_START = datetime(2014, 7, 30, tzinfo=timezone.utc)

HRRR_CYCLE_INTERVAL_HOURS = 1

HRRR_STANDARD_FORECAST_HOURS = 18
HRRR_EXTENDED_FORECAST_HOURS = 48
_EXTENDED_CYCLE_HOURS = frozenset({0, 6, 12, 18})

# Approximate lag between cycle analysis time and S3 availability.
# Conservatively set to 2 hours; real-world lag is typically 45-90 minutes.
HRRR_S3_PUBLICATION_LAG_HOURS = 2

_MAX_DURATION_HOURS = 48


class WeatherTimeRangeError(ValueError):
    """The requested forecast time range is outside HRRR's temporal coverage."""


@dataclass(frozen=True, slots=True)
class HrrrCycle:
    """A single HRRR forecast cycle + forecast hour that covers one timestep.

    ``analysis_time`` is when the HRRR model run was initialized (e.g.,
    2026-05-10T12:00Z). ``forecast_hour`` is how many hours past the analysis
    this timestep is (e.g., 2 means T+2). ``valid_time`` is what time this
    data actually represents (``analysis_time + forecast_hour``).
    """

    analysis_time: datetime
    forecast_hour: int
    valid_time: datetime


def _require_aware_utc(dt: datetime, label: str) -> None:
    """Raise ``ValueError`` if *dt* is naive (no tzinfo)."""
    if dt.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware (got naive datetime)")


def _max_forecast_hours(cycle_hour: int) -> int:
    """Return the maximum forecast horizon for the given cycle hour."""
    if cycle_hour in _EXTENDED_CYCLE_HOURS:
        return HRRR_EXTENDED_FORECAST_HOURS
    return HRRR_STANDARD_FORECAST_HOURS


def _latest_available_cycle(now_utc: datetime) -> datetime:
    """Estimate the most recent HRRR cycle likely available on S3.

    Accounts for the publication lag: data from cycle T is typically
    available at T + ``HRRR_S3_PUBLICATION_LAG_HOURS``.
    """
    available_at = now_utc - timedelta(hours=HRRR_S3_PUBLICATION_LAG_HOURS)
    return available_at.replace(minute=0, second=0, microsecond=0)


def validate_hrrr_time_range(
    forecast_start: datetime,
    duration_hours: int,
    *,
    now: datetime | None = None,
) -> None:
    """Validate that the requested time window is within HRRR temporal coverage.

    Checks:
    - ``forecast_start`` is timezone-aware
    - ``duration_hours`` is positive and within limits
    - ``forecast_start`` is not before the HRRR archive start date
    - The end of the window is not unreachably far in the future

    Args:
        forecast_start: Timezone-aware start of the forecast window.
        duration_hours: Number of hours in the forecast window.
        now: Override for current time (for testing). Must be timezone-aware.

    Raises:
        WeatherTimeRangeError: If the time range is outside HRRR coverage.
        ValueError: If inputs are invalid (naive datetime, non-positive duration).
    """
    _require_aware_utc(forecast_start, "forecast_start")
    if duration_hours <= 0:
        raise ValueError("duration_hours must be positive")
    if duration_hours > _MAX_DURATION_HOURS:
        raise WeatherTimeRangeError(
            f"duration_hours ({duration_hours}) exceeds maximum ({_MAX_DURATION_HOURS})"
        )

    if forecast_start < HRRR_ARCHIVE_START:
        raise WeatherTimeRangeError(
            f"forecast_start ({forecast_start.isoformat()}) is before the HRRR archive "
            f"start ({HRRR_ARCHIVE_START.isoformat()})"
        )

    current_time = now if now is not None else datetime.now(timezone.utc)
    _require_aware_utc(current_time, "now")

    forecast_end = forecast_start + timedelta(hours=duration_hours)
    latest_cycle = _latest_available_cycle(current_time)
    max_reachable = latest_cycle + timedelta(hours=HRRR_EXTENDED_FORECAST_HOURS)

    if forecast_end > max_reachable:
        raise WeatherTimeRangeError(
            f"Forecast window ends at {forecast_end.isoformat()} which is beyond the "
            f"furthest reachable HRRR forecast ({max_reachable.isoformat()}) given "
            f"current time {current_time.isoformat()}"
        )


def resolve_hrrr_cycles(
    forecast_start: datetime,
    duration_hours: int,
    *,
    now: datetime | None = None,
) -> list[HrrrCycle]:
    """Determine which HRRR cycle + forecast hour covers each hourly timestep.

    For a forecast window of ``duration_hours`` starting at ``forecast_start``,
    returns one :class:`HrrrCycle` per hour. The strategy depends on whether
    each timestep is in the past or future:

    - **Future timesteps:** use the latest available cycle and compute the
      forecast hour offset. Falls back to earlier cycles if the offset exceeds
      the cycle's forecast horizon.
    - **Past timesteps:** use ``fxx=0`` (analysis) of each hour's own cycle,
      giving the best-available HRRR analysis for that hour.

    Args:
        forecast_start: Timezone-aware start of the forecast window.
        duration_hours: Number of hourly timesteps to resolve.
        now: Override for current time (for testing). Must be timezone-aware.

    Returns:
        List of ``HrrrCycle`` objects, one per hourly timestep, ordered
        chronologically.

    Raises:
        ValueError: If ``forecast_start`` is naive or ``duration_hours`` is
            not positive.
    """
    _require_aware_utc(forecast_start, "forecast_start")
    if duration_hours <= 0:
        raise ValueError("duration_hours must be positive")

    current_time = now if now is not None else datetime.now(timezone.utc)
    _require_aware_utc(current_time, "now")

    latest_cycle = _latest_available_cycle(current_time)
    cycles: list[HrrrCycle] = []

    for hour_offset in range(duration_hours):
        valid_time = forecast_start + timedelta(hours=hour_offset)
        valid_time_truncated = valid_time.replace(minute=0, second=0, microsecond=0)

        if valid_time_truncated <= latest_cycle:
            # Past or current: use the analysis (fxx=0) from this hour's cycle.
            cycles.append(
                HrrrCycle(
                    analysis_time=valid_time_truncated,
                    forecast_hour=0,
                    valid_time=valid_time_truncated,
                )
            )
        else:
            # Future: find a cycle whose forecast horizon reaches this time.
            cycle = _resolve_future_cycle(valid_time_truncated, latest_cycle)
            cycles.append(cycle)

    return cycles


def _resolve_future_cycle(
    valid_time: datetime,
    latest_cycle: datetime,
) -> HrrrCycle:
    """Find the best cycle for a future valid time.

    Starts from ``latest_cycle`` and walks backward until it finds a cycle
    whose maximum forecast horizon covers ``valid_time``.
    """
    candidate = latest_cycle
    while candidate >= HRRR_ARCHIVE_START:
        forecast_hour = int((valid_time - candidate).total_seconds() / 3600)
        max_hours = _max_forecast_hours(candidate.hour)
        if 0 <= forecast_hour <= max_hours:
            return HrrrCycle(
                analysis_time=candidate,
                forecast_hour=forecast_hour,
                valid_time=valid_time,
            )
        candidate -= timedelta(hours=HRRR_CYCLE_INTERVAL_HOURS)

    raise WeatherTimeRangeError(
        f"No HRRR cycle can reach valid_time={valid_time.isoformat()}"
    )
