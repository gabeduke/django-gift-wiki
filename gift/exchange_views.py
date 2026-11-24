"""Pages for exchanges (see gift/exchange.py for the rules).

Every state change is a POST. Pairings appear only on the giver's own
reveal, and never while the session is over the shoulder.
"""

import math

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .exchange import (
    MIN_PARTICIPANTS,
    SMALL_DRAW,
    DrawError,
    add_person,
    addable_people,
    can_manage,
    can_see_letter,
    delete_letters,
    deliver_letters,
    draw_names,
    needs_redraw,
    on_board,
    remove_person,
)
from .forms import ExchangeForm, ExchangeLetterForm
from .middleware.ops_token import not_found
from .models import Exchange, ExchangeLetter, ExchangeParticipant, WishList
from .visibility import is_over_the_shoulder

# The roster ring: an SVG circle of everyone in the exchange.
RING_SIZE = 320
RING_RADIUS = 120

# Invites someone said "not this time" to, for this session.
DECLINED_SESSION_KEY = 'declined_exchanges'


def display_name(person):
    return person.get_full_name() or person.username


def initials(person):
    parts = [p for p in (person.first_name, person.last_name) if p]
    if not parts:
        parts = [person.username]
    return ''.join(p[0] for p in parts).upper()[:2]


def ring_layout(participants):
    """Place everyone evenly around a circle, in roster (alphabetical) order.

    Never in draw order: neighbours on the ring would give the pairings away.
    Nodes shrink as the ring fills so they never overlap.
    """
    centre = RING_SIZE / 2
    count = len(participants)
    # Leave a little air between neighbours on the circumference
    gap = 2 * math.pi * RING_RADIUS / max(count, 1)
    radius = max(9, min(22, round(gap / 2 - 3)))
    nodes = []
    for index, participant in enumerate(participants):
        angle = 2 * math.pi * index / max(count, 1) - math.pi / 2
        nodes.append(
            {
                'participant': participant,
                'initials': initials(participant.giver),
                'name': display_name(participant.giver),
                'x': round(centre + RING_RADIUS * math.cos(angle), 1),
                'y': round(centre + RING_RADIUS * math.sin(angle), 1),
                'r': radius,
            }
        )
    return nodes


def lists_for(person):
    """The lists whose gifts are for `person`."""
    return WishList.objects.filter(
        Q(dependent=person) | Q(owner=person, dependent__isnull=True)
    ).order_by('-updated_at')


def first_error(form):
    errors = [error for field_errors in form.errors.values() for error in field_errors]
    return errors[0] if errors else 'That didn’t save — please check it and try again.'


def detail_url(exchange_id, anchor=''):
    url = reverse('gift:exchange_detail', args=[exchange_id])
    return f'{url}#{anchor}' if anchor else url


def row_status(exchange, mine, wrote, unread):
    """What the exchange list says to *you* about an exchange."""
    if exchange.id in unread:
        return 'A letter for you'
    if mine is None:
        if exchange.is_active and not exchange.is_drawn:
            return 'Join'
        return 'Names drawn' if exchange.is_drawn else ''
    if exchange.is_drawn and mine.receiver_id:
        if not mine.reveal_seen_at:
            return 'Open yours'
        if (
            exchange.kind_info.letter_is_the_gift
            and not exchange.letters_delivered
            and exchange.id not in wrote
        ):
            return 'Write your letter'
    return "You're in"


@require_GET
@login_required
def exchange_list(request):
    exchanges = list(
        Exchange.objects.select_related('organizer').prefetch_related('participants')
    )
    mine = {
        p.exchange_id: p for p in ExchangeParticipant.objects.filter(giver=request.user)
    }
    wrote = set(
        ExchangeLetter.objects.filter(author=request.user).values_list('exchange_id', flat=True)
    )
    unread = set(
        ExchangeLetter.objects.filter(
            receiver=request.user, read_at__isnull=True, exchange__letters_delivered_at__isnull=False
        ).values_list('exchange_id', flat=True)
    )
    for exchange in exchanges:
        exchange.status = row_status(exchange, mine.get(exchange.id), wrote, unread)
    return render(
        request,
        'gift/exchange_list.html',
        {
            'active_exchanges': [e for e in exchanges if e.is_active],
            'past_exchanges': [e for e in exchanges if not e.is_active],
            'form': ExchangeForm(),
        },
    )


