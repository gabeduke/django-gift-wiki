from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = 'Clear profile picture references whose file is missing from storage'

    def handle(self, *args, **options):
        users_cleaned = 0

        for user in User.objects.exclude(profile_picture='').exclude(profile_picture__isnull=True):
            picture = user.profile_picture
            try:
                # Ask the field's own storage (S3 in prod), not the local disk
                if picture.storage.exists(picture.name):
                    continue
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f'Error checking profile picture for {user.username}: {e}')
                )
                continue

            self.stdout.write(f'Clearing missing profile picture for user: {user.username}')
            user.profile_picture = None
            user.profile_picture_thumbnail = None
            user.profile_picture_web = None
            user.save()
            users_cleaned += 1

        if users_cleaned > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Cleaned up {users_cleaned} user(s) with missing profile pictures'
                )
            )
        else:
            self.stdout.write('No users with missing profile pictures found.')
