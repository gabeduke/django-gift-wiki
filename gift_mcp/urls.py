"""Routes for the MCP server. Mounted at the site root: the OAuth discovery
documents have to live at /.well-known/…, so this app can't take a prefix."""

from django.urls import path

from . import views

app_name = 'gift_mcp'

urlpatterns = [
    # The MCP endpoint itself (with and without a slash: a POST can't survive a redirect)
    path('mcp', views.mcp_endpoint, name='mcp'),
    path('mcp/', views.mcp_endpoint),
    # OAuth discovery (RFC 9728 / RFC 8414)
    path(
        '.well-known/oauth-protected-resource',
        views.protected_resource_metadata,
        name='protected_resource',
    ),
    path('.well-known/oauth-protected-resource/mcp', views.protected_resource_metadata),
    path(
        '.well-known/oauth-authorization-server',
        views.authorization_server_metadata,
        name='authorization_server',
    ),
    # OAuth
    path('oauth/register', views.register, name='oauth_register'),
    path('oauth/authorize', views.authorize, name='oauth_authorize'),
    path('oauth/token', views.token, name='oauth_token'),
    # A person's own tokens and connected apps
    path('connect-ai/', views.connect, name='connect_ai'),
]
