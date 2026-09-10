#!/usr/bin/env python3
"""Verify a pg_dump file is a real, complete backup before trusting it.

A backup that silently fails is worse than no backup: it removes the pressure to
have a working one. The classic failure is a truncated dump — the connection
drops mid-stream, the file lands in the bucket at a plausible size, and nobody
finds out until a restore is attempted under pressure, which is always the worst
possible moment.

pg_dump writes `-- PostgreSQL database dump complete` as its final line. Its
presence is the difference between "a file was uploaded" and "a backup exists".

    python scripts/verify_pg_dump.py backup.sql.gz

Exit code 0 if the dump is trustworthy, 1 if it is not.
"""

from __future__ import annotations

import argparse
import gzip
import sys
from dataclasses import dataclass, field
from pathlib import Path

COMPLETION_MARKER = 'PostgreSQL database dump complete'

# Tables whose absence means we dumped the wrong database, or got schema only.
# Deliberately core tables that will always hold rows in this app.
REQUIRED_TABLES = ('gift_item', 'gift_wikiuser', 'gift_wishlist')

# The production database is ~33 MB; a compressed dump is far smaller, but a
# real one is never a few hundred bytes. This is a floor against catastrophe
# (empty database, wrong target), not a precise size expectation.
DEFAULT_MIN_BYTES = 2048


@dataclass
class DumpVerdict:
    ok: bool
    size_bytes: int = 0
    reasons: list[str] = field(default_factory=list)


def _read_text(path: Path) -> str:
    if path.suffix == '.gz':
        with gzip.open(path, 'rt', errors='replace') as handle:
            return handle.read()
    return path.read_text(errors='replace')


def verify_dump(
    path,
    required_tables: tuple[str, ...] = REQUIRED_TABLES,
    min_bytes: int = DEFAULT_MIN_BYTES,
) -> DumpVerdict:
    path = Path(path)
    reasons: list[str] = []

    if not path.exists():
        return DumpVerdict(ok=False, reasons=[f'dump not found at {path}'])

    size = path.stat().st_size
    if size == 0:
        return DumpVerdict(ok=False, size_bytes=0, reasons=['dump is empty (0 bytes)'])

    try:
        content = _read_text(path)
    except (OSError, gzip.BadGzipFile) as exc:
        return DumpVerdict(ok=False, size_bytes=size, reasons=[f'dump unreadable: {exc}'])

    # Uncompressed length is the meaningful measure; a gzipped dump of a small
    # database compresses hard enough to pass a byte floor while being wrong.
    if len(content) < min_bytes:
        reasons.append(
            f'dump is suspiciously small: {len(content)} bytes of SQL, '
            f'expected at least {min_bytes}'
        )

    if COMPLETION_MARKER not in content:
        reasons.append(
            'dump is incomplete — missing the pg_dump completion marker, which '
            'means it was truncated (dropped connection, disk full, timeout)'
        )

    # A schema-only dump is the other silent failure: right tables, completion
    # marker, plausible size, zero rows. Restoring it yields an empty app that
    # looks structurally correct. pg_dump writes data as COPY blocks.
    if 'COPY ' not in content:
        reasons.append(
            'dump contains no data section (no COPY blocks) — this is a '
            'schema-only dump and would restore an empty database'
        )

    missing = [t for t in required_tables if t not in content]
    if missing:
        reasons.append(
            f'dump is missing expected tables: {", ".join(missing)} — wrong '
            f'database, or a schema-only dump'
        )

    return DumpVerdict(ok=not reasons, size_bytes=size, reasons=reasons)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dump', help='path to the .sql or .sql.gz file')
    parser.add_argument(
        '--min-bytes',
        type=int,
        default=DEFAULT_MIN_BYTES,
        help=f'minimum uncompressed SQL size (default {DEFAULT_MIN_BYTES})',
    )
    args = parser.parse_args(argv)

    verdict = verify_dump(args.dump, min_bytes=args.min_bytes)

    if verdict.ok:
        print(f'OK: {args.dump} is a complete dump ({verdict.size_bytes} bytes on disk)')
        return 0

    print(f'FAILED: {args.dump} is not a trustworthy backup', file=sys.stderr)
    for reason in verdict.reasons:
        print(f'  - {reason}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
