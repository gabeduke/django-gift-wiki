from django.contrib import admin
from .models import WishList, Item, Suggestion, ItemGroup, Category

admin.site.register(WishList)
admin.site.register(Item)
admin.site.register(Suggestion)
admin.site.register(ItemGroup)
admin.site.register(Category)