"""Gift exchanges (#78): opt in, draw names, and find out privately.

The promise that matters is secrecy: a pairing is shown to its giver and
nobody else — not the organizer, not the roster, not a session that's over
the shoulder. The rest is the draw being a fair loop and the reveal showing
up until it's been opened.
"""

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from gift.exchange import DrawError, draw_names
from gift.models import Exchange, ExchangeParticipant, WishList

User = get_user_model()

pytestmark = pytest.mark.unit

NAMES = ['Ann', 'Ben', 'Cal', 'Dee', 'Eve']


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def people(db):
    return [
        User.objects.create_user(
            username=name.lower(), email=f'{name.lower()}@example.com', password='x', first_name=name
        )
        for name in NAMES
    ]


@pytest.fixture
def exchange(people):
    exchange = Exchange.objects.create(name='The Great Duke Swap', organizer=people[0])
    for person in people:
        ExchangeParticipant.objects.create(exchange=exchange, giver=person)
    return exchange


def receiver_of(exchange, person):
    return ExchangeParticipant.objects.get(exchange=exchange, giver=person).receiver


def url(name, exchange, *args):
    return reverse(f'gift:{name}', args=[exchange.id, *args])


class TestDraw:
    def test_everyone_gives_once_and_gets_once_and_never_to_themselves(self, exchange, people):
        for _ in range(20):
            draw_names(exchange)
            entries = list(exchange.participants.all())
            receivers = [e.receiver_id for e in entries]
            assert sorted(receivers) == sorted(p.id for p in people)
            assert all(e.receiver_id != e.giver_id for e in entries)

    def test_it_is_one_loop_so_no_two_people_simply_swap(self, exchange, people):
        for _ in range(20):
            draw_names(exchange)
            gives_to = {e.giver_id: e.receiver_id for e in exchange.participants.all()}
            start = people[0].id
            seen, current = set(), start
            while current not in seen:
                seen.add(current)
                current = gives_to[current]
            assert len(seen) == len(people)

    def test_needs_three_people(self, people):
        exchange = Exchange.objects.create(name='Tiny', organizer=people[0])
        for person in people[:2]:
            ExchangeParticipant.objects.create(exchange=exchange, giver=person)
        with pytest.raises(DrawError):
            draw_names(exchange)
        assert not Exchange.objects.get(pk=exchange.pk).is_drawn

    def test_drawing_again_seals_every_envelope(self, exchange, people):
        draw_names(exchange)
        exchange.participants.update(reveal_seen_at='2026-11-20T00:00Z')
        draw_names(exchange)
        assert not exchange.participants.filter(reveal_seen_at__isnull=False).exists()


class TestWhoCanDraw:
    def test_organizer_draws_with_a_post(self, exchange, people):
        signed_in(people[0]).post(url('exchange_draw', exchange))
        assert Exchange.objects.get(pk=exchange.pk).is_drawn

    def test_anyone_else_cannot(self, exchange, people):
        signed_in(people[1]).post(url('exchange_draw', exchange))
        assert not Exchange.objects.get(pk=exchange.pk).is_drawn

    def test_a_get_never_draws(self, exchange, people):
        response = signed_in(people[0]).get(url('exchange_draw', exchange))
        assert response.status_code == 405
        assert not Exchange.objects.get(pk=exchange.pk).is_drawn

    def test_drawing_twice_needs_an_explicit_redraw(self, exchange, people):
        organizer = signed_in(people[0])
        organizer.post(url('exchange_draw', exchange))
        before = {e.giver_id: e.receiver_id for e in exchange.participants.all()}
        drawn_at = Exchange.objects.get(pk=exchange.pk).drawn_at
        organizer.post(url('exchange_draw', exchange))
        assert Exchange.objects.get(pk=exchange.pk).drawn_at == drawn_at
        assert {e.giver_id: e.receiver_id for e in exchange.participants.all()} == before
        organizer.post(url('exchange_draw', exchange), {'redraw': '1'})
        assert Exchange.objects.get(pk=exchange.pk).drawn_at > drawn_at


class TestSecrecy:
    def test_the_organizer_sees_who_is_in_but_not_who_drew_whom(self, exchange, people):
        draw_names(exchange)
        organizer = people[0]
        mine = receiver_of(exchange, organizer)
        page = signed_in(organizer).get(url('exchange_detail', exchange)).content.decode()
        # Their own pick is on the page; nobody else's reveal markup is
        assert page.count('data-reveal-name') == 1
        assert f'>{mine.first_name}</p>' in page
        for person in people:
            assert person.first_name in page  # the roster

    def test_someone_not_in_the_exchange_sees_no_pick(self, exchange, people, other_user):
        draw_names(exchange)
        page = signed_in(other_user).get(url('exchange_detail', exchange)).content.decode()
        assert 'data-reveal-name' not in page

    def test_ring_is_in_alphabetical_order_not_draw_order(self, exchange, people):
        draw_names(exchange)
        response = signed_in(people[1]).get(url('exchange_detail', exchange))
        ring_names = [node['name'] for node in response.context['ring']]
        assert ring_names == sorted(NAMES)

    def test_draw_message_names_nobody(self, exchange, people):
        response = signed_in(people[0]).post(url('exchange_draw', exchange), follow=True)
        text = ' '.join(str(m) for m in response.context['messages'])
        assert 'Names are drawn' in text
        assert not any(re.search(rf'\b{name}\b', text) for name in NAMES)