@require_POST
@login_required
def exchange_create(request):
    form = ExchangeForm(request.POST)
    if not form.is_valid():
        messages.error(request, first_error(form))
        return redirect('gift:exchange_list')
    exchange = form.save(commit=False)
    exchange.organizer = request.user
    exchange.save()
    # The organizer is usually playing too; they can step out before the draw.
    ExchangeParticipant.objects.create(exchange=exchange, giver=request.user)
    messages.success(
        request, f'{exchange.name} is open. It’s on everyone’s home page so they can join.'
    )
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


@require_GET
@login_required
def exchange_detail(request, exchange_id):
    exchange = get_object_or_404(Exchange.objects.select_related('organizer'), id=exchange_id)
    participants = sorted(
        exchange.participants.select_related('giver'),
        key=lambda p: display_name(p.giver).lower(),
    )
    mine = next((p for p in participants if p.giver_id == request.user.id), None)
    shoulder = is_over_the_shoulder(request)
    stale = needs_redraw(exchange, participants)
    kind = exchange.kind_info

    reveal = None
    if mine and exchange.is_drawn and mine.receiver_id and not shoulder:
        receiver = mine.receiver
        # Only a letter written for this receiver; a stale one never shows
        letter = ExchangeLetter.objects.filter(
            exchange=exchange, author=request.user, receiver=receiver
        ).first()
        reveal = {
            'entry': mine,
            'name': display_name(receiver),
            'first_name': receiver.first_name or receiver.username,
            'lists': list(lists_for(receiver)) if kind.shows_lists else [],
            # Names the shuffle animation flicks through before landing
            'decoys': [display_name(p.giver) for p in participants if p.giver_id != request.user.id],
            'letter': letter,
            'can_write': exchange.is_active and not exchange.letters_delivered,
        }

    received_letters = []
    if exchange.letters_delivered:
        received_letters = list(
            exchange.letters.filter(receiver=request.user).select_related('author')
        )

    manager = can_manage(request.user, exchange)
    manage = {}
    if manager:
        letters = list(exchange.letters.all()) if exchange.is_drawn else []
        written = len(letters)
        manage = {
            'addable': list(addable_people(exchange))
            if exchange.is_active and not exchange.letters_delivered
            else [],
            # Counts, never names: who has written is the giver's business
            'letters_written': written,
            'letters_read': sum(1 for letter in letters if letter.read_at),
            'without_letter': max(0, len(participants) - written),
            'small_draw': len(participants) == SMALL_DRAW,
            'step': (
                'wrapped' if not exchange.is_active
                else 'delivered' if exchange.letters_delivered
                else 'drawn' if exchange.is_drawn
                else 'joining'
            ),
        }
    return render(
        request,
        'gift/exchange_detail.html',
        {
            'exchange': exchange,
            'participants': participants,
            'ring': ring_layout(participants),
            'ring_size': RING_SIZE,
            'opened_count': sum(1 for p in participants if p.reveal_seen_at),
            'mine': mine,
            'reveal': reveal,
            'stale': stale,
            'over_the_shoulder': shoulder,
            'can_manage': manager,
            'can_draw': manager and len(participants) >= MIN_PARTICIPANTS,
            'min_participants': MIN_PARTICIPANTS,
            'form': ExchangeForm(instance=exchange) if manager else None,
            'kind': kind,
            'received_letters': received_letters,
            'manage': manage,
            'letter_max': ExchangeLetter.MAX_LENGTH,
        },
    )


def _locked(request, exchange):
    """Joining and leaving stop once names are drawn — the organizer can still
    add or remove people, which only changes one pick."""
    if not exchange.is_active:
        messages.error(request, 'This exchange has wrapped up.')
        return True
    if exchange.is_drawn:
        organizer = display_name(exchange.organizer) if exchange.organizer else 'the organizer'
        messages.error(
            request, f'Names have already been drawn — ask {organizer} to add or remove you.'
        )
        return True
    return False


