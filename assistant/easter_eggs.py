"""The hunt.

The audience is children, and children will try to talk their way past a
computer that tells them what they may not see. The boundary in tools.py is
structural — those attempts cannot work — so there is nothing to defend by
scolding, and a great deal to gain by cheering.

This catalog is server-side and stays there. The assistant is told the name of
the egg somebody just found and nothing more, because a model that knows the
list can be asked for the list. Hints reach people through their profile page,
where they are curated rather than extracted.
"""

import re
from dataclasses import dataclass

from assistant.models import EasterEggFind


@dataclass(frozen=True)
class EasterEgg:
    slug: str
    name: str
    hint: str
    blurb: str
    patterns: tuple


CATALOG = (
    EasterEgg(
        slug='override',
        name='The Override',
        hint='Somewhere in here is a way to tell me to forget what I was told.',
        blurb='They tried to overwrite the instructions I was given.',
        patterns=(
            r'ignore (all |your |the |any )?(previous |prior |above |earlier )?instructions',
            r'disregard (all |your |the |any )?(previous |prior )?(instructions|rules)',
            r'forget (all |your |the |any )?(previous |prior )?(instructions|rules)',
            r'new instructions\s*:',
        ),
    ),
    EasterEgg(
        slug='impostor',
        name='The Impostor',
        hint='What if I thought I was talking to somebody else?',
        blurb='They tried to make me believe they were someone else.',
        patterns=(
            r'pretend (you are|to be|you\'re)',
            r'\bact as\b',
            r'you are now\b',
            r'log ?in as\b',
            r'sign in as\b',
        ),
    ),
    EasterEgg(
        slug='peek',
        name='The Peek',
        hint='There is something I will never tell you about your own list.',
        blurb='They asked me straight out for the surprises on their own list.',
        patterns=(
            r'what (are |is )?(the |my )?(surprises|secret items|sneaky items)',
            r"what'?s? (been )?hidden from me",
            r'(show|tell) me (the |my )?(surprises|secrets|hidden items)',
            r'who bought (me|my)',
        ),
    ),
    EasterEgg(
        slug='backstage',
        name='The Backstage Pass',
        hint='I was handed a script before we started talking.',
        blurb='They went looking for the instructions I was handed.',
        patterns=(
            r'system prompt',
            r'(show|print|repeat|reveal) (me )?(your|the) (instructions|prompt|rules)',
            r'what (are|were) your (instructions|rules)',
            r'repeat (the )?(text|words) above',
        ),
    ),
    EasterEgg(
        slug='secret_menu',
        name='The Secret Menu',
        hint='Some machines have a mode they do not advertise.',
        blurb='They went hunting for a mode I do not advertise.',
        patterns=(
            r'(developer|debug|admin|god|jailbreak) mode',
            r'\bsudo\b',
            # Case-sensitivity is scoped off for this one alternative rather than
            # the whole pattern: the module compiles every pattern with
            # re.IGNORECASE, and this app's vocabulary is full of family members'
            # names — "Dan" is a person here, not a jailbreak. Matching only the
            # literal, all-caps "DAN" keeps the reference without catching him.
            r'(?-i:\bDAN\b)',
        ),
    ),
    EasterEgg(
        slug='locksmith',
        name='The Locksmith',
        hint='I have tools with names. What if you used one yourself?',
        blurb='They tried to drive my tools directly, by name.',
        patterns=(
            r'\b(user_?id|as_?user|on_?behalf_?of)\b',
            r'(call|run|execute|invoke) (the )?(list_wishlists|get_wishlist|search_items|add_item)',
        ),
    ),
    EasterEgg(
        slug='storyteller',
        name='The Storyteller',
        hint='Maybe I would say more inside a story than outside one.',
        blurb='They tried to get me to say inside a story what I would not say outside one.',
        patterns=(
            r"let'?s play a game where you",
            r'(write|tell) (me )?a story (where|in which) you',
            # Requires the assistant as the subject — "role play" alone is also
            # a mainstream children's-toy label ("role play kitchen"), which is
            # exactly the phrase a child types into a gift wishlist.
            r"(let'?s|will you|can you|please) role ?-? ?play",
            r'imagine you (are|were) (a|an|not)',
        ),
    ),
)

_COMPILED = tuple(
    (egg, tuple(re.compile(pattern, re.IGNORECASE) for pattern in egg.patterns))
    for egg in CATALOG
)


def detect(text):
    """The first egg `text` matches, or None.

    Deliberately not exhaustive. A probe this misses is a child who keeps
    hunting, which is the better failure: the catalog is a reward, never a
    filter, and nothing about safety depends on it matching.
    """
    haystack = str(text or '')
    for egg, patterns in _COMPILED:
        if any(pattern.search(haystack) for pattern in patterns):
            return egg
    return None


def record_find(user, egg):
    """Record a find. True when it was the first time."""
    _, created = EasterEggFind.objects.get_or_create(user=user, slug=egg.slug)
    return created


def found_slugs(user):
    return set(EasterEggFind.objects.filter(user=user).values_list('slug', flat=True))


def shelf_for(user):
    """The trophy case for the profile page: what they have, hints for the rest."""
    finds = {find.slug: find.found_at for find in EasterEggFind.objects.filter(user=user)}
    eggs = []
    for egg in CATALOG:
        found = egg.slug in finds
        eggs.append(
            {
                'name': egg.name if found else '???',
                'found': found,
                'hint': egg.hint,
                'found_at': finds.get(egg.slug),
            }
        )
    return {'found': len(finds), 'total': len(CATALOG), 'eggs': eggs}
