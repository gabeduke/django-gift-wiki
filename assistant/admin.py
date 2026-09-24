from django.contrib import admin

from assistant.models import AssistantSettings, AssistantUsage


@admin.register(AssistantSettings)
class AssistantSettingsAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'per_user_monthly_messages', 'global_monthly_messages',
                    'model_name', 'enabled_until', 'updated_at']
    readonly_fields = ['updated_at']

    def has_add_permission(self, request):
        """One row only — reach it through the changelist."""
        return not AssistantSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AssistantUsage)
class AssistantUsageAdmin(admin.ModelAdmin):
    list_display = ['user', 'period', 'message_count', 'input_tokens', 'output_tokens']
    list_filter = ['period']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['user', 'period', 'message_count', 'input_tokens', 'output_tokens']
