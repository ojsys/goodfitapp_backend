from django.contrib import admin

from .models import Decision, Match, MatchProfile


@admin.register(MatchProfile)
class MatchProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'gender', 'show_me', 'age_min', 'age_max', 'max_miles', 'cooldown_until')
    search_fields = ('user__email', 'user__first_name')
    raw_id_fields = ('user',)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'a', 'b', 'state', 'locked_at', 'met_at', 'ended_at')
    list_filter = ('state',)
    search_fields = ('a__email', 'b__email')
    raw_id_fields = ('a', 'b', 'chat', 'suggested_event', 'suggested_by', 'ended_by')


@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = ('actor', 'target', 'action', 'created_at')
    list_filter = ('action',)
    raw_id_fields = ('actor', 'target')
