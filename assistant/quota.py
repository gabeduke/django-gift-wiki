"""Usage accounting for the assistant.

Every counter here is an atomic F() update rather than a read-modify-write:
two browser tabs must not be able to both slip under the cap.
"""

from django.db.models import F, Sum

from assistant.models import AssistantUsage, current_period


def reserve_message(user, period=None):
    """Claim one message for `user` and return their new count for the period.

    Claimed *before* the model call, so a second request can't spend the same
    allowance. refund_message() puts it back if the call fails.
    """
    period = period or current_period()
    usage, _ = AssistantUsage.objects.get_or_create(user=user, period=period)
    AssistantUsage.objects.filter(pk=usage.pk).update(message_count=F('message_count') + 1)
    return AssistantUsage.objects.values_list('message_count', flat=True).get(pk=usage.pk)


def refund_message(user, period=None):
    """Hand back a message reserved for a call that never happened."""
    AssistantUsage.objects.filter(
        user=user, period=period or current_period(), message_count__gt=0
    ).update(message_count=F('message_count') - 1)


def record_tokens(user, input_tokens, output_tokens, period=None):
    """Add what a turn actually cost. Recorded for tuning, never enforced."""
    AssistantUsage.objects.filter(user=user, period=period or current_period()).update(
        input_tokens=F('input_tokens') + input_tokens,
        output_tokens=F('output_tokens') + output_tokens,
    )


def messages_used(user, period=None):
    count = (
        AssistantUsage.objects.filter(user=user, period=period or current_period())
        .values_list('message_count', flat=True)
        .first()
    )
    return count or 0


def global_messages_used(period=None):
    total = AssistantUsage.objects.filter(period=period or current_period()).aggregate(
        total=Sum('message_count')
    )['total']
    return total or 0
