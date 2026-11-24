"""
Utility functions for image processing and resizing.
"""

import os
import sys
from io import BytesIO

from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image


def resize_image(image_field, max_width, max_height, quality=85):
    """
    Resize an image to fit within max_width and max_height while maintaining aspect ratio.

    Args:
        image_field: Django ImageField or file-like object
        max_width: Maximum width in pixels
        max_height: Maximum height in pixels
        quality: JPEG quality (1-100, default 85)

    Returns:
        InMemoryUploadedFile: Resized image ready to save to a model field
    """
    if not image_field:
        return None

    # Open the image
    img = Image.open(image_field)

    # Convert RGBA to RGB if necessary (for JPEG compatibility)
    if img.mode in ('RGBA', 'LA', 'P'):
        # Create a white background
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # Calculate new dimensions maintaining aspect ratio
    original_width, original_height = img.size
    ratio = min(max_width / original_width, max_height / original_height)

    # Only resize if image is larger than target size
    if ratio < 1:
        new_width = int(original_width * ratio)
        new_height = int(original_height * ratio)
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Save to BytesIO
    output = BytesIO()
    img.save(output, format='JPEG', quality=quality, optimize=True)
    output.seek(0)

    # Get the original filename
    filename = os.path.basename(image_field.name) if hasattr(image_field, 'name') else 'image.jpg'
    name, ext = os.path.splitext(filename)
    filename = f'{name}_resized.jpg'

    # Create InMemoryUploadedFile
    return InMemoryUploadedFile(
        output, 'ImageField', filename, 'image/jpeg', sys.getsizeof(output), None
    )


def process_profile_picture(image_field):
    """
    Process a profile picture: create thumbnail (150x150) and web size (400x400).

    Args:
        image_field: Django ImageField or file-like object

    Returns:
        tuple: (thumbnail_file, web_file) - Both as InMemoryUploadedFile objects
    """
    thumbnail = resize_image(image_field, max_width=150, max_height=150, quality=90)
    web_size = resize_image(image_field, max_width=400, max_height=400, quality=85)

    return thumbnail, web_size


# Letter photos: big enough to read handwriting, small enough for a phone.
LETTER_IMAGE_MAX_SIDE = 2000
LETTER_IMAGE_MAX_BYTES = 15 * 1024 * 1024


def process_letter_image(upload):
    """A photo or scan for an exchange letter, ready to store.

    Turned the right way up, shrunk to fit LETTER_IMAGE_MAX_SIDE and re-encoded
    as JPEG — which also drops the EXIF data, so a phone photo doesn't carry
    where it was taken. Raises ValueError for anything that isn't an image.
    """
    from django.core.files.base import ContentFile
    from PIL import ImageOps, UnidentifiedImageError

    try:
        image = Image.open(upload)
        image.load()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError('That file isn’t a photo we can read.') from error

    image = ImageOps.exif_transpose(image)
    if image.mode in ('RGBA', 'LA', 'P'):
        # Scans with transparency go on white paper, not black
        image = image.convert('RGBA')
        background = Image.new('RGB', image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    elif image.mode != 'RGB':
        image = image.convert('RGB')
    image.thumbnail((LETTER_IMAGE_MAX_SIDE, LETTER_IMAGE_MAX_SIDE), Image.LANCZOS)

    out = BytesIO()
    image.save(out, format='JPEG', quality=85, optimize=True)
    return ContentFile(out.getvalue(), name='letter.jpg')
