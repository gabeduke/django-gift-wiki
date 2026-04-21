"""Tests for /sessionLogin request validation.

The Firebase Admin SDK verify path is intentionally not exercised here per issue #37 —
these tests cover only the input-validation branches that fail before reaching the SDK.
"""

import json

import pytest


@pytest.mark.unit
class TestSessionLoginValidation:
    def test_empty_body_returns_400(self, client):
        response = client.post('/sessionLogin', data=b'', content_type='application/json')
        assert response.status_code == 400
        assert json.loads(response.content) == {'error': 'Invalid JSON body'}

    def test_invalid_json_returns_400(self, client):
        response = client.post('/sessionLogin', data=b'{not json', content_type='application/json')
        assert response.status_code == 400
        assert json.loads(response.content) == {'error': 'Invalid JSON body'}

    def test_missing_id_token_returns_400(self, client):
        response = client.post('/sessionLogin', data='{}', content_type='application/json')
        assert response.status_code == 400
        body = json.loads(response.content)
        assert 'ID token' in body['error']

    def test_get_method_not_allowed(self, client):
        response = client.get('/sessionLogin')
        assert response.status_code == 405
