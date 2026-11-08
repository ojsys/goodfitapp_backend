"""
Moderation console (Django admin until the business portal, Phase 10).

Queue: open first, then unsafe, under 21, the rest; oldest first in each.
Pick reports and an outcome from the Action menu; reporters see the result
in Your reports. A decision about a member (suspend, age check, ban)
settles every open report about them.
"""

from django.contrib import admin, messages
from django.db.models import Case, Count, IntegerField, Q, When
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from . import moderation
from .models import Block, ModerationAction, Report

SEVERITY = {0: ('Unsafe', '#A8392C', '#F6E1DD'), 1: ('Under 21', '#7D6224', '#F3E8CC'), 2: ('Standard', '#4E5E2B', '#EEF2E2')}


def _pill(text, fg, bg):
    return format_html('<span style="display:inline-block;padding:2px 9px;border-radius:99px;font-weight:700;'
                       'font-size:11px;color:{};background:{}">{}</span>', fg, bg, text)


def _age(dt):
    s = (timezone.now() - dt).total_seconds()
    if s < 3600:
        return f'{int(s // 60)} min'
    if s < 86400:
        return f'{int(s // 3600)} h'
    return f'{int(s // 86400)} d'


def _decide(decision, label):
    def action(modeladmin, request, queryset):
        n = 0
        ids = list(queryset.filter(status='open').order_by('priority', 'created_at').values_list('id', flat=True))
        for pk in ids:
            r = Report.objects.select_related('target_user').get(pk=pk)
            if r.status != 'open':
                continue  # settled together with an earlier one
            n += moderation.decide(r, decision, request.user)
        modeladmin.message_user(request, f'{label}: {n} report{"s" if n != 1 else ""} resolved.', messages.SUCCESS)
    action.__name__ = f'decide_{decision}'
    action.short_description = label
    return action


