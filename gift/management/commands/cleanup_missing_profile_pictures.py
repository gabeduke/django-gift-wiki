from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
import os
from django.conf import settings

User = get_user_model()


class Command(BaseCommand):
    help = 'Clean up users with missing profile picture files'

    def handle(self, *args, **options):
        users_cleaned = 0
        
        for user in User.objects.exclude(profile_picture=''):
            if user.profile_picture:
                try:
                    # Check if file exists
                    if hasattr(user.profile_picture, 'name'):
                        file_path = os.path.join(settings.MEDIA_ROOT, user.profile_picture.name)
                        if not os.path.exists(file_path):
                            self.stdout.write(
                                f"Clearing missing profile picture for user: {user.username}"
                            )
                            user.profile_picture = None
                            user.profile_picture_thumbnail = None
                            user.profile_picture_web = None
                            user.save()
                            users_cleaned += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Error checking profile picture for {user.username}: {e}"
                        )
                    )
        
        if users_cleaned > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Cleaned up {users_cleaned} user(s) with missing profile pictures'
                )
            )
        else:
            self.stdout.write('No users with missing profile pictures found.')


