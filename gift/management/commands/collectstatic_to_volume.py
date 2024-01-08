import os
import shutil

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Collect static files to a volume'

    def add_arguments(self, parser):
        parser.add_argument('destination', type=str, help='Destination directory for static files')

    def handle(self, *args, **options):
        # Collect static files
        call_command('collectstatic', '--noinput')

        # Define source and destination
        source_dir = os.path.join(os.getcwd(), 'staticfiles')  # Adjust if your STATIC_ROOT is different
        destination_dir = options['destination']

        # Copy files from source to destination
        if not os.path.exists(destination_dir):
            os.makedirs(destination_dir)
        for item in os.listdir(source_dir):
            s = os.path.join(source_dir, item)
            d = os.path.join(destination_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)

        self.stdout.write(self.style.SUCCESS('Successfully copied static files to {}'.format(destination_dir)))
