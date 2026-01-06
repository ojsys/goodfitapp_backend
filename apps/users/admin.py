"""
Admin configuration for User models
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, UserGoals, UserStats, UserPreferences


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin for custom User model"""

    list_display = ['email', 'display_name', 'online_status', 'is_active', 'is_staff', 'created_at']
    list_filter = ['is_active', 'is_staff', 'online_status', 'created_at']
    search_fields = ['email', 'display_name', 'first_name', 'last_name']
    ordering = ['-created_at']

    fieldsets = (
        ('Authentication', {
            'fields': ('email', 'password')
        }),
        ('Profile', {
            'fields': ('display_name', 'first_name', 'last_name', 'avatar_url', 'bio')
        }),
        ('Status', {
            'fields': ('online_status', 'last_seen')
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'display_name', 'password1', 'password2'),
        }),
    )

    readonly_fields = ['created_at', 'updated_at', 'last_seen']


@admin.register(UserGoals)
class UserGoalsAdmin(admin.ModelAdmin):
    """Admin for User Goals"""

    list_display = ['user', 'daily_step_goal', 'weekly_workout_goal', 'daily_calorie_goal']
    search_fields = ['user__email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(UserStats)
class UserStatsAdmin(admin.ModelAdmin):
    """Admin for User Stats"""

    list_display = ['user', 'current_streak', 'total_workouts', 'total_minutes', 'total_calories']
    search_fields = ['user__email']
    readonly_fields = ['created_at', 'updated_at']
    list_filter = ['current_streak']


@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    """Admin for User Preferences"""

    list_display = ['user', 'theme', 'units', 'profile_visibility']
    search_fields = ['user__email']
    readonly_fields = ['created_at', 'updated_at']
    list_filter = ['theme', 'units', 'profile_visibility']
