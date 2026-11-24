"""Pages for gift exchanges (see gift/exchange.py for the rules).

Every state change is a POST. Pairings appear only on the giver's own
reveal, and never while the session is over the shoulder.
"""

import math

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .exchange import MIN_PARTICIPANTS, DrawError, can_manage, draw_names
from .forms import ExchangeForm
from .models import Exchange, ExchangeParticipant, WishList
from .visibility import is_over_the_shoulder

# The roster ring: an SVG circle of everyone in the exchange.
RING_SIZE = 320
RING_RADIUS = 120


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
    """
    centre = RING_SIZE / 2
    count = len(participants)
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
            }
        )
    return nodes


def lists_for(person):
    """The lists whose gifts are for `person`."""
    return WishList.objects.filter(
        Q(dependent=person) | Q(owner=person, dependent__isnull=True)
    ).order_by('-updated_at')


@require_GET
@login_required
def exchange_list(request):
    exchanges = Exchange.objects.select_related('organizer').prefetch_related('participants')
    joined = set(
        ExchangeParticipant.objects.filter(giver=request.user).values_list('exchange_id', flat=True)
    )
    for exchange in exchanges:
        exchange.joined = exchange.id in joined
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
        messages.error(request, 'Please give the exchange a name.')
        return redirect('gift:exchange_list')
    exchange = form.save(commit=False)
    exchange.organizer = request.user
    exchange.save()
    # The organizer is usually playing too; they can step out before the draw.
    ExchangeParticipant.objects.create(exchange=exchange, giver=request.user)
    messages.success(request, f'{exchange.name} is open — invite everyone to join!')
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

    reveal = None
    if mine and exchange.is_drawn and mine.receiver_id and not shoulder:
        receiver = mine.receiver
        reveal = {
            'entry': mine,
            'name': display_name(receiver),
            'first_name': receiver.first_name or receiver.username,
            'lists': list(lists_for(receiver)),
            # Names the shuffle animation flicks through before landing
            'decoys': [display_name(p.giver) for p in participants if p.giver_id != request.user.id],
        }

    manager = can_manage(request.user, exchange)
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
            'over_the_shoulder': shoulder,
            'can_manage': manager,
            'can_draw': manager and len(participants) >= MIN_PARTICIPANTS,
            'min_participants': MIN_PARTICIPANTS,
            'form': ExchangeForm(instance=exchange) if manager else None,
        },
    )


def _locked(request, exchange):
    """Joining and leaving stop once names are drawn — it would break the loop."""
    if exchange.is_drawn:
        messages.error(
            request, 'Names have already been drawn. Ask the organizer to draw again.'
        )
        return True
    if not exchange.is_active:
        messages.error(request, 'This exchange has wrapped up.')
        return True
    return False


@require_POST
@login_required
def exchange_join(request, exchange_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if not _locked(request, exchange):
        ExchangeParticipant.objects.get_or_create(exchange=exchange, giver=request.user)
        messages.success(request, f"You're in {exchange.name}! 🎁")
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


@require_POST
@login_required
def exchange_leave(request, exchange_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if not _locked(request, exchange):
        ExchangeParticipant.objects.filter(exchange=exchange, giver=request.user).delete()
        messages.info(request, f"You've left {exchange.name}.")
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


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
            messages.error(request, 'Please give the exchange a name.')
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


@require_POST
@login_required
def exchange_remove(request, exchange_id, participant_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if _manage_or_refuse(request, exchange) and not _locked(request, exchange):
        ExchangeParticipant.objects.filter(exchange=exchange, id=participant_id).delete()
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
            messages.success(
                request, 'Names are drawn! Everyone will see theirs next time they open the app.'
            )
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


@require_POST
@login_required
def exchange_wrap_up(request, exchange_id):
    exchange = get_object_or_404(Exchange, id=exchange_id)
    if _manage_or_refuse(request, exchange):
        exchange.is_active = request.POST.get('reopen') == '1'
        exchange.save(update_fields=['is_active'])
    return redirect('gift:exchange_detail', exchange_id=exchange.id)


@require_POST
@login_required
def exchange_reveal_seen(request, exchange_id):
    """The giver has opened their envelope: stop showing it on the home page."""
    if not is_over_the_shoulder(request):
        ExchangeParticipant.objects.filter(
            exchange_id=exchange_id,
            giver=request.user,
            receiver__isnull=False,
            reveal_seen_at__isnull=True,
        ).update(reveal_seen_at=timezone.now())
    return redirect('gift:exchange_detail', exchange_id=exchange_id)
