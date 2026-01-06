"""
Admin configuration for Activity models
"""

from django.contrib import admin
from .models import Activity, DailySummary


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    """Admin for Activity model"""

    list_display = ['title', 'user', 'type', 'start_time', 'duration', 'distance', 'calories_burned']
    list_filter = ['type', 'start_time', 'created_at']
    search_fields = ['user__email', 'title', 'notes']
    ordering = ['-start_time']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'type', 'title', 'notes')
        }),
        ('Time Tracking', {
            'fields': ('start_time', 'end_time', 'duration')
        }),
        ('Performance Metrics', {
            'fields': ('distance', 'calories_burned', 'average_speed', 'pace', 'elevation_gain', 'heart_rate_avg', 'heart_rate_max')
        }),
        ('Location', {
            'fields': ('start_latitude', 'start_longitude', 'start_address', 'route')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(DailySummary)
class DailySummaryAdmin(admin.ModelAdmin):
    """Admin for Daily Summary model"""

    list_display = ['user', 'date', 'total_steps', 'total_workouts', 'total_calories', 'total_distance']
    list_filter = ['date']
    search_fields = ['user__email']
    ordering = ['-date']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('User & Date', {
            'fields': ('user', 'date')
        }),
        ('Daily Totals', {
            'fields': ('total_steps', 'total_distance', 'total_calories', 'total_active_minutes', 'total_workouts')
        }),
        ('Goal Progress', {
            'fields': ('step_goal_progress', 'calorie_goal_progress', 'workout_goal_progress')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
