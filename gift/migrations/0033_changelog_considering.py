# "What's new" entry for 🤔 considering and the reworked My Purchases.

from datetime import date

from django.db import migrations


def create_entry(apps, schema_editor):
    ChangelogEntry = apps.get_model('gift', 'ChangelogEntry')
    ChangelogEntry.objects.get_or_create(
        slug='considering-and-my-purchases',
        defaults={
            'title': 'Thinking of getting something? Mark it 🤔',
            'body': 'Tap 🤔 next to Mark Purchased to say you’re considering a gift. Other '
            'givers see who’s eyeing what, so nobody doubles up — and it stays hidden from '
            'whoever the list is for. My Purchases now shows what you’ve bought and what '
            'you’re considering for each person, with totals.',
            'published_at': date(2026, 11, 24),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ('gift', '0032_item_considered_by'),
    ]

    operations = [
        migrations.RunPython(create_entry, reverse_code=migrations.RunPython.noop),
    ]
