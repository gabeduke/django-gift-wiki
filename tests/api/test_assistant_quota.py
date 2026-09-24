"""Tests for the assistant's metering: settings, usage counters, and the gate.

Cost is the unknown in this feature, so the counters are the part that has to
be right before anything is allowed to call a model.
"""

import pytest

from assistant.models import AssistantSettings, AssistantUsage, current_period
from gift.models import FeatureFlag
from giftwiki.feature_flags import _cache, _clear_cache, get_assistant_enabled


@pytest.fixture
def assistant_on(db):
    """Turn the feature on the way an admin would, and clear the flag cache."""
    FeatureFlag.objects.update_or_create(name='ASSISTANT_ENABLED', defaults={'enabled': True})
    _cache.clear()
    _clear_cache()
    yield
    _cache.clear()
    _clear_cache()


@pytest.mark.unit
class TestAssistantFlag:
    def test_off_by_default(self, db):
        _cache.clear()
        _clear_cache()

        assert get_assistant_enabled() is False

    def test_on_when_the_flag_row_says_so(self, assistant_on):
        assert get_assistant_enabled() is True


@pytest.mark.unit
class TestAssistantSettings:
    def test_load_creates_the_single_row(self, db):
        config = AssistantSettings.load()

        assert config.pk == 1
        assert AssistantSettings.objects.count() == 1

    def test_load_is_idempotent(self, db):
        AssistantSettings.load()
        AssistantSettings.load()

        assert AssistantSettings.objects.count() == 1

    def test_saving_a_second_row_overwrites_the_first(self, db):
        AssistantSettings.load()
        AssistantSettings(per_user_monthly_messages=7).save()

        assert AssistantSettings.objects.count() == 1
        assert AssistantSettings.load().per_user_monthly_messages == 7


@pytest.mark.unit
class TestUsageModel:
    def test_period_is_a_month_key(self):
        from datetime import date

        assert current_period(date(2026, 9, 23)) == '2026-09'

    def test_one_row_per_user_per_period(self, db, user):
        from django.db import IntegrityError

        AssistantUsage.objects.create(user=user, period='2026-09')

        with pytest.raises(IntegrityError):
            AssistantUsage.objects.create(user=user, period='2026-09')
