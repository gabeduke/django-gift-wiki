# "What's new" entries for the holiday polish release: the installable app,
# the mobile tab bar, and quick add's duplicate check.

from datetime import date

from django.db import migrations

ENTRIES = [
    (
        'install-the-app',
        'Wikileet on your home screen',
        'Add Wikileet to your phone’s home screen and it opens full-screen like an app — '
        'with its own gift-box icon. On iPhone: Share, then Add to Home Screen.',
        date(2026, 10, 11),
    ),
    (
        'add-idea-anywhere',
        'Add an idea from anywhere',
        'Tap the green + at the bottom of your phone (or press A on a computer) to drop an '
        'idea on anyone’s list. Paste a shop link and it fills in the name for you.',
        date(2026, 10, 11),
    ),
    (
        'duplicate-check',
        'No more doubled-up gifts',
        'Quick add now shows what’s already on the list — including the sneaky things others '
        'have added — and gives you a heads-up if your idea looks like one of them.',
        date(2026, 10, 11),
    ),
]


def create_entries(apps, schema_editor):
    ChangelogEntry = apps.get_model('gift', 'ChangelogEntry')
    for slug, title, body, published_at in ENTRIES:
        ChangelogEntry.objects.get_or_create(
            slug=slug,
            defaults={'title': title, 'body': body, 'published_at': published_at},
        )


class Migration(migrations.Migration):
    dependencies = [
        ('gift', '0023_item_added_by'),
    ]

    operations = [
        migrations.RunPython(create_entries, reverse_code=migrations.RunPython.noop),
    ]
