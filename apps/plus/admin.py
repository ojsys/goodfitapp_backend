from django.contrib import admin

from .models import Subscription
from .services import refresh_plan


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """Give Plus with store "Given by the team" (blank end = no end)."""
    list_display = ('user', 'store', 'product', 'status', 'expires_at', 'will_renew', 'environment', 'updated_at')
    list_filter = ('store', 'status', 'product', 'environment')
    search_fields = ('user__email', 'user__first_name', 'original_id')
    raw_id_fields = ('user',)
    readonly_fields = ('access_until', 'last_event', 'last_event_at', 'created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        refresh_plan(obj.user)

    def delete_model(self, request, obj):
        user = obj.user
        super().delete_model(request, obj)
        refresh_plan(user)
