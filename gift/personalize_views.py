"""Making things yours: profile pictures and 🎨 Decorate for a list.

Every photo goes through gift/utils.py (upright, cropped or shrunk, re-encoded
so it carries no EXIF/GPS) and gets a random name, because media URLs on S3
are public. A replaced or removed photo's files are deleted.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .decor import LIST_EMOJI
from .forms import DecorateListForm, ProfilePictureForm
from .models import WishList
from .themes import THEMES
from .utils import delete_stored_files
from .visibility import can_add_openly, recipient_of

logger = logging.getLogger(__name__)


def _first_error(form):
    for errors in form.errors.values():
        return errors[0]
    return 'Something went wrong — please try again.'


def _set_or_remove_picture(request, person):
    """Shared by your own picture and the picture of someone you look after.
    Returns the message to show."""
    if 'remove' in request.POST:
        if person.profile_picture:
            person.remove_profile_picture()
        return messages.SUCCESS, 'Photo removed.'

    form = ProfilePictureForm(request.POST, request.FILES, instance=person)
    if not form.is_valid():
        return messages.ERROR, _first_error(form)
    form.save()
    logger.info('Profile picture updated', extra={'user_id': person.pk})
    return messages.SUCCESS, 'Looking good! Your new photo is up.' if person == request.user else (
        f'Photo saved for {person.first_name or person.username}.'
    )


def _pictures_enabled():
    from giftwiki.feature_flags import get_profile_picture_enabled

    return get_profile_picture_enabled()


@require_POST
@login_required
def profile_picture(request):
    """Upload (or, with `remove`, take away) your own profile picture."""
    if _pictures_enabled():
        level, text = _set_or_remove_picture(request, request.user)
        messages.add_message(request, level, text)
    return redirect('gift:account')


@require_POST
@login_required
def managed_user_picture(request, user_id):
    """The picture for someone you look after, such as a child without a login."""
    from .views import _get_managed_user_or_none

    person = _get_managed_user_or_none(request.user, user_id)
    if person is None:
        messages.error(request, 'You can only change photos for people you look after.')
    elif _pictures_enabled():
        level, text = _set_or_remove_picture(request, person)
        messages.add_message(request, level, text)
    return redirect('gift:account')


@login_required
def decorate_wishlist(request, wishlist_id):
    """🎨 Decorate: pick an emoji, a colour and a cover photo for a list.

    Anyone who can edit the list can decorate it — including the kid it's
    for. Nothing here is a secret, so the visibility rules don't come into it.
    """
    wishlist = get_object_or_404(
        WishList.objects.select_related('owner', 'dependent'), id=wishlist_id
    )
    if not can_add_openly(wishlist, request.user):
        messages.error(request, 'Only the people who look after this list can decorate it.')
        return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)

    old_image = wishlist.image.name if wishlist.image else None
    form = DecorateListForm(request.POST or None, request.FILES or None, instance=wishlist)
    if request.method == 'POST':
        if form.is_valid():
            wishlist = form.save()
            new_image = wishlist.image.name if wishlist.image else None
            if old_image and old_image != new_image:
                delete_stored_files(wishlist.image.storage, [old_image])
            messages.success(request, 'Your list is decorated! 🎉')
            return redirect('gift:wishlist_detail', wishlist_id=wishlist.id)
        messages.error(request, _first_error(form))

    return render(
        request,
        'gift/wishlist_decorate.html',
        {
            'wishlist': wishlist,
            'form': form,
            'recipient': recipient_of(wishlist),
            'emoji_options': LIST_EMOJI,
            'colour_options': [(key, label, colour) for key, (label, colour) in THEMES.items()],
        },
    )
