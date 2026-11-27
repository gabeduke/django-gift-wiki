# "What's new" entry for exchange curators and keep-apart rules.

from datetime import date

from django.db import migrations


def create_entry(apps, schema_editor):
    ChangelogEntry = apps.get_model('gift', 'ChangelogEntry')
    ChangelogEntry.objects.get_or_create(
        slug='exchange-curators',
        defaults={
            'title': 'Exchanges have curators',
            'body': 'Whoever starts an exchange is its curator, and can name others to help. '
            'Curators can keep two people from drawing each other — spouses, say — and, if '
            'something still needs fixing, open the draw and change a pick by hand.',
            'published_at': date(2026, 11, 27),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ('gift', '0037_exchange_curators'),
    ]

    operations = [
        migrations.RunPython(create_entry, reverse_code=migrations.RunPython.noop),
    ]
