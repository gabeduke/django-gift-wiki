#!/usr/bin/env python3
"""Check Neon free-tier consumption and report how close we are to throttling.

The Free plan has three per-project monthly limits, each of which takes the site
down in its own way, and none of which Neon warns about (spending notifications
are a paid feature):

  compute  100 CU-hours   exceeding it suspends the database until the period
                          resets — downtime, not an overage charge
  storage  0.5 GB         exceeding it makes writes start failing
  egress   5 GB           exceeding it suspends the database

Five signals, because they fail differently:

  usage       absolute CU-hours consumed this period
  storage     share of the 0.5 GB cap in use
  egress      share of the 5 GB transfer allowance in use
  projection  period-to-date burn rate extrapolated to the period end, which
              catches a rising rate long before the absolute number looks bad
  activity    share of wall-clock time a compute has been awake. This is the
              leading indicator: a stray health check or probe that stops the
              compute suspending shows up here within hours. It is what would
              have caught the k3s regression that pinned prod at 99.6% active.

Run standalone; no Django import, stdlib only.

    NEON_API_KEY=... NEON_PROJECT_ID=... python scripts/check_neon_quota.py

Exit code is the alert level: 0 ok, 1 warn, 2 critical.
"""

from __future__ import annotations

import argparse
import enum
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

NEON_API = 'https://console.neon.tech/api/v2'

# Free plan, per project per month. Each of these takes the site down in its
# own way, so all three are checked:
#   compute  exceeding it suspends the compute until the period resets
#   storage  exceeding it makes writes (insert/update/delete) start failing
#   egress   exceeding it suspends the compute, same as running out of compute
FREE_TIER_CU_HOURS = 100.0
FREE_TIER_STORAGE_BYTES = 512 * 1024 * 1024  # 0.5 GB
FREE_TIER_EGRESS_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB

# Alert when absolute usage crosses these shares of the allowance.
WARN_PCT = 50.0
CRITICAL_PCT = 80.0

# Ignore the projection until this much of the period has elapsed. A burst in
# the first minutes of a period extrapolates to an absurd number otherwise.
MIN_PROJECTION_HOURS = 6.0

# Share of wall-clock time computes may be awake before we consider it a
# regression. Summed across every endpoint in the project, so a value near 1.0
# means one compute is never suspending. Healthy for this app is under 0.1.
ACTIVE_RATIO_WARN = 0.25


class Level(enum.IntEnum):
    OK = 0
    WARN = 1
    CRITICAL = 2


OK = Level.OK
WARN = Level.WARN
CRITICAL = Level.CRITICAL


@dataclass
class QuotaResult:
    level: Level
    cu_hours_used: float
    pct_used: float
    allowance: float
    projected_cu_hours: float | None
    active_ratio: float | None
    elapsed_hours: float
    storage_bytes: int = 0
    pct_storage: float = 0.0
    egress_bytes: int = 0
    pct_egress: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def as_dict(self):
        return {
            'level': self.level.name,
            'cu_hours_used': round(self.cu_hours_used, 2),
            'pct_used': round(self.pct_used, 1),
            'allowance': self.allowance,
            'projected_cu_hours': (
                None if self.projected_cu_hours is None else round(self.projected_cu_hours, 1)
            ),
            'active_ratio': (None if self.active_ratio is None else round(self.active_ratio, 3)),
            'elapsed_hours': round(self.elapsed_hours, 1),
            'storage_mb': round(self.storage_bytes / 1024 / 1024, 1),
            'pct_storage': round(self.pct_storage, 1),
            'egress_mb': round(self.egress_bytes / 1024 / 1024, 1),
            'pct_egress': round(self.pct_egress, 1),
            'reasons': self.reasons,
        }


def _threshold_level(pct: float) -> Level:
    if pct >= CRITICAL_PCT:
        return Level.CRITICAL
    if pct >= WARN_PCT:
        return Level.WARN
    return Level.OK


