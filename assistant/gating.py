"""One answer to 'may this person use the assistant right now?'.

The template asks it to decide whether to render the bubble; the endpoint asks
it again on every request. An unrendered UI is not a security control.
"""

from dataclasses import dataclass

from django.utils import timezone

from assistant.models import AssistantSettings, current_period
from assistant.quota import global_messages_used, messages_used
from giftwiki.feature_flags import get_assistant_enabled

CAP_MESSAGE = 'You have used all your assistant messages this month. They come back on the 1st.'
GLOBAL_MESSAGE = "The family's assistant budget is used up for this month. It comes back on the 1st."


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str = ''
    message: str = ''


AVAILABLE = Availability(True)


def assistant_available_for(user):
    """Whether `user` may send a message, and the reason when they may not.

    Checked in cost order: the flag first, because it is answered from an
    in-memory cache and costs no query at all.
    """
    if not getattr(user, 'is_authenticated', False):
        return Availability(False, 'anonymous')
    if not get_assistant_enabled():
        return Availability(False, 'disabled')

    config = AssistantSettings.load()
    if config.enabled_until and timezone.localdate() > config.enabled_until:
        return Availability(False, 'expired')

    period = current_period()
    if messages_used(user, period) >= config.per_user_monthly_messages:
        return Availability(False, 'user_cap', CAP_MESSAGE)
    if global_messages_used(period) >= config.global_monthly_messages:
        return Availability(False, 'global_cap', GLOBAL_MESSAGE)

    return AVAILABLE
