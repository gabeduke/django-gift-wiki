# Colour themes come back (see gift/themes.py) with a new set of colours.
#
# Everyone starts on Forest: choices saved under the old switcher (removed in
# April) used names that no longer exist, and nobody should get a surprise
# colour change on deploy. People opt in from the new picker on My Lists.

from datetime import date

from django.db import migrations, models


def reset_to_default(apps, schema_editor):
    WikiUser = apps.get_model('gift', 'WikiUser')
    WikiUser.objects.exclude(color_palette='forest').update(color_palette='forest')


def announce(apps, schema_editor):
    ChangelogEntry = apps.get_model('gift', 'ChangelogEntry')
    ChangelogEntry.objects.get_or_create(
        slug='colour-themes',
        defaults={
            'title': 'Make it yours',
            'body': 'Pick your own colour at the bottom of My Lists — the whole app, logo '
            'included, follows along. Only you see your choice.',
            'published_at': date(2026, 10, 12),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ('gift', '0024_changelog_holiday_polish'),
    ]

    operations = [
        migrations.AlterField(
            model_name='wikiuser',
            name='color_palette',
            field=models.CharField(
                choices=[
                    ('forest', 'Forest'),
                    ('lake', 'Lake'),
                    ('midnight', 'Midnight'),
                    ('plum', 'Plum'),
                    ('cranberry', 'Cranberry'),
                    ('slate', 'Slate'),
                ],
                default='forest',
                help_text='Colour theme for the interface',
                max_length=20,
            ),
        ),
        migrations.RunPython(reset_to_default, reverse_code=migrations.RunPython.noop),
        migrations.RunPython(announce, reverse_code=migrations.RunPython.noop),
    ]
