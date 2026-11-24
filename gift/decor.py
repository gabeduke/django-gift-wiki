"""What a list can be decorated with (the 🎨 Decorate page).

Emoji are curated, not free text, so every one renders, none can break the
layout, and a child can pick one with a single tap. Colours are the themes in
gift/themes.py — already checked for WCAG AA — so a list's colour is just a
theme key, rendered as `data-theme` on that list's page.
"""

LIST_EMOJI = [
    '🎁', '🌟', '🌈', '🦄', '🦖', '🚀', '⚽', '🏀',
    '🎨', '🎮', '🎸', '🎹', '📚', '🧸', '🎀', '🏰',
    '🐶', '🐱', '🦊', '🐼', '🌸', '🍕', '🧁', '🏕️',
]

LIST_EMOJI_CHOICES = [('', 'None'), *[(emoji, emoji) for emoji in LIST_EMOJI]]
