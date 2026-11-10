"""Staff dashboard API (/api/staff/), used by the React app at /staff/.

Signed in with the same Django session as /admin/ (staff accounts only).
Every change is written to Django's admin log, so /admin/ and the dashboard
share one history.
"""

import json
from datetime import timedelta

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Count, Q, Sum
from django.db.models.deletion import Collector
from django.db.models.functions import TruncDate
from django.forms import modelform_factory
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import permissions
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import registry as reg

User = get_user_model()
PAGE = 50


def bad(message, status=400, code='bad', **extra):
    return Response({'code': code, 'message': message, **extra}, status=status)


def role(u):
    if u.is_superuser:
        return 'admin'
    return 'staff' if u.is_staff else None


def me(u):
    if not (u.is_authenticated and u.is_active and u.is_staff):
        return None
    return {'id': u.id, 'name': u.full_name or u.email, 'first_name': u.first_name or (u.full_name or u.email).split()[0],
            'email': u.email, 'role': role(u), 'groups': list(u.groups.values_list('name', flat=True))}


def log(user, obj, flag, message):
    LogEntry.objects.log_actions(user.id, [obj], flag, change_message=message[:1000], single_object=True)


class IsStaff(permissions.BasePermission):
    message = 'Staff accounts only.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_active and u.is_staff)


class Staff(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsStaff]
    need = None  # 'app.codename' Django permission for this view

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.need and not request.user.is_superuser and not request.user.has_perm(self.need):
            self.permission_denied(request, message='You don’t have access to this. Ask an admin.')


# ------------------------------------------------------------------ session

@method_decorator(ensure_csrf_cookie, name='dispatch')
class SessionView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({'csrf': get_token(request), 'user': me(request.user)})


@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        u = authenticate(request, username=email, password=request.data.get('password') or '')
        if u is None or not u.is_active:
            return bad('That email and password don’t match.', code='login')
        if not u.is_staff:
            return bad('This account isn’t a staff account.', code='not_staff', status=403)
        login(request, u)
        return Response({'csrf': get_token(request), 'user': me(u)})


@method_decorator(csrf_protect, name='dispatch')
class LogoutView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        logout(request)
        return Response({'ok': True, 'csrf': get_token(request)})


# ----------------------------------------------------------------- overview

def _daily(qs, field, days):
    since = timezone.now() - timedelta(days=days)
    rows = (qs.filter(**{f'{field}__gte': since}).annotate(d=TruncDate(field)).values('d')
            .annotate(n=Count('id')).order_by('d'))
    by = {r['d']: r['n'] for r in rows}
    today = timezone.localdate()
    return [{'day': (today - timedelta(days=i)).isoformat(), 'n': by.get(today - timedelta(days=i), 0)}
            for i in range(days - 1, -1, -1)]


