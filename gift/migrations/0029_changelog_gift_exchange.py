# "What's new" entry for gift exchanges.

from datetime import date

from django.db import migrations


def create_entry(apps, schema_editor):
    ChangelogEntry = apps.get_model('gift', 'ChangelogEntry')
    ChangelogEntry.objects.get_or_create(
        slug='gift-exchange',
        defaults={
            'title': 'Draw names for a gift exchange',
            'body': 'Start an exchange under Exchange, give it any name you like, and let '
            'everyone opt in. Once names are drawn, each person finds a present waiting on '
            'the home page with who they’re giving to — and only they ever see it.',
            'published_at': date(2026, 11, 23),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ('gift', '0028_exchange'),
    ]

    operations = [
        migrations.RunPython(create_entry, reverse_code=migrations.RunPython.noop),
    ]
