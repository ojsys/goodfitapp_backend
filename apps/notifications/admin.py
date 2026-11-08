from django.contrib import admin

from .models import Device, Notification, NotificationSettings


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['updated_at', 'recipient', 'kind', '__str__', 'read_at']
    list_filter = ['kind']
    search_fields = ['recipient__email']
    raw_id_fields = ['recipient', 'actor']


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['user', 'platform', 'last_seen']
    raw_id_fields = ['user']


admin.site.register(NotificationSettings)
