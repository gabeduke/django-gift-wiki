"""Gift exchanges: who's in, drawing names, and who sees what.

The rule everything here keeps: a pairing is only ever shown to its giver.
The organizer runs the draw but sees the roster and who has opened their
envelope, never who drew whom.
"""

import random

from django.db import transaction
from django.utils import timezone

from .models import Exchange, ExchangeParticipant

# With two people each knows who the other drew, so it isn't a secret.
MIN_PARTICIPANTS = 3

_rng = random.SystemRandom()


class DrawError(Exception):
    """The draw can't happen; the message is safe to show the organizer."""


def can_manage(user, exchange):
    return user.is_authenticated and (user.is_staff or exchange.organizer_id == user.id)


def draw_names(exchange):
    """Give every participant someone to buy for.

    Shuffles everyone into one loop and has each person give to the next, so
    nobody draws themselves and nobody can deduce a pairing from their own
    (no A→B, B→A swaps once there are three or more). Drawing again starts over:
    every envelope is sealed again.
    """
    with transaction.atomic():
        exchange = Exchange.objects.select_for_update().get(pk=exchange.pk)
        people = list(exchange.participants.select_for_update())
        if len(people) < MIN_PARTICIPANTS:
            raise DrawError(f'At least {MIN_PARTICIPANTS} people need to join before drawing names.')
        _rng.shuffle(people)
        for giver, receiver in zip(people, people[1:] + people[:1], strict=True):
            giver.receiver_id = receiver.giver_id
            giver.reveal_seen_at = None
            giver.save(update_fields=['receiver', 'reveal_seen_at'])
        exchange.drawn_at = timezone.now()
        exchange.save(update_fields=['drawn_at'])
    return exchange


def assignments_for(user):
    """The user's drawn entries in active exchanges, receiver loaded."""
    if not user.is_authenticated:
        return []
    return list(
        ExchangeParticipant.objects.filter(
            giver=user,
            exchange__is_active=True,
            exchange__drawn_at__isnull=False,
            receiver__isnull=False,
        ).select_related('exchange', 'receiver')
    )


def open_invitations_for(user):
    """Active exchanges still taking people that the user hasn't joined."""
    return list(
        Exchange.objects.filter(is_active=True, drawn_at__isnull=True).exclude(
            participants__giver=user
        )
    )
