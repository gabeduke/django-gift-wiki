"""Gift exchanges: who's in, drawing names, letters, and who sees what.

The rule everything here keeps: a pairing is shown to its giver, and to the
exchange's curators only on the page made for adjusting the draw — never on
the roster, in a message or in a log. A letter is seen by its writer, then —
once delivered — by the person it's for, and on the board only if both of
them said so.

Curators are the organizer who made the exchange plus anyone they name. They
can say who to keep apart (ExchangeKeepApart); every way a pick gets assigned
here honours those rules.
"""

import random

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Exchange, ExchangeKeepApart, ExchangeLetter, ExchangeParticipant

# With two people each knows who the other drew. Three works, but in a loop
# of three your own pick gives the rest away; the organizer page says so.
MIN_PARTICIPANTS = 3
SMALL_DRAW = 3

# Plain shuffles find a loop quickly unless the rules are tight; then a
# search takes over, and gives up after this many steps.
SHUFFLE_TRIES = 200
SEARCH_STEPS = 50_000

_rng = random.SystemRandom()


class DrawError(Exception):
    """The draw can't happen; the message is safe to show a curator."""


def is_curator(user, exchange):
    """The organizer, or someone they named. Curators may see the draw."""
    if not user.is_authenticated:
        return False
    return exchange.organizer_id == user.id or exchange.curators.filter(pk=user.pk).exists()


def can_manage(user, exchange):
    """Run the exchange: curators, and staff. Staff who aren't curators get
    the roster tools but not the rules or the draw — they may be playing."""
    return user.is_authenticated and (user.is_staff or is_curator(user, exchange))


def can_name_curators(user, exchange):
    return user.is_authenticated and (user.is_staff or exchange.organizer_id == user.id)


def curators_of(exchange):
    """Everyone curating: the organizer first, then co-curators by name."""
    people = [exchange.organizer] if exchange.organizer else []
    people += [
        person
        for person in exchange.curators.order_by('first_name', 'last_name', 'username')
        if person.id != exchange.organizer_id
    ]
    return people


def kept_apart(exchange):
    """The keep-apart rules as a set of frozenset({user id, user id})."""
    return {
        frozenset(pair)
        for pair in exchange.keep_apart.values_list('first__giver_id', 'second__giver_id')
    }


def _allowed(apart, giver_id, receiver_id):
    return giver_id != receiver_id and frozenset((giver_id, receiver_id)) not in apart


def _loop(ids, apart):
    """Everyone in one random loop with no kept-apart neighbours, or None."""
    ids = list(ids)
    for _ in range(SHUFFLE_TRIES):
        _rng.shuffle(ids)
        if all(_allowed(apart, a, b) for a, b in zip(ids, ids[1:] + ids[:1], strict=True)):
            return ids

    start, rest, path = ids[0], set(ids[1:]), [ids[0]]
    steps = 0

    def extend():
        nonlocal steps
        if not rest:
            return _allowed(apart, path[-1], start)
        steps += 1
        if steps > SEARCH_STEPS:
            return False
        options = [person for person in rest if _allowed(apart, path[-1], person)]
        _rng.shuffle(options)
        for person in options:
            rest.remove(person)
            path.append(person)
            if extend():
                return True
            path.pop()
            rest.add(person)
        return False

    return path if extend() else None


def draw_names(exchange):
    """Give every participant someone to draw for.

    Shuffles everyone into one loop and has each person give to the next, so
    nobody draws themselves and nobody gets a simple swap (A→B, B→A). Drawing
    again starts over: everyone's pick is sealed again and marked changed, and
    letters not yet delivered are thrown away — they were written for someone
    else. Once letters are delivered the draw is final.

    People kept apart are never next to each other in the loop, so neither
    draws the other.
    """
    with transaction.atomic():
        exchange = Exchange.objects.select_for_update().get(pk=exchange.pk)
        if exchange.letters_delivered:
            raise DrawError('Letters have already been delivered, so the draw is final.')
        people = list(exchange.participants.select_for_update())
        if len(people) < MIN_PARTICIPANTS:
            raise DrawError(f'At least {MIN_PARTICIPANTS} people need to join before drawing names.')
        redraw = exchange.is_drawn
        order = _loop([p.giver_id for p in people], kept_apart(exchange))
        if order is None:
            raise DrawError(
                'The keep-apart rules leave no way to put everyone in one loop. '
                'Take one off, or add more people, and draw again.'
            )
        by_giver = {p.giver_id: p for p in people}
        for giver_id, receiver_id in zip(order, order[1:] + order[:1], strict=True):
            giver = by_giver[giver_id]
            giver.receiver_id = receiver_id
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
    only one pick changes. Letters to or from them go too. If A and C are kept
    apart, A is left without a pick and the exchange needs drawing again.
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
                inherit = entry.receiver_id
                if not inherit or not _allowed(kept_apart(exchange), giver.giver_id, inherit):
                    inherit = None
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


