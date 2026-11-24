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

from gift.exchange import DrawError, deliver_letters, draw_names
from gift.models import Exchange, ExchangeLetter, ExchangeParticipant, WishList

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


def assert_one_loop(gives_to):
    start = next(iter(gives_to))
    seen, current = set(), start
    while current not in seen:
        seen.add(current)
        current = gives_to[current]
    assert current == start and seen == set(gives_to)


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
        assert 'See your pick' in home

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


class TestOrganizerAdds:
    def add(self, client, exchange, person):
        return client.post(url('exchange_add', exchange), {'user_id': person.id})

    def test_organizer_adds_someone(self, exchange, people, other_user):
        self.add(signed_in(people[0]), exchange, other_user)
        assert exchange.participants.filter(giver=other_user).exists()

    def test_nobody_else_can(self, exchange, people, other_user):
        self.add(signed_in(people[1]), exchange, other_user)
        assert not exchange.participants.filter(giver=other_user).exists()

    def test_a_get_adds_nobody(self, exchange, people, other_user):
        response = signed_in(people[0]).get(url('exchange_add', exchange), {'user_id': other_user.id})
        assert response.status_code == 405
        assert not exchange.participants.filter(giver=other_user).exists()

    def test_only_people_who_can_sign_in(self, exchange, people):
        no_login = User.objects.create_user(username='baby', email='', password='x')
        self.add(signed_in(people[0]), exchange, no_login)
        assert not exchange.participants.filter(giver=no_login).exists()
        response = signed_in(people[0]).post(url('exchange_add', exchange), {'user_id': 'nope'})
        assert response.status_code == 302

    def test_after_the_draw_they_are_fitted_in_and_one_pick_changes(self, exchange, people, other_user):
        exchange = draw_names(exchange)
        ExchangeParticipant.objects.filter(exchange=exchange).update(reveal_seen_at='2026-11-20T00:00Z')
        before = {e.giver_id: e.receiver_id for e in exchange.participants.all()}
        self.add(signed_in(people[0]), exchange, other_user)

        after = {e.giver_id: e.receiver_id for e in exchange.participants.all()}
        assert_one_loop(after)
        changed = [g for g in before if before[g] != after[g]]
        assert len(changed) == 1
        moved = ExchangeParticipant.objects.get(exchange=exchange, giver=changed[0])
        assert moved.pick_changed and moved.reveal_seen_at is None
        assert ExchangeParticipant.objects.filter(exchange=exchange, reveal_seen_at__isnull=False).count() == 4
        page = signed_in(people[0]).get(url('exchange_detail', exchange))
        assert not page.context['stale']

    def test_removing_after_the_draw_closes_the_loop(self, exchange, people):
        exchange = draw_names(exchange)
        leaving = people[2]
        giver = ExchangeParticipant.objects.get(exchange=exchange, receiver=leaving)
        inherits = receiver_of(exchange, leaving)
        write(signed_in(giver.giver), exchange, 'for someone leaving')
        write(signed_in(leaving), exchange, 'from someone leaving')
        entry = ExchangeParticipant.objects.get(exchange=exchange, giver=leaving)

        signed_in(people[0]).post(url('exchange_remove', exchange, entry.id))
        after = {e.giver_id: e.receiver_id for e in exchange.participants.all()}
        assert_one_loop(after)
        assert receiver_of(exchange, giver.giver) == inherits
        assert not ExchangeLetter.objects.exists()

    def test_not_once_letters_are_delivered(self, exchange, people, other_user):
        deliver_letters(draw_names(exchange))
        self.add(signed_in(people[0]), exchange, other_user)
        assert not exchange.participants.filter(giver=other_user).exists()


@pytest.fixture
def drawn(exchange):
    return draw_names(exchange)


def write(client, exchange, body):
    return client.post(url('exchange_letter', exchange), {'body': body})


