"""Credentials for the MCP server.

Every secret here is stored as a SHA-256 hash, never as the token itself: a
database dump or backup can't be replayed against the server. The tokens are 256
random bits, so an unsalted fast hash is the right tool (there is nothing to
brute-force).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class ApiToken(models.Model):
    """A personal token a person makes for themselves (Claude Code, scripts)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mcp_api_tokens'
    )
    name = models.CharField(max_length=80, help_text='What this token is for, e.g. "Claude Code"')
    token_hash = models.CharField(max_length=64, unique=True)
    # The first few characters, so a person can tell their tokens apart. Not a secret.
    token_prefix = models.CharField(max_length=16)
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.token_prefix}…)'

    @property
    def active(self):
        return self.revoked_at is None


class OAuthClient(models.Model):
    """An app (Claude, ChatGPT…) that registered itself to ask people for access."""

    client_id = models.CharField(max_length=64, unique=True)
    client_name = models.CharField(max_length=200)
    redirect_uris = models.JSONField(default=list)
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.client_name


class AuthorizationCode(models.Model):
    """The short-lived, single-use code a person's approval turns into."""

    code_hash = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name='codes')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mcp_auth_codes'
    )
    redirect_uri = models.TextField()
    code_challenge = models.CharField(max_length=128)
    scope = models.CharField(max_length=100, default='')
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)


class OAuthToken(models.Model):
    """An access or refresh token issued to a client on someone's behalf."""

    ACCESS = 'access'
    REFRESH = 'refresh'
    KINDS = [(ACCESS, 'Access'), (REFRESH, 'Refresh')]

    token_hash = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=10, choices=KINDS)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name='tokens')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mcp_oauth_tokens'
    )
    scope = models.CharField(max_length=100, default='')
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'client'])]