class TestReveal:
    def test_home_shows_the_envelope_until_it_is_opened(self, exchange, people):
        draw_names(exchange)
        client = signed_in(people[2])
        assert 'Names are drawn for The Great Duke Swap!' in client.get('/').content.decode()

        # Looking at the page doesn't count as opening it
        client.get(url('exchange_detail', exchange))
        assert 'Names are drawn for The Great Duke Swap!' in client.get('/').content.decode()

        client.post(url('exchange_reveal_seen', exchange))
        home = client.get('/').content.decode()
        assert 'Names are drawn for' not in home
        assert "you're giving to" in home

    def test_nothing_shows_before_the_draw(self, exchange, people):
        home = signed_in(people[2]).get('/').content.decode()
        assert 'Names are drawn for' not in home

    def test_hidden_over_the_shoulder_and_cannot_be_dismissed_there(self, exchange, people):
        draw_names(exchange)
        mine = receiver_of(exchange, people[2])
        client = signed_in(people[2])
        client.post('/over-the-shoulder/', {'on': '1'})

        assert 'Names are drawn for' not in client.get('/').content.decode()
        page = client.get(url('exchange_detail', exchange)).content.decode()
        assert 'data-reveal-name' not in page
        assert 'hidden while you' in page

        client.post(url('exchange_reveal_seen', exchange))
        entry = ExchangeParticipant.objects.get(exchange=exchange, giver=people[2])
        assert entry.reveal_seen_at is None
        assert entry.receiver == mine

    def test_wrapped_up_exchanges_leave_the_home_page(self, exchange, people):
        draw_names(exchange)
        exchange.is_active = False
        exchange.save()
        assert 'Names are drawn for' not in signed_in(people[2]).get('/').content.decode()


class TestHomeGrouping:
    def test_your_pick_is_labelled_with_the_exchange_name_once_opened(self, exchange, people):
        draw_names(exchange)
        giver = people[3]
        pick = receiver_of(exchange, giver)
        WishList.objects.create(owner=pick, title=f"{pick.first_name}'s list")
        client = signed_in(giver)
        label = '🎯 Your The Great Duke Swap pick'

        before = client.get('/?group_by=christmas_exchange')
        assert label not in before.context['wishlists_grouped']

        client.post(url('exchange_reveal_seen', exchange))
        after = client.get('/?group_by=christmas_exchange')
        assert [wl.owner for wl in after.context['wishlists_grouped'][label]] == [pick]


class TestJoining:
    def test_join_and_leave_before_the_draw(self, exchange, other_user):
        client = signed_in(other_user)
        client.post(url('exchange_join', exchange))
        assert exchange.participants.filter(giver=other_user).exists()
        client.post(url('exchange_leave', exchange))
        assert not exchange.participants.filter(giver=other_user).exists()

    def test_locked_once_names_are_drawn(self, exchange, people, other_user):
        draw_names(exchange)
        signed_in(other_user).post(url('exchange_join', exchange))
        signed_in(people[1]).post(url('exchange_leave', exchange))
        assert not exchange.participants.filter(giver=other_user).exists()
        assert exchange.participants.filter(giver=people[1]).exists()

    def test_home_invites_people_who_have_not_joined(self, exchange, other_user, people):
        assert 'is taking names' in signed_in(other_user).get('/').content.decode()
        assert 'is taking names' not in signed_in(people[1]).get('/').content.decode()


class TestNaming:
    def test_create_with_any_name_and_the_organizer_is_in(self, user):
        client = signed_in(user)
        client.post(reverse('gift:exchange_create'), {'name': 'Yankee Swap Supreme'})
        exchange = Exchange.objects.get()
        assert exchange.name == 'Yankee Swap Supreme'
        assert exchange.organizer == user
        assert exchange.participants.filter(giver=user).exists()

    def test_organizer_can_rename_others_cannot(self, exchange, people):
        signed_in(people[1]).post(url('exchange_edit', exchange), {'name': 'Hijacked'})
        assert Exchange.objects.get(pk=exchange.pk).name == 'The Great Duke Swap'
        signed_in(people[0]).post(url('exchange_edit', exchange), {'name': 'Kringle Club'})
        assert Exchange.objects.get(pk=exchange.pk).name == 'Kringle Club'

    def test_pages_render(self, exchange, people):
        client = signed_in(people[0])
        assert client.get(reverse('gift:exchange_list')).status_code == 200
        page = client.get(url('exchange_detail', exchange)).content.decode()
        assert '{#' not in page and '#}' not in page
