from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

from . import views

app_name = "gift"
urlpatterns = [
    # Home
    path('', views.home, name='home'),

    # Authentication
    path('signup/', views.SignUpView.as_view(), name='signup'),
    path('profile/', views.profile, name='account'),
    path('accounts/', include('django.contrib.auth.urls')),

    # Wishlists
    path('wishlist/create/', views.wishlist_create, name='create_wishlist'),
    path('wishlist/<int:wishlist_id>/', views.wishlist_detail, name='wishlist_detail'),
    path('wishlist/<int:wishlist_id>/edit/', views.wishlist_edit, name='edit_wishlist'),
    path('wishlist/<int:wishlist_id>/delete/', views.wishlist_delete, name='delete_wishlist'),
    path('wishlist/<int:wishlist_id>/add_item/', views.item_add, name='add_item'),
    path('wishlist/<int:wishlist_id>/add_item_ajax/', views.item_add_ajax, name='item_add_ajax'),

    # Items
    path('item/edit/<int:item_id>/', views.item_edit, name='edit_item'),
    path('item/delete/<int:item_id>/', views.item_delete, name='delete_item'),
    path('item/purchase/<int:item_id>/', views.item_purchase, name='purchase_item'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)