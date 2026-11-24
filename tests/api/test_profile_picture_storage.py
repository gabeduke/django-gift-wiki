"""Profile pictures must not assume the local disk.

Before uploads went to S3, `WikiUser.save()` checked MEDIA_ROOT for the file
and cleared the picture when it wasn't there — which, on S3, is always.
"""

from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import Storage

from gift.models import WikiUser


class RemoteOnlyStorage(Storage):
    """A storage whose files are never on local disk, like S3."""

    def __init__(self):
        self.files = {}

    def _save(self, name, content):
        self.files[name] = content.read()
        return name

    def _open(self, name, mode='rb'):
        return ContentFile(self.files[name], name=name)

    def exists(self, name):
        return name in self.files

    def url(self, name):
        return f'https://bucket.example/{name}'

    def path(self, name):
        raise NotImplementedError('not on local disk')


@pytest.fixture
def remote_storage():
    storage = RemoteOnlyStorage()
    fields = [WikiUser._meta.get_field(name) for name in ('profile_picture', 'profile_picture_web')]
    originals = [field.storage for field in fields]
    for field in fields:
        field.storage = storage
    yield storage
    for field, original in zip(fields, originals, strict=True):
        field.storage = original


@pytest.fixture(params=[True, False], ids=['flag-on', 'flag-off'])
def picture_flag(request):
    with patch('giftwiki.feature_flags.get_profile_picture_enabled', return_value=request.param):
        yield request.param


@pytest.mark.django_db
class TestProfilePictureOnRemoteStorage:
    def test_saving_keeps_a_picture_that_isnt_on_local_disk(
        self, user, remote_storage, picture_flag
    ):
        remote_storage.files['profile_pictures/me.jpg'] = b'jpeg'
        WikiUser.objects.filter(pk=user.pk).update(profile_picture='profile_pictures/me.jpg')
        user.refresh_from_db()

        user.first_name = 'Renamed'
        user.save()
        user.refresh_from_db()

        assert user.profile_picture.name == 'profile_pictures/me.jpg'

    def test_saving_doesnt_reprocess_a_stored_picture(self, user, remote_storage):
        """Reprocessing on S3 is a download and two uploads on every save."""
        remote_storage.files['profile_pictures/me.jpg'] = b'jpeg'
        WikiUser.objects.filter(pk=user.pk).update(profile_picture='profile_pictures/me.jpg')
        user.refresh_from_db()

        with (
            patch('giftwiki.feature_flags.get_profile_picture_enabled', return_value=True),
            patch('gift.utils.process_profile_picture') as process,
        ):
            user.save()

        process.assert_not_called()

    def test_urls_come_from_the_storage(self, user, remote_storage):
        WikiUser.objects.filter(pk=user.pk).update(
            profile_picture='profile_pictures/me.jpg',
            profile_picture_web='profile_pictures/web/me.jpg',
        )
        user.refresh_from_db()

        assert user.get_profile_picture_url() == 'https://bucket.example/profile_pictures/me.jpg'
        assert (
            user.get_profile_picture_web_url()
            == 'https://bucket.example/profile_pictures/web/me.jpg'
        )

    def test_no_picture_means_no_url(self, user):
        assert user.get_profile_picture_url() is None
        assert user.get_profile_picture_web_url() is None
