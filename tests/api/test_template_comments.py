"""Regression test: multi-line {# #} comments are NOT valid Django template
comments (they only work on a single line) and leak into rendered HTML.
Keep rendered pages free of raw template-comment markers."""

import pytest

pytestmark = pytest.mark.unit


class TestTemplateCommentLeak:
    def test_home_page_has_no_template_comment_markers(self, authenticated_user, wishlist):
        response = authenticated_user.get('/')
        assert response.status_code == 200
        content = response.content.decode()
        assert '{#' not in content
        assert '#}' not in content

    def test_wishlist_detail_has_no_template_comment_markers(self, authenticated_user, wishlist):
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
        content = response.content.decode()
        assert '{#' not in content
        assert '#}' not in content
