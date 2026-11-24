# "What's new" entry for exchange kinds, letters and adding people.

from datetime import date

from django.db import migrations


def create_entry(apps, schema_editor):
    ChangelogEntry = apps.get_model('gift', 'ChangelogEntry')
    ChangelogEntry.objects.get_or_create(
        slug='exchange-kinds-letters',
        defaults={
            'title': 'Thankfulness letters, kindness and outings',
            'body': 'An exchange doesn’t have to be gifts: draw names to write someone a '
            'letter of thanks, do something kind, or take them out. Write to the person you '
            'drew — or snap a photo of a handwritten letter or poem — and it arrives when the '
            'organizer delivers them.',
            'published_at': date(2026, 11, 24),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ('gift', '0030_exchange_kinds_letters'),
    ]

    operations = [
        migrations.RunPython(create_entry, reverse_code=migrations.RunPython.noop),
    ]
