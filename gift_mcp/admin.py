"""Admin views of who has MCP credentials. Read-mostly: credentials are made by the person
they belong to (on /connect-ai/ or through the OAuth sign-in), never from here, so there is
no "add" and the hashes stay out of sight. Revoking a token is just filling in `revoked_at`."""

from django.contrib import admin

from .models import ApiToken, OAuthClient, OAuthToken


class NoAdd(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False


@admin.register(ApiToken)
class ApiTokenAdmin(NoAdd):
    list_display = ('name', 'user', 'token_prefix', 'created_at', 'last_used_at', 'revoked_at')
    list_filter = ('revoked_at',)
    search_fields = ('name', 'user__email', 'user__username')
    exclude = ('token_hash',)
    readonly_fields = ('user', 'name', 'token_prefix', 'created_at', 'last_used_at')


@admin.register(OAuthClient)
class OAuthClientAdmin(NoAdd):
    list_display = ('client_name', 'client_id', 'created_at', 'last_used_at')
    search_fields = ('client_name', 'client_id')
    readonly_fields = ('client_id', 'client_name', 'redirect_uris', 'created_at', 'last_used_at')


@admin.register(OAuthToken)
class OAuthTokenAdmin(NoAdd):
    list_display = ('user', 'client', 'kind', 'created_at', 'expires_at', 'revoked_at')
    list_filter = ('kind', 'revoked_at')
    search_fields = ('user__email', 'user__username', 'client__client_name')
    exclude = ('token_hash',)
    readonly_fields = (
        'user',
        'client',
        'kind',
        'scope',
        'created_at',
        'expires_at',
        'last_used_at',
    )
