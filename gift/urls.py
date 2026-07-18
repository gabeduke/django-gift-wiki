from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from . import views

app_name = 'gift'
urlpatterns = [
    # Home
    path('', views.home, name='home'),
    # Authentication
    # Signup removed - users are auto-created via Traefik forward auth
    path('profile/', views.profile, name='account'),
    path('select-scraped-page/', views.select_scraped_page, name='select_scraped_page'),
    path('logout/', views.logout_view, name='logout'),
    path('accounts/logout/', views.logout_view),  # Override Django's default POST-only logout
    path('accounts/', include('django.contrib.auth.urls')),  # Keep for login if needed
    path('password-reset-request/', views.password_reset_request, name='password_reset_request'),
    path('managed-user/<int:user_id>/edit/', views.edit_managed_user, name='edit_managed_user'),
    # Wishlists
    path('wishlist/create/', views.wishlist_create, name='create_wishlist'),
    path('wishlist/<int:wishlist_id>/', views.wishlist_detail, name='wishlist_detail'),
    path('wishlist/<int:wishlist_id>/edit/', views.wishlist_edit, name='edit_wishlist'),
    path('wishlist/<int:wishlist_id>/delete/', views.wishlist_delete, name='delete_wishlist'),
    path(
        'wishlist/<int:wishlist_id>/clear-purchased/',
        views.wishlist_clear_purchased,
        name='clear_purchased',
    ),
    path('wishlist/<int:wishlist_id>/add_item/', views.item_add, name='add_item'),
    path('wishlist/<int:wishlist_id>/add_item_ajax/', views.item_add_ajax, name='item_add_ajax'),
    # Items
    path('item/edit/<int:item_id>/', views.item_edit, name='edit_item'),
    path('item/delete/<int:item_id>/', views.item_delete, name='delete_item'),
    path('item/purchase/<int:item_id>/', views.item_purchase, name='purchase_item'),
    # Categories
    path('category/edit/<int:category_id>/', views.category_edit, name='edit_category'),
    # Public pages (no auth required)
    path('privacy/', views.privacy_view, name='privacy'),
    path('data-deletion/', views.data_deletion_view, name='data_deletion'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
