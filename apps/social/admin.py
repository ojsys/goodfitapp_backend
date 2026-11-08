from django.contrib import admin

from .models import (Announcement, Club, ClubGoal, ClubMembership, ClubTeamLog, Comment, Follow, Hide, Post,
                     PrivacyZone, Prop, RideInvite, RideSuggestion, Wave)


class MembershipInline(admin.TabularInline):
    model = ClubMembership
    extra = 0
    raw_id_fields = ['user']


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ['name', 'neighborhood', 'is_house']
    inlines = [MembershipInline]


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ['id', 'author', 'type', 'audience', 'created_at']
    list_filter = ['type', 'audience']
    raw_id_fields = ['author', 'tagged']


admin.site.register(Comment)
admin.site.register(Follow)
admin.site.register(Prop)
admin.site.register(Wave)
admin.site.register(PrivacyZone)


@admin.register(RideSuggestion)
class RideSuggestionAdmin(admin.ModelAdmin):
    """Until the business portal (Phase 10), club teams approve here."""
    list_display = ['id', 'club', 'member', 'status', 'created_at']
    list_filter = ['status', 'club']
    actions = ['approve']

    @admin.action(description='Approve: create the club event with the member as ride leader')
    def approve(self, request, queryset):
        from .community_views import approve_suggestion
        for s in queryset.filter(status='new'):
            approve_suggestion(s, request.user)


admin.site.register(ClubGoal)
admin.site.register(Announcement)
admin.site.register(ClubTeamLog)
admin.site.register(RideInvite)
admin.site.register(Hide)