class TestLetters:
    BODY = 'I love how you always save me the last slice of pie.'

    def test_writer_saves_and_sees_their_letter(self, drawn, people):
        client = signed_in(people[1])
        write(client, drawn, self.BODY)
        letter = ExchangeLetter.objects.get()
        assert letter.author == people[1]
        assert letter.receiver == receiver_of(drawn, people[1])
        assert self.BODY in client.get(url('exchange_detail', drawn)).content.decode()

    def test_receiver_sees_nothing_until_delivered(self, drawn, people):
        write(signed_in(people[1]), drawn, self.BODY)
        receiver = signed_in(receiver_of(drawn, people[1]))
        assert self.BODY not in receiver.get(url('exchange_detail', drawn)).content.decode()
        assert 'A letter for you' not in receiver.get('/').content.decode()

        signed_in(people[0]).post(url('exchange_deliver', drawn))
        assert self.BODY in receiver.get(url('exchange_detail', drawn)).content.decode()
        home = receiver.get('/').content.decode()
        assert 'A note with your gift is waiting' in home
        assert 'Ben' not in home.split('wl-exchange-banner', 1)[1].split('</a>', 1)[0]

    def test_reading_it_clears_the_home_card(self, drawn, people):
        write(signed_in(people[1]), drawn, self.BODY)
        deliver_letters(drawn)
        receiver = signed_in(receiver_of(drawn, people[1]))
        letter = ExchangeLetter.objects.get()
        receiver.post(url('exchange_letter_read', drawn, letter.id))
        assert 'A letter for you' not in receiver.get('/').content.decode()

    def test_organizer_and_others_never_see_it(self, drawn, people, other_user):
        writer = people[1]
        write(signed_in(writer), drawn, self.BODY)
        deliver_letters(drawn)
        receiver = receiver_of(drawn, writer)
        for person in [people[0], other_user, *people]:
            if person in (writer, receiver):
                continue
            page = signed_in(person).get(url('exchange_detail', drawn)).content.decode()
            assert self.BODY not in page

    def test_redraw_throws_away_undelivered_letters(self, drawn, people):
        write(signed_in(people[1]), drawn, self.BODY)
        draw_names(drawn)
        assert not ExchangeLetter.objects.exists()

    def test_the_draw_is_final_once_delivered(self, drawn, people):
        before = {e.giver_id: e.receiver_id for e in drawn.participants.all()}
        deliver_letters(drawn)
        with pytest.raises(DrawError):
            draw_names(drawn)
        signed_in(people[0]).post(url('exchange_draw', drawn), {'redraw': '1'})
        assert {e.giver_id: e.receiver_id for e in drawn.participants.all()} == before

    def test_no_editing_after_delivery(self, drawn, people):
        client = signed_in(people[1])
        write(client, drawn, self.BODY)
        deliver_letters(drawn)
        write(client, drawn, 'changed my mind')
        assert ExchangeLetter.objects.get().body == self.BODY

    def test_blank_takes_it_back(self, drawn, people):
        client = signed_in(people[1])
        write(client, drawn, self.BODY)
        write(client, drawn, '   ')
        assert not ExchangeLetter.objects.exists()

    def test_not_over_the_shoulder(self, drawn, people):
        client = signed_in(people[1])
        client.post('/over-the-shoulder/', {'on': '1'})
        write(client, drawn, self.BODY)
        assert not ExchangeLetter.objects.exists()

    def test_only_the_organizer_delivers(self, drawn, people):
        signed_in(people[1]).post(url('exchange_deliver', drawn))
        assert not Exchange.objects.get(pk=drawn.pk).letters_delivered

    def test_letters_are_escaped(self, drawn, people):
        write(signed_in(people[1]), drawn, '<script>alert(1)</script>')
        deliver_letters(drawn)
        page = signed_in(receiver_of(drawn, people[1])).get(url('exchange_detail', drawn))
        assert '<script>alert(1)</script>' not in page.content.decode()

    def test_too_long_is_refused(self, drawn, people):
        write(signed_in(people[1]), drawn, 'x' * (ExchangeLetter.MAX_LENGTH + 1))
        assert not ExchangeLetter.objects.exists()


