"""Gate for the operator-only endpoints, `/health/db/` and `/metrics`.

Both are answered by early middleware, before sessions or authentication. A
public `/health/db/` lets any stranger or crawler run a query and reset Neon's
autosuspend timer; a public `/metrics` leaks paths and usage patterns (#130).

A caller must send `Authorization: Bearer $OPS_TOKEN`. With `OPS_TOKEN` unset
the endpoints are open under DEBUG (local development) and 404 everywhere else.

Refuse with `not_found()`, never `raise Http404`: Django's 404 handler renders
a template whose context processors query the database, and a refused request
must not touch it.
"""

import hmac

from django.conf import settings
from django.http import HttpResponseNotFound


def ops_request_allowed(request):
    token = getattr(settings, 'OPS_TOKEN', '')
    if not token:
        return settings.DEBUG

    scheme, _, credentials = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer':
        return False
    return hmac.compare_digest(credentials.strip().encode(), token.encode())


def not_found():
    return HttpResponseNotFound()