class StatusFilter(admin.SimpleListFilter):
    title = 'queue'
    parameter_name = 'queue'

    def lookups(self, request, model_admin):
        return [('open', 'Open'), ('resolved', 'Resolved'), ('all', 'All')]

    def queryset(self, request, queryset):
        v = self.value() or 'open'
        return queryset if v == 'all' else queryset.filter(status=v)

    def choices(self, changelist):
        for lookup, title in self.lookup_choices:
            yield {'selected': (self.value() or 'open') == lookup, 'display': title,
                   'query_string': changelist.get_query_string({self.parameter_name: lookup})}


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['severity', 'age', 'kind', 'reason_text', 'about', 'times_reported', 'reporter_link', 'status_pill']
    list_display_links = ['reason_text']
    list_filter = [StatusFilter, 'priority', 'target_kind', 'reason', 'outcome']
    search_fields = ['target_user__email', 'target_user__first_name', 'target_user__display_name',
                     'reporter__email', 'snapshot', 'details', 'context']
    list_per_page = 50
    actions = [
        _decide('no_violation', 'No violation'),
        _decide('remove_warn', 'Remove it and warn the member'),
        _decide('warn', 'Warn the member (keep the content)'),
        _decide('suspend', 'Remove it and suspend the member'),
        _decide('age_check', 'Under 21: pause account for an age check'),
        _decide('ban', 'Ban the member'),
    ]
    readonly_fields = ['severity', 'kind', 'reason_text', 'context', 'about', 'reporter_link', 'created_at',
                       'what_was_reported', 'details', 'member_history', 'status', 'outcome', 'outcome_note',
                       'reviewed_by', 'resolved_at']
    fieldsets = [
        ('Report', {'fields': ['severity', 'kind', 'reason_text', 'context', 'created_at', 'reporter_link']}),
        ('What was reported', {'fields': ['about', 'what_was_reported', 'details']}),
        ('Member history', {'fields': ['member_history']}),
        ('Decision', {'fields': ['status', 'outcome', 'outcome_note', 'reviewed_by', 'resolved_at'],
                      'description': 'Decide from the queue: tick this report and pick an outcome from the '
                                     'Action menu.'}),
    ]

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return (super().get_queryset(request).select_related('target_user', 'reporter', 'reviewed_by')
                .annotate(open_about=Count('target_user__reports_about',
                                           filter=Q(target_user__reports_about__status='open'))))

    def get_ordering(self, request):
        # Without this the model's newest-first ordering wins over the queue order.
        open_first = Case(When(status='open', then=0), default=1, output_field=IntegerField())
        return [open_first.asc(), 'priority', 'created_at']

    def changelist_view(self, request, extra_context=None):
        open_qs = Report.objects.filter(status='open')
        c = open_qs.aggregate(n=Count('id'), unsafe=Count('id', filter=Q(priority=0)),
                              u21=Count('id', filter=Q(priority=1)))
        extra_context = dict(extra_context or {},
                             title=f'Moderation queue · {c["n"]} open · {c["unsafe"]} unsafe · {c["u21"]} under 21')
        return super().changelist_view(request, extra_context)

    @admin.display(description='Severity', ordering='priority')
    def severity(self, r):
        return _pill(*SEVERITY[r.priority])

    @admin.display(description='Waiting', ordering='created_at')
    def age(self, r):
        return _age(r.created_at) if r.status == 'open' else '·'

    @admin.display(description='What', ordering='target_kind')
    def kind(self, r):
        return r.get_target_kind_display()

    @admin.display(description='Reason', ordering='reason')
    def reason_text(self, r):
        return r.reason_label

    def _user_link(self, u):
        if not u:
            return '·'
        url = reverse('admin:users_user_change', args=[u.id])
        state = '' if u.is_active else ' (inactive)'
        return format_html('<a href="{}">{}</a>{}', url, u.full_name or u.email, state)

    @admin.display(description='About')
    def about(self, r):
        return self._user_link(r.target_user)

    @admin.display(description='Open about them', ordering='open_about')
    def times_reported(self, r):
        n = getattr(r, 'open_about', 0)
        return format_html('<b style="color:#A8392C">{}</b>', n) if n > 1 else n

    @admin.display(description='Reporter')
    def reporter_link(self, r):
        return self._user_link(r.reporter)

    @admin.display(description='Status', ordering='status')
    def status_pill(self, r):
        if r.status == 'open':
            return _pill('Open', '#7D6224', '#F3E8CC')
        return _pill(r.get_outcome_display() or 'Resolved', '#4E5E2B', '#EEF2E2')

    @admin.display(description='Snapshot')
    def what_was_reported(self, r):
        return format_html('<pre style="white-space:pre-wrap;max-width:780px;font-size:13px;margin:0;'
                           'background:var(--darkened-bg);color:var(--body-fg);border:1px solid var(--hairline-color);'
                           'padding:10px;border-radius:8px">{}</pre>', r.snapshot or '(nothing captured)')

    @admin.display(description='History')
    def member_history(self, r):
        u = r.target_user
        if not u:
            return '·'
        reports = Report.objects.filter(target_user=u).exclude(pk=r.pk)
        acts = ModerationAction.objects.filter(member=u)[:10]
        head = format_html('{} other report(s), {} upheld. Blocked by {} member(s).', reports.count(),
                           reports.filter(outcome='action_taken').count(), Block.objects.filter(blocked=u).count())
        rows = format_html_join('', '<li>{} · {}</li>', ((a.created_at.strftime('%b %d %Y'), a.get_kind_display())
                                                         for a in acts))
        return format_html('{}<ul style="margin:6px 0 0 16px">{}</ul>', head, rows) if acts else head


@admin.register(ModerationAction)
class ModerationActionAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'member', 'kind', 'by', 'report']
    list_filter = ['kind']
    search_fields = ['member__email', 'member__first_name', 'note']
    raw_id_fields = ['member', 'report', 'by']
    actions = ['reinstate']

    @admin.action(description='Reinstate these members (reactivate the account)')
    def reinstate(self, request, queryset):
        n = 0
        for a in queryset.select_related('member'):
            if not a.member.is_active:
                a.member.is_active = True
                a.member.save(update_fields=['is_active'])
                ModerationAction.objects.create(member=a.member, kind='reinstated', by=request.user)
                n += 1
        self.message_user(request, f'Reinstated {n} member(s).', messages.SUCCESS)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'blocker', 'blocked']
    search_fields = ['blocker__email', 'blocked__email']
    raw_id_fields = ['blocker', 'blocked']
