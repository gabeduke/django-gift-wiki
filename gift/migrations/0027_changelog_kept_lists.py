# "What's new" entries for lists kept for kids: parents now see and mark what's
# been bought, and "Over the shoulder" hides it all when looking together.

from datetime import date

from django.db import migrations

ENTRIES = [
    (
        'kept-lists-purchases',
        'Shop for the kids too',
        'On a list you keep for one of your kids, you can now see what’s been bought and '
        'mark things purchased yourself. Your kid still sees none of it — no surprises '
        'spoiled.',
        date(2026, 11, 16),
    ),
    (
        'over-the-shoulder',
        'Looking at a list together',
        'Showing someone a list on your screen? Tap 👀 Over the shoulder and what’s been '
        'bought and the sneaky surprises stay hidden until you turn it off at the top of '
        'the page.',
        date(2026, 11, 16),
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
        ('gift', '0026_pinned_wishlist'),
    ]

    operations = [
        migrations.RunPython(create_entries, reverse_code=migrations.RunPython.noop),
    ]
