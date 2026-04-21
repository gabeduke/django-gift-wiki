"""Tests for public pages that render without authentication."""

import pytest


@pytest.mark.unit
class TestPublicPages:
    def test_privacy_page_renders_unauthenticated(self, client):
        response = client.get('/privacy/')
        assert response.status_code == 200
        assert 'gift/privacy.html' in [t.name for t in response.templates]

    def test_data_deletion_page_renders_unauthenticated(self, client):
        response = client.get('/data-deletion/')
        assert response.status_code == 200
        assert 'gift/data_deletion.html' in [t.name for t in response.templates]
