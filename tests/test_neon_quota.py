"""Tests for the Neon free-tier quota check.

The Free plan gives 100 CU-hours per project per month. Exceeding it suspends
the compute until the next billing period — an outage, not a bill — and the Free
plan has no spending notifications, so this check is the only warning we get.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from scripts.check_neon_quota import (
    CRITICAL,
    FREE_TIER_EGRESS_BYTES,
    FREE_TIER_STORAGE_BYTES,
    OK,
    WARN,
    WARN_PCT,
    evaluate_quota,
)

PERIOD_START = datetime(2026, 9, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 10, 1, tzinfo=UTC)


def cu_seconds(cu_hours):
    return cu_hours * 3600


def build(cu_hours_used, now, active_seconds=0):
    """Evaluate with the fixed September period and the given consumption."""
    return evaluate_quota(
        cpu_used_sec=cu_seconds(cu_hours_used),
        active_time_seconds=active_seconds,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        now=now,
    )


@pytest.mark.unit
class TestQuotaThresholds:
    def test_reports_ok_when_usage_is_low(self):
        # 10 of 100 CU-hours, a third of the way through the month
        result = build(10, now=PERIOD_START + timedelta(days=10))

        assert result.level == OK
        assert result.cu_hours_used == pytest.approx(10)
        assert result.pct_used == pytest.approx(10)

    def test_warns_at_half_the_allowance(self):
        result = build(50, now=PERIOD_START + timedelta(days=25))

        assert result.level == WARN
        assert any('50' in r or 'half' in r.lower() for r in result.reasons)

    def test_critical_at_eighty_percent_of_allowance(self):
        result = build(80, now=PERIOD_START + timedelta(days=28))

        assert result.level == CRITICAL

    def test_critical_when_allowance_already_exhausted(self):
        result = build(100, now=PERIOD_START + timedelta(days=20))

        assert result.level == CRITICAL


@pytest.mark.unit
class TestProjection:
    def test_warns_when_projected_usage_would_exhaust_the_allowance(self):
        """15 CU-hours in 3 days projects to ~150 for the month — over budget,
        even though absolute usage is only 15%."""
        result = build(15, now=PERIOD_START + timedelta(days=3))

        assert result.projected_cu_hours == pytest.approx(150, rel=0.02)
        assert result.level == WARN
        assert any('project' in r.lower() for r in result.reasons)

    def test_does_not_project_from_too_short_a_window(self):
        """A burst in the first minutes of a period would project absurdly.
        Projection is withheld until enough of the period has elapsed."""
        result = build(2, now=PERIOD_START + timedelta(minutes=30))

        assert result.projected_cu_hours is None
        assert result.level == OK

    def test_handles_a_period_that_just_reset(self):
        """Downgrading resets the consumption period; now == period_start."""
        result = build(0, now=PERIOD_START)

        assert result.level == OK
        assert result.projected_cu_hours is None
        assert result.active_ratio is None


@pytest.mark.unit
class TestComputeActivitySignal:
    def test_warns_when_the_compute_is_pinned_awake(self):
        """The leading indicator: this is the signal that would have caught the
        k3s health-check regression, which held the compute at 99.6% active."""
        elapsed = timedelta(days=2)
        result = build(
            12, now=PERIOD_START + elapsed, active_seconds=elapsed.total_seconds() * 0.99
        )

        assert result.active_ratio == pytest.approx(0.99, rel=0.01)
        assert result.level >= WARN
        assert any('active' in r.lower() for r in result.reasons)

    def test_idle_compute_does_not_warn(self):
        """Healthy post-fix shape: compute awake only a few percent of the time."""
        elapsed = timedelta(days=10)
        result = build(
            5, now=PERIOD_START + elapsed, active_seconds=elapsed.total_seconds() * 0.04
        )

        assert result.active_ratio == pytest.approx(0.04, rel=0.01)
        assert result.level == OK


@pytest.mark.unit
class TestAgainstTheRealIncident:
    """Characterisation test using the actual counters measured on prod before
    the k3s health-check regression was found on 2026-09-08.

    These are not synthetic numbers: they are what the Neon API returned while a
    stale k3s Deployment was probing /health/ twice a second. If this check had
    existed, it should have fired.
    """

    def test_would_have_caught_the_health_check_regression(self):
        result = evaluate_quota(
            cpu_used_sec=167_387,
            active_time_seconds=669_168,
            period_start=datetime(2026, 9, 1, tzinfo=UTC),
            period_end=datetime(2026, 10, 1, tzinfo=UTC),
            now=datetime(2026, 9, 8, 12, 31, tzinfo=UTC),
        )

        # Absolute usage alone looked survivable at 46.5 of 100 CU-hours...
        assert result.cu_hours_used == pytest.approx(46.5, rel=0.01)
        assert result.pct_used < WARN_PCT

        # ...but both forward-looking signals fire.
        assert result.projected_cu_hours == pytest.approx(185, rel=0.03)
        assert result.active_ratio == pytest.approx(1.03, rel=0.02)
        assert result.level == WARN
        assert len(result.reasons) == 2


@pytest.mark.unit
class TestStorageAndEgress:
    """Compute hours are not the only free-tier limit that takes the site down.

    Storage over 0.5 GB/project makes writes fail; egress over 5 GB/project
    suspends the compute the same way exhausting CU-hours does.
    """

    def test_warns_when_storage_is_half_the_cap(self):
        result = evaluate_quota(
            cpu_used_sec=0,
            active_time_seconds=0,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            now=PERIOD_START + timedelta(days=10),
            storage_bytes=int(FREE_TIER_STORAGE_BYTES * 0.55),
        )

        assert result.level == WARN
        assert any('storage' in r.lower() for r in result.reasons)

    def test_critical_when_storage_is_nearly_full(self):
        result = evaluate_quota(
            cpu_used_sec=0,
            active_time_seconds=0,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            now=PERIOD_START + timedelta(days=10),
            storage_bytes=int(FREE_TIER_STORAGE_BYTES * 0.85),
        )

        assert result.level == CRITICAL
        assert any('storage' in r.lower() for r in result.reasons)

    def test_warns_when_egress_approaches_the_cap(self):
        result = evaluate_quota(
            cpu_used_sec=0,
            active_time_seconds=0,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            now=PERIOD_START + timedelta(days=10),
            egress_bytes=int(FREE_TIER_EGRESS_BYTES * 0.6),
        )

        assert result.level == WARN
        assert any('egress' in r.lower() or 'transfer' in r.lower() for r in result.reasons)

    def test_current_real_usage_is_nowhere_near_any_cap(self):
        """Actual gift-wiki figures: 33 MB stored, 24 MB egress."""
        result = evaluate_quota(
            cpu_used_sec=0,
            active_time_seconds=0,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            now=PERIOD_START + timedelta(days=10),
            storage_bytes=34_250_752,
            egress_bytes=24_985_788,
        )

        assert result.level == OK
        assert result.pct_storage == pytest.approx(6.4, rel=0.05)
