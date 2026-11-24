"""robots.txt is public and DB-free: crawlers fetch it with no session, and a
fetch that woke the Neon compute would burn the free-tier allowance."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

pytestmark = pytest.mark.unit


class TestRobots:
    def test_public_plain_text_and_cacheable(self, client):
        response = client.get('/robots.txt')

        assert response.status_code == 200
        assert response['Content-Type'].startswith('text/plain')
        assert 'max-age=86400' in response['Cache-Control']

    def test_blocks_everything_except_the_oauth_review_pages(self, client):
        lines = client.get('/robots.txt').content.decode().splitlines()

        assert lines == [
            'User-agent: *',
            'Allow: /privacy/',
            'Allow: /data-deletion/',
            'Disallow: /',
        ]

    @pytest.mark.django_db
    def test_runs_no_database_queries(self, client):
        with CaptureQueriesContext(connection) as queries:
            client.get('/robots.txt')

        assert len(queries) == 0