def breaks_rules(participants, apart):
    """Does the draw pair two people who are kept apart? (A rule added after
    the draw, usually.)"""
    return any(
        p.receiver_id and frozenset((p.giver_id, p.receiver_id)) in apart for p in participants
    )


def keep_apart(exchange, first, second):
    """Add a rule that two participants never draw each other."""
    if first.pk == second.pk:
        raise DrawError('Choose two different people.')
    if first.exchange_id != exchange.pk or second.exchange_id != exchange.pk:
        raise DrawError('Choose two people who are in.')
    low, high = sorted((first, second), key=lambda entry: entry.pk)
    return ExchangeKeepApart.objects.get_or_create(exchange=exchange, first=low, second=high)[0]


def pick_options(participants, apart):
    """For each giver, the people a curator could hand them instead.

    Changing a pick is a swap: A takes X, and whoever had X takes A's old
    pick. So X is on offer only if both new pairs are allowed.
    """
    giver_of = {p.receiver_id: p for p in participants if p.receiver_id}
    person = {p.giver_id: p.giver for p in participants}
    options = {}
    for entry in participants:
        options[entry.pk] = [
            person[receiver_id]
            for receiver_id, other in giver_of.items()
            if other.pk != entry.pk
            and _allowed(apart, entry.giver_id, receiver_id)
            and _allowed(apart, other.giver_id, entry.receiver_id)
        ]
    return options


def change_pick(exchange, entry_id, receiver_id):
    """A curator hands one giver a different person.

    Whoever had that person takes the giver's old pick, so everyone still
    gives once and gets once. Both of them get a sealed new pick, and lose
    any letter they'd written. Nobody ends up with themselves, or with
    someone they're kept apart from.
    """
    with transaction.atomic():
        exchange = Exchange.objects.select_for_update().get(pk=exchange.pk)
        if not exchange.is_active:
            raise DrawError('This exchange has wrapped up.')
        if not exchange.is_drawn:
            raise DrawError('Draw names first.')
        if exchange.letters_delivered:
            raise DrawError('Letters have been delivered, so the draw is final.')
        people = list(exchange.participants.select_for_update())
        if needs_redraw(exchange, people):
            raise DrawError('Who’s in has changed since the draw — draw again first.')
        entry = next((p for p in people if p.pk == entry_id), None)
        other = next((p for p in people if p.receiver_id == receiver_id), None)
        if entry is None or other is None:
            raise DrawError('Choose someone who’s in.')
        if other.pk == entry.pk:
            return
        apart = kept_apart(exchange)
        if entry.giver_id == receiver_id or other.giver_id == entry.receiver_id:
            raise DrawError('That would leave someone drawing themselves.')
        if not _allowed(apart, entry.giver_id, receiver_id) or not _allowed(
            apart, other.giver_id, entry.receiver_id
        ):
            raise DrawError('That would pair two people you’re keeping apart.')
        old = entry.receiver_id
        _repick(entry, receiver_id)
        _repick(other, old)


def _can_sign_in():
    """Active people with an email or a linked email — see the Firebase
    middleware."""
    User = get_user_model()
    return User.objects.filter(is_active=True).filter(
        Q(email__gt='') | Q(linked_emails__isnull=False)
    )


def addable_people(exchange):
    """People a curator can add: anyone who can sign in and isn't in yet.
    Someone who can't sign in would never see who they drew."""
    return (
        _can_sign_in()
        .exclude(exchange_entries__exchange=exchange)
        .distinct()
        .order_by('first_name', 'last_name', 'username')
    )


def possible_curators(exchange):
    """People who could be named a curator: they can sign in and aren't one."""
    return (
        _can_sign_in()
        .exclude(pk=exchange.organizer_id or 0)
        .exclude(curated_exchanges=exchange)
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


def delete_exchange(exchange):
    """Delete an exchange outright — for one made by mistake. Everyone in it,
    their picks and their letters go with it, photos included."""
    with transaction.atomic():
        delete_letters(ExchangeLetter.objects.filter(exchange=exchange))
        exchange.delete()


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
