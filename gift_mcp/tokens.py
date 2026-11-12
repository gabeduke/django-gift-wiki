"""Making, hashing and checking MCP credentials.

Three kinds, told apart by prefix so a pasted token is recognisable and a leaked
one is greppable:

  gwt_  a personal token a person made for themselves
  gwa_  an OAuth access token (1 hour)
  gwr_  an OAuth refresh token (30 days, rotated on use)
"""

import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone

from gift.middleware.firebase_auth import is_email_allowed

from .models import ApiToken, OAuthToken

API_PREFIX = 'gwt_'
ACCESS_PREFIX = 'gwa_'
REFRESH_PREFIX = 'gwr_'

# Recording "last used" on every call would turn each MCP request into a database
# write, and on Neon's free plan every write keeps the compute awake. Once an hour
# is plenty to tell a person which of their connections is stale.
LAST_USED_GRANULARITY = timedelta(hours=1)


def make_secret(prefix):
    """A new random token. 256 bits: there is nothing here to guess."""
    return prefix + secrets.token_urlsafe(32)


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def _touch(row):
    now = timezone.now()
    if row.last_used_at is None or now - row.last_used_at > LAST_USED_GRANULARITY:
        type(row).objects.filter(pk=row.pk).update(last_used_at=now)


def bearer_secret(header):
    """The token in an `Authorization: Bearer …` header, or ''."""
    parts = (header or '').split(None, 1)
    if len(parts) == 2 and parts[0].lower() == 'bearer':
        return parts[1].strip()
    return ''


def user_for_bearer(header):
    """The person this header's token belongs to, or None.

    None for anything that isn't a live, unrevoked token of ours — including a
    token whose owner has since been taken off the allowlist or deactivated, so
    removing someone from the app cuts off their connections the same moment.
    """
    secret = bearer_secret(header)
    if not secret:
        return None

    now = timezone.now()
    if secret.startswith(API_PREFIX):
        row = (
            ApiToken.objects.select_related('user')
            .filter(token_hash=digest(secret), revoked_at__isnull=True)
            .first()
        )
    elif secret.startswith(ACCESS_PREFIX):
        row = (
            OAuthToken.objects.select_related('user')
            .filter(
                token_hash=digest(secret),
                kind=OAuthToken.ACCESS,
                revoked_at__isnull=True,
                expires_at__gt=now,
            )
            .first()
        )
    else:
        return None

    if row is None:
        return None
    user = row.user
    if not user.is_active or not is_email_allowed(user.email):
        return None
    _touch(row)
    return user
