# "What's new" entry for profile photos and decorating lists.

from datetime import date

from django.db import migrations


def create_entry(apps, schema_editor):
    ChangelogEntry = apps.get_model('gift', 'ChangelogEntry')
    ChangelogEntry.objects.get_or_create(
        slug='make-lists-yours',
        defaults={
            'title': 'Photos, and lists that look like you',
            'body': 'Add your photo on My Lists — grown-ups can add one for the kids they '
            'look after, too. Then open a list and tap 🎨 Decorate to give it an emoji, a '
            'colour and a cover photo. Everyone who opens it will see it.',
            'published_at': date(2026, 11, 24),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ('gift', '0034_make_lists_yours'),
    ]

    operations = [
        migrations.RunPython(create_entry, reverse_code=migrations.RunPython.noop),
    ]
