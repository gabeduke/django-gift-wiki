import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from gift.models import ScrapedWikiItem, ScrapedWikiPage


class Command(BaseCommand):
    help = 'Import scraped wiki data from JSON file'

    def add_arguments(self, parser):
        parser.add_argument(
            'json_file',
            type=str,
            help='Path to the scraped_wiki_data.json file',
            default='scraped_wiki_data.json',
            nargs='?',
        )

    def handle(self, *args, **options):
        json_file = options['json_file']

        # Try to find the file
        json_path = Path(json_file)
        if not json_path.is_absolute():
            # Try multiple locations:
            # 1. Current directory
            # 2. Project root (where manage.py is)
            # 3. Relative to this command file
            possible_paths = [
                Path(json_file),  # Current directory
                Path(__file__).parent.parent.parent.parent / json_file,  # Project root
                Path('/app') / json_file,  # Container path
            ]

            json_path = None
            for path in possible_paths:
                if path.exists():
                    json_path = path
                    break

            if json_path is None:
                self.stdout.write(
                    self.style.ERROR(
                        f'File not found: {json_file}\n'
                        f'Tried: {", ".join(str(p) for p in possible_paths)}'
                    )
                )
                return

        self.stdout.write(f'Importing data from: {json_path}')

        # Check if data already exists
        existing_pages = ScrapedWikiPage.objects.count()
        if existing_pages > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'Found {existing_pages} existing scraped pages in database. '
                    f'Will skip pages that already exist (idempotent import).'
                )
            )

        with open(json_path, encoding='utf-8') as f:
            data = json.load(f)

        # Parse scraped_at timestamp
        scraped_at_str = data.get('scraped_at', '')
        try:
            # Try to parse the timestamp
            from datetime import datetime

            scraped_at = datetime.strptime(scraped_at_str, '%Y-%m-%d %H:%M:%S')
            scraped_at = timezone.make_aware(scraped_at)
        except (ValueError, TypeError):
            scraped_at = timezone.now()

        pages_created = 0
        items_created = 0

        for page_data in data.get('pages', []):
            # Skip pages with no items
            if page_data.get('item_count', 0) == 0:
                continue

            # Check if page already exists
            url = page_data.get('url', '')
            title = page_data.get('title') or page_data.get('link_text', 'Untitled')

            scraped_page, created = ScrapedWikiPage.objects.get_or_create(
                url=url,
                defaults={
                    'title': title,
                    'scraped_at': scraped_at,
                    'item_count': page_data.get('item_count', 0),
                },
            )

            if created:
                pages_created += 1
                self.stdout.write(f'  Created page: {title} ({scraped_page.item_count} items)')
            else:
                self.stdout.write(f'  Page already exists: {title}')
                # Update item count if it changed
                if scraped_page.item_count != page_data.get('item_count', 0):
                    scraped_page.item_count = page_data.get('item_count', 0)
                    scraped_page.save()

            # Import items
            for item_data in page_data.get('items', []):
                item_name = item_data.get('name', '').strip()
                if not item_name:
                    continue

                # Check if item already exists
                item, item_created = ScrapedWikiItem.objects.get_or_create(
                    scraped_page=scraped_page,
                    name=item_name,
                    defaults={
                        'description': item_data.get('description', ''),
                        'purchased': item_data.get('purchased', False),
                        'original_text': item_data.get('original_text', ''),
                    },
                )

                if item_created:
                    items_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'\nImport complete!\n'
                f'  Pages created: {pages_created}\n'
                f'  Items created: {items_created}\n'
                f'  Total pages in database: {ScrapedWikiPage.objects.count()}\n'
                f'  Total items in database: {ScrapedWikiItem.objects.count()}'
            )
        )
