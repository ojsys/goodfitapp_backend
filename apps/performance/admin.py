from django.contrib import admin

from .models import Challenge, ChallengeEntry, Segment, SegmentEffort, Trophy


@admin.register(Segment)
class SegmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'area', 'kind', 'distance_m', 'avg_grade', 'is_active']
    list_filter = ['kind', 'is_active']
    search_fields = ['name', 'area']
    readonly_fields = ['distance_m', 'elev_diff_m', 'avg_grade', 'start_lat', 'start_lng', 'end_lat', 'end_lng',
                       'min_lat', 'max_lat', 'min_lng', 'max_lng']


@admin.register(SegmentEffort)
class SegmentEffortAdmin(admin.ModelAdmin):
    list_display = ['segment', 'user', 'elapsed_s', 'start_at', 'is_pr', 'private']
    list_filter = ['segment', 'is_pr']
    raw_id_fields = ['activity', 'user']


@admin.register(Challenge)
class ChallengeAdmin(admin.ModelAdmin):
    list_display = ['title', 'kind', 'target', 'starts_at', 'ends_at', 'featured', 'club']
    list_filter = ['kind', 'featured']
    filter_horizontal = ['segments']


admin.site.register(ChallengeEntry)
admin.site.register(Trophy)
