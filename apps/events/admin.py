"""
Event Admin Configuration
"""

from django.contrib import admin
from .models import Event, EventRSVP


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    """Admin interface for Event model"""

    list_display = [
        'title',
        'host_name',
        'start_time',
        'location_name',
        'vibe',
        'price_type',
        'attendee_count',
        'is_active',
        'is_cancelled',
    ]
    list_filter = [
        'vibe',
        'price_type',
        'is_active',
        'is_cancelled',
        'start_time',
    ]
    search_fields = [
        'title',
        'description',
        'location_name',
        'location_address',
        'host__email',
    ]
    readonly_fields = [
        'attendee_count',
        'is_past',
        'created_at',
        'updated_at',
    ]
    date_hierarchy = 'start_time'
    ordering = ['-start_time']

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'description', 'image_url')
        }),
        ('Host', {
            'fields': ('host', 'host_name')
        }),
        ('Event Details', {
            'fields': ('vibe', 'price_type', 'price_amount', 'tags')
        }),
        ('Date & Time', {
            'fields': ('start_time', 'end_time')
        }),
        ('Location', {
            'fields': ('location_name', 'location_address', 'latitude', 'longitude')
        }),
        ('Capacity', {
            'fields': ('max_attendees', 'is_full', 'attendee_count')
        }),
        ('Additional Info', {
            'fields': ('what_to_bring',)
        }),
        ('Status', {
            'fields': ('is_active', 'is_cancelled', 'is_past')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(EventRSVP)
class EventRSVPAdmin(admin.ModelAdmin):
    """Admin interface for EventRSVP model"""

    list_display = [
        'user',
        'event',
        'status',
        'checked_in',
        'created_at',
    ]
    list_filter = [
        'status',
        'checked_in',
        'created_at',
    ]
    search_fields = [
        'user__email',
        'event__title',
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
