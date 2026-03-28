from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = 'Make a user an admin (superuser and staff)'

    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help='Email address of the user to make admin')

    def handle(self, *args, **options):
        email = options['email']

        try:
            user = User.objects.get(email=email)
            user.is_superuser = True
            user.is_staff = True
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f'Successfully made {user.username} ({user.email}) a superuser!')
            )
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User with email {email} not found'))
            self.stdout.write('Available users:')
            for u in User.objects.all()[:10]:
                self.stdout.write(f'  - {u.username} ({u.email})')
