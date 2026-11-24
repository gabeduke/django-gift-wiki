"""Profile photos and 🎨 Decorate: making a list look like yours.

Photos are public on S3 (unsigned URLs), so what matters most here is what
gets stored: no GPS, a name that says nothing about whose photo it is, and no
file left behind when it's replaced or removed.
"""

import os
from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image

from gift.decor import LIST_EMOJI
from gift.models import WikiUser, WishList
from gift.themes import THEMES

pytestmark = pytest.mark.api

GPS = 0x8825
ORIENTATION = 0x0112


def photo(name='IMG_0001 Ellie at school.jpg', size=(1200, 900), orientation=None):
    """A phone-style JPEG carrying a GPS position the app must not keep."""
    image = Image.new('RGB', size, (200, 180, 150))
    exif = Image.Exif()
    exif[GPS] = {1: 'N', 2: (38.0, 53.0, 0.0)}
    if orientation:
        exif[ORIENTATION] = orientation
    out = BytesIO()
    image.save(out, format='JPEG', exif=exif)
    return SimpleUploadedFile(name, out.getvalue(), content_type='image/jpeg')


def not_a_photo():
    return SimpleUploadedFile('notes.jpg', b'definitely not a jpeg', content_type='image/jpeg')


@pytest.fixture
def media(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


@pytest.fixture
def kid(db):
    return WikiUser.objects.create_user(username='ellie', first_name='Ellie', last_name='Duke')


@pytest.fixture
def kids_list(wishlist, kid):
    wishlist.dependent = kid
    wishlist.save()
    return wishlist


def stored(field):
    with Image.open(field.path) as image:
        image.load()
        return image.size, image.getexif()


@pytest.mark.django_db
class TestProfilePhotoUpload:
    def post(self, client, **data):
        return client.post(reverse('gift:profile_picture'), data)

    def test_upload_stores_clean_square_copies(self, authenticated_user, user, media):
        response = self.post(authenticated_user, profile_picture=photo())

        assert response.status_code == 302
        user.refresh_from_db()
        sizes = {
            name: stored(getattr(user, name))
            for name in ('profile_picture', 'profile_picture_web', 'profile_picture_thumbnail')
        }
        assert sizes['profile_picture'][0] == (800, 800)
        assert sizes['profile_picture_web'][0] == (400, 400)
        assert sizes['profile_picture_thumbnail'][0] == (160, 160)
        for _size, exif in sizes.values():
            assert GPS not in exif

    def test_stored_names_say_nothing_about_the_person(self, authenticated_user, user, media):
        self.post(authenticated_user, profile_picture=photo())

        user.refresh_from_db()
        for name in (user.profile_picture.name, user.profile_picture_thumbnail.name):
            assert name.startswith('profile_pictures/')
            assert 'ellie' not in name.lower() and 'img_0001' not in name.lower()

    def test_a_sideways_phone_photo_is_turned_upright(self, authenticated_user, user, media):
        # Square either way, so the rotation itself is checked on covers below
        self.post(authenticated_user, profile_picture=photo(orientation=6))

        user.refresh_from_db()
        _size, exif = stored(user.profile_picture)
        assert ORIENTATION not in exif

    def test_not_a_photo_is_refused_with_a_message(self, authenticated_user, user, media):
        response = self.post(authenticated_user, profile_picture=not_a_photo())

        user.refresh_from_db()
        assert not user.profile_picture
        messages = [str(m) for m in response.wsgi_request._messages]
        assert any('isn’t a photo' in m for m in messages)

    def test_a_huge_file_is_refused(self, authenticated_user, user, media):
        with patch('gift.utils.PHOTO_MAX_BYTES', 10):
            self.post(authenticated_user, profile_picture=photo())

        user.refresh_from_db()
        assert not user.profile_picture

    def test_replacing_deletes_the_old_files(self, authenticated_user, user, media):
        self.post(authenticated_user, profile_picture=photo())
        user.refresh_from_db()
        old = [user.profile_picture.path, user.profile_picture_thumbnail.path]

        self.post(authenticated_user, profile_picture=photo())

        user.refresh_from_db()
        assert user.profile_picture.path not in old
        assert not any(os.path.exists(path) for path in old)

    def test_remove_clears_the_photo_and_its_files(self, authenticated_user, user, media):
        self.post(authenticated_user, profile_picture=photo())
        user.refresh_from_db()
        path = user.profile_picture.path

        self.post(authenticated_user, remove='1')

        user.refresh_from_db()
        assert not user.profile_picture and not user.profile_picture_thumbnail
        assert not os.path.exists(path)

    def test_admin_style_save_is_cleaned_too(self, user, media):
        """Anything assigned and saved, not just the form, loses its GPS."""
        user.profile_picture = photo()
        user.save()

        assert GPS not in stored(user.profile_picture)[1]

    def test_nothing_happens_with_the_flag_off(self, authenticated_user, user, media):
        with patch('giftwiki.feature_flags.get_profile_picture_enabled', return_value=False):
            self.post(authenticated_user, profile_picture=photo())

        user.refresh_from_db()
        assert not user.profile_picture

    def test_profile_pictures_are_on_by_default(self, db, monkeypatch):
        from giftwiki.feature_flags import get_profile_picture_enabled

        monkeypatch.delenv('PROFILE_PICTURE_ENABLED', raising=False)
        assert get_profile_picture_enabled()


@pytest.mark.django_db
class TestPhotoForSomeoneYouLookAfter:
    def test_a_keeper_can_set_the_kids_photo(self, authenticated_user, kids_list, kid, media):
        authenticated_user.post(
            reverse('gift:managed_user_picture', args=[kid.id]), {'profile_picture': photo()}
        )

        kid.refresh_from_db()
        assert kid.profile_picture

    def test_someone_else_cannot(self, authenticated_other_user, kids_list, kid, media):
        authenticated_other_user.post(
            reverse('gift:managed_user_picture', args=[kid.id]), {'profile_picture': photo()}
        )

        kid.refresh_from_db()
        assert not kid.profile_picture

    def test_the_edit_modal_offers_it(self, authenticated_user, kids_list, kid):
        html = authenticated_user.get(reverse('gift:account')).content.decode()

        assert reverse('gift:managed_user_picture', args=[kid.id]) in html


@pytest.mark.django_db
class TestAvatars:
    def give_photo(self, person):
        person.profile_picture = photo()
        person.save()

    def test_nav_shows_your_photo(self, authenticated_user, user, wishlist, media):
        self.give_photo(user)
        user.refresh_from_db()

        html = authenticated_user.get(reverse('gift:home')).content.decode()

        assert user.profile_picture_thumbnail.url in html

    def test_initials_without_a_photo(self, authenticated_user, user, wishlist):
        user.first_name, user.last_name = 'Pat', 'Lee'
        user.save()

        html = authenticated_user.get(reverse('gift:home')).content.decode()

        assert 'PL' in html
        assert 'wl-avatar-img' not in html

    def test_flag_off_hides_photos(self, authenticated_user, user, wishlist, media):
        self.give_photo(user)
        with patch('giftwiki.feature_flags.get_profile_picture_enabled', return_value=False):
            html = authenticated_user.get(reverse('gift:home')).content.decode()

        assert 'wl-avatar-img' not in html

    def test_a_kept_list_shows_the_kid_not_the_parent(
        self, authenticated_other_user, kids_list, kid
    ):
        html = authenticated_other_user.get(reverse('gift:home')).content.decode()

        row = html[html.index(f'href="/wishlist/{kids_list.id}/"') :]
        row = row[: row.index('</a>')]
        assert 'ED' in row  # Ellie Duke, not testuser's "TE"

    def test_list_page_shows_the_recipients_photo(self, authenticated_user, kids_list, kid, media):
        self.give_photo(kid)
        kid.refresh_from_db()

        html = authenticated_user.get(
            reverse('gift:wishlist_detail', args=[kids_list.id])
        ).content.decode()

        assert kid.profile_picture_thumbnail.url in html


@pytest.mark.django_db
class TestDecorate:
    def url(self, wishlist):
        return reverse('gift:decorate_wishlist', args=[wishlist.id])

    def test_the_list_page_offers_it_to_the_owner(self, authenticated_user, wishlist):
        html = authenticated_user.get(
            reverse('gift:wishlist_detail', args=[wishlist.id])
        ).content.decode()

        assert self.url(wishlist) in html

    def test_not_to_a_gift_giver(self, authenticated_other_user, wishlist):
        html = authenticated_other_user.get(
            reverse('gift:wishlist_detail', args=[wishlist.id])
        ).content.decode()

        assert self.url(wishlist) not in html

    def test_the_page_offers_every_emoji_and_colour(self, authenticated_user, wishlist):
        html = authenticated_user.get(self.url(wishlist)).content.decode()

        for emoji in LIST_EMOJI:
            assert emoji in html
        for key in THEMES:
            assert f'value="{key}"' in html

    def test_owner_can_pick_an_emoji_and_a_colour(self, authenticated_user, wishlist):
        response = authenticated_user.post(self.url(wishlist), {'emoji': '🦖', 'accent': 'plum'})

        assert response.status_code == 302
        wishlist.refresh_from_db()
        assert (wishlist.emoji, wishlist.accent) == ('🦖', 'plum')

    def test_the_kid_can_decorate_their_own_list(self, kids_list, kid):
        client = Client()
        client.force_login(kid)

        client.post(self.url(kids_list), {'emoji': '🦄', 'accent': 'lake'})

        kids_list.refresh_from_db()
        assert kids_list.emoji == '🦄'

    def test_a_gift_giver_cannot(self, authenticated_other_user, wishlist):
        authenticated_other_user.post(self.url(wishlist), {'emoji': '🦖', 'accent': 'plum'})

        wishlist.refresh_from_db()
        assert (wishlist.emoji, wishlist.accent) == ('', '')

    @pytest.mark.parametrize('field,value', [('emoji', '<b>'), ('accent', 'neon')])
    def test_only_the_offered_choices_are_kept(self, authenticated_user, wishlist, field, value):
        authenticated_user.post(self.url(wishlist), {field: value})

        wishlist.refresh_from_db()
        assert getattr(wishlist, field) == ''

    def test_cover_photo_is_cleaned_and_shrunk(self, authenticated_user, wishlist, media):
        authenticated_user.post(
            self.url(wishlist), {'emoji': '', 'accent': '', 'image': photo(size=(4000, 1000))}
        )

        wishlist.refresh_from_db()
        size, exif = stored(wishlist.image)
        assert size == (1600, 400)
        assert GPS not in exif
        assert wishlist.image.name.startswith('wishlist_images/')

    def test_sideways_cover_is_turned_upright(self, authenticated_user, wishlist, media):
        authenticated_user.post(
            self.url(wishlist), {'image': photo(size=(1200, 600), orientation=6)}
        )

        wishlist.refresh_from_db()
        assert stored(wishlist.image)[0] == (600, 1200)

    def test_saving_again_keeps_the_cover(self, authenticated_user, wishlist, media):
        authenticated_user.post(self.url(wishlist), {'image': photo()})
        wishlist.refresh_from_db()
        name = wishlist.image.name

        authenticated_user.post(self.url(wishlist), {'emoji': '🎸'})

        wishlist.refresh_from_db()
        assert wishlist.image.name == name

    def test_removing_the_cover_deletes_it(self, authenticated_user, wishlist, media):
        authenticated_user.post(self.url(wishlist), {'image': photo()})
        wishlist.refresh_from_db()
        path = wishlist.image.path

        authenticated_user.post(self.url(wishlist), {'remove_image': '1'})

        wishlist.refresh_from_db()
        assert not wishlist.image
        assert not os.path.exists(path)

    def test_not_a_photo_is_refused(self, authenticated_user, wishlist, media):
        response = authenticated_user.post(self.url(wishlist), {'image': not_a_photo()})

        assert response.status_code == 200
        assert 'isn’t a photo' in response.content.decode()
        wishlist.refresh_from_db()
        assert not wishlist.image


@pytest.mark.django_db
class TestADecoratedList:
    @pytest.fixture
    def decorated(self, wishlist, media):
        WishList.objects.filter(pk=wishlist.pk).update(emoji='🚀', accent='cranberry')
        wishlist.refresh_from_db()
        return wishlist

    def test_its_page_takes_its_colour(self, authenticated_other_user, decorated):
        html = authenticated_other_user.get(
            reverse('gift:wishlist_detail', args=[decorated.id])
        ).content.decode()

        assert '<div class="wl-page" data-theme="cranberry">' in html
        assert '🚀' in html

    def test_the_visitors_own_theme_stays_on_the_rest(
        self, authenticated_other_user, other_user, decorated
    ):
        other_user.color_palette = 'lake'
        other_user.save()

        html = authenticated_other_user.get(
            reverse('gift:wishlist_detail', args=[decorated.id])
        ).content.decode()

        assert '<html lang="en" data-theme="lake">' in html

    def test_home_shows_its_emoji(self, authenticated_other_user, decorated):
        html = authenticated_other_user.get(reverse('gift:home')).content.decode()

        assert 'wl-list-emoji' in html and '🚀' in html

    def test_my_lists_shows_its_cover(self, authenticated_user, decorated, media):
        decorated.image = photo()
        decorated.save()

        html = authenticated_user.get(reverse('gift:account')).content.decode()

        assert decorated.image.url in html


class TestDecorChoices:
    def test_every_emoji_fits_the_column(self):
        field = WishList._meta.get_field('emoji')
        assert all(len(emoji) <= field.max_length for emoji in LIST_EMOJI)
        assert len(set(LIST_EMOJI)) == len(LIST_EMOJI)

    def test_list_colours_are_the_themes(self):
        """So the theme tests' WCAG AA checks cover list colours too."""
        field = WishList._meta.get_field('accent')
        assert {key for key, _label in field.choices} == set(THEMES)