class OverviewView(Staff):
    def get(self, request):
        from apps.activities.models import Activity
        from apps.business.models import BusinessAccount, FeaturedPlacement
        from apps.events.models import Event
        from apps.plus.models import Subscription
        from apps.safety.models import Report, SupportMessage
        from apps.social.models import Club, Post

        now = timezone.now()
        d7, d30 = now - timedelta(days=7), now - timedelta(days=30)
        members = User.objects.filter(is_staff=False)
        active7 = Activity.objects.filter(start_time__gte=d7).values('user').distinct().count()
        open_reports = Report.objects.filter(status='open')
        revenue = FeaturedPlacement.objects.filter(payment='charged').aggregate(s=Sum('price_cents'))['s'] or 0
        u = request.user
        return Response({
            'stats': [
                {'k': 'Members', 'v': members.count(), 'n': f'+{members.filter(created_at__gte=d7).count()} this week'},
                {'k': 'Active this week', 'v': active7, 'n': 'recorded an activity'},
                {'k': 'Activities', 'v': Activity.objects.count(),
                 'n': f'+{Activity.objects.filter(start_time__gte=d7).count()} this week'},
                {'k': 'Upcoming events', 'v': Event.objects.filter(start_time__gte=now).count(),
                 'n': f'{Club.objects.count()} clubs'},
                {'k': 'Plus members', 'v': Subscription.objects.filter(status__in=['trial', 'active', 'grace']).count(),
                 'n': 'active subscriptions'},
                {'k': 'Featured revenue', 'v': f'${revenue / 100:,.0f}', 'n': 'charged to date'},
            ],
            'queues': [
                {'key': 'reports', 'label': 'Open reports', 'n': open_reports.count(),
                 'urgent': open_reports.filter(priority=Report.PRIORITY_UNSAFE).count(),
                 'allowed': u.is_superuser or u.has_perm('safety.change_report')},
                {'key': 'featured', 'label': 'Featured events to review',
                 'n': FeaturedPlacement.objects.filter(status='in_review').count(), 'urgent': 0,
                 'allowed': u.is_superuser or u.has_perm('business.change_featuredplacement')},
                {'key': 'businesses', 'label': 'Businesses to verify',
                 'n': BusinessAccount.objects.filter(status='pending', is_house=False).count(), 'urgent': 0,
                 'allowed': u.is_superuser or u.has_perm('business.change_businessaccount')},
                {'key': 'support', 'label': 'Support messages',
                 'n': SupportMessage.objects.filter(handled=False).count(),
                 'urgent': SupportMessage.objects.filter(handled=False, topic='safety').count(),
                 'allowed': u.is_superuser or u.has_perm('safety.change_supportmessage')},
            ],
            'signups': _daily(members, 'created_at', 30),
            'activities': _daily(Activity.objects.all(), 'start_time', 30),
            'mix': list(Activity.objects.filter(start_time__gte=d30).values('type').annotate(n=Count('id'))
                        .order_by('-n')[:6]),
            'recent': [_log_item(e) for e in LogEntry.objects.select_related('user', 'content_type')[:8]],
            'posts_week': Post.objects.filter(created_at__gte=d7).count(),
        })


def _log_item(e):
    ct = e.content_type
    model = f'{ct.app_label}.{ct.model}' if ct else None
    try:
        msg = e.get_change_message()
    except (ValueError, json.JSONDecodeError):
        msg = e.change_message
    return {'id': e.id, 'when': e.action_time.isoformat(), 'by': (e.user.full_name or e.user.email) if e.user else '—',
            'action': {ADDITION: 'added', CHANGE: 'changed', DELETION: 'deleted'}.get(e.action_flag, 'changed'),
            'model': model, 'model_name': str(ct.model_class()._meta.verbose_name).capitalize()
            if ct and ct.model_class() else (ct.model if ct else ''),
            'object_id': e.object_id, 'object': e.object_repr, 'message': msg}


