from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from . import exchange_views, views

app_name = 'gift'
urlpatterns = [
    # Home
    path('', views.home, name='home'),
    # Authentication
    # Signup removed - users are auto-created via Traefik forward auth
    path('profile/', views.profile, name='account'),
    path('profile/theme/', views.set_theme, name='set_theme'),
    path('profile/pin/<int:wishlist_id>/', views.pin_wishlist, name='pin_wishlist'),
    path('my-purchases/', views.my_purchases, name='my_purchases'),
    path('over-the-shoulder/', views.over_the_shoulder, name='over_the_shoulder'),
    path('received-gifts/', views.received_gifts, name='received_gifts'),
    path('changelog/', views.changelog, name='changelog'),
    path('changelog/dismiss/', views.changelog_dismiss, name='changelog_dismiss'),
    path('select-scraped-page/', views.select_scraped_page, name='select_scraped_page'),
    path('logout/', views.logout_view, name='logout'),
    # Ours, not Django's LogoutView: it also deletes __session and signs out of Firebase
    path('accounts/logout/', views.logout_view),
    path('accounts/', include('django.contrib.auth.urls')),  # Keep for login if needed
    path('password-reset-request/', views.password_reset_request, name='password_reset_request'),
    path('managed-user/create/', views.create_managed_user, name='create_managed_user'),
    path('managed-user/<int:user_id>/edit/', views.edit_managed_user, name='edit_managed_user'),
    path(
        'managed-user/<int:user_id>/assign-email/',
        views.assign_login_email,
        name='assign_login_email',
    ),
    # Gift exchanges
    path('exchanges/', exchange_views.exchange_list, name='exchange_list'),
    path('exchanges/new/', exchange_views.exchange_create, name='exchange_create'),
    path('exchanges/<int:exchange_id>/', exchange_views.exchange_detail, name='exchange_detail'),
    path('exchanges/<int:exchange_id>/join/', exchange_views.exchange_join, name='exchange_join'),
    path('exchanges/<int:exchange_id>/leave/', exchange_views.exchange_leave, name='exchange_leave'),
    path(
        'exchanges/<int:exchange_id>/not-this-time/',
        exchange_views.exchange_decline,
        name='exchange_decline',
    ),
    path('exchanges/<int:exchange_id>/edit/', exchange_views.exchange_edit, name='exchange_edit'),
    path(
        'exchanges/<int:exchange_id>/remove/<int:participant_id>/',
        exchange_views.exchange_remove,
        name='exchange_remove',
    ),
    path('exchanges/<int:exchange_id>/add/', exchange_views.exchange_add, name='exchange_add'),
    path('exchanges/<int:exchange_id>/letter/', exchange_views.exchange_letter, name='exchange_letter'),
    path(
        'exchanges/<int:exchange_id>/deliver/',
        exchange_views.exchange_deliver,
        name='exchange_deliver',
    ),
    path('exchanges/<int:exchange_id>/board/', exchange_views.exchange_board, name='exchange_board'),
    path(
        'exchanges/<int:exchange_id>/letters/<int:letter_id>/photo/',
        exchange_views.exchange_letter_image,
        name='exchange_letter_image',
    ),
    path(
        'exchanges/<int:exchange_id>/letters/<int:letter_id>/privacy/',
        exchange_views.exchange_letter_privacy,
        name='exchange_letter_privacy',
    ),
    path(
        'exchanges/<int:exchange_id>/letters/<int:letter_id>/read/',
        exchange_views.exchange_letter_read,
        name='exchange_letter_read',
    ),
    path('exchanges/<int:exchange_id>/draw/', exchange_views.exchange_draw, name='exchange_draw'),
    path(
        'exchanges/<int:exchange_id>/wrap-up/',
        exchange_views.exchange_wrap_up,
        name='exchange_wrap_up',
    ),
    path(
        'exchanges/<int:exchange_id>/opened/',
        exchange_views.exchange_reveal_seen,
        name='exchange_reveal_seen',
    ),
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
    path(
        'wishlist/<int:wishlist_id>/archive-purchased/',
        views.wishlist_archive_purchased,
        name='archive_purchased',
    ),
    path('wishlist/picker/', views.wishlist_picker, name='wishlist_picker'),
    path('wishlist/<int:wishlist_id>/glance/', views.wishlist_glance, name='wishlist_glance'),
    path('wishlist/<int:wishlist_id>/add_item/', views.item_add, name='add_item'),
    path(
        'wishlist/<int:wishlist_id>/add_surprise_item/',
        views.sneaky_item_add,
        name='add_sneaky_item',
    ),
    # Items
    path('item/quick-add/', views.item_quick_add, name='quick_add_item'),
    path('share/', views.share_target, name='share_target'),
    path('item/edit/<int:item_id>/', views.item_edit, name='edit_item'),
    path('item/delete/<int:item_id>/', views.item_delete, name='delete_item'),
    path('item/purchase/<int:item_id>/', views.item_purchase, name='purchase_item'),
    path('item/<int:item_id>/thank-you/', views.item_thank_you_toggle, name='toggle_thank_you'),
    # Categories
    path('category/edit/<int:category_id>/', views.category_edit, name='edit_category'),
    path(
        'wishlist/<int:wishlist_id>/category/create/',
        views.category_create_ajax,
        name='create_category_ajax',
    ),
    # Public pages (no auth required)
    path('privacy/', views.privacy_view, name='privacy'),
    path('data-deletion/', views.data_deletion_view, name='data_deletion'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
