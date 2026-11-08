from django.contrib import admin, messages
from django.utils import timezone

from . import services as svc
from .models import BusinessAccount, BusinessMember, FeaturedPlacement, NameFlag, TeamInvite


class MemberInline(admin.TabularInline):
    model = BusinessMember
    raw_id_fields = ('user',)
    extra = 0


@admin.register(BusinessAccount)
class BusinessAccountAdmin(admin.ModelAdmin):
    """Verify businesses (within 1 business day). Set the Partner plan here
    while Stripe is off."""
    list_display = ('name', 'category', 'status', 'is_house', 'plan', 'plan_status', 'club', 'created_at')
    list_filter = ('status', 'category', 'plan', 'is_house')
    search_fields = ('name', 'work_email', 'address')
    raw_id_fields = ('club',)
    inlines = [MemberInline]
    actions = ['verify', 'reject']

    @admin.action(description='Verify the selected businesses')
    def verify(self, request, qs):
        n = 0
        for a in qs.exclude(status='verified'):
            a.status, a.verified_at = 'verified', timezone.now()
            a.save(update_fields=['status', 'verified_at'])
            svc._email(a, 'Your business is verified', f'{a.name} is verified on A Good Fit. You can feature events now.')
            n += 1
        self.message_user(request, f'{n} verified.')

    @admin.action(description='Don’t approve the selected businesses (set a review note first)')
    def reject(self, request, qs):
        qs.update(status='rejected')


@admin.register(FeaturedPlacement)
class FeaturedPlacementAdmin(admin.ModelAdmin):
    """A person reviews each featured event: guideline fit, accurate details,
    a real business. Approving charges the card (Stripe on), then schedules
    it. Set a review note before sending one back."""
    list_display = ('event', 'account', 'package', 'status', 'payment', 'starts_at', 'ends_at', 'submitted_at')
    list_filter = ('status', 'package', 'payment')
    search_fields = ('event__title', 'account__name')
    raw_id_fields = ('event', 'account', 'created_by', 'reviewed_by')
    readonly_fields = ('submitted_at', 'reviewed_at', 'reviewed_by', 'stripe_payment_intent', 'starts_at', 'ends_at')
    actions = ['approve', 'send_back']

    @admin.action(description='Approve (charge, then schedule)')
    def approve(self, request, qs):
        for p in qs:
            try:
                svc.approve(p, request.user)
                self.message_user(request, f'Approved {p.event.title} ({p.get_payment_display()}).')
            except svc.Denied as e:
                self.message_user(request, f'{p.event.title}: {e.message}', level=messages.ERROR)

    @admin.action(description='Send back with the review note')
    def send_back(self, request, qs):
        for p in qs:
            try:
                svc.reject(p, request.user, p.review_note)
            except svc.Denied as e:
                self.message_user(request, f'{p.event.title}: {e.message}', level=messages.ERROR)


@admin.register(TeamInvite)
class TeamInviteAdmin(admin.ModelAdmin):
    list_display = ('club', 'user', 'role', 'status', 'created_at')
    list_filter = ('status', 'role')
    raw_id_fields = ('club', 'user', 'invited_by')


@admin.register(NameFlag)
class NameFlagAdmin(admin.ModelAdmin):
    list_display = ('club', 'event', 'status', 'decided_at')
    raw_id_fields = ('club', 'event', 'decided_by')