class TestKinds:
    def test_switching_kind_after_the_draw_keeps_pairings(self, drawn, people):
        before = {e.giver_id: e.receiver_id for e in drawn.participants.all()}
        signed_in(people[0]).post(
            url('exchange_edit', drawn), {'name': 'Thankfulness', 'kind': 'thanks', 'icon': '🦃'}
        )
        exchange = Exchange.objects.get(pk=drawn.pk)
        assert (exchange.kind, exchange.display_icon) == ('thanks', '🦃')
        assert {e.giver_id: e.receiver_id for e in exchange.participants.all()} == before

    def test_letter_kinds_use_an_envelope_and_their_own_words(self, drawn, people):
        Exchange.objects.filter(pk=drawn.pk).update(kind='thanks')
        page = signed_in(people[1]).get(url('exchange_detail', drawn)).content.decode()
        assert 'wl-reveal-envelope' in page and 'wl-reveal-gift' not in page
        assert 'writing to' in page
        assert '💌' in page

    def test_icon_defaults_to_the_kind(self, people):
        exchange = Exchange.objects.create(name='Be kind', kind='kindness', organizer=people[0])
        assert exchange.display_icon == '💛'

    def test_unknown_icons_are_refused(self, exchange, people):
        signed_in(people[0]).post(
            url('exchange_edit', exchange), {'name': 'X', 'kind': 'gift', 'icon': '<b>'}
        )
        assert Exchange.objects.get(pk=exchange.pk).icon == ''


def photo(name='letter.jpg', size=(3000, 1500), gps=True):
    """A phone-sized JPEG, with a GPS tag the upload must not keep."""
    from io import BytesIO

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    image = Image.new('RGB', size, (200, 180, 150))
    exif = Image.Exif()
    if gps:
        exif[0x8825] = {1: 'N', 2: (38.0, 53.0, 0.0)}
    out = BytesIO()
    image.save(out, format='JPEG', exif=exif)
    return SimpleUploadedFile(name, out.getvalue(), content_type='image/jpeg')