class LogView(Staff):
    def get(self, request):
        qs = LogEntry.objects.select_related('user', 'content_type')
        if request.GET.get('model'):
            m = reg.model_for(request.GET['model'])
            if not m:
                return bad('Unknown model.', 404)
            qs = qs.filter(content_type=ContentType.objects.get_for_model(m))
            if request.GET.get('object'):
                qs = qs.filter(object_id=str(request.GET['object']))
        if request.GET.get('user'):
            qs = qs.filter(user_id=request.GET['user'])
        page = max(int(request.GET.get('page') or 1), 1)
        total = qs.count()
        return Response({'total': total, 'page': page, 'pages': max((total + PAGE - 1) // PAGE, 1),
                         'items': [_log_item(e) for e in qs[(page - 1) * PAGE:page * PAGE]]})


# ------------------------------------------------------------ data browser

class ModelsView(Staff):
    def get(self, request):
        groups = {}
        for m in reg.all_models():
            s = reg.summary(request.user, m)
            if not s['perms']['view']:
                continue
            s['count'] = m._default_manager.count()
            groups.setdefault(m._meta.app_label, {'app': m._meta.app_label, 'label': s['app_label'], 'models': []})
            groups[m._meta.app_label]['models'].append(s)
        order = {a: i for i, a in enumerate(reg.APPS)}
        out = sorted(groups.values(), key=lambda g: order.get(g['app'], 99))
        for g in out:
            g['models'].sort(key=lambda s: s['name'])
        return Response({'apps': out})


def _model(request, label, action='view'):
    m = reg.model_for(label)
    if not m:
        return None, bad('That isn’t something the dashboard knows about.', 404)
    if not reg.can(request.user, action, m):
        return None, bad('You don’t have access to this. Ask an admin.', 403, code='forbidden')
    return m, None


def _search(m, q):
    cond = Q()
    for s in reg.search_fields(m):
        cond |= Q(**{f'{s}__icontains': q})
    if q.isdigit():
        cond |= Q(pk=int(q))
    return cond


class ModelListView(Staff):
    def get(self, request, label):
        m, err = _model(request, label)
        if err:
            return err
        u = request.user
        if request.GET.get('schema'):
            return Response({'model': reg.summary(u, m), 'fields': [reg.meta_field(u, m, f) for f in reg.fields(m)]})
        qs = m._default_manager.all()
        rel = [f.name for f in reg.fields(m) if f.is_relation]
        if rel:
            qs = qs.select_related(*rel[:8])
        q = (request.GET.get('q') or '').strip()
        if q:
            try:
                qs = qs.filter(_search(m, q))
            except Exception:  # noqa: BLE001 - an odd admin search field
                qs = qs.filter(pk=int(q)) if q.isdigit() else qs.none()
        names = {f.name: f for f in reg.fields(m)}
        for k, v in request.GET.items():
            if k.startswith('f_'):
                name = k[2:]
                f = names.get(name)
                if not f or reg.hidden(u, m, f):
                    continue
                if isinstance(f, models.BooleanField):
                    qs = qs.filter(**{name: v == 'true'})
                elif f.is_relation:
                    qs = qs.filter(**{f'{name}_id': v or None})
                else:
                    qs = qs.filter(**{name: v})
        order = request.GET.get('order') or ''
        if order.lstrip('-') in names and not reg.hidden(u, m, names[order.lstrip('-')]):
            qs = qs.order_by(order, '-pk')
        elif not m._meta.ordering:
            qs = qs.order_by('-pk')
        page = max(int(request.GET.get('page') or 1), 1)
        total = qs.count()
        cols = reg.columns(m)
        colf = [names[c] for c in cols]
        rows = [{'pk': o.pk, 'label': reg.label(o), 'cells': {f.name: reg.value(u, m, o, f) for f in colf}}
                for o in qs[(page - 1) * PAGE:page * PAGE]]
        return Response({
            'model': reg.summary(u, m), 'total': total, 'page': page, 'pages': max((total + PAGE - 1) // PAGE, 1),
            'columns': [reg.meta_field(u, m, f) for f in colf], 'filters': reg.filters(m), 'rows': rows,
            'searchable': bool(reg.search_fields(m)),
        })

    def post(self, request, label):
        m, err = _model(request, label, 'add')
        if err:
            return err
        if reg.key(m) in reg.NO_CREATE:
            return bad('These aren’t created here.', 403, code='forbidden')
        return _save(request, m, m(), ADDITION)


def _save(request, m, obj, flag):
    u = request.user
    editable = [f for f in reg.fields(m) if reg.meta_field(u, m, f)['editable']]
    data = request.data or {}
    names = [f.name for f in editable if f.name in data]
    if flag == ADDITION:
        names = [f.name for f in editable]
    if not names:
        return bad('Nothing to change.')
    Form = modelform_factory(m, fields=names)
    initial = {}
    for f in editable:
        if f.name in names:
            v = data.get(f.name, getattr(obj, f.attname) if flag == CHANGE else None)
            if isinstance(f, models.JSONField) and not isinstance(v, str):
                v = json.dumps(v)
            if isinstance(f, models.BooleanField) and v is None:
                v = False
            initial[f.name] = '' if v is None else v
    form = Form(data=initial, instance=obj)
    if not form.is_valid():
        return bad('Check the highlighted fields.', code='invalid',
                   errors={k: [str(e) for e in v] for k, v in form.errors.items()})
    changed = form.changed_data
    with transaction.atomic():
        try:
            if flag == ADDITION:
                obj = form.save()
            else:
                # Only what changed (plus updated_at), so an edit doesn't bump
                # other automatic timestamps such as a member's last seen.
                obj = form.save(commit=False)
                auto = [f.name for f in reg.fields(m) if getattr(f, 'auto_now', False) and f.name == 'updated_at']
                if changed:
                    obj.save(update_fields=[m._meta.get_field(c).name for c in changed] + auto)
        except ValidationError as e:
            return bad('; '.join(e.messages))
        if flag == ADDITION:
            log(u, obj, ADDITION, json.dumps([{'added': {}}]))
        elif changed:
            log(u, obj, CHANGE, json.dumps([{'changed': {'fields': [
                str(m._meta.get_field(c).verbose_name).capitalize() for c in changed]}}]))
    return Response(_detail(u, m, obj), status=201 if flag == ADDITION else 200)


def _detail(u, m, obj):
    data = {'model': reg.summary(u, m), 'pk': obj.pk, 'label': reg.label(obj, 200),
            'fields': [{**reg.meta_field(u, m, f), 'value': reg.value(u, m, obj, f)} for f in reg.fields(m)]}
    # Things that point at this record, with counts and a link to the list.
    rel = []
    for r in m._meta.related_objects:
        rm = r.related_model
        if not reg.model_for(reg.key(rm)) or not reg.can(u, 'view', rm) or r.many_to_many:
            continue
        try:
            n = rm._default_manager.filter(**{r.field.name: obj.pk}).count()
        except Exception:  # noqa: BLE001
            continue
        if n:
            rel.append({'model': reg.key(rm), 'name': str(rm._meta.verbose_name_plural).capitalize(),
                        'field': r.field.name, 'via': str(r.field.verbose_name), 'count': n})
    data['related'] = sorted(rel, key=lambda r: -r['count'])[:24]
    data['history'] = [_log_item(e) for e in LogEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(m), object_id=str(obj.pk)).select_related(
        'user', 'content_type')[:20]]
    if reg.key(m) == 'users.user':
        data['member'] = _member_extra(obj)
    return data


class ModelDetailView(Staff):
    def _obj(self, request, label, pk, action):
        m, err = _model(request, label, action)
        if err:
            return None, None, err
        try:
            return m, m._default_manager.get(pk=pk), None
        except (m.DoesNotExist, ValueError, ValidationError):
            return None, None, bad('That record doesn’t exist (it may have been deleted).', 404)

    def get(self, request, label, pk):
        m, obj, err = self._obj(request, label, pk, 'view')
        if err:
            return err
        d = _detail(request.user, m, obj)
        if request.GET.get('delete_preview') and reg.can(request.user, 'delete', m):
            c = Collector(using='default')
            try:
                c.collect([obj])
                d['delete_preview'] = sorted(
                    [{'name': str(model._meta.verbose_name_plural).capitalize(), 'count': len(objs)}
                     for model, objs in c.data.items()], key=lambda x: -x['count'])
            except Exception as e:  # noqa: BLE001 - protected relations
                d['delete_preview'] = None
                d['delete_blocked'] = str(e)[:300]
        return Response(d)

    def patch(self, request, label, pk):
        m, obj, err = self._obj(request, label, pk, 'change')
        if err:
            return err
        if reg.key(m) == 'users.user' and not request.user.is_superuser:
            # Staff can't hand out staff/admin rights.
            for k in ('is_staff', 'is_superuser'):
                if k in (request.data or {}):
                    return bad('Only admins can change staff access.', 403, code='forbidden')
        return _save(request, m, obj, CHANGE)

    def delete(self, request, label, pk):
        m, obj, err = self._obj(request, label, pk, 'delete')
        if err:
            return err
        if reg.key(m) == 'users.user' and obj.pk == request.user.pk:
            return bad('You can’t delete your own account here.')
        log(request.user, obj, DELETION, '')
        try:
            obj.delete()
        except Exception as e:  # noqa: BLE001 - protected relations
            return bad(f'Couldn’t delete: {str(e)[:200]}', 409)
        return Response(status=204)


class OptionsView(Staff):
    """Picker for a link to another record (id + label)."""

    def get(self, request, label):
        m, err = _model(request, label)
        if err:
            return err
        qs = m._default_manager.all()
        q = (request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(_search(m, q))
        return Response({'items': [{'id': o.pk, 'label': reg.label(o)} for o in qs.order_by('-pk')[:20]]})


# ------------------------------------------------------------------- members

def _member_extra(u):
    from apps.activities.models import Activity
    from apps.safety.models import ModerationAction, Report
    return {
        'active': u.is_active, 'role': role(u), 'plan': getattr(u, 'plan', ''),
        'activities': Activity.objects.filter(user=u).count(),
        'reports_about': Report.objects.filter(target_user=u).count(),
        'open_reports': Report.objects.filter(target_user=u, status='open').count(),
        'actions': [{'kind': a.get_kind_display(), 'when': a.created_at.isoformat(), 'note': a.note,
                     'by': (a.by.full_name or a.by.email) if a.by else '—'}
                    for a in ModerationAction.objects.filter(member=u).select_related('by')[:10]],
    }


class MemberActionView(Staff):
    need = 'users.change_user'

    def post(self, request, pk, action):
        from apps.safety.models import ModerationAction
        try:
            u = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return bad('No such member.', 404)
        if u.is_staff and not request.user.is_superuser:
            return bad('Only admins can act on staff accounts.', 403, code='forbidden')
        if u.pk == request.user.pk:
            return bad('You can’t do this to your own account.')
        note = (request.data.get('note') or '')[:300]
        if action == 'suspend':
            if not u.is_active:
                return bad('Already suspended.', 409)
            u.is_active = False
            u.save(update_fields=['is_active'])
            ModerationAction.objects.create(member=u, kind='suspended', by=request.user, note=note)
        elif action == 'reinstate':
            if u.is_active:
                return bad('This account is active.', 409)
            u.is_active = True
            u.save(update_fields=['is_active'])
            ModerationAction.objects.create(member=u, kind='reinstated', by=request.user, note=note)
        else:
            return bad('Unknown action.', 404)
        log(request.user, u, CHANGE, f'{action.capitalize()}d from the staff dashboard. {note}'.strip())
        return Response(_detail(request.user, User, u))


# -------------------------------------------------------------------- queues

def _when(dt):
    return dt.isoformat() if dt else None


def _who(u):
    return {'id': u.id, 'name': u.full_name or u.email, 'email': u.email} if u else None


DECISIONS = [
    ['no_violation', 'No violation'],
    ['remove_warn', 'Remove it and warn'],
    ['warn', 'Warn (keep it)'],
    ['suspend', 'Remove and suspend'],
    ['age_check', 'Under 21: age check'],
    ['ban', 'Ban the member'],
]


class ReportsView(Staff):
    need = 'safety.change_report'

    def get(self, request):
        from apps.safety.models import Report
        state = request.GET.get('status') or 'open'
        qs = Report.objects.select_related('reporter', 'target_user', 'reviewed_by')
        qs = qs.filter(status=state).order_by('priority', 'created_at') if state == 'open' \
            else qs.filter(status=state).order_by('-resolved_at')
        counts = dict(Report.objects.filter(status='open').values_list('target_user').annotate(n=Count('id')))
        items = [{
            'id': r.id, 'priority': r.priority, 'severity': r.get_priority_display(), 'kind': r.get_target_kind_display(),
            'reason': r.reason_label, 'context': r.context, 'snapshot': r.snapshot, 'details': r.details,
            'about': _who(r.target_user), 'about_active': r.target_user.is_active if r.target_user else None,
            'times': counts.get(r.target_user_id, 0), 'reporter': _who(r.reporter), 'created_at': _when(r.created_at),
            'status': r.status, 'outcome': r.get_outcome_display() if r.outcome else '', 'outcome_note': r.outcome_note,
            'reviewed_by': _who(r.reviewed_by), 'resolved_at': _when(r.resolved_at),
        } for r in qs[:100]]
        return Response({'items': items, 'decisions': DECISIONS,
                         'open': Report.objects.filter(status='open').count()})


class ReportDecideView(Staff):
    need = 'safety.change_report'

    def post(self, request, pk):
        from apps.safety import moderation
        from apps.safety.models import Report
        decision = request.data.get('decision')
        if decision not in dict(DECISIONS):
            return bad('Pick an outcome.')
        try:
            r = Report.objects.select_related('target_user').get(pk=pk)
        except Report.DoesNotExist:
            return bad('No such report.', 404)
        if r.status != 'open':
            return bad('This report was already settled.', 409)
        n = moderation.decide(r, decision, request.user, (request.data.get('note') or '').strip())
        log(request.user, r, CHANGE, f'{dict(DECISIONS)[decision]} ({n} report{"s" if n != 1 else ""} resolved)')
        return Response({'resolved': n})


def _placement(p):
    e = p.event
    return {'id': p.id, 'status': p.status, 'status_label': p.get_status_display(), 'package': p.get_package_display(),
            'price': f'${p.price_cents / 100:,.0f}', 'payment': p.get_payment_display(),
            'account': {'id': p.account_id, 'name': p.account.name, 'verified': p.account.status == 'verified'},
            'event': {'id': e.id, 'title': e.title, 'description': e.description, 'start_time': _when(e.start_time),
                      'location': e.location_name, 'address': e.location_address},
            'neighborhoods': p.neighborhoods, 'interests': p.interests, 'starts_at': _when(p.starts_at),
            'ends_at': _when(p.ends_at), 'submitted_at': _when(p.submitted_at), 'review_note': p.review_note,
            'reviewed_by': _who(p.reviewed_by), 'created_by': _who(p.created_by)}


class PlacementsView(Staff):
    need = 'business.change_featuredplacement'

    def get(self, request):
        from apps.business.models import FeaturedPlacement
        state = request.GET.get('status') or 'in_review'
        qs = FeaturedPlacement.objects.select_related('account', 'event', 'reviewed_by', 'created_by')
        qs = qs.filter(status=state).order_by('submitted_at' if state == 'in_review' else '-reviewed_at')
        return Response({'items': [_placement(p) for p in qs[:100]],
                         'counts': dict(FeaturedPlacement.objects.values_list('status').annotate(n=Count('id')))})


class PlacementActView(Staff):
    need = 'business.change_featuredplacement'

    def post(self, request, pk, action):
        from apps.business import services as svc
        from apps.business.models import FeaturedPlacement
        try:
            p = FeaturedPlacement.objects.select_related('account', 'event').get(pk=pk)
        except FeaturedPlacement.DoesNotExist:
            return bad('No such featured event.', 404)
        try:
            if action == 'approve':
                svc.approve(p, request.user)
                msg = f'Approved ({p.get_payment_display()})'
            elif action == 'reject':
                note = (request.data.get('note') or '').strip()
                if not note:
                    return bad('Say what needs to change. The business sees this note.')
                svc.reject(p, request.user, note)
                msg = f'Sent back: {note}'
            else:
                return bad('Unknown action.', 404)
        except svc.Denied as e:
            return bad(e.message, e.http, code=e.code)
        p.refresh_from_db()
        log(request.user, p, CHANGE, msg)
        return Response(_placement(p))


def _business(a):
    return {'id': a.id, 'name': a.name, 'category': a.get_category_display(), 'address': a.address, 'website': a.website, 'work_email': a.work_email,
            'status': a.status, 'status_label': a.get_status_display(), 'plan': a.plan, 'is_house': a.is_house,
            'created_at': _when(a.created_at), 'verified_at': _when(a.verified_at), 'review_note': a.review_note,
            'team': [{'name': m.user.full_name or m.user.email, 'email': m.user.email, 'role': m.role}
                     for m in a.members.select_related('user')[:6]]}


class BusinessesView(Staff):
    need = 'business.change_businessaccount'

    def get(self, request):
        from apps.business.models import BusinessAccount
        state = request.GET.get('status') or 'pending'
        qs = BusinessAccount.objects.filter(status=state, is_house=False).order_by(
            'created_at' if state == 'pending' else '-created_at')
        return Response({'items': [_business(a) for a in qs[:100]],
                         'counts': dict(BusinessAccount.objects.filter(is_house=False).values_list('status')
                                        .annotate(n=Count('id')))})


class BusinessActView(Staff):
    need = 'business.change_businessaccount'

    def post(self, request, pk, action):
        from apps.business import services as svc
        from apps.business.models import BusinessAccount
        try:
            a = BusinessAccount.objects.get(pk=pk)
        except BusinessAccount.DoesNotExist:
            return bad('No such business.', 404)
        if action == 'verify':
            a.status, a.verified_at = 'verified', timezone.now()
            a.save(update_fields=['status', 'verified_at'])
            svc._email(a, 'Your business is verified',
                       f'{a.name} is verified on A Good Fit. You can feature events now.')
            msg = 'Verified'
        elif action == 'reject':
            note = (request.data.get('note') or '').strip()
            if not note:
                return bad('Add a note saying why. The business sees it.')
            a.status, a.review_note = 'rejected', note[:300]
            a.save(update_fields=['status', 'review_note'])
            svc._email(a, 'About your A Good Fit business account', f'We couldn’t verify {a.name}: {note}')
            msg = f'Not approved: {note}'
        else:
            return bad('Unknown action.', 404)
        log(request.user, a, CHANGE, msg)
        return Response(_business(a))


class SupportView(Staff):
    need = 'safety.change_supportmessage'

    def get(self, request):
        from apps.safety.models import SupportMessage
        handled = request.GET.get('handled') == 'true'
        qs = SupportMessage.objects.filter(handled=handled).select_related('user').order_by(
            '-created_at' if handled else 'created_at')
        return Response({'items': [{'id': s.id, 'topic': s.get_topic_display(), 'safety': s.topic == 'safety',
                                    'text': s.text, 'user': _who(s.user), 'created_at': _when(s.created_at),
                                    'handled': s.handled} for s in qs[:100]],
                         'open': SupportMessage.objects.filter(handled=False).count()})


class SupportActView(Staff):
    need = 'safety.change_supportmessage'

    def post(self, request, pk):
        from apps.safety.models import SupportMessage
        try:
            s = SupportMessage.objects.get(pk=pk)
        except SupportMessage.DoesNotExist:
            return bad('No such message.', 404)
        s.handled = bool(request.data.get('handled', True))
        s.save(update_fields=['handled'])
        log(request.user, s, CHANGE, 'Marked handled' if s.handled else 'Reopened')
        return Response({'ok': True})


# ---------------------------------------------------------------------- team

def _staffer(u):
    return {'id': u.id, 'name': u.full_name or u.email, 'email': u.email, 'role': role(u), 'active': u.is_active,
            'last_login': _when(u.last_login), 'groups': list(u.groups.values_list('name', flat=True))}


class TeamView(Staff):
    def get(self, request):
        qs = User.objects.filter(is_staff=True).order_by('-is_superuser', 'email').prefetch_related('groups')
        return Response({'items': [_staffer(u) for u in qs], 'can_manage': request.user.is_superuser,
                         'groups': list(Group.objects.values_list('name', flat=True))})

    def post(self, request):
        """Admins make an existing account staff (or admin)."""
        if not request.user.is_superuser:
            return bad('Only admins can add staff.', 403, code='forbidden')
        email = (request.data.get('email') or '').strip().lower()
        new_role = request.data.get('role') or 'staff'
        if new_role not in ('staff', 'admin'):
            return bad('Pick staff or admin.')
        try:
            u = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return bad('No account with that email. They need to sign up in the app first.', 404)
        if u.is_staff:
            return bad('They’re already on the team.', 409)
        _set_role(u, new_role)
        log(request.user, u, CHANGE, f'Made {new_role} from the staff dashboard')
        return Response(_staffer(u), status=201)


def _set_role(u, new_role):
    u.is_staff = new_role in ('staff', 'admin')
    u.is_superuser = new_role == 'admin'
    u.save(update_fields=['is_staff', 'is_superuser'])
    staff = Group.objects.filter(name='Staff').first()
    if staff:
        if new_role == 'staff':
            u.groups.add(staff)
        elif new_role is None:
            u.groups.remove(staff)


class TeamMemberView(Staff):
    def patch(self, request, pk):
        if not request.user.is_superuser:
            return bad('Only admins can change roles.', 403, code='forbidden')
        new_role = request.data.get('role')
        if new_role not in ('staff', 'admin', None):
            return bad('Pick staff or admin.')
        try:
            u = User.objects.get(pk=pk, is_staff=True)
        except User.DoesNotExist:
            return bad('Not on the team.', 404)
        if u.pk == request.user.pk:
            return bad('You can’t change your own role.')
        if u.is_superuser and new_role != 'admin' and User.objects.filter(is_superuser=True, is_active=True).count() <= 1:
            return bad('There has to be at least one admin.')
        _set_role(u, new_role)
        log(request.user, u, CHANGE, f'Role set to {new_role or "none (removed from the team)"}')
        return Response(_staffer(u) if u.is_staff else {'removed': True})
