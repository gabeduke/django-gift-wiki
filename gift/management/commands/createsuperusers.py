import os

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Create superusers based on environment variables'

    def handle(self, *args, **kwargs):
        i = 1
        created_users = []
        while True:
            username = os.getenv(f'DJANGO_SUPERUSER_{i}_USERNAME')
            email = os.getenv(f'DJANGO_SUPERUSER_{i}_EMAIL')
            password = os.getenv(f'DJANGO_SUPERUSER_{i}_PASSWORD')
            if not username or not email or not password:
                break
            if not User.objects.filter(username=username).exists():
                User.objects.create_superuser(username, email, password)
                created_users.append(username)
            i += 1
        if created_users:
            self.stdout.write(self.style.SUCCESS(f'Successfully created superusers: {", ".join(created_users)}'))
        else:
            self.stdout.write(self.style.WARNING('No new superusers were created'))
