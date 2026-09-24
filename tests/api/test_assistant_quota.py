"""Tests for the assistant's metering: settings, usage counters, and the gate.

Cost is the unknown in this feature, so the counters are the part that has to
be right before anything is allowed to call a model.
"""

import pytest

from assistant.gating import assistant_available_for
from assistant.models import AssistantSettings, AssistantUsage, current_period
from assistant.quota import (
    global_messages_used,
    messages_used,
    record_tokens,
    refund_message,
    reserve_message,
)
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

    def test_period_defaults_to_the_current_month(self):
        from django.utils import timezone

        assert current_period() == timezone.localdate().strftime('%Y-%m')

    def test_one_row_per_user_per_period(self, db, user):
        from django.db import IntegrityError

        AssistantUsage.objects.create(user=user, period='2026-09')

        with pytest.raises(IntegrityError):
            AssistantUsage.objects.create(user=user, period='2026-09')


@pytest.mark.unit
class TestReserveAndRefund:
    def test_reserve_returns_the_new_count(self, db, user):
        assert reserve_message(user) == 1
        assert reserve_message(user) == 2

    def test_reserve_creates_the_row_once(self, db, user):
        reserve_message(user)
        reserve_message(user)

        assert AssistantUsage.objects.filter(user=user).count() == 1

    def test_refund_puts_it_back(self, db, user):
        reserve_message(user)
        refund_message(user)

        assert messages_used(user) == 0

    def test_refund_never_goes_negative(self, db, user):
        refund_message(user)

        assert messages_used(user) == 0

    def test_tokens_accumulate(self, db, user):
        reserve_message(user)
        record_tokens(user, 100, 20)
        record_tokens(user, 50, 10)

        usage = AssistantUsage.objects.get(user=user, period=current_period())
        assert usage.input_tokens == 150
        assert usage.output_tokens == 30

    def test_usage_is_counted_per_person(self, db, user, other_user):
        reserve_message(user)
        reserve_message(other_user)
        reserve_message(other_user)

        assert messages_used(user) == 1
        assert global_messages_used() == 3

    def test_other_periods_do_not_count(self, db, user):
        AssistantUsage.objects.create(user=user, period='2020-01', message_count=99)

        assert messages_used(user) == 0
        assert global_messages_used() == 0


@pytest.mark.unit
class TestTheGate:
    def test_anonymous_is_turned_away(self, db):
        from django.contrib.auth.models import AnonymousUser

        assert assistant_available_for(AnonymousUser()).reason == 'anonymous'

    def test_closed_when_the_flag_is_off(self, db, user):
        _clear_cache()

        assert assistant_available_for(user).reason == 'disabled'

    def test_open_when_the_flag_is_on(self, assistant_on, user):
        assert assistant_available_for(user).available is True

    def test_closed_after_enabled_until(self, assistant_on, user):
        from datetime import timedelta

        from django.utils import timezone

        config = AssistantSettings.load()
        config.enabled_until = timezone.localdate() - timedelta(days=1)
        config.save()

        assert assistant_available_for(user).reason == 'expired'

    def test_open_on_the_last_enabled_day(self, assistant_on, user):
        from django.utils import timezone

        config = AssistantSettings.load()
        config.enabled_until = timezone.localdate()
        config.save()

        assert assistant_available_for(user).available is True

    def test_closed_at_the_personal_cap(self, assistant_on, user):
        config = AssistantSettings.load()
        config.per_user_monthly_messages = 2
        config.save()
        reserve_message(user)
        reserve_message(user)

        assert assistant_available_for(user).reason == 'user_cap'

    def test_one_persons_cap_does_not_close_it_for_another(self, assistant_on, user, other_user):
        config = AssistantSettings.load()
        config.per_user_monthly_messages = 1
        config.global_monthly_messages = 100
        config.save()
        reserve_message(user)

        assert assistant_available_for(user).reason == 'user_cap'
        assert assistant_available_for(other_user).available is True

    def test_closed_at_the_global_ceiling(self, assistant_on, user, other_user):
        config = AssistantSettings.load()
        config.per_user_monthly_messages = 100
        config.global_monthly_messages = 2
        config.save()
        reserve_message(other_user)
        reserve_message(other_user)

        assert assistant_available_for(user).reason == 'global_cap'

    def test_a_closed_gate_carries_copy_for_the_panel(self, assistant_on, user):
        config = AssistantSettings.load()
        config.per_user_monthly_messages = 0
        config.save()

        assert assistant_available_for(user).message
