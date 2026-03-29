"""
URL configuration for giftwiki project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from gift import views as gift_views

urlpatterns = [
    path('', include('gift.urls')),  # Include the gift app's URLs at the root
    path('admin/', admin.site.urls),
    path('metrics/', gift_views.metrics_view, name='metrics'),  # Prometheus metrics endpoint
    path('auth.html', gift_views.auth_view, name='auth_page'),  # Auth page with injected config
    path('sessionLogin', gift_views.session_login_view, name='session_login'),  # Firebase session cookie creation (replaces Cloud Function)
]

# Serve static files in development
# Note: In development, Django automatically serves static files from app static directories
# when DEBUG=True and the staticfiles app is installed (which it is)
if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += [path('__debug__/', include('debug_toolbar.urls'))]
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
