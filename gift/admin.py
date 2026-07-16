from django.contrib import admin
from django.contrib.auth import get_user_model

from gift.models import (
    Category,
    Family,
    FeatureFlag,
    Item,
    ItemGroup,
    ScrapedWikiItem,
    ScrapedWikiPage,
    Suggestion,
    WishList,
    AllowedEmail,
    LinkedEmail,
    Season,
)
from django.contrib.auth.admin import UserAdmin

User = get_user_model()

class CustomUserAdmin(UserAdmin):
    model = User
    fieldsets = UserAdmin.fieldsets + (
        ('Extra Info', {'fields': ('family_name', 'birthday', 'secret_santa_target', 'profile_picture')}),
    )

admin.site.register(User, CustomUserAdmin)
admin.site.register(Family)
admin.site.register(Season)
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.contrib import messages
import django.contrib.admin.helpers as admin_helpers

@admin.register(WishList)
class WishListAdmin(admin.ModelAdmin):
    list_display = ['title', 'owner']
    search_fields = ['title', 'owner__username']
    actions = ['merge_wishlists']

    def merge_wishlists(self, request, queryset):
        if 'apply' in request.POST:
            primary_id = request.POST.get('primary_wishlist')
            if not primary_id:
                self.message_user(request, "No primary wishlist selected.", level=messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())
            
            primary_wl = queryset.get(id=primary_id)
            secondary_wls = queryset.exclude(id=primary_id)
            
            for secondary in secondary_wls:
                secondary.items.all().update(wishlist=primary_wl)
                secondary.groups.all().update(wishlist=primary_wl)
                
                for manager in secondary.managers.all():
                    primary_wl.managers.add(manager)
                    
                secondary.delete()
                
            self.message_user(request, f"Successfully merged wishlists into '{primary_wl}'.")
            return HttpResponseRedirect(request.get_full_path())
            
        context = {
            'title': 'Merge Wishlists',
            'wishlists': queryset,
            'queryset': queryset,
            'opts': self.model._meta,
            'action_checkbox_name': admin_helpers.ACTION_CHECKBOX_NAME,
        }
        return render(request, 'admin/gift/wishlist/merge_wishlists.html', context)
    merge_wishlists.short_description = "Merge selected wishlists"
admin.site.register(Item)
admin.site.register(Suggestion)
admin.site.register(ItemGroup)
admin.site.register(Category)

@admin.register(AllowedEmail)
class AllowedEmailAdmin(admin.ModelAdmin):
    list_display = ['email', 'created_at']
    search_fields = ['email']

@admin.register(LinkedEmail)
class LinkedEmailAdmin(admin.ModelAdmin):
    list_display = ['email', 'user', 'created_at']
    search_fields = ['email', 'user__username', 'user__email']
    raw_id_fields = ['user']


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ['name', 'enabled', 'description', 'updated_at']
    list_filter = ['enabled', 'updated_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['enabled']  # Allow enabling/disabling from list view
    fieldsets = (
        ('Flag Information', {'fields': ('name', 'description', 'enabled')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    def save_model(self, request, obj, form, change):
        """Override save to clear feature flag cache."""
        super().save_model(request, obj, form, change)
        # Clear the in-memory cache when flags are changed
        from giftwiki.feature_flags import _clear_cache

        _clear_cache()


@admin.register(ScrapedWikiPage)
class ScrapedWikiPageAdmin(admin.ModelAdmin):
    list_display = ['title', 'item_count', 'is_imported', 'imported_by', 'scraped_at']
    list_filter = ['is_imported', 'scraped_at']
    search_fields = ['title', 'url']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Page Information', {'fields': ('title', 'url', 'item_count', 'scraped_at')}),
        ('Import Status', {'fields': ('is_imported', 'imported_by')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    actions = ['reset_import_status']

    def reset_import_status(self, request, queryset):
        """Admin action to reset import status for selected pages."""
        count = queryset.update(is_imported=False, imported_by=None)
        # Also reset user selections
        from django.contrib.auth import get_user_model

        User = get_user_model()
        User.objects.filter(selected_scraped_page__in=queryset).update(
            scraped_page_selected=False, selected_scraped_page=None
        )
        self.message_user(request, f'Reset import status for {count} page(s).')

    reset_import_status.short_description = 'Reset import status (for testing)'


@admin.register(ScrapedWikiItem)
class ScrapedWikiItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'scraped_page', 'purchased', 'created_at']
    list_filter = ['purchased', 'scraped_page', 'created_at']
    search_fields = ['name', 'description', 'original_text']
    readonly_fields = ['created_at']
