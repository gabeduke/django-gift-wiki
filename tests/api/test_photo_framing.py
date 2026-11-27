"""Framing a photo: the person drags and zooms it inside a frame before saving.

The browser never re-encodes anything. It sends the original file plus
crop_x / crop_y / crop_w / crop_h — the chosen box as fractions of the photo
*as shown* (upright) — and the server crops inside the usual clean-up. Those
four numbers come from a browser, so the other half of these tests is that
nonsense in them never costs anyone their upload.
"""

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image, ImageOps

from gift.forms import parse_crop_box
from gift.models import WikiUser

pytestmark = pytest.mark.api

GPS = 0x8825
ORIENTATION = 0x0112
RED, BLUE = (220, 30, 30), (30, 30, 220)
PICTURE_FIELDS = ('profile_picture', 'profile_picture_web', 'profile_picture_thumbnail')


def two_colours(size):
    """Left half red, right half blue: which part was kept shows in the result."""
    image = Image.new('RGB', size, RED)
    image.paste(BLUE, (size[0] // 2, 0, size[0], size[1]))
    return image


def as_upload(image, orientation=None):
    """`image` as a phone-style JPEG carrying a GPS position."""
    exif = Image.Exif()
    exif[GPS] = {1: 'N', 2: (38.0, 53.0, 0.0)}
    if orientation:
        exif[ORIENTATION] = orientation
    out = BytesIO()
    image.save(out, format='JPEG', quality=95, exif=exif)
    return SimpleUploadedFile('IMG_0001.jpg', out.getvalue(), content_type='image/jpeg')


def photo(size=(1200, 800)):
    return as_upload(two_colours(size))


def box(x, y, w, h):
    return {'crop_x': str(x), 'crop_y': str(y), 'crop_w': str(w), 'crop_h': str(h)}


def is_colour(pixel, colour):
    # JPEG is lossy: close is as good as it gets
    return all(abs(a - b) < 40 for a, b in zip(pixel, colour, strict=True))


def stored(field):
    with field.storage.open(field.name) as handle:
        image = Image.open(handle)
        image.load()
    return image


def stored_bytes(field):
    with field.storage.open(field.name) as handle:
        return handle.read()


def edges(image):
    """Pixels just inside the left and right edges, halfway down."""
    width, height = image.size
    return image.getpixel((2, height // 2)), image.getpixel((width - 3, height // 2))


@pytest.fixture
def media(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


MALFORMED = [
    {'crop_x': 'left', 'crop_y': '0', 'crop_w': '0.5', 'crop_h': '0.5'},
    {'crop_x': 'nan', 'crop_y': '0', 'crop_w': '0.5', 'crop_h': '0.5'},
    {'crop_x': '0', 'crop_y': '0', 'crop_w': 'inf', 'crop_h': '0.5'},
    {'crop_x': '0', 'crop_y': '-inf', 'crop_w': '0.5', 'crop_h': '0.5'},
    {'crop_x': '0', 'crop_y': '0', 'crop_w': '1e999', 'crop_h': '0.5'},
    {'crop_x': '0', 'crop_y': '0', 'crop_w': '', 'crop_h': '0.5'},
    {'crop_x': '\x00', 'crop_y': '0', 'crop_w': '0.5', 'crop_h': '0.5'},
    {'crop_x': '0', 'crop_y': '0', 'crop_w': '0', 'crop_h': '0.5'},
    {'crop_x': '0', 'crop_y': '0', 'crop_w': '0.5', 'crop_h': '-0.5'},
    {'crop_x': '0.2', 'crop_y': '0.2', 'crop_w': '-0.1', 'crop_h': '-0.1'},
    # Entirely off the photo
    {'crop_x': '1.5', 'crop_y': '0', 'crop_w': '0.5', 'crop_h': '0.5'},
    {'crop_x': '-2', 'crop_y': '0', 'crop_w': '0.5', 'crop_h': '0.5'},
    # One of the four missing
    {'crop_x': '0', 'crop_y': '0', 'crop_w': '0.5'},
]


class TestParseCropBox:
    def test_a_sensible_box_comes_back_as_it_was(self):
        assert parse_crop_box(['0.25', '0.5', '0.5', '0.25']) == (0.25, 0.5, 0.5, 0.25)

    def test_a_box_hanging_off_the_photo_is_trimmed_to_it(self):
        x, y, w, h = parse_crop_box(['-0.5', '0.75', '1', '1'])

        assert (x, y) == (0.0, 0.75)
        assert (w, h) == pytest.approx((0.5, 0.25))

    @pytest.mark.parametrize('values', MALFORMED)
    def test_nonsense_means_no_box(self, values):
        names = ('crop_x', 'crop_y', 'crop_w', 'crop_h')
        assert parse_crop_box([values.get(name) for name in names]) is None


@pytest.mark.django_db
class TestFramedProfilePicture:
    url = reverse('gift:profile_picture')

    def upload(self, client, user, **extra):
        response = client.post(self.url, {'profile_picture': photo(), **extra})
        assert response.status_code == 302
        user.refresh_from_db()
        return user

    def test_the_chosen_region_is_kept_and_made_square(self, authenticated_user, user, media):
        # 600x400 of the red half; the default centre square would straddle both
        user = self.upload(authenticated_user, user, **box(0, 0.25, 0.5, 0.5))

        sizes = [stored(getattr(user, name)).size for name in PICTURE_FIELDS]
        assert sizes == [(400, 400), (400, 400), (160, 160)]
        for name in PICTURE_FIELDS:
            left, right = edges(stored(getattr(user, name)))
            assert is_colour(left, RED) and is_colour(right, RED)

    def test_the_other_side_can_be_chosen_too(self, authenticated_user, user, media):
        user = self.upload(authenticated_user, user, **box(0.5, 0, 0.5, 1))

        left, right = edges(stored(user.profile_picture))
        assert is_colour(left, BLUE) and is_colour(right, BLUE)

    def test_without_a_box_it_is_the_centre_square(self, authenticated_user, user, media):
        user = self.upload(authenticated_user, user)

        image = stored(user.profile_picture)
        left, right = edges(image)
        assert image.size == (800, 800)
        assert is_colour(left, RED) and is_colour(right, BLUE)

    def test_the_whole_photo_as_a_box_is_the_same_as_no_box(self, authenticated_user, user, media):
        plain = stored_bytes(self.upload(authenticated_user, user).profile_picture)

        user = self.upload(authenticated_user, user, **box(0, 0, 1, 1))

        assert stored_bytes(user.profile_picture) == plain

    @pytest.mark.parametrize('values', MALFORMED)
    def test_nonsense_falls_back_to_the_default(self, authenticated_user, user, media, values):
        plain = [
            stored_bytes(getattr(self.upload(authenticated_user, user), n)) for n in PICTURE_FIELDS
        ]

        user = self.upload(authenticated_user, user, **values)

        assert [stored_bytes(getattr(user, name)) for name in PICTURE_FIELDS] == plain

    def test_a_sideways_photo_is_cropped_the_way_it_is_shown(self, authenticated_user, user, media):
        upright = two_colours((600, 1200))
        sideways = upright.transpose(Image.Transpose.ROTATE_90)
        upload = as_upload(sideways, orientation=6)
        # The file really is the upright photo lying on its side: blue on top
        # as stored, red on the left once a browser has turned it
        as_stored = Image.open(upload)
        assert is_colour(as_stored.getpixel((300, 20)), BLUE)
        assert ImageOps.exif_transpose(as_stored).size == (600, 1200)
        upload.seek(0)

        # Top-left of the upright photo: red. On the pixels as stored it would be blue.
        response = authenticated_user.post(
            self.url, {'profile_picture': upload, **box(0, 0, 0.5, 0.25)}
        )

        assert response.status_code == 302
        user.refresh_from_db()
        image = stored(user.profile_picture)
        left, right = edges(image)
        assert image.size == (300, 300)
        assert is_colour(left, RED) and is_colour(right, RED)

    def test_where_it_was_taken_is_still_removed(self, authenticated_user, user, media):
        user = self.upload(authenticated_user, user, **box(0.1, 0.1, 0.5, 0.5))

        for name in PICTURE_FIELDS:
            exif = stored(getattr(user, name)).getexif()
            assert GPS not in exif and ORIENTATION not in exif

    def test_a_box_without_a_photo_changes_nothing(self, authenticated_user, user, media):
        user = self.upload(authenticated_user, user)
        name, before = user.profile_picture.name, stored_bytes(user.profile_picture)

        authenticated_user.post(self.url, box(0, 0, 0.5, 0.5))

        user.refresh_from_db()
        assert user.profile_picture.name == name
        assert stored_bytes(user.profile_picture) == before

    def test_the_box_applies_to_that_one_photo_only(self, authenticated_user, user, media):
        self.upload(authenticated_user, user, **box(0, 0, 0.5, 1))

        # The same person's next photo, saved without a form (as admin does)
        person = WikiUser.objects.get(pk=user.pk)
        person.profile_picture = photo()
        person.save()

        left, right = edges(stored(person.profile_picture))
        assert is_colour(left, RED) and is_colour(right, BLUE)

    def test_the_box_never_outlives_the_save(self, user, media):
        from gift.forms import ProfilePictureForm

        form = ProfilePictureForm(box(0, 0, 0.5, 1), {'profile_picture': photo()}, instance=user)
        assert form.is_valid()
        form.save()
        # No new photo this time: a leftover box must not be waiting for one
        user.first_name = 'Someone'
        user.save()

        assert '_profile_picture_box' not in user.__dict__
        left, right = edges(stored(user.profile_picture))
        assert is_colour(left, RED) and is_colour(right, RED)


@pytest.mark.django_db
class TestFramedPictureForSomeoneYouLookAfter:
    def test_a_keeper_frames_the_kids_photo(self, authenticated_user, wishlist, media):
        kid = WikiUser.objects.create_user(username='ellie', first_name='Ellie')
        wishlist.dependent = kid
        wishlist.save()

        response = authenticated_user.post(
            reverse('gift:managed_user_picture', args=[kid.id]),
            {'profile_picture': photo(), **box(0.5, 0, 0.5, 1)},
        )

        assert response.status_code == 302
        kid.refresh_from_db()
        left, right = edges(stored(kid.profile_picture))
        assert is_colour(left, BLUE) and is_colour(right, BLUE)


@pytest.mark.django_db
class TestFramedCoverPhoto:
    def url(self, wishlist):
        return reverse('gift:decorate_wishlist', args=[wishlist.id])

    def upload(self, client, wishlist, image=None, **extra):
        response = client.post(
            self.url(wishlist), {'emoji': '', 'accent': '', 'image': image or photo(), **extra}
        )
        assert response.status_code == 302
        wishlist.refresh_from_db()
        return wishlist

    def test_the_chosen_region_is_kept_with_its_shape(self, authenticated_user, wishlist, media):
        # A 3:1 strip from the blue half of a 1200x800 photo
        wishlist = self.upload(authenticated_user, wishlist, **box(0.5, 0.25, 0.5, 0.25))

        image = stored(wishlist.image)
        left, right = edges(image)
        assert image.size == (600, 200)
        assert is_colour(left, BLUE) and is_colour(right, BLUE)

    def test_a_big_crop_is_still_shrunk(self, authenticated_user, wishlist, media):
        wishlist = self.upload(
            authenticated_user, wishlist, image=photo((6000, 2000)), **box(0, 0, 0.5, 0.5)
        )

        image = stored(wishlist.image)
        assert image.size == (1600, 533)
        assert is_colour(edges(image)[1], RED)

    def test_without_a_box_it_is_the_whole_photo(self, authenticated_user, wishlist, media):
        wishlist = self.upload(authenticated_user, wishlist)

        image = stored(wishlist.image)
        left, right = edges(image)
        assert image.size == (1200, 800)
        assert is_colour(left, RED) and is_colour(right, BLUE)

    @pytest.mark.parametrize('values', MALFORMED)
    def test_nonsense_falls_back_to_the_default(self, authenticated_user, wishlist, media, values):
        plain = stored_bytes(self.upload(authenticated_user, wishlist).image)

        wishlist = self.upload(authenticated_user, wishlist, **values)

        assert stored_bytes(wishlist.image) == plain

    def test_a_sideways_photo_is_cropped_the_way_it_is_shown(
        self, authenticated_user, wishlist, media
    ):
        upright = two_colours((600, 1200))
        upload = as_upload(upright.transpose(Image.Transpose.ROTATE_90), orientation=6)
        assert ImageOps.exif_transpose(Image.open(upload)).size == (600, 1200)
        upload.seek(0)

        # Upright: a 300x300 red square. As stored it would be 600x150 of blue.
        wishlist = self.upload(authenticated_user, wishlist, image=upload, **box(0, 0, 0.5, 0.25))

        image = stored(wishlist.image)
        left, right = edges(image)
        assert image.size == (300, 300)
        assert is_colour(left, RED) and is_colour(right, RED)

    def test_where_it_was_taken_is_still_removed(self, authenticated_user, wishlist, media):
        wishlist = self.upload(authenticated_user, wishlist, **box(0.1, 0.1, 0.5, 0.5))

        exif = stored(wishlist.image).getexif()
        assert GPS not in exif and ORIENTATION not in exif

    def test_a_box_without_a_photo_changes_nothing(self, authenticated_user, wishlist, media):
        wishlist = self.upload(authenticated_user, wishlist)
        name, before = wishlist.image.name, stored_bytes(wishlist.image)

        response = authenticated_user.post(
            self.url(wishlist), {'emoji': '🦖', 'accent': '', **box(0, 0, 0.5, 0.5)}
        )

        assert response.status_code == 302
        wishlist.refresh_from_db()
        assert wishlist.emoji == '🦖'
        assert wishlist.image.name == name
        assert stored_bytes(wishlist.image) == before
