from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

app_name = "gift"
urlpatterns = [
    path('', views.landing_page, name='landing_page'),
    # path('health/', views.health_check, name='health_check'),
    path('signup/', views.SignUpView.as_view(), name='signup'),
    path('login/', auth_views.LoginView.as_view(template_name='gift/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('wishlist/<int:wishlist_id>/add_item/', views.add_item, name='add_item'),
    path('wishlist/<int:wishlist_id>/add_items_batch/', views.add_items_batch, name='add_items_batch'),
    path('item/edit/<int:item_id>/', views.edit_item, name='edit_item'),
    path('item/delete/<int:item_id>/', views.delete_item, name='delete_item'),
    path('wishlist/<int:wishlist_id>/', views.wishlist_detail, name='wishlist_detail'),
    path('item/purchase/<int:item_id>/', views.purchase_item, name='purchase_item'),
    path('wishlist/create/', views.create_wishlist, name='create_wishlist'),
    path('profile/', views.account_settings, name='account'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)