def evaluate_quota(
    cpu_used_sec: float,
    active_time_seconds: float,
    period_start: datetime,
    period_end: datetime,
    now: datetime,
    allowance: float = FREE_TIER_CU_HOURS,
    storage_bytes: int = 0,
    egress_bytes: int = 0,
) -> QuotaResult:
    """Turn raw Neon consumption counters into an alert level.

    `cpu_used_sec` is already CU-weighted by Neon (active seconds x compute
    size), so CU-hours is just seconds/3600.
    """
    elapsed_seconds = max((now - period_start).total_seconds(), 0.0)
    period_seconds = (period_end - period_start).total_seconds()
    elapsed_hours = elapsed_seconds / 3600.0

    cu_hours_used = cpu_used_sec / 3600.0
    pct_used = (cu_hours_used / allowance * 100.0) if allowance else 0.0

    projected = None
    if elapsed_hours >= MIN_PROJECTION_HOURS and period_seconds > 0:
        projected = cu_hours_used * (period_seconds / elapsed_seconds)

    active_ratio = (active_time_seconds / elapsed_seconds) if elapsed_seconds > 0 else None

    pct_storage = (storage_bytes / FREE_TIER_STORAGE_BYTES * 100.0) if storage_bytes else 0.0
    pct_egress = (egress_bytes / FREE_TIER_EGRESS_BYTES * 100.0) if egress_bytes else 0.0

    level = Level.OK
    reasons: list[str] = []

    def note(pct: float, message: str):
        nonlocal level
        crossed = _threshold_level(pct)
        if crossed > Level.OK:
            level = max(level, crossed)
            reasons.append(message)

    note(
        pct_used,
        f'{pct_used:.1f}% of the {allowance:.0f} CU-hour compute allowance used '
        f'({cu_hours_used:.1f} CU-hours) — over it, the compute is suspended '
        f'until the period resets',
    )
    note(
        pct_storage,
        f'{pct_storage:.1f}% of the {FREE_TIER_STORAGE_BYTES / 1024 / 1024:.0f} MB storage '
        f'limit used ({storage_bytes / 1024 / 1024:.0f} MB) — over it, writes start failing',
    )
    note(
        pct_egress,
        f'{pct_egress:.1f}% of the {FREE_TIER_EGRESS_BYTES / 1024 / 1024 / 1024:.0f} GB egress '
        f'allowance used ({egress_bytes / 1024 / 1024:.0f} MB) — over it, the compute is '
        f'suspended',
    )

    if projected is not None and projected >= allowance:
        level = max(level, Level.WARN)
        reasons.append(
            f'projected {projected:.0f} CU-hours by period end, over the '
            f'{allowance:.0f} CU-hour allowance'
        )

    if active_ratio is not None and active_ratio >= ACTIVE_RATIO_WARN:
        level = max(level, Level.WARN)
        reasons.append(
            f'compute active {active_ratio * 100:.0f}% of elapsed time — expected '
            f'under {ACTIVE_RATIO_WARN * 100:.0f}%; something may be keeping it awake'
        )

    return QuotaResult(
        level=level,
        cu_hours_used=cu_hours_used,
        pct_used=pct_used,
        allowance=allowance,
        projected_cu_hours=projected,
        active_ratio=active_ratio,
        elapsed_hours=elapsed_hours,
        storage_bytes=storage_bytes,
        pct_storage=pct_storage,
        egress_bytes=egress_bytes,
        pct_egress=pct_egress,
        reasons=reasons,
    )


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def fetch_project(project_id: str, api_key: str) -> dict:
    request = urllib.request.Request(
        f'{NEON_API}/projects/{project_id}',
        headers={'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)['project']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='emit JSON instead of text')
    parser.add_argument(
        '--project-id', default=os.getenv('NEON_PROJECT_ID'), help='Neon project id'
    )
    args = parser.parse_args(argv)

    api_key = os.getenv('NEON_API_KEY')
    if not api_key or not args.project_id:
        print('NEON_API_KEY and NEON_PROJECT_ID are required', file=sys.stderr)
        return 2

    try:
        project = fetch_project(args.project_id, api_key)
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        # Do not fail the alert closed: a broken check should be loud.
        print(f'could not read Neon consumption: {exc}', file=sys.stderr)
        return 2

    result = evaluate_quota(
        cpu_used_sec=project.get('cpu_used_sec', 0),
        active_time_seconds=project.get('active_time_seconds', 0),
        period_start=_parse_ts(project['consumption_period_start']),
        period_end=_parse_ts(project['consumption_period_end']),
        now=datetime.now(UTC),
        storage_bytes=project.get('synthetic_storage_size', 0),
        egress_bytes=project.get('data_transfer_bytes', 0),
    )

    if args.json:
        print(json.dumps({**result.as_dict(), 'project': project.get('name')}, indent=2))
    else:
        print(f"Neon project: {project.get('name')} [{result.level.name}]")
        print(
            f'  {result.cu_hours_used:.1f} / {result.allowance:.0f} CU-hours '
            f'({result.pct_used:.1f}%) after {result.elapsed_hours:.0f}h of the period'
        )
        if result.projected_cu_hours is not None:
            print(f'  projected by period end: {result.projected_cu_hours:.0f} CU-hours')
        print(
            f'  storage: {result.storage_bytes / 1024 / 1024:.0f} MB '
            f'({result.pct_storage:.1f}% of limit)   '
            f'egress: {result.egress_bytes / 1024 / 1024:.0f} MB '
            f'({result.pct_egress:.1f}% of allowance)'
        )
        if result.active_ratio is not None:
            print(f'  compute active: {result.active_ratio * 100:.1f}% of elapsed time')
        for reason in result.reasons:
            print(f'  ! {reason}')

    return int(result.level)


if __name__ == '__main__':
    sys.exit(main())
