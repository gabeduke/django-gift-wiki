"""Gift exchanges: who's in, drawing names, letters, and who sees what.

The rule everything here keeps: a pairing is only ever shown to its giver.
The organizer runs the draw but sees the roster and who has opened theirs,
never who drew whom. A letter is seen by its writer, then — once delivered —
by the person it's for, and on the board only if both of them said so.
"""

import random

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Exchange, ExchangeLetter, ExchangeParticipant

# With two people each knows who the other drew. Three works, but in a loop
# of three your own pick gives the rest away; the organizer page says so.
MIN_PARTICIPANTS = 3
SMALL_DRAW = 3

_rng = random.SystemRandom()


class DrawError(Exception):
    """The draw can't happen; the message is safe to show the organizer."""


def can_manage(user, exchange):
    return user.is_authenticated and (user.is_staff or exchange.organizer_id == user.id)


def draw_names(exchange):
    """Give every participant someone to draw for.

    Shuffles everyone into one loop and has each person give to the next, so
    nobody draws themselves and nobody gets a simple swap (A→B, B→A). Drawing
    again starts over: everyone's pick is sealed again and marked changed, and
    letters not yet delivered are thrown away — they were written for someone
    else. Once letters are delivered the draw is final.
    """
    with transaction.atomic():
        exchange = Exchange.objects.select_for_update().get(pk=exchange.pk)
        if exchange.letters_delivered:
            raise DrawError('Letters have already been delivered, so the draw is final.')
        people = list(exchange.participants.select_for_update())
        if len(people) < MIN_PARTICIPANTS:
            raise DrawError(f'At least {MIN_PARTICIPANTS} people need to join before drawing names.')
        redraw = exchange.is_drawn
        _rng.shuffle(people)
        for giver, receiver in zip(people, people[1:] + people[:1], strict=True):
            giver.receiver_id = receiver.giver_id
            giver.reveal_seen_at = None
            giver.pick_changed = redraw
            giver.save(update_fields=['receiver', 'reveal_seen_at', 'pick_changed'])
        delete_letters(ExchangeLetter.objects.filter(exchange=exchange))
        exchange.drawn_at = timezone.now()
        exchange.save(update_fields=['drawn_at'])
    return exchange


def _repick(entry, receiver_id):
    """Point one giver at someone new: their old pick, envelope and letter go."""
    entry.receiver_id = receiver_id
    entry.reveal_seen_at = None
    entry.pick_changed = True
    entry.save(update_fields=['receiver', 'reveal_seen_at', 'pick_changed'])
    delete_letters(ExchangeLetter.objects.filter(exchange=entry.exchange, author=entry.giver_id))


def add_person(exchange, person):
    """Add someone, fitting them into the loop if names are already drawn.

    A late joiner is slotted in after one random giver (A→B becomes A→new→B),
    so only that one person's pick changes — nobody else has to start over.
    """
    with transaction.atomic():
        exchange = Exchange.objects.select_for_update().get(pk=exchange.pk)
        entry, created = ExchangeParticipant.objects.get_or_create(exchange=exchange, giver=person)
        if not created or not exchange.is_drawn:
            return entry
        givers = list(
            exchange.participants.select_for_update()
            .exclude(pk=entry.pk)
            .filter(receiver__isnull=False)
        )
        if givers:
            before = _rng.choice(givers)
            entry.receiver_id = before.receiver_id
            entry.save(update_fields=['receiver'])
            _repick(before, person.id)
    return entry


def remove_person(exchange, entry):
    """Take someone out, closing the loop around them if names are drawn.

    Whoever drew them inherits their pick (A→gone→C becomes A→C), so again
    only one pick changes. Letters to or from them go too.
    """
    with transaction.atomic():
        exchange = Exchange.objects.select_for_update().get(pk=exchange.pk)
        if exchange.is_drawn:
            giver = (
                exchange.participants.select_for_update()
                .filter(receiver=entry.giver_id)
                .exclude(pk=entry.pk)
                .first()
            )
            if giver is not None:
                # With only two left, the giver would inherit themselves
                inherit = entry.receiver_id if entry.receiver_id != giver.giver_id else None
                _repick(giver, inherit)
            delete_letters(
                ExchangeLetter.objects.filter(exchange=exchange).filter(
                    Q(author=entry.giver_id) | Q(receiver=entry.giver_id)
                )
            )
        entry.delete()


def needs_redraw(exchange, participants):
    """The loop no longer covers exactly the people in it (rare now that adds
    and removes splice the loop, but a deleted account can still break it)."""
    if not exchange.is_drawn:
        return False
    givers = {p.giver_id for p in participants}
    receivers = [p.receiver_id for p in participants]
    return None in receivers or set(receivers) != givers


def addable_people(exchange):
    """People the organizer can add: anyone who can sign in (an email or a
    linked email — see the Firebase middleware) and isn't in yet. Someone who
    can't sign in would never see who they drew."""
    User = get_user_model()
    return (
        User.objects.filter(is_active=True)
        .filter(Q(email__gt='') | Q(linked_emails__isnull=False))
        .exclude(exchange_entries__exchange=exchange)
        .distinct()
        .order_by('first_name', 'last_name', 'username')
    )


def deliver_letters(exchange, participants=None):
    """Hand out every letter. Refused while the draw is broken: delivering makes
    it final, and someone would be left out for good."""
    if not exchange.is_drawn:
        raise DrawError('Draw names first.')
    if not exchange.is_active:
        raise DrawError('This exchange has wrapped up.')
    if participants is None:
        participants = list(exchange.participants.all())
    if needs_redraw(exchange, participants):
        raise DrawError('Who’s in has changed since the draw — draw again before delivering.')
    exchange.letters_delivered_at = timezone.now()
    exchange.save(update_fields=['letters_delivered_at'])


def letters_for(user):
    """Delivered letters to `user` in active exchanges, newest exchange first."""
    if not user.is_authenticated:
        return []
    return list(
        ExchangeLetter.objects.filter(
            receiver=user,
            exchange__is_active=True,
            exchange__letters_delivered_at__isnull=False,
        )
        .select_related('exchange', 'author')
        .order_by('-exchange__created_at', 'id')
    )


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


def open_invitations_for(user, declined=()):
    """Active exchanges still taking people that the user hasn't joined or
    said "not this time" to."""
    return list(
        Exchange.objects.filter(is_active=True, drawn_at__isnull=True)
        .exclude(participants__giver=user)
        .exclude(id__in=declined)
    )


def delete_letters(letters):
    """Delete letters, and their photos once the deletion has committed — the
    storage doesn't clean up after itself, and a rolled-back delete must not
    lose a photo."""
    for letter in list(letters):
        if letter.image:
            storage, name = letter.image.storage, letter.image.name
            transaction.on_commit(lambda storage=storage, name=name: storage.delete(name))
        letter.delete()


def can_see_letter(user, letter, exchange):
    """The author always; the receiver once delivered; everyone in the
    exchange once it's on the board."""
    if letter.author_id == user.id:
        return True
    if not exchange.letters_delivered:
        return False
    if letter.receiver_id == user.id:
        return True
    return on_board(letter, exchange) and (
        can_manage(user, exchange) or exchange.participants.filter(giver=user).exists()
    )


def on_board(letter, exchange):
    """Both sides said yes: the writer when writing, the reader after reading."""
    return (
        exchange.board_enabled
        and exchange.letters_delivered
        and letter.shareable
        and letter.shared_by_receiver
        and letter.read_at is not None
    )