@pytest.fixture
def media(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


class TestLetterPhotos:
    def upload(self, client, exchange, **fields):
        return client.post(url('exchange_letter', exchange), fields)

    def test_a_photo_alone_is_a_letter_shrunk_and_stripped(self, drawn, people, media):
        from PIL import Image

        self.upload(signed_in(people[1]), drawn, body='', image=photo())
        letter = ExchangeLetter.objects.get()
        with Image.open(letter.image.path) as stored:
            assert max(stored.size) == 2000
            assert 0x8825 not in stored.getexif()
        assert 'exchange-letters/' in letter.image.name
        assert 'ben' not in letter.image.name.lower()

    def test_not_an_image_is_refused(self, drawn, people, media):
        from django.core.files.uploadedfile import SimpleUploadedFile

        bogus = SimpleUploadedFile('x.jpg', b'not really', content_type='image/jpeg')
        self.upload(signed_in(people[1]), drawn, body='hi', image=bogus)
        assert not ExchangeLetter.objects.exists()

    def test_only_the_right_people_see_the_photo(self, drawn, people, other_user, media):
        writer = people[1]
        self.upload(signed_in(writer), drawn, body='hi', image=photo())
        letter = ExchangeLetter.objects.get()
        photo_url = url('exchange_letter_image', drawn, letter.id)
        receiver = receiver_of(drawn, writer)
        bystander = next(p for p in people if p not in (writer, receiver))

        assert signed_in(writer).get(photo_url).status_code == 200
        assert signed_in(receiver).get(photo_url).status_code == 404  # not delivered yet
        deliver_letters(drawn)
        assert signed_in(receiver).get(photo_url).status_code == 200
        assert signed_in(bystander).get(photo_url).status_code == 404
        assert signed_in(other_user).get(photo_url).status_code == 404
        assert Client().get(photo_url).status_code == 302

    def test_replacing_or_removing_deletes_the_old_file(self, drawn, people, media):
        client = signed_in(people[1])
        self.upload(client, drawn, body='hi', image=photo())
        first = ExchangeLetter.objects.get().image.path
        self.upload(client, drawn, body='hi', image=photo(gps=False))
        second = ExchangeLetter.objects.get().image.path
        assert first != second
        assert not __import__('os').path.exists(first)
        self.upload(client, drawn, body='hi', remove_image='on')
        assert not ExchangeLetter.objects.get().image
        assert not __import__('os').path.exists(second)

    def test_redraw_deletes_photos_too(
        self, drawn, people, media, django_capture_on_commit_callbacks
    ):
        self.upload(signed_in(people[1]), drawn, body='', image=photo())
        path = ExchangeLetter.objects.get().image.path
        with django_capture_on_commit_callbacks(execute=True):
            draw_names(drawn)
        assert not __import__('os').path.exists(path)


class TestBoard:
    @pytest.fixture
    def delivered(self, drawn, people):
        Exchange.objects.filter(pk=drawn.pk).update(board_enabled=True)
        for person, text in [(people[1], 'Shared one'), (people[2], 'Private one')]:
            signed_in(person).post(
                url('exchange_letter', drawn),
                {'body': text, **({'shareable': 'on'} if text == 'Shared one' else {})},
            )
        exchange = Exchange.objects.get(pk=drawn.pk)
        deliver_letters(exchange)
        for letter in ExchangeLetter.objects.all():
            signed_in(letter.receiver).post(
                url('exchange_letter_read', exchange, letter.id), {'share': '1'}
            )
        return exchange

    def test_shows_only_letters_both_sides_agreed_to(self, delivered, people):
        page = signed_in(people[3]).get(url('exchange_board', delivered)).content.decode()
        assert 'Shared one' in page
        assert 'Private one' not in page

    def test_the_receiver_can_take_it_down(self, delivered, people):
        letter = ExchangeLetter.objects.get(body='Shared one')
        signed_in(letter.receiver).post(
            url('exchange_letter_privacy', delivered, letter.id), {'share': '0'}
        )
        page = signed_in(people[3]).get(url('exchange_board', delivered)).content.decode()
        assert 'Shared one' not in page

    def test_nobody_else_can_take_it_down(self, delivered, people):
        letter = ExchangeLetter.objects.get(body='Shared one')
        bystander = next(p for p in people if p not in (letter.author, letter.receiver))
        signed_in(bystander).post(
            url('exchange_letter_privacy', delivered, letter.id), {'share': '0'}
        )
        assert ExchangeLetter.objects.get(pk=letter.pk).shared_by_receiver

    def test_not_before_delivery_not_when_off_not_for_outsiders(self, drawn, people, other_user):
        assert signed_in(people[1]).get(url('exchange_board', drawn)).status_code == 404
        deliver_letters(drawn)
        assert signed_in(people[1]).get(url('exchange_board', drawn)).status_code == 404
        Exchange.objects.filter(pk=drawn.pk).update(board_enabled=True)
        assert signed_in(people[1]).get(url('exchange_board', drawn)).status_code == 200
        assert signed_in(other_user).get(url('exchange_board', drawn)).status_code == 404

    def test_board_photos_are_visible_to_members(self, drawn, people, media):
        Exchange.objects.filter(pk=drawn.pk).update(board_enabled=True)
        signed_in(people[1]).post(
            url('exchange_letter', drawn), {'body': '', 'image': photo(), 'shareable': 'on'}
        )
        letter = ExchangeLetter.objects.get()
        deliver_letters(Exchange.objects.get(pk=drawn.pk))
        signed_in(letter.receiver).post(url('exchange_letter_read', drawn, letter.id), {'share': '1'})
        bystander = next(p for p in people if p not in (letter.author, letter.receiver))
        assert signed_in(bystander).get(url('exchange_letter_image', drawn, letter.id)).status_code == 200


class TestReviewFixes:
    def test_delivery_refused_while_the_draw_is_broken(self, drawn, people):
        # An account vanishing leaves someone without a giver
        ExchangeParticipant.objects.filter(exchange=drawn, giver=people[4]).update(receiver=None)
        signed_in(people[0]).post(url('exchange_deliver', drawn))
        assert not Exchange.objects.get(pk=drawn.pk).letters_delivered

    def test_delivery_refused_once_wrapped_up(self, drawn, people):
        Exchange.objects.filter(pk=drawn.pk).update(is_active=False)
        signed_in(people[0]).post(url('exchange_deliver', drawn))
        assert not Exchange.objects.get(pk=drawn.pk).letters_delivered

    def test_a_redraw_tells_people_their_pick_changed(self, drawn, people):
        client = signed_in(people[1])
        client.post(url('exchange_reveal_seen', drawn))
        draw_names(drawn)
        assert 'Your pick for The Great Duke Swap has changed' in client.get('/').content.decode()

    def test_the_first_draw_is_not_called_a_change(self, drawn, people):
        assert 'has changed' not in signed_in(people[1]).get('/').content.decode()

    def test_the_board_waits_for_the_reader(self, drawn, people):
        Exchange.objects.filter(pk=drawn.pk).update(board_enabled=True)
        write_shared = {'body': 'Shared one', 'shareable': 'on'}
        signed_in(people[1]).post(url('exchange_letter', drawn), write_shared)
        deliver_letters(Exchange.objects.get(pk=drawn.pk))
        board = url('exchange_board', drawn)
        assert 'Shared one' not in signed_in(people[3]).get(board).content.decode()
        letter = ExchangeLetter.objects.get()
        signed_in(letter.receiver).post(url('exchange_letter_read', drawn, letter.id))
        assert 'Shared one' not in signed_in(people[3]).get(board).content.decode()

    def test_board_hidden_over_the_shoulder(self, drawn, people):
        Exchange.objects.filter(pk=drawn.pk).update(board_enabled=True)
        deliver_letters(Exchange.objects.get(pk=drawn.pk))
        client = signed_in(people[1])
        client.post('/over-the-shoulder/', {'on': '1'})
        assert 'hidden while you' in client.get(url('exchange_board', drawn)).content.decode()

    def test_received_letters_hidden_over_the_shoulder(self, drawn, people):
        write(signed_in(people[1]), drawn, 'a private note')
        deliver_letters(drawn)
        client = signed_in(receiver_of(drawn, people[1]))
        client.post('/over-the-shoulder/', {'on': '1'})
        assert 'is waiting' not in client.get('/').content.decode()
        assert 'a private note' not in client.get(url('exchange_detail', drawn)).content.decode()

    def test_line_breaks_count_once(self, drawn, people):
        body = ('x' * 99 + '\r\n') * 40  # 4,000 characters as the browser counts them
        write(signed_in(people[1]), drawn, body)
        assert ExchangeLetter.objects.get().body == body.replace('\r\n', '\n').strip()

    def test_writing_a_letter_counts_as_opening(self, drawn, people):
        write(signed_in(people[1]), drawn, 'hello')
        assert ExchangeParticipant.objects.get(exchange=drawn, giver=people[1]).reveal_seen_at

    def test_not_this_time_hides_the_invite(self, exchange, other_user):
        client = signed_in(other_user)
        assert 'is taking names' in client.get('/').content.decode()
        client.post(url('exchange_decline', exchange))
        assert 'is taking names' not in client.get('/').content.decode()

    def test_seen_in_the_background(self, drawn, people):
        response = signed_in(people[1]).post(
            url('exchange_reveal_seen', drawn), HTTP_X_REQUESTED_WITH='fetch'
        )
        assert response.status_code == 204

    def test_letter_kinds_do_not_label_wishlists(self, drawn, people):
        Exchange.objects.filter(pk=drawn.pk).update(kind='thanks')
        client = signed_in(people[1])
        client.post(url('exchange_reveal_seen', drawn))
        pick = receiver_of(drawn, people[1])
        WishList.objects.create(owner=pick, title='theirs')
        grouped = client.get('/?group_by=christmas_exchange').context['wishlists_grouped']
        assert not any(label.startswith('🎯') for label in grouped)

    def test_list_page_says_what_to_do(self, drawn, people):
        page = signed_in(people[1]).get(reverse('gift:exchange_list')).content.decode()
        assert 'Open yours' in page
