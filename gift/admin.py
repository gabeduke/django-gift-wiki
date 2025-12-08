from django.contrib import admin
from django.contrib.auth import get_user_model

from gift.models import Suggestion, WishList, Item, ItemGroup, Category, Family, FeatureFlag, ScrapedWikiPage, ScrapedWikiItem

User = get_user_model()

admin.site.register(User)
admin.site.register(Family)
admin.site.register(WishList)
admin.site.register(Item)
admin.site.register(Suggestion)
admin.site.register(ItemGroup)
admin.site.register(Category)


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ['name', 'enabled', 'description', 'updated_at']
    list_filter = ['enabled', 'updated_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['enabled']  # Allow enabling/disabling from list view
    fieldsets = (
        ('Flag Information', {
            'fields': ('name', 'description', 'enabled')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
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
        ('Page Information', {
            'fields': ('title', 'url', 'item_count', 'scraped_at')
        }),
        ('Import Status', {
            'fields': ('is_imported', 'imported_by')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    actions = ['reset_import_status']

    def reset_import_status(self, request, queryset):
        """Admin action to reset import status for selected pages."""
        count = queryset.update(is_imported=False, imported_by=None)
        # Also reset user selections
        from django.contrib.auth import get_user_model
        User = get_user_model()
        User.objects.filter(selected_scraped_page__in=queryset).update(
            scraped_page_selected=False,
            selected_scraped_page=None
        )
        self.message_user(request, f'Reset import status for {count} page(s).')
    reset_import_status.short_description = 'Reset import status (for testing)'


@admin.register(ScrapedWikiItem)
class ScrapedWikiItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'scraped_page', 'purchased', 'created_at']
    list_filter = ['purchased', 'scraped_page', 'created_at']
    search_fields = ['name', 'description', 'original_text']
    readonly_fields = ['created_at']
