"""Tests for services.weather_models -- HRRR cycle resolution and time validation."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests.conftest import utc

from services.weather_models import (
    HRRR_ARCHIVE_START,
    HRRR_EXTENDED_FORECAST_HOURS,
    HRRR_S3_PUBLICATION_LAG_HOURS,
    HRRR_STANDARD_FORECAST_HOURS,
    HrrrCycle,
    WeatherTimeRangeError,
    resolve_hrrr_cycles,
    validate_hrrr_time_range,
)


# ---------------------------------------------------------------------------
# validate_hrrr_time_range
# ---------------------------------------------------------------------------


class TestValidateHrrrTimeRange:
    def test_accepts_recent_past_window(self) -> None:
        now = utc(2026, 5, 10, 18)
        validate_hrrr_time_range(utc(2026, 5, 10, 6), 6, now=now)

    def test_accepts_near_future_window(self) -> None:
        now = utc(2026, 5, 10, 12)
        validate_hrrr_time_range(utc(2026, 5, 10, 14), 6, now=now)

    def test_rejects_before_archive_start(self) -> None:
        with pytest.raises(WeatherTimeRangeError, match="archive start"):
            validate_hrrr_time_range(utc(2014, 1, 1), 6)

    def test_rejects_window_too_far_in_future(self) -> None:
        now = utc(2026, 5, 10, 12)
        far_future = now + timedelta(hours=100)
        with pytest.raises(WeatherTimeRangeError, match="beyond"):
            validate_hrrr_time_range(far_future, 6, now=now)

    def test_rejects_non_positive_duration(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            validate_hrrr_time_range(utc(2026, 5, 10, 12), 0)

    def test_rejects_excessive_duration(self) -> None:
        now = utc(2026, 5, 10, 12)
        with pytest.raises(WeatherTimeRangeError, match="exceeds maximum"):
            validate_hrrr_time_range(utc(2026, 5, 9, 12), 49, now=now)

    def test_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            validate_hrrr_time_range(datetime(2026, 5, 10, 12), 6)

    def test_boundary_exactly_at_max_reachable(self) -> None:
        """Window ending exactly at the max reachable time should pass."""
        now = utc(2026, 5, 10, 12)
        latest_cycle = now - timedelta(hours=HRRR_S3_PUBLICATION_LAG_HOURS)
        max_reachable = latest_cycle + timedelta(hours=HRRR_EXTENDED_FORECAST_HOURS)
        start = max_reachable - timedelta(hours=1)
        validate_hrrr_time_range(start, 1, now=now)


# ---------------------------------------------------------------------------
# resolve_hrrr_cycles -- pastcast (past times)
# ---------------------------------------------------------------------------


class TestResolvePastcastCycles:
    def test_past_hours_use_analysis_fxx0(self) -> None:
        now = utc(2026, 5, 10, 18)
        cycles = resolve_hrrr_cycles(utc(2026, 5, 10, 6), 6, now=now)

        assert len(cycles) == 6
        for i, cycle in enumerate(cycles):
            expected_valid = utc(2026, 5, 10, 6 + i)
            assert cycle.valid_time == expected_valid
            assert cycle.forecast_hour == 0
            assert cycle.analysis_time == expected_valid

    def test_pastcast_across_midnight(self) -> None:
        now = utc(2026, 5, 11, 6)
        cycles = resolve_hrrr_cycles(utc(2026, 5, 10, 22), 4, now=now)

        assert len(cycles) == 4
        assert cycles[0].valid_time == utc(2026, 5, 10, 22)
        assert cycles[1].valid_time == utc(2026, 5, 10, 23)
        assert cycles[2].valid_time == utc(2026, 5, 11, 0)
        assert cycles[3].valid_time == utc(2026, 5, 11, 1)
        for cycle in cycles:
            assert cycle.forecast_hour == 0


# ---------------------------------------------------------------------------
# resolve_hrrr_cycles -- forecast (future times)
# ---------------------------------------------------------------------------


class TestResolveForecastCycles:
    def test_future_hours_use_latest_cycle(self) -> None:
        now = utc(2026, 5, 10, 14)
        latest_cycle = utc(2026, 5, 10, 12)  # 14 - 2h lag

        cycles = resolve_hrrr_cycles(utc(2026, 5, 10, 16), 3, now=now)

        assert len(cycles) == 3
        for cycle in cycles:
            assert cycle.analysis_time == latest_cycle
        assert cycles[0].forecast_hour == 4  # 16 - 12 = 4
        assert cycles[1].forecast_hour == 5
        assert cycles[2].forecast_hour == 6

    def test_future_valid_times_are_correct(self) -> None:
        now = utc(2026, 5, 10, 14)
        cycles = resolve_hrrr_cycles(utc(2026, 5, 10, 16), 3, now=now)

        assert cycles[0].valid_time == utc(2026, 5, 10, 16)
        assert cycles[1].valid_time == utc(2026, 5, 10, 17)
        assert cycles[2].valid_time == utc(2026, 5, 10, 18)

    def test_far_future_falls_back_to_extended_cycle(self) -> None:
        """If the latest standard cycle can't reach the time, fall back to an
        extended cycle (00/06/12/18) with a 48h horizon."""
        now = utc(2026, 5, 10, 14)
        latest_cycle = utc(2026, 5, 10, 12)

        target_fxx = HRRR_STANDARD_FORECAST_HOURS + 2  # beyond 18h
        target_time = latest_cycle + timedelta(hours=target_fxx)
        cycles = resolve_hrrr_cycles(target_time, 1, now=now)

        assert len(cycles) == 1
        cycle = cycles[0]
        assert cycle.valid_time == target_time
        assert cycle.analysis_time.hour in {0, 6, 12, 18}
        assert cycle.forecast_hour <= HRRR_EXTENDED_FORECAST_HOURS


# ---------------------------------------------------------------------------
# resolve_hrrr_cycles -- mixed (past + future)
# ---------------------------------------------------------------------------


class TestResolveMixedCycles:
    def test_mixed_window_transitions_from_past_to_future(self) -> None:
        now = utc(2026, 5, 10, 14)
        latest_cycle = utc(2026, 5, 10, 12)
        start = utc(2026, 5, 10, 11)  # 1h before latest cycle

        cycles = resolve_hrrr_cycles(start, 6, now=now)

        assert len(cycles) == 6
        # First two: past (11:00, 12:00) -> fxx=0
        assert cycles[0].forecast_hour == 0
        assert cycles[0].analysis_time == utc(2026, 5, 10, 11)
        assert cycles[1].forecast_hour == 0
        assert cycles[1].analysis_time == utc(2026, 5, 10, 12)

        # Remaining: future (13:00 onward) -> use latest cycle
        for cycle in cycles[2:]:
            assert cycle.analysis_time == latest_cycle
            assert cycle.forecast_hour > 0


# ---------------------------------------------------------------------------
# resolve_hrrr_cycles -- edge cases and validation
# ---------------------------------------------------------------------------


class TestResolveCyclesEdgeCases:
    def test_single_hour_duration(self) -> None:
        now = utc(2026, 5, 10, 18)
        cycles = resolve_hrrr_cycles(utc(2026, 5, 10, 12), 1, now=now)
        assert len(cycles) == 1
        assert cycles[0].valid_time == utc(2026, 5, 10, 12)

    def test_rejects_naive_forecast_start(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            resolve_hrrr_cycles(datetime(2026, 5, 10, 12), 6)

    def test_rejects_non_positive_duration(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            resolve_hrrr_cycles(utc(2026, 5, 10, 12), 0)

    def test_all_cycles_have_correct_valid_times(self) -> None:
        now = utc(2026, 5, 10, 18)
        start = utc(2026, 5, 10, 6)
        cycles = resolve_hrrr_cycles(start, 12, now=now)

        for i, cycle in enumerate(cycles):
            expected = start + timedelta(hours=i)
            assert cycle.valid_time == expected

    def test_analysis_time_plus_fxx_equals_valid_time(self) -> None:
        """Invariant: analysis_time + forecast_hour == valid_time."""
        now = utc(2026, 5, 10, 14)
        cycles = resolve_hrrr_cycles(utc(2026, 5, 10, 10), 8, now=now)

        for cycle in cycles:
            reconstructed = cycle.analysis_time + timedelta(hours=cycle.forecast_hour)
            assert reconstructed == cycle.valid_time


# ---------------------------------------------------------------------------
# HrrrCycle dataclass
# ---------------------------------------------------------------------------


class TestHrrrCycle:
    def test_frozen(self) -> None:
        cycle = HrrrCycle(
            analysis_time=utc(2026, 5, 10, 12),
            forecast_hour=2,
            valid_time=utc(2026, 5, 10, 14),
        )
        with pytest.raises(AttributeError):
            cycle.forecast_hour = 3  # type: ignore[misc]

    def test_equality(self) -> None:
        a = HrrrCycle(utc(2026, 5, 10, 12), 2, utc(2026, 5, 10, 14))
        b = HrrrCycle(utc(2026, 5, 10, 12), 2, utc(2026, 5, 10, 14))
        assert a == b
