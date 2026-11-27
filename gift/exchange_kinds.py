"""What kind of exchange it is: a gift swap, thankfulness letters, kindness,
or an outing. A kind is only words and pictures — the draw, the reveal and
letters work the same for all of them. Adding one is an entry here.
"""

from dataclasses import dataclass

DEFAULT_KIND = 'gift'


@dataclass(frozen=True)
class Kind:
    label: str
    icon: str
    # The reveal picture: 'present' (a wrapped box) or 'envelope' — also the
    # word for it ("4 of 6 presents opened")
    art: str
    # "You're giving to …"
    verb: str
    budget_label: str
    letter_title: str
    letter_prompt: str
    # Heading over a delivered letter, for the person reading it
    received_title: str
    # Is the letter the whole point? Then the home page nudges until it's written.
    letter_is_the_gift: bool
    # Point the giver at their pick's wishlists?
    shows_lists: bool
    blurb: str


KINDS = {
    'gift': Kind(
        label='Gift exchange',
        icon='🎁',
        art='present',
        verb="You're giving to",
        budget_label='Spending limit',
        letter_title='A note to go with your gift',
        letter_prompt='Optional. It’s delivered, signed, when the letters are handed '
        'out — so if you’re keeping your identity a surprise, wait until the day.',
        received_title='A note with your gift',
        letter_is_the_gift=False,
        shows_lists=True,
        blurb='Everyone draws one name and shops for just that person.',
    ),
    'thanks': Kind(
        label='Thankfulness letters',
        icon='💌',
        art='envelope',
        verb="You're writing to",
        budget_label='Spending limit',
        letter_title='Your letter',
        letter_prompt='What do you appreciate about them? A memory, something they do, '
        'why you’re glad they’re family. Type it, or snap a photo of one you wrote by hand.',
        received_title='A letter for you',
        letter_is_the_gift=True,
        shows_lists=False,
        blurb='Everyone draws one name and writes that person a letter of thanks.',
    ),
    'kindness': Kind(
        label='Kindness exchange',
        icon='💛',
        art='envelope',
        verb="You're being kind to",
        budget_label='Spending limit',
        letter_title='A note for them',
        letter_prompt='Tell them what you did, or just leave a kind word.',
        received_title='Something kind for you',
        letter_is_the_gift=False,
        shows_lists=False,
        blurb='Everyone draws one name and does something kind for that person.',
    ),
    'experience': Kind(
        label='Experience exchange',
        icon='🎟️',
        art='envelope',
        verb="You're taking out",
        budget_label='Spend up to',
        letter_title='Your invitation',
        letter_prompt='Where are you taking them? A show, a movie, coffee — say what and when.',
        received_title='Your invitation',
        letter_is_the_gift=True,
        shows_lists=False,
        blurb='Everyone draws one name and treats that person to an outing.',
    ),
}

KIND_CHOICES = [(key, kind.label) for key, kind in KINDS.items()]

# Icons a curator can pick instead of the kind's own. Curated, not free
# text, so every one renders and none can break the layout.
ICON_CHOICES = [
    ('', 'Match the kind'),
    *[
        (icon, icon)
        for icon in [
            '🎁', '💌', '💛', '🎟️', '🙏', '🦃', '🍂', '🥧', '🎄', '⛄', '🕯️',
            '☕', '🎶', '🎬', '🍿', '🌻', '🌟', '✨', '🤝', '❤️',
        ]
    ],
]


def kind_for(key):
    return KINDS.get(key, KINDS[DEFAULT_KIND])
