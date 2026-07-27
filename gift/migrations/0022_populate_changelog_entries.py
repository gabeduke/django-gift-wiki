# Backfill "What's new" entries for features shipped through 2026-07-27 (issue #90)

from datetime import date

from django.db import migrations


ENTRIES = [
    (
        'managed-accounts',
        'Managed accounts for kids',
        'Create accounts for kids or family members and manage their wishlists on their behalf.',
        date(2026, 7, 18),
    ),
    (
        'birthdays-everywhere',
        'Birthdays on profiles and lists',
        'Birthdays now show on profiles, wishlists, and quick category creation.',
        date(2026, 7, 18),
    ),
    (
        'anonymous-purchased-badges',
        "Anonymous 'Purchased' badges",
        'Gifts you buy show as purchased without spoiling who bought them — with a reveal toggle if you are the purchaser.',
        date(2026, 7, 21),
    ),
    (
        'upcoming-birthdays',
        'Upcoming birthdays on the home page',
        'The home page now shows the next 5 family birthdays with links straight to their wishlists.',
        date(2026, 7, 27),
    ),
    (
        'collapsible-groups',
        'Collapsible groups',
        'Tap a group header to collapse it, or use Expand all / Collapse all — the page remembers your layout.',
        date(2026, 7, 27),
    ),
    (
        'my-purchases',
        'My Purchases page',
        "See everything you've marked as purchased, grouped by list, with your total spend.",
        date(2026, 7, 27),
    ),
    (
        'most-wanted',
        "'Most wanted' markers",
        'Owners can ⭐ star their top items to guide givers.',
        date(2026, 7, 27),
    ),
    (
        'surprise-items-received-gifts',
        'Surprise items + Received gifts',
        "Add 🤫 surprise gifts to someone's list that they can't see — then after the big day, archive purchased gifts to your per-year Received page and track thank-you cards.",
        date(2026, 7, 27),
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
        ('gift', '0021_changelogentry'),
    ]

    operations = [
        migrations.RunPython(create_entries, reverse_code=migrations.RunPython.noop),
    ]
