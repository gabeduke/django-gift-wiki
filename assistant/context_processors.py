"""Tells the base template whether to render the bubble.

The endpoint asks the same question again on every request: this is a rendering
decision, not a security control.
"""

from assistant.gating import assistant_available_for


def assistant_availability(request):
    return {'assistant_available': assistant_available_for(getattr(request, 'user', None)).available}
