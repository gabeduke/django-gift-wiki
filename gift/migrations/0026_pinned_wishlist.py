# Pin a list to the top of My Lists. The rest of the page shows lists as
# compact rows, so the pinned one is the only big card.

from datetime import date

import django.db.models.deletion
from django.db import migrations, models


def announce(apps, schema_editor):
    ChangelogEntry = apps.get_model('gift', 'ChangelogEntry')
    ChangelogEntry.objects.get_or_create(
        slug='pinned-list',
        defaults={
            'title': 'Pin your list',
            'body': 'My Lists now shows every list at a glance. Pin the one you add to most '
            '(⋯ → Pin to top) and it stays open at the top — and quick add\'s "Mine" goes '
            'straight to it.',
            'published_at': date(2026, 10, 12),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ('gift', '0025_themes'),
    ]

    operations = [
        migrations.AddField(
            model_name='wikiuser',
            name='pinned_wishlist',
            field=models.ForeignKey(
                blank=True,
                help_text='The list pinned to the top of My Lists',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='gift.wishlist',
            ),
        ),
        migrations.RunPython(announce, reverse_code=migrations.RunPython.noop),
    ]
