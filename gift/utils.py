"""
Utility functions for image processing and resizing.
"""

from io import BytesIO

from PIL import Image

# Every uploaded photo: big enough for a phone screen, and no bigger than this
# on the way in.
PHOTO_MAX_BYTES = 15 * 1024 * 1024
PHOTO_TOO_BIG = 'That photo is too big — 15 MB at most.'
LETTER_IMAGE_MAX_SIDE = 2000
LETTER_IMAGE_MAX_BYTES = PHOTO_MAX_BYTES
COVER_MAX_SIDE = 1600
AVATAR_SIDES = {'original': 800, 'web': 400, 'thumbnail': 160}


def open_photo(upload):
    """An uploaded photo as an RGB image, turned the right way up.

    Raises ValueError for anything that isn't an image we can read. What comes
    back has no EXIF data once re-encoded with `to_jpeg`, so a phone photo
    doesn't carry where it was taken.
    """
    from PIL import ImageOps, UnidentifiedImageError

    if hasattr(upload, 'seek'):
        upload.seek(0)
    try:
        image = Image.open(upload)
        image.load()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError('That file isn’t a photo we can read.') from error

    image = ImageOps.exif_transpose(image)
    if image.mode in ('RGBA', 'LA', 'P'):
        # Transparency goes on white paper, not black
        image = image.convert('RGBA')
        background = Image.new('RGB', image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    elif image.mode != 'RGB':
        image = image.convert('RGB')
    return image


def to_jpeg(image, name, quality=85):
    """`image` re-encoded as a JPEG file, with no metadata carried over."""
    from django.core.files.base import ContentFile

    out = BytesIO()
    image.save(out, format='JPEG', quality=quality, optimize=True)
    return ContentFile(out.getvalue(), name=name)


def fit_within(image, side):
    image = image.copy()
    image.thumbnail((side, side), Image.LANCZOS)
    return image


def process_profile_picture(upload):
    """Square, cleaned copies of a profile picture: (original, web, thumbnail).

    Centre-cropped so a face fills the round avatar instead of being squashed.
    """
    from PIL import ImageOps

    image = open_photo(upload)
    side = min(image.size)
    square = ImageOps.fit(image, (side, side), Image.LANCZOS)
    return tuple(
        to_jpeg(fit_within(square, AVATAR_SIDES[size]), f'{size}.jpg', quality=88)
        for size in ('original', 'web', 'thumbnail')
    )


def process_cover_image(upload):
    """A list's cover photo, ready to store: upright, shrunk, no EXIF."""
    return to_jpeg(fit_within(open_photo(upload), COVER_MAX_SIDE), 'cover.jpg')


def process_letter_image(upload):
    """A photo or scan for an exchange letter, ready to store.

    Turned the right way up, shrunk to fit LETTER_IMAGE_MAX_SIDE and re-encoded
    as JPEG — which also drops the EXIF data. Raises ValueError for anything
    that isn't an image.
    """
    return to_jpeg(fit_within(open_photo(upload), LETTER_IMAGE_MAX_SIDE), 'letter.jpg')


def delete_stored_files(storage, names):
    """Delete files that nothing points at any more. Never fails a request:
    a leftover file costs pennies, a crash costs the save."""
    import logging

    for name in names:
        if not name:
            continue
        try:
            storage.delete(name)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning('Could not delete %s', name, exc_info=True)