@require_POST
@login_required
def exchange_join(request, exchange_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if not _locked(request, exchange):
        ExchangeParticipant.objects.get_or_create(exchange=exchange, giver=request.user)
        messages.success(request, f"You're in {exchange.name}! {exchange.display_icon}")
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


@require_POST
@login_required
def exchange_leave(request, exchange_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if not _locked(request, exchange):
        ExchangeParticipant.objects.filter(exchange=exchange, giver=request.user).delete()
        messages.info(request, f"You've left {exchange.name}.")
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


@require_POST
@login_required
def exchange_decline(request, exchange_id):
    """"Not this time": hide the home-page invite for this session."""
    declined = set(request.session.get(DECLINED_SESSION_KEY, []))
    declined.add(int(exchange_id))
    request.session[DECLINED_SESSION_KEY] = sorted(declined)
    return redirect('gift:home')


def _manage_or_refuse(request, exchange):
    if can_manage(request.user, exchange):
        return True
    messages.error(request, 'Only the organizer can do that.')
    return False


@require_POST
@login_required
def exchange_edit(request, exchange_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if _manage_or_refuse(request, exchange):
        form = ExchangeForm(request.POST, instance=exchange)
        if form.is_valid():
            form.save()
            messages.success(request, 'Saved.')
        else:
            messages.error(request, first_error(form))
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


def _roster_locked(request, exchange):
    """The organizer can still change who's in after the draw, but not once
    it's wrapped up or letters are out."""
    if not exchange.is_active:
        messages.error(request, 'This exchange has wrapped up.')
        return True
    if exchange.letters_delivered:
        messages.error(request, 'Letters have been delivered, so the draw is final.')
        return True
    return False


@require_POST
@login_required
def exchange_add(request, exchange_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if _manage_or_refuse(request, exchange) and not _roster_locked(request, exchange):
        user_id = request.POST.get('user_id', '')
        person = addable_people(exchange).filter(id=user_id).first() if user_id.isdigit() else None
        if person is None:
            messages.error(request, 'Choose someone who can sign in and isn’t in yet.')
        else:
            add_person(exchange, person)
            if exchange.is_drawn:
                messages.success(
                    request,
                    f'Added {display_name(person)} and fitted them into the draw. One '
                    'person’s pick changed to make room; they’ll see a new one waiting.',
                )
            else:
                messages.success(request, f'Added {display_name(person)}.')
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


@require_POST
@login_required
def exchange_remove(request, exchange_id, participant_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if _manage_or_refuse(request, exchange) and not _roster_locked(request, exchange):
        entry = (
            ExchangeParticipant.objects.filter(exchange=exchange, id=participant_id)
            .select_related('giver')
            .first()
        )
        if entry is not None:
            name = display_name(entry.giver)
            remove_person(exchange, entry)
            if exchange.is_drawn:
                messages.success(
                    request,
                    f'Removed {name}. Whoever had drawn them has a new pick waiting; '
                    'everyone else keeps theirs.',
                )
            else:
                messages.success(request, f'Removed {name}.')
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


@require_POST
@login_required
def exchange_draw(request, exchange_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if not _manage_or_refuse(request, exchange):
        return redirect('gift:exchange_detail', exchange_id=exchange.id)
    if not exchange.is_active:
        messages.error(request, 'This exchange has wrapped up.')
    elif exchange.is_drawn and request.POST.get('redraw') != '1':
        messages.error(request, 'Names are already drawn.')
    else:
        try:
            draw_names(exchange)
        except DrawError as error:
            messages.error(request, str(error))
        else:
            # Deliberately says nothing about who drew whom
            messages.success(request, 'Names are drawn. Everyone finds theirs on the home page.')
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


@require_POST
@login_required
def exchange_wrap_up(request, exchange_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if _manage_or_refuse(request, exchange):
        exchange.is_active = request.POST.get('reopen') == '1'
        exchange.save(update_fields=['is_active'])
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


def _mark_opened(request, exchange_id):
    ExchangeParticipant.objects.filter(
        exchange_id=exchange_id,
        giver=request.user,
        receiver__isnull=False,
        reveal_seen_at__isnull=True,
    ).update(reveal_seen_at=timezone.now())


@require_POST
@login_required
def exchange_reveal_seen(request, exchange_id):
    """The giver has opened theirs: stop showing it on the home page. The
    unwrap animation calls this in the background; the button is for no-JS."""
    if not is_over_the_shoulder(request):
        _mark_opened(request, exchange_id)
    if request.headers.get('X-Requested-With') == 'fetch':
        return HttpResponse(status=204)
    return redirect(detail_url(exchange_id, 'reveal'))


@require_POST
@login_required
def exchange_letter(request, exchange_id):
    """Write, rewrite or (with nothing in it) take back your letter."""
    exchange = get_object_or_404(Exchange, id=exchange_id)
    entry = ExchangeParticipant.objects.filter(
        exchange=exchange, giver=request.user, receiver__isnull=False
    ).first()
    back = detail_url(exchange.id, 'reveal')
    if entry is None or is_over_the_shoulder(request):
        return redirect('gift:exchange_detail', exchange_id=exchange.id)
    if not exchange.is_active:
        messages.error(request, 'This exchange has wrapped up.')
        return redirect(back)
    if exchange.letters_delivered:
        messages.error(request, 'Letters have already been delivered.')
        return redirect(back)

    letter = ExchangeLetter.objects.filter(exchange=exchange, author=request.user).first()
    old_image = letter.image.name if letter and letter.image else None
    form = ExchangeLetterForm(request.POST, request.FILES, instance=letter)
    if not form.is_valid():
        # The page keeps a draft in the browser, so nothing typed is lost
        messages.error(request, first_error(form))
        return redirect(back)

    # Writing to them means you've seen who they are
    _mark_opened(request, exchange.id)
    if form.is_empty:
        if letter:
            delete_letters([letter])
            messages.info(request, 'Your letter is cleared.')
        return redirect(back)

    letter = form.save(commit=False)
    letter.exchange = exchange
    letter.author = request.user
    letter.receiver_id = entry.receiver_id
    letter.save()
    if old_image and old_image != (letter.image.name if letter.image else None):
        letter.image.storage.delete(old_image)
    organizer = display_name(exchange.organizer) if exchange.organizer else 'the organizer'
    messages.success(request, f'Saved. Only you can see it until {organizer} delivers the letters.')
    return redirect(back)


@require_GET
@login_required
def exchange_letter_image(request, exchange_id, letter_id):
    """A letter's photo, to the people who may read the letter — never a
    public link."""
    letter = get_object_or_404(
        ExchangeLetter.objects.select_related('exchange'), id=letter_id, exchange_id=exchange_id
    )
    if not letter.image or not can_see_letter(request.user, letter, letter.exchange):
        return not_found()
    response = FileResponse(letter.image.open('rb'), content_type='image/jpeg')
    response['Cache-Control'] = 'private, max-age=3600'
    return response


@require_POST
@login_required
def exchange_letter_read(request, exchange_id, letter_id):
    """The reader says thank you — and, if they like, shares it on the board."""
    share = request.POST.get('share') == '1'
    ExchangeLetter.objects.filter(
        id=letter_id,
        exchange_id=exchange_id,
        receiver=request.user,
        exchange__letters_delivered_at__isnull=False,
        read_at__isnull=True,
    ).update(read_at=timezone.now(), shared_by_receiver=share)
    return redirect(detail_url(exchange_id, 'letters'))


@require_POST
@login_required
def exchange_letter_privacy(request, exchange_id, letter_id):
    """The reader puts a letter on (or takes it off) the board."""
    ExchangeLetter.objects.filter(
        id=letter_id,
        exchange_id=exchange_id,
        receiver=request.user,
        read_at__isnull=False,
    ).update(shared_by_receiver=request.POST.get('share') == '1')
    return redirect(detail_url(exchange_id, 'letters'))


@require_GET
@login_required
def exchange_board(request, exchange_id):
    """Every delivered letter that both its writer and its reader chose to
    share, for the people in the exchange."""
    exchange = get_object_or_404(Exchange.objects.select_related('organizer'), id=exchange_id)
    member = exchange.participants.filter(giver=request.user).exists()
    if not (exchange.board_enabled and exchange.letters_delivered) or not (
        member or can_manage(request.user, exchange)
    ):
        return not_found()
    shoulder = is_over_the_shoulder(request)
    letters = []
    if not shoulder:
        letters = [
            letter
            for letter in exchange.letters.select_related('author', 'receiver').order_by(
                'receiver__first_name', 'receiver__username'
            )
            if on_board(letter, exchange)
        ]
    return render(
        request,
        'gift/exchange_board.html',
        {
            'exchange': exchange,
            'kind': exchange.kind_info,
            'letters': letters,
            'over_the_shoulder': shoulder,
        },
    )


@require_POST
@login_required
def exchange_deliver(request, exchange_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if _manage_or_refuse(request, exchange) and not exchange.letters_delivered:
        try:
            deliver_letters(exchange)
        except DrawError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, 'Letters delivered! 💌 Everyone finds theirs on the home page.')
    return redirect('gift:exchange_detail', exchange_id=exchange.id)
