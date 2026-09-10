"""Tests for backup dump verification.

A backup that silently fails is worse than no backup, because it removes the
pressure to have a real one. The classic failure is a truncated dump — the
connection drops mid-stream, the file lands in the bucket looking plausible, and
nobody finds out until a restore is attempted under pressure.

pg_dump writes a completion marker as its last line. Checking for it is the
difference between "a file was uploaded" and "a backup exists".
"""

import gzip

import pytest

from scripts.verify_pg_dump import verify_dump

HEADER = '--\n-- PostgreSQL database dump\n--\n\nSET statement_timeout = 0;\n'
FOOTER = '--\n-- PostgreSQL database dump complete\n--\n'


def make_dump(tmp_path, *, tables=('gift_item', 'gift_wikiuser', 'gift_wishlist'),
              complete=True, gz=False, padding=4096):
    body = HEADER
    for t in tables:
        body += f'CREATE TABLE public.{t} (id bigint NOT NULL);\n'
        body += f'COPY public.{t} (id) FROM stdin;\n1\n\\.\n'
    body += 'x' * padding  # stand in for real data volume
    if complete:
        body += FOOTER
    path = tmp_path / ('dump.sql.gz' if gz else 'dump.sql')
    if gz:
        path.write_bytes(gzip.compress(body.encode()))
    else:
        path.write_text(body)
    return path


@pytest.mark.unit
class TestVerifyDump:
    def test_accepts_a_complete_dump(self, tmp_path):
        result = verify_dump(make_dump(tmp_path))

        assert result.ok
        assert result.reasons == []

    def test_accepts_a_complete_gzipped_dump(self, tmp_path):
        result = verify_dump(make_dump(tmp_path, gz=True))

        assert result.ok

    def test_rejects_a_missing_file(self, tmp_path):
        result = verify_dump(tmp_path / 'nope.sql')

        assert not result.ok
        assert any('not found' in r.lower() for r in result.reasons)

    def test_rejects_an_empty_file(self, tmp_path):
        path = tmp_path / 'dump.sql'
        path.write_text('')

        result = verify_dump(path)

        assert not result.ok

    def test_rejects_a_truncated_dump(self, tmp_path):
        """The important case: header present, data present, no completion
        marker — exactly what a dropped connection mid-dump produces."""
        result = verify_dump(make_dump(tmp_path, complete=False))

        assert not result.ok
        assert any('complete' in r.lower() for r in result.reasons)

    def test_rejects_a_dump_missing_expected_tables(self, tmp_path):
        """Guards against dumping the wrong database, or a schema-only dump."""
        result = verify_dump(make_dump(tmp_path, tables=('gift_item',)))

        assert not result.ok
        assert any('gift_wishlist' in r for r in result.reasons)

    def test_rejects_a_suspiciously_small_dump(self, tmp_path):
        """A dump far smaller than the real database means something emptied it."""
        result = verify_dump(make_dump(tmp_path, padding=0), min_bytes=100_000)

        assert not result.ok
        assert any('small' in r.lower() or 'bytes' in r.lower() for r in result.reasons)


@pytest.mark.unit
class TestSchemaOnlyDump:
    """A schema-only dump is the other silent failure: it has every table name,
    a completion marker, and a plausible size — but not a single row. Restoring
    from one gives you an empty application that looks structurally correct.
    """

    def test_rejects_a_dump_with_no_data_section(self, tmp_path):
        body = HEADER
        for t in ('gift_item', 'gift_wikiuser', 'gift_wishlist'):
            body += f'CREATE TABLE public.{t} (id bigint NOT NULL);\n'
        body += 'x' * 4096 + FOOTER  # complete, right tables, no COPY blocks
        path = tmp_path / 'schema_only.sql'
        path.write_text(body)

        result = verify_dump(path)

        assert not result.ok
        assert any('data' in r.lower() for r in result.reasons)

    def test_accepts_a_dump_containing_a_data_section(self, tmp_path):
        body = HEADER
        for t in ('gift_item', 'gift_wikiuser', 'gift_wishlist'):
            body += f'CREATE TABLE public.{t} (id bigint NOT NULL);\n'
            body += f'COPY public.{t} (id) FROM stdin;\n1\n\\.\n'
        body += 'x' * 4096 + FOOTER
        path = tmp_path / 'full.sql'
        path.write_text(body)

        assert verify_dump(path).ok